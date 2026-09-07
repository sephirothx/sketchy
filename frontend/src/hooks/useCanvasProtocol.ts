import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ClientCanvasHistory,
  canFillWithinBudget,
  canStartStrokeWithinBudget,
  decodeCanvasHistory,
  pointsFitWithinBudget,
} from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import {
  CompletionWatch,
  RecoverySender,
  onServerCanvasSequence,
  repackDrawFrames,
  requestSessionRebind,
  staleNoticeAction,
} from "../lib/canvasRecovery";
import { CANVAS_SYNC_TIMEOUT_MS, createCanvasSyncRequester } from "../lib/canvasSyncRequests";
import { currentClientConfig } from "../lib/clientConfig";
import type { CanvasSyncRequester, PrefixClaim } from "../lib/canvasSyncRequests";
import { decodeLiveDrawing, endsPath, encodeClear, toWireFrame  } from "../lib/liveDrawing";
import type { LiveDrawingPacket } from "../lib/liveDrawing";
import type { ErrorCode } from "../types";
import { recordClientError } from "../lib/clientErrorLog";
import { emitWithAck, socket } from "../lib/socket";
import { useCanvasBudgetStore } from "../store/canvasBudgetStore";

const MAX_PENDING_CANVAS_ACTIONS = 256;

/** Whether this frame closed or committed an action in the local history.

The server attaches the commit to exactly the frame that commits an action, so
a viewer can check the two agree instead of trusting them to. `applied` is what
makes this exact rather than a guess about server state: `apply` accepts a
`draw_end` only when it really closed an open path, which is the same condition
the server commits on.

Without the check a viewer that stopped reading commits would drift in silence -
same pixels, stale sequence - until something validated against that sequence
finally arrived. Cheap to recover from and almost impossible to notice, which
is the wrong way round. */
function commitsAnAction(packet: LiveDrawingPacket, applied: boolean): boolean {
  if (!applied) return false;
  return endsPath(packet)
    || packet.event === "draw_shape"
    || packet.event === "draw_fill"
    || packet.event === "clear_canvas";
}

