import { useCallback, useEffect, useRef, useState } from "react";
import { Canvas } from "./Canvas";
import { decodeCanvasHistory } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { emitWithAck, socket, socketRequestErrorMessage } from "../lib/socket";
import type { DrawingRecapMetadata, DrawingRecapResponse } from "../types";

interface DrawingRecapGalleryProps {
  entries: DrawingRecapMetadata[];
  onClose: () => void;
}

export function DrawingRecapGallery({ entries, onClose }: DrawingRecapGalleryProps) {
  const [position, setPosition] = useState(0);
  const [actions, setActions] = useState<DecodedCanvasAction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cacheRef = useRef(new Map<number, DecodedCanvasAction[]>());
  const loadGenerationRef = useRef(0);
  const entry = entries[position];

  const changePosition = useCallback((nextPosition: number) => {
    loadGenerationRef.current += 1;
    setActions(null);
    setError(null);
    setPosition(Math.max(0, Math.min(entries.length - 1, nextPosition)));
  }, [entries.length]);

  const loadDrawing = useCallback(async () => {
    if (!entry) return;
    const loadGeneration = ++loadGenerationRef.current;
    const cached = cacheRef.current.get(entry.index);
    if (cached) {
      setActions(cached);
      setError(null);
      return;
    }

    setActions(null);
    setError(null);
    try {
      const response = await emitWithAck<DrawingRecapResponse>(
        "get_recap_drawing",
        { index: entry.index },
      );
      if (loadGeneration !== loadGenerationRef.current) return;
      if (!response.ok || !response.drawing) {
        setError(response.error || "This drawing could not be loaded.");
        return;
      }
      const decoded = decodeCanvasHistory(response.drawing.canvas);
      if (!decoded) {
        setError("This drawing could not be decoded.");
        return;
      }
      cacheRef.current.set(entry.index, decoded);
      setActions(decoded);
    } catch (loadError) {
      if (loadGeneration !== loadGenerationRef.current) return;
      setError(socketRequestErrorMessage(loadError, "load this drawing"));
    }
  }, [entry]);

  useEffect(() => {
    void loadDrawing();
    return () => {
      loadGenerationRef.current += 1;
    };
  }, [loadDrawing]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft" && position > 0) {
        changePosition(position - 1);
      }
      if (event.key === "ArrowRight" && position < entries.length - 1) {
        changePosition(position + 1);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [changePosition, entries.length, onClose, position]);

  useEffect(() => {
    socket.on("game_started", onClose);
    return () => {
      socket.off("game_started", onClose);
    };
  }, [onClose]);

  if (!entry) return null;

  return (
    <main className="drawing-recap" aria-labelledby="drawing-recap-title">
      <section className="drawing-recap-card">
        <header className="drawing-recap-header">
          <div>
            <p className="drawing-recap-kicker">Drawing recap</p>
            <h1 id="drawing-recap-title">{entry.word}</h1>
            <p className="drawing-recap-meta">
              Drawn by{" "}
              <strong
                className="colored-player-name"
                style={{ color: entry.drawerNameColor }}
              >
                {entry.drawerNickname}
              </strong>
              {" · "}Round {entry.roundNumber} · Turn {entry.turnNumber}
            </p>
          </div>
          <button type="button" className="drawing-recap-close" onClick={onClose}>
            Back
          </button>
        </header>

        <div className="drawing-recap-canvas" aria-busy={actions === null && !error}>
          {error ? (
            <div className="drawing-recap-status" role="alert">
              <p>{error}</p>
              <button type="button" onClick={() => void loadDrawing()}>Try again</button>
            </div>
          ) : actions === null ? (
            <p className="drawing-recap-status">Loading drawing…</p>
          ) : (
            <Canvas
              isDrawer={false}
              color="#000000"
              brushWidth={4}
              tool="pen"
              solutionWord={entry.word}
              snapshotActions={actions}
            />
          )}
        </div>

        {entry.actionCount === 0 && actions !== null && (
          <p className="drawing-recap-empty">No drawing was captured for this turn.</p>
        )}

        <nav className="drawing-recap-navigation" aria-label="Drawing recap navigation">
          <button
            type="button"
            disabled={position === 0}
            onClick={() => changePosition(position - 1)}
          >
            Previous
          </button>
          <strong>{position + 1} of {entries.length}</strong>
          <button
            type="button"
            disabled={position === entries.length - 1}
            onClick={() => changePosition(position + 1)}
          >
            Next
          </button>
        </nav>
      </section>
    </main>
  );
}
