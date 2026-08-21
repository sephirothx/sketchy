import { useCallback, useEffect, useRef, useState } from "react";
import type { CanvasRef } from "./Canvas";
import { CanvasSnapshot } from "./CanvasSnapshot";
import { decodeCanvasHistory } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useEscapeLayer } from "../hooks/useFocusTrap";
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
  const canvasRef = useRef<CanvasRef | null>(null);
  const entry = entries[position];

  const changePosition = useCallback((nextPosition: number) => {
    loadGenerationRef.current += 1;
    setActions(null);
    setError(null);
    setPosition(Math.max(0, Math.min(entries.length - 1, nextPosition)));
  }, [entries.length]);

  // The room tells us up front which bitmaps it still holds, so a dropped one
  // is a state to render rather than a request to make and watch fail.
  const unavailable = Boolean(entry) && entry.available === false;

  const loadDrawing = useCallback(async () => {
    if (!entry || entry.available === false) return;
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

  useEscapeLayer(true, onClose);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "ArrowLeft" && position > 0) {
        changePosition(position - 1);
      }
      if (event.key === "ArrowRight" && position < entries.length - 1) {
        changePosition(position + 1);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [changePosition, entries.length, position]);

  if (!entry) return null;

  return (
    <main className="drawing-recap" aria-labelledby="drawing-recap-title">
      <section className="drawing-recap-card">
        <header className="drawing-recap-header">
          <div>
            <p className="drawing-recap-kicker">Drawing recap</p>
            <h1 id="drawing-recap-title">{entry.prompt}</h1>
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
          <div className="drawing-recap-header-actions">
            <button
              type="button"
              className="drawing-recap-download"
              disabled={actions === null || unavailable || Boolean(error)}
              onClick={() => canvasRef.current?.saveImage()}
            >
              Save image
            </button>
            <button type="button" className="drawing-recap-close" onClick={onClose}>
              Close
            </button>
          </div>
        </header>

        <div
          className="drawing-recap-canvas"
          aria-busy={actions === null && !error && !unavailable}
        >
          {unavailable ? (
            <div className="drawing-recap-status">
              <p>This drawing was not kept.</p>
              <p className="drawing-recap-status-detail">
                The room ran out of room for it. Later turns were kept instead.
              </p>
            </div>
          ) : error ? (
            <div className="drawing-recap-status" role="alert">
              <p>{error}</p>
              <button type="button" onClick={() => void loadDrawing()}>Try again</button>
            </div>
          ) : actions === null ? (
            <p className="drawing-recap-status">Loading drawing…</p>
          ) : (
            <CanvasSnapshot
              ref={canvasRef}
              actions={actions}
              downloadPrompt={entry.prompt}
              label={`Drawing of ${entry.prompt} by ${entry.drawerNickname}`}
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
