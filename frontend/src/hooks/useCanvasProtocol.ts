import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ClientCanvasHistory,
  decodeCanvasHistory,
  semanticStart,
} from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { decodeLiveDrawing, encodeClear } from "../lib/liveDrawing";
import type { LiveDrawingPacket } from "../lib/liveDrawing";
import { encodeCheckpointPng } from "../lib/canvasRenderer";
import { emitWithAck, socket } from "../lib/socket";

const MAX_PENDING_CANVAS_ACTIONS = 256;

export type DrawingFrame = number | Uint8Array;

type PendingCanvasMutation =
  | {
    kind: "draw";
    generation: number;
    frames: DrawingFrame[];
    expectedRevision: number | null;
    expectedHash: number | null;
  }
  | {
    kind: "undo";
    generation: number;
    request: [number, number, number, number];
    expectedRevision: number;
    expectedHash: number;
  }
  | {
    kind: "checkpoint";
    generation: number;
    png: Uint8Array;
    foldedCount: number;
    prefixHash: number;
    expectedRevision: number;
    expectedHash: number;
  };

export interface CanvasProtocolRenderer {
  apply(packet: LiveDrawingPacket): void;
  clear(): void;
  replay(actions: DecodedCanvasAction[]): void;
}

export interface CanvasProtocol {
  beginDrawAction(frame: DrawingFrame, isPath?: boolean): number | null;
  sendPathFrame(frame: DrawingFrame): void;
  finishPathAction(): void;
  requestUndo(): void;
  requestClear(): void;
  requestAuthoritativeSync(discardPending?: boolean): void;
}