export type { DrawingFrame } from "../lib/liveDrawing";
import type { DrawingFrame } from "../lib/liveDrawing";

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
  /** Whether the frame was applied and sent. A frame that was not - no path
  open, undecodable, over the point budget, refused by the history - leaves
  the open path where it was, and the caller's idea of its last point must
  stay there too, since the next relative frame is resolved against it (#559). */
  sendPathFrame(frame: DrawingFrame): boolean;
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
  // Built in the mount effect with the handlers; the callbacks below reach
  // them through refs, since a stroke may finish before the effect re-runs.
  const senderRef = useRef<RecoverySender | null>(null);
  const watchRef = useRef<CompletionWatch | null>(null);

  // Frames leave through one door, and never into a socket that is not
  // connected: Socket.IO would buffer them and flush that buffer on reconnect,
  // before the seat is rebound, into whatever the canvas has become (#597).
  // A frame dropped here is recovered by the sync that follows the rebind.
  const sendDraw = useCallback((frame: DrawingFrame, identity?: [number, number]): void => {
    if (!socket.connected) return;
    if (identity) socket.emit("draw", toWireFrame(frame), identity);
    else socket.emit("draw", toWireFrame(frame));
  }, []);
  // What this client can honestly say it already holds, so the server can
  // reply with only the missing tail.
  //
  // Only claimed with nothing pending. A client with unacknowledged mutations
  // has optimistically applied actions the server may never have accepted, so
  // its history is a guess rather than a prefix of server truth - and a sync
  // is exactly the moment that guess is being abandoned. Viewers, who never
  // hold pending mutations and are most of a room, always qualify; the drawer
  // qualifies between strokes.
  const authoritativePrefixClaim = useCallback((): PrefixClaim | null => {
    const history = historyRef.current;
    if (pendingMutationsRef.current.size > 0) return null;
    if (history.generation == null || history.historyHash == null) return null;
    if (history.actions.length === 0) return null;
    return {
      generation: history.generation,
      actionCount: history.actions.length,
      historyHash: history.historyHash,
    };
  }, []);

  // Built in the mount effect rather than during render: it closes over refs
  // to read the prefix claim at request time, and reading a ref during render
  // is exactly what the hooks rule forbids.
  // One transaction at a time (#598): the request carries an id the reply
  // echoes and the prefix claimed at that moment; a refusal says when to ask
  // again; a lost request is retried with backoff; and when every attempt is
  // gone the session is handed to the reconnect hook for a transport restart.
  const ensureSyncRequester = useCallback((): CanvasSyncRequester => {
    syncRequestsRef.current ??= createCanvasSyncRequester({
      send: (requestId, claim) => emitWithAck<{ ok: boolean; errorCode?: ErrorCode; retryAfterMs?: number }>(
        "request_sync_strokes",
        claim ? [requestId, claim.generation, claim.actionCount, claim.historyHash] : [requestId],
        { timeoutMs: CANVAS_SYNC_TIMEOUT_MS },
      ),
      claim: authoritativePrefixClaim,
      exhausted: () => requestSessionRebind(),
      setTimeout: (handler, delayMs) => window.setTimeout(handler, delayMs),
      clearTimeout: (timeoutId) => window.clearTimeout(timeoutId),
    });
    return syncRequestsRef.current;
  }, [authoritativePrefixClaim]);

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
      senderRef.current?.cancel();
      watchRef.current?.cancelAll();
    }
    ensureSyncRequester().request();
  }, [ensureSyncRequester]);

  const allocateSequence = useCallback((): number | null => {
    if (pendingMutationsRef.current.size >= MAX_PENDING_CANVAS_ACTIONS) {
      requestAuthoritativeSync();
      return null;
    }
    const sequence = nextSequenceRef.current;
    nextSequenceRef.current += 1;
    return sequence;
  }, [requestAuthoritativeSync]);

  // A relative `draw_move` (#559) carries offsets from the open path's last
  // point, which the history holds; decoded against it here so that every
  // consumer below sees points. One that arrives with no open path decodes
  // to nothing, like a frame that does not decode at all.
  const decodeAgainstHistory = useCallback((frame: unknown): LiveDrawingPacket | null => {
    const packet = decodeLiveDrawing(frame, historyRef.current.openPathLastPoint());
    return packet?.event === "draw_move_relative" ? null : packet;
  }, []);

  const beginDrawAction = useCallback((
    frame: DrawingFrame,
    isPath = false,
  ): number | null => {
    const packet = decodeAgainstHistory(frame);
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
    sendDraw(frame, [generation, sequence]);
    // A shape, fill or clear commits on this one frame: its clock starts now.
    if (!isPath) watchRef.current?.arm(sequence);
    publishBudgets();
    return sequence;
  }, [allocateSequence, decodeAgainstHistory, publishBudgets, requestAuthoritativeSync, sendDraw]);

  const sendPathFrame = useCallback((frame: DrawingFrame): boolean => {
    const sequence = activeOutgoingSequenceRef.current;
    if (sequence === null) return false;
    const pending = pendingMutationsRef.current.get(sequence);
    const packet = decodeAgainstHistory(frame);
    if (!pending || pending.kind !== "draw" || !packet) return false;
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
      return false;
    }
    if (!historyRef.current.apply(packet)) {
      requestAuthoritativeSync();
      return false;
    }
    pending.frames.push(frame);
    sendDraw(frame);
    if (packet.event === "draw_move") publishBudgets();
    return true;
  }, [decodeAgainstHistory, publishBudgets, requestAuthoritativeSync, sendDraw]);

  const finishPathAction = useCallback((): void => {
    const sequence = activeOutgoingSequenceRef.current;
    if (sequence === null) return;
    const pending = pendingMutationsRef.current.get(sequence);
    if (pending?.kind === "draw") {
      pending.expectedRevision = historyRef.current.revision;
      pending.expectedHash = historyRef.current.historyHash;
      // Finished here; the server has a deadline to say so (#597).
      watchRef.current?.arm(sequence);
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
    watchRef.current?.arm(sequence);
    void emitWithAck<{ ok: boolean; errorCode?: ErrorCode }>("undo_stroke", request)
      .then((response) => {
        if (!response?.ok && response?.errorCode !== "canvas_out_of_sequence") {
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
    // A frame that commits an action carries the commit with it, so a viewer
    // can never see a commit for a frame that has not arrived - and the room
    // is spared a second event per action. The drawer is skipped by the
    // rebroadcast and still receives `canvas_commit` on its own.
    const onDraw = (payload: unknown, commit?: unknown) => {
      const packet = decodeAgainstHistory(payload);
      if (!packet) {
        requestAuthoritativeSync();
        return;
      }
      const applied = historyRef.current.apply(packet);
      renderer.apply(packet);
      publishBudgets();
      if (commitsAnAction(packet, applied) !== (commit !== undefined)) {
        // A committing frame with no commit, or a commit on a frame that
        // committed nothing. Either way the two sides disagree about what this
        // frame did, so stop here and take server truth - loudly, because the
        // alternative is a viewer that looks perfectly fine and is not.
        recordClientError(
          "socket",
          `draw frame ${packet.event} ${commit === undefined ? "missing its" : "carried an unexpected"} commit`,
        );
        requestAuthoritativeSync();
        return;
      }
      if (commit !== undefined) onCanvasCommit(commit);
    };

    // The reply was applied. A converged canvas discharges every trigger
    // coalesced meanwhile; one that fell back asks once more.
    const finishSync = (converged: boolean) => {
      ensureSyncRequester().applied(converged);
    };

    const isIncompletePath = (pending: PendingCanvasMutation): boolean =>
      pending.kind === "draw"
      && pending.frames.length > 0
      && decodeLiveDrawing(pending.frames[0])?.event === "draw_start"
      && !closesPath(pending.frames.at(-1)!);
    const closesPath = (frame: DrawingFrame): boolean => {
      const packet = decodeLiveDrawing(frame);
      return packet !== null && endsPath(packet);
    };

    // One paced sender for every replay, and one deadline per finished action.
    // Both are pure (`lib/canvasRecovery.ts`); this is only the wiring.
    const sender = new RecoverySender({
      emit: sendDraw,
      allowance: () => currentClientConfig(),
      now: () => performance.now(),
      schedule: (callback, delayMs) => window.setTimeout(callback, delayMs),
      cancel: (handle) => window.clearTimeout(handle as number),
      tooLarge: () => requestAuthoritativeSync(),
    });
    // Resend a pending action whole: the server replays the stored commit of
    // one it already has, and accepts one it never saw. A path still open is
    // not resent - its end will come, or the next opener will provoke a gap.
    const replay = (sequence: number): void => {
      const pending = pendingMutationsRef.current.get(sequence);
      if (!pending || isIncompletePath(pending)) return;
      if (pending.kind === "undo") {
        if (socket.connected) socket.emit("undo_stroke", pending.request);
        return;
      }
      sender.enqueue({
        sequence,
        frames: repackDrawFrames(pending.frames),
        identity: [pending.generation, sequence],
      });
    };
    const watch = new CompletionWatch({
      schedule: (callback, delayMs) => window.setTimeout(callback, delayMs),
      cancel: (handle) => window.clearTimeout(handle as number),
      resend: replay,
      giveUp: () => requestAuthoritativeSync(),
    });
    senderRef.current = sender;
    watchRef.current = watch;
    const stopSequenceWatch = onServerCanvasSequence((generation, sequence) => {
      if (generation === historyRef.current.generation) watch.serverCommitted(sequence);
    });
    // A replaced connection cannot carry on a replay, and a deadline cannot
    // be met against a dead socket: the rebind's sync decides what is still
    // pending and re-arms a deadline for each action it replays.
    const onDisconnect = () => {
      sender.cancel();
      watch.cancelAll();
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
      sender.cancel();
      watch.cancelAll();
      historyRef.current.replace(actions, revision, generation, sequence, historyHash);
      nextSequenceRef.current = committedSequence + 1;
      renderer.replay(actions);
      publishBudgets();
      finishSync(true);
    };

    // Adopt `actions` as the authority and reconcile what this client still
    // holds pending, the same way for a full reply and for a tail (#598): a
    // tail used to clear every pending mutation, including strokes drawn after
    // the request went out, as if they had never happened.
    const adoptAuthority = (
      actions: DecodedCanvasAction[],
      revision: unknown,
      generation: unknown,
      sequence: unknown,
      historyHash: unknown,
    ): void => {
      if (!historyRef.current.replace(actions, revision, generation, sequence, historyHash)) {
        finishSync(false);
        requestAuthoritativeSync();
        return;
      }
      activeOutgoingSequenceRef.current = null;
      // A fresh authority supersedes any replay still queued against the old.
      sender.cancel();
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
      for (const pendingSequence of [...pendingMutationsRef.current.keys()]) {
        if (pendingSequence <= committedSequence) {
          // Committed by the server: nothing left to wait for, and a deadline
          // left armed here would fire into a gone entry and, at its end,
          // discard strokes that are still in flight.
          pendingMutationsRef.current.delete(pendingSequence);
          watch.confirm(pendingSequence);
        }
      }
      for (const [pendingSequence, pending] of [...pendingMutationsRef.current.entries()]) {
        if (isIncompletePath(pending)) {
          pendingMutationsRef.current.delete(pendingSequence);
          watch.confirm(pendingSequence);
        }
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
            const packet = decodeAgainstHistory(frame);
            if (!packet || !historyRef.current.apply(packet)) {
              recoveryValid = false;
              break;
            }
          }
          if (!recoveryValid) break;
          pending.expectedRevision = historyRef.current.revision;
          pending.expectedHash = historyRef.current.historyHash;
          sender.enqueue({
            sequence: pendingSequence,
            frames: repackDrawFrames(pending.frames),
            identity: [pending.generation, pendingSequence],
          });
          watch.arm(pendingSequence);
        } else {
          const request = historyRef.current.prepareUndo(pendingSequence);
          if (!request) {
            recoveryValid = false;
            break;
          }
          pending.request = request;
          pending.expectedRevision = historyRef.current.revision!;
          pending.expectedHash = historyRef.current.historyHash!;
          if (socket.connected) socket.emit("undo_stroke", request);
          watch.arm(pendingSequence);
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
      finishSync(true);
    };

    const onSyncStrokes = (
      payload: unknown,
      revision: unknown,
      generation: unknown,
      sequence: unknown,
      historyHash: unknown,
      requestId: unknown,
    ) => {
      const verdict = ensureSyncRequester().classify({
        requestId: typeof requestId === "number" ? requestId : 0,
        generation: typeof generation === "number" ? generation : -1,
      });
      // The answer to a request this client has since abandoned - a reset, a
      // room switch - describes a canvas that is no longer this one.
      if (verdict === "stale") return;
      const actions = decodeCanvasHistory(payload);
      if (!actions) {
        finishSync(false);
        requestAuthoritativeSync();
        return;
      }
      adoptAuthority(actions, revision, generation, sequence, historyHash);
    };

    // Only the actions this client was missing, spliced onto the prefix it
    // claimed. `replace` recomputes the prefix hashes and rejects a history
    // that does not hash to what the server said, so a splice that is wrong
    // for any reason costs one full sync rather than a wrong canvas.
    const onSyncStrokesTail = (
      payload: unknown,
      baseCount: unknown,
      revision: unknown,
      generation: unknown,
      sequence: unknown,
      historyHash: unknown,
      requestId: unknown,
    ) => {
      // A tail only ever answers a claim, so it must name the outstanding
      // request and be cut for the prefix that request claimed: the drawer
      // may have drawn since, and those strokes are pending, not history.
      const verdict = ensureSyncRequester().classify({
        requestId: typeof requestId === "number" ? requestId : 0,
        generation: typeof generation === "number" ? generation : -1,
        baseActionCount: typeof baseCount === "number" ? baseCount : -1,
      });
      if (verdict !== "matches") return;
      const tail = decodeCanvasHistory(payload);
      if (
        !tail
        || typeof baseCount !== "number"
        || !Number.isSafeInteger(baseCount)
        || baseCount < 0
        || baseCount > historyRef.current.actions.length
      ) {
        finishSync(false);
        requestAuthoritativeSync();
        return;
      }
      const combined = historyRef.current.actions.slice(0, baseCount).concat(tail);
      adoptAuthority(combined, revision, generation, sequence, historyHash);
    };

    function onCanvasCommit(payload: unknown) {
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
      watch.confirm(sequence);
    }

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
      watch.confirm(sequence);
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
        if (isIncompletePath(pending)) {
          pendingMutationsRef.current.delete(sequence);
          watch.confirm(sequence);
          if (activeOutgoingSequenceRef.current === sequence) {
            activeOutgoingSequenceRef.current = null;
          }
          continue;
        }
        // Repacked and paced: a second request for the same range while the
        // first is still going out costs nothing more (#597).
        replay(sequence);
      }
    };

    const onCanvasReset = (payload: unknown) => {
      if (!historyRef.current.reset(payload)) {
        requestAuthoritativeSync();
        return;
      }
      pendingMutationsRef.current.clear();
      sender.cancel();
      watch.cancelAll();
      activeOutgoingSequenceRef.current = null;
      nextSequenceRef.current = 1;
      // A new turn replaces the history wholesale, so a sync still owed
      // against the old generation is worthless - and carrying its latch into
      // the new turn would suppress the syncs that turn goes on to need.
      syncRequestsRef.current?.reset();
      renderer.clear();
      publishBudgets();
    };

    socket.on("draw", onDraw);
    socket.on("sync_strokes", onSyncStrokes);
    socket.on("sync_strokes_tail", onSyncStrokesTail);
    socket.on("canvas_commit", onCanvasCommit);
    socket.on("canvas_undo", onUndoStroke);
    // One notice per window instead of a history dump (#562): recover
    // through the transaction, after the delay the server named if any.
    let staleTimer: number | null = null;
    const onCanvasStale = (payload: unknown) => {
      const action = staleNoticeAction(payload, historyRef.current.generation);
      if (!action) return;
      if (staleTimer !== null) window.clearTimeout(staleTimer);
      if (action.delayMs === 0) {
        requestAuthoritativeSync(action.discardPending);
        return;
      }
      staleTimer = window.setTimeout(() => {
        staleTimer = null;
        requestAuthoritativeSync(action.discardPending);
      }, action.delayMs);
    };
    socket.on("request_canvas_actions", onRequestCanvasActions);
    socket.on("canvas_reset", onCanvasReset);
    socket.on("canvas_stale", onCanvasStale);
    socket.on("disconnect", onDisconnect);
    // Through the requester rather than a bare emit: this one is the most
    // likely of all to go unanswered, since the canvas can mount before the
    // socket has finished binding itself to a seat in the room.
    ensureSyncRequester().request();

    return () => {
      socket.off("draw", onDraw);
      socket.off("sync_strokes", onSyncStrokes);
      socket.off("sync_strokes_tail", onSyncStrokesTail);
      socket.off("canvas_commit", onCanvasCommit);
      socket.off("canvas_undo", onUndoStroke);
      socket.off("request_canvas_actions", onRequestCanvasActions);
      socket.off("canvas_reset", onCanvasReset);
      socket.off("canvas_stale", onCanvasStale);
      socket.off("disconnect", onDisconnect);
      if (staleTimer !== null) window.clearTimeout(staleTimer);
      stopSequenceWatch();
      sender.cancel();
      watch.cancelAll();
      senderRef.current = null;
      watchRef.current = null;
      syncRequestsRef.current?.reset();
    };
  }, [decodeAgainstHistory, ensureSyncRequester, publishBudgets, renderer, requestAuthoritativeSync, sendDraw]);

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
