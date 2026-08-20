import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ClientCanvasHistory,
  canFillWithinBudget,
  canStartStrokeWithinBudget,
  decodeCanvasHistory,
  pointsFitWithinBudget,
} from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { createCanvasSyncRequester } from "../lib/canvasSyncRequests";
import type { CanvasSyncRequester } from "../lib/canvasSyncRequests";
import { decodeLiveDrawing, encodeClear } from "../lib/liveDrawing";
import type { LiveDrawingPacket } from "../lib/liveDrawing";
import { emitWithAck, socket } from "../lib/socket";
import { useCanvasBudgetStore } from "../store/canvasBudgetStore";

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
): CanvasProtocol {
  const historyRef = useRef(new ClientCanvasHistory());
  const nextSequenceRef = useRef(1);
  const pendingMutationsRef = useRef(new Map<number, PendingCanvasMutation>());
  const activeOutgoingSequenceRef = useRef<number | null>(null);
  const syncRequestsRef = useRef<CanvasSyncRequester | null>(null);
  if (syncRequestsRef.current == null) {
    syncRequestsRef.current = createCanvasSyncRequester(
      () => socket.emit("request_sync_strokes"),
    );
  }

  // Republished wherever an action enters or leaves the history, which is the
  // only thing that moves the budget. Extending a path does not: its points
  // ride inside one replayed action.
  const publishBudgets = useCallback((): void => {
    const actions = historyRef.current.actions;
    useCanvasBudgetStore.getState().setBudgets({
      fill: canFillWithinBudget(actions),
      stroke: canStartStrokeWithinBudget(actions),
    });
  }, []);

  const requestAuthoritativeSync = useCallback((discardPending = true): void => {
    if (discardPending) {
      pendingMutationsRef.current.clear();
      activeOutgoingSequenceRef.current = null;
    }
    syncRequestsRef.current!.request();
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

  const beginDrawAction = useCallback((
    frame: DrawingFrame,
    isPath = false,
  ): number | null => {
    const packet = decodeLiveDrawing(frame);
    if (!packet || !historyRef.current.apply(packet)) return null;
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
    publishBudgets();
    return sequence;
  }, [allocateSequence, publishBudgets, requestAuthoritativeSync]);

  const sendPathFrame = useCallback((frame: DrawingFrame): void => {
    const sequence = activeOutgoingSequenceRef.current;
    if (sequence === null) return;
    const pending = pendingMutationsRef.current.get(sequence);
    const packet = decodeLiveDrawing(frame);
    if (!pending || pending.kind !== "draw" || !packet) return;
    if (
      packet.event === "draw_move"
      && !pointsFitWithinBudget(
        historyRef.current.actions,
        packet.payload.points.length,
      )
    ) {
      // The server refuses a batch whole, so taking part of it here would put
      // the two histories out of step. Drop it and let the stroke end where
      // the budget ran out.
      return;
    }
    if (!historyRef.current.apply(packet)) {
      requestAuthoritativeSync();
      return;
    }
    pending.frames.push(frame);
    socket.emit("draw", frame);
    if (packet.event === "draw_move") publishBudgets();
  }, [publishBudgets, requestAuthoritativeSync]);

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
    publishBudgets();
    void emitWithAck<{ ok: boolean; error?: string }>("undo_stroke", request)
      .then((response) => {
        if (!response?.ok && response?.error !== "Drawing actions are out of sequence") {
          requestAuthoritativeSync();
        }
      })
      .catch(() => requestAuthoritativeSync(false));
  }, [allocateSequence, publishBudgets, renderer, requestAuthoritativeSync]);

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
      publishBudgets();
    };

    const finishQueuedSync = () => {
      syncRequestsRef.current!.drainQueued();
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
      publishBudgets();
      finishQueuedSync();
    };

    const onSyncStrokes = (
      payload: unknown,
      revision: unknown,
      generation: unknown,
      sequence: unknown,
      historyHash: unknown,
    ) => {
      syncRequestsRef.current!.arrived();
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
      publishBudgets();
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
      pendingMutationsRef.current.delete(sequence);
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
      publishBudgets();
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

    const onCanvasReset = (payload: unknown) => {
      if (!historyRef.current.reset(payload)) {
        requestAuthoritativeSync();
        return;
      }
      pendingMutationsRef.current.clear();
      activeOutgoingSequenceRef.current = null;
      nextSequenceRef.current = 1;
      // A new turn replaces the history wholesale, so a sync still owed
      // against the old generation is worthless - and carrying its latch into
      // the new turn would suppress the syncs that turn goes on to need.
      syncRequestsRef.current!.reset();
      renderer.clear();
      publishBudgets();
    };

    socket.on("draw", onDraw);
    socket.on("sync_strokes", onSyncStrokes);
    socket.on("canvas_commit", onCanvasCommit);
    socket.on("canvas_undo", onUndoStroke);
    socket.on("request_canvas_actions", onRequestCanvasActions);
    socket.on("canvas_reset", onCanvasReset);
    // Through the requester rather than a bare emit: this one is the most
    // likely of all to go unanswered, since the canvas can mount before the
    // socket has finished binding itself to a seat in the room.
    syncRequestsRef.current!.request();

    return () => {
      socket.off("draw", onDraw);
      socket.off("sync_strokes", onSyncStrokes);
      socket.off("canvas_commit", onCanvasCommit);
      socket.off("canvas_undo", onUndoStroke);
      socket.off("request_canvas_actions", onRequestCanvasActions);
      socket.off("canvas_reset", onCanvasReset);
      syncRequestsRef.current!.reset();
    };
  }, [publishBudgets, renderer, requestAuthoritativeSync]);

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