export function useCanvasProtocol(
  renderer: CanvasProtocolRenderer,
  onRejected?: (reason: string) => void,
): CanvasProtocol {
  const historyRef = useRef(new ClientCanvasHistory());
  const nextSequenceRef = useRef(1);
  const pendingMutationsRef = useRef(new Map<number, PendingCanvasMutation>());
  const activeOutgoingSequenceRef = useRef<number | null>(null);
  const syncInFlightRef = useRef(false);
  const syncQueuedRef = useRef(false);
  const compactingRef = useRef(false);
  const queuedDrawRef = useRef<{ frame: DrawingFrame; isPath: boolean } | null>(null);
  const beginDrawActionRef = useRef<(
    frame: DrawingFrame,
    isPath?: boolean,
  ) => number | null>(() => null);

  const flushQueuedDraw = useCallback(() => {
    const queued = queuedDrawRef.current;
    queuedDrawRef.current = null;
    if (queued) beginDrawActionRef.current(queued.frame, queued.isPath);
  }, []);

  const requestAuthoritativeSync = useCallback((discardPending = true): void => {
    if (discardPending) {
      pendingMutationsRef.current.clear();
      activeOutgoingSequenceRef.current = null;
    }
    if (syncInFlightRef.current) {
      syncQueuedRef.current = true;
      return;
    }
    syncInFlightRef.current = true;
    syncQueuedRef.current = false;
    socket.emit("request_sync_strokes");
  }, []);

  const allocateSequence = useCallback((): number | null => {
    if (pendingMutationsRef.current.size >= MAX_PENDING_CANVAS_ACTIONS) {
      requestAuthoritativeSync();
      return null;
    }
    const sequence = nextSequenceRef.current;
    nextSequenceRef.current += 1;
    return sequence;
  }, [requestAuthoritativeSync]);

  const emitCheckpoint = useCallback((
    png: Uint8Array,
    foldedCount: number,
    prefixHash: number,
  ): number | null => {
    const sequence = allocateSequence();
    const generation = historyRef.current.generation;
    if (sequence === null || generation === null) {
      requestAuthoritativeSync();
      return null;
    }
    if (!historyRef.current.applyCheckpoint(png, foldedCount)) {
      requestAuthoritativeSync();
      return null;
    }
    pendingMutationsRef.current.set(sequence, {
      kind: "checkpoint",
      generation,
      png,
      foldedCount,
      prefixHash,
      expectedRevision: historyRef.current.revision!,
      expectedHash: historyRef.current.historyHash!,
    });
    socket.emit("canvas_checkpoint", png, [generation, sequence, foldedCount, prefixHash]);
    return sequence;
  }, [allocateSequence, requestAuthoritativeSync]);

  const compactWindow = useCallback(async (foldedCount: number): Promise<boolean> => {
    const history = historyRef.current;
    const start = semanticStart(history.actions);
    const folded = history.actions.slice(start, start + foldedCount);
    const previous = history.checkpointPng();
    const prefixHash = history.prefixHashForFold(foldedCount);
    if (prefixHash === null) {
      requestAuthoritativeSync();
      return false;
    }
    try {
      const png = await encodeCheckpointPng(previous, folded);
      return emitCheckpoint(png, foldedCount, prefixHash) !== null;
    } catch {
      requestAuthoritativeSync();
      return false;
    }
  }, [emitCheckpoint, requestAuthoritativeSync]);

  const beginDrawAction = useCallback((
    frame: DrawingFrame,
    isPath = false,
  ): number | null => {
    const packet = decodeLiveDrawing(frame);
    if (!packet || !historyRef.current.canApply(packet)) return null;
    const fold = historyRef.current.neededFoldForPacket(packet);
    if (fold) {
      if (compactingRef.current) {
        queuedDrawRef.current = { frame, isPath };
        return 0;
      }
      compactingRef.current = true;
      void compactWindow(fold).then((ok) => {
        compactingRef.current = false;
        if (!ok) {
          queuedDrawRef.current = null;
          return;
        }
        beginDrawActionRef.current(frame, isPath);
        flushQueuedDraw();
      });
      return 0;
    }
    if (!historyRef.current.apply(packet)) {
      if (compactingRef.current) {
        queuedDrawRef.current = { frame, isPath };
        return 0;
      }
      return null;
    }
    const sequence = allocateSequence();
    const generation = historyRef.current.generation;
    if (sequence === null || generation === null) {
      requestAuthoritativeSync();
      return null;
    }
    pendingMutationsRef.current.set(sequence, {
      kind: "draw",
      generation,
      frames: [frame],
      expectedRevision: isPath ? null : historyRef.current.revision,
      expectedHash: isPath ? null : historyRef.current.historyHash,
    });
    activeOutgoingSequenceRef.current = isPath ? sequence : null;
    socket.emit("draw", frame, [generation, sequence]);
    return sequence;
  }, [allocateSequence, compactWindow, flushQueuedDraw, requestAuthoritativeSync]);

  useEffect(() => {
    beginDrawActionRef.current = beginDrawAction;
  }, [beginDrawAction]);

  const sendPathFrame = useCallback((frame: DrawingFrame): void => {
    const sequence = activeOutgoingSequenceRef.current;
    if (sequence === null) return;
    const pending = pendingMutationsRef.current.get(sequence);
    const packet = decodeLiveDrawing(frame);
    if (!pending || pending.kind !== "draw" || !packet) return;
    if (!historyRef.current.apply(packet)) {
      requestAuthoritativeSync();
      return;
    }
    pending.frames.push(frame);
    socket.emit("draw", frame);
  }, [requestAuthoritativeSync]);

  const finishPathAction = useCallback((): void => {
    const sequence = activeOutgoingSequenceRef.current;
    if (sequence === null) return;
    const pending = pendingMutationsRef.current.get(sequence);
    if (pending?.kind === "draw") {
      pending.expectedRevision = historyRef.current.revision;
      pending.expectedHash = historyRef.current.historyHash;
    }
    activeOutgoingSequenceRef.current = null;
  }, []);

  const requestUndo = useCallback(() => {
    if (activeOutgoingSequenceRef.current !== null) return;
    const sequence = allocateSequence();
    if (sequence === null) return;
    const request = historyRef.current.prepareUndo(sequence);
    if (!request) {
      nextSequenceRef.current -= 1;
      return;
    }
    pendingMutationsRef.current.set(sequence, {
      kind: "undo",
      generation: request[0],
      request,
      expectedRevision: historyRef.current.revision!,
      expectedHash: historyRef.current.historyHash!,
    });
    renderer.replay(historyRef.current.actions);
    void emitWithAck<{ ok: boolean; error?: string }>("undo_stroke", request)
      .then((response) => {
        if (!response?.ok && response?.error !== "Drawing actions are out of sequence") {
          requestAuthoritativeSync();
        }
      })
      .catch(() => requestAuthoritativeSync(false));
  }, [allocateSequence, renderer, requestAuthoritativeSync]);

  const requestClear = useCallback(() => {
    if (activeOutgoingSequenceRef.current !== null) return;
    renderer.clear();
    beginDrawAction(encodeClear());
  }, [beginDrawAction, renderer]);

  useEffect(() => {
    const onDraw = (payload: unknown) => {
      const packet = decodeLiveDrawing(payload);
      if (!packet) {
        requestAuthoritativeSync();
        return;
      }
      historyRef.current.apply(packet);
      renderer.apply(packet);
    };

    const finishQueuedSync = () => {
      if (!syncQueuedRef.current) return;
      syncQueuedRef.current = false;
      requestAuthoritativeSync();
    };

    const restoreAuthoritative = (
      actions: DecodedCanvasAction[],
      revision: unknown,
      generation: unknown,
      sequence: unknown,
      historyHash: unknown,
      committedSequence: number,
    ) => {
      pendingMutationsRef.current.clear();
      historyRef.current.replace(actions, revision, generation, sequence, historyHash);
      nextSequenceRef.current = committedSequence + 1;
      renderer.replay(actions);
      finishQueuedSync();
    };

    const onSyncStrokes = (
      payload: unknown,
      revision: unknown,
      generation: unknown,
      sequence: unknown,
      historyHash: unknown,
    ) => {
      syncInFlightRef.current = false;
      const actions = decodeCanvasHistory(payload);
      if (!actions || !historyRef.current.replace(
        actions, revision, generation, sequence, historyHash,
      )) {
        requestAuthoritativeSync();
        return;
      }
      activeOutgoingSequenceRef.current = null;
      const committedGeneration = historyRef.current.generation!;
      const committedSequence = historyRef.current.sequence!;
      if ([...pendingMutationsRef.current.values()].some(
        (pending) => pending.generation !== committedGeneration,
      )) {
        restoreAuthoritative(
          actions, revision, generation, sequence, historyHash, committedSequence,
        );
        return;
      }
      for (const pendingSequence of pendingMutationsRef.current.keys()) {
        if (pendingSequence <= committedSequence) {
          pendingMutationsRef.current.delete(pendingSequence);
        }
      }
      for (const [pendingSequence, pending] of [...pendingMutationsRef.current.entries()]) {
        if (pending.kind !== "draw") continue;
        const incomplete = pending.frames.length > 0
          && decodeLiveDrawing(pending.frames[0])?.event === "draw_start"
          && decodeLiveDrawing(pending.frames.at(-1)!)?.event !== "draw_end";
        if (incomplete) pendingMutationsRef.current.delete(pendingSequence);
      }
      const pendingSequences = [...pendingMutationsRef.current.keys()]
        .sort((left, right) => left - right);
      if (pendingSequences.some(
        (pendingSequence, index) => pendingSequence !== committedSequence + index + 1,
      )) {
        restoreAuthoritative(
          actions, revision, generation, sequence, historyHash, committedSequence,
        );
        return;
      }

      let recoveryValid = true;
      for (const pendingSequence of pendingSequences) {
        const pending = pendingMutationsRef.current.get(pendingSequence)!;
        if (pending.kind === "draw") {
          for (const frame of pending.frames) {
            const packet = decodeLiveDrawing(frame);
            if (!packet || !historyRef.current.apply(packet)) {
              recoveryValid = false;
              break;
            }
          }
          if (!recoveryValid) break;
          pending.expectedRevision = historyRef.current.revision;
          pending.expectedHash = historyRef.current.historyHash;
          pending.frames.forEach((frame, index) => {
            socket.emit(
              "draw",
              frame,
              index === 0 ? [pending.generation, pendingSequence] : undefined,
            );
          });
        } else if (pending.kind === "checkpoint") {
          socket.emit(
            "canvas_checkpoint",
            pending.png,
            [pending.generation, pendingSequence, pending.foldedCount, pending.prefixHash],
          );
        } else {
          const request = historyRef.current.prepareUndo(pendingSequence);
          if (!request) {
            recoveryValid = false;
            break;
          }
          pending.request = request;
          pending.expectedRevision = historyRef.current.revision!;
          pending.expectedHash = historyRef.current.historyHash!;
          socket.emit("undo_stroke", request);
        }
      }
      if (!recoveryValid) {
        restoreAuthoritative(
          actions, revision, generation, sequence, historyHash, committedSequence,
        );
        return;
      }
      nextSequenceRef.current = (pendingSequences.at(-1) ?? committedSequence) + 1;
      renderer.replay(historyRef.current.actions);
      finishQueuedSync();
    };

    const onCanvasCommit = (payload: unknown) => {
      const sequence = Array.isArray(payload) ? payload[1] : null;
      const pending = typeof sequence === "number"
        ? pendingMutationsRef.current.get(sequence)
        : undefined;
      const valid = pending?.kind === "draw"
        ? historyRef.current.confirmAction(
          payload, pending.expectedRevision, pending.expectedHash,
        )
        : historyRef.current.confirmAction(payload);
      if (!valid) {
        requestAuthoritativeSync();
        return;
      }
      const drawerCommit = pending?.kind === "draw";
      pendingMutationsRef.current.delete(sequence);
      if (drawerCommit && !compactingRef.current) {
        const fold = historyRef.current.opportunisticFoldCount();
        if (fold) {
          compactingRef.current = true;
          void compactWindow(fold).finally(() => {
            compactingRef.current = false;
            flushQueuedDraw();
          });
        }
      }
    };

    const onUndoStroke = (payload: unknown) => {
      const sequence = Array.isArray(payload) ? payload[1] : null;
      const pending = typeof sequence === "number"
        ? pendingMutationsRef.current.get(sequence)
        : undefined;
      const valid = pending?.kind === "undo"
        ? historyRef.current.confirmUndo(
          payload, pending.expectedRevision, pending.expectedHash,
        )
        : historyRef.current.confirmUndo(payload);
      if (!valid) {
        requestAuthoritativeSync();
        return;
      }
      pendingMutationsRef.current.delete(sequence);
      renderer.replay(historyRef.current.actions);
    };

    const onRequestCanvasActions = (payload: unknown) => {
      if (
        !Array.isArray(payload)
        || payload.length !== 3
        || !Number.isSafeInteger(payload[0])
        || !Number.isSafeInteger(payload[1])
        || !Number.isSafeInteger(payload[2])
        || payload[0] !== historyRef.current.generation
      ) {
        requestAuthoritativeSync();
        return;
      }
      for (let sequence = payload[1]; sequence <= payload[2]; sequence++) {
        const pending = pendingMutationsRef.current.get(sequence);
        if (!pending) {
          requestAuthoritativeSync();
          return;
        }
        if (pending.kind === "undo") {
          socket.emit("undo_stroke", pending.request);
          continue;
        }
        if (pending.kind === "checkpoint") {
          socket.emit(
            "canvas_checkpoint",
            pending.png,
            [pending.generation, sequence, pending.foldedCount, pending.prefixHash],
          );
          continue;
        }
        const incomplete = pending.frames.length > 0
          && decodeLiveDrawing(pending.frames[0])?.event === "draw_start"
          && decodeLiveDrawing(pending.frames.at(-1)!)?.event !== "draw_end";
        if (incomplete) {
          pendingMutationsRef.current.delete(sequence);
          if (activeOutgoingSequenceRef.current === sequence) {
            activeOutgoingSequenceRef.current = null;
          }
          continue;
        }
        pending.frames.forEach((frame, index) => {
          socket.emit(
            "draw",
            frame,
            index === 0 ? [pending.generation, sequence] : undefined,
          );
        });
      }
    };

    const onCanvasCheckpoint = (payload: unknown) => {
      if (!Array.isArray(payload) || payload.length !== 6) {
        requestAuthoritativeSync();
        return;
      }
      const sequence = payload[1];
      const pending = typeof sequence === "number"
        ? pendingMutationsRef.current.get(sequence)
        : undefined;
      if (pending?.kind === "checkpoint") {
        const valid = historyRef.current.confirmAction(
          payload.slice(0, 4),
          pending.expectedRevision,
          pending.expectedHash,
        );
        if (!valid) {
          requestAuthoritativeSync();
          return;
        }
        pendingMutationsRef.current.delete(sequence);
        return;
      }
      const png = payload[5] instanceof Uint8Array
        ? payload[5]
        : payload[5] instanceof ArrayBuffer
          ? new Uint8Array(payload[5])
          : ArrayBuffer.isView(payload[5])
            ? new Uint8Array(
              payload[5].buffer,
              payload[5].byteOffset,
              payload[5].byteLength,
            )
            : null;
      if (
        typeof payload[4] !== "number"
        || png === null
        || !historyRef.current.applyCheckpoint(png, payload[4])
        || !historyRef.current.confirmAction(payload.slice(0, 4))
      ) {
        requestAuthoritativeSync();
        return;
      }
      renderer.replay(historyRef.current.actions);
    };

    const onCanvasRejected = (payload: unknown) => {
      if (!Array.isArray(payload) || payload.length !== 3) {
        requestAuthoritativeSync();
        return;
      }
      const sequence = payload[1];
      const reason = payload[2];
      if (typeof sequence === "number") {
        pendingMutationsRef.current.delete(sequence);
        if (activeOutgoingSequenceRef.current === sequence) {
          activeOutgoingSequenceRef.current = null;
        }
      }
      if (typeof reason === "string") onRejected?.(reason);
      requestAuthoritativeSync();
    };

    const onCanvasReset = (payload: unknown) => {
      if (!historyRef.current.reset(payload)) {
        requestAuthoritativeSync();
        return;
      }
      pendingMutationsRef.current.clear();
      activeOutgoingSequenceRef.current = null;
      nextSequenceRef.current = 1;
      renderer.clear();
    };

    socket.on("draw", onDraw);
    socket.on("sync_strokes", onSyncStrokes);
    socket.on("canvas_commit", onCanvasCommit);
    socket.on("canvas_undo", onUndoStroke);
    socket.on("canvas_checkpoint", onCanvasCheckpoint);
    socket.on("canvas_rejected", onCanvasRejected);
    socket.on("request_canvas_actions", onRequestCanvasActions);
    socket.on("canvas_reset", onCanvasReset);
    socket.emit("request_sync_strokes");

    return () => {
      socket.off("draw", onDraw);
      socket.off("sync_strokes", onSyncStrokes);
      socket.off("canvas_commit", onCanvasCommit);
      socket.off("canvas_undo", onUndoStroke);
      socket.off("canvas_checkpoint", onCanvasCheckpoint);
      socket.off("canvas_rejected", onCanvasRejected);
      socket.off("request_canvas_actions", onRequestCanvasActions);
      socket.off("canvas_reset", onCanvasReset);
    };
  }, [compactWindow, flushQueuedDraw, onRejected, renderer, requestAuthoritativeSync]);

  return useMemo(() => ({
    beginDrawAction,
    sendPathFrame,
    finishPathAction,
    requestUndo,
    requestClear,
    requestAuthoritativeSync,
  }), [
    beginDrawAction,
    finishPathAction,
    requestAuthoritativeSync,
    requestClear,
    requestUndo,
    sendPathFrame,
  ]);
}
