import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { CanvasSnapshot } from "./CanvasSnapshot";
import { decodeCanvasHistory, type DecodedCanvasAction } from "../lib/canvasHistory";

/** A drawing kept with a report, drawn from its stored frame.

One component for everyone the drawing is shown to - the moderator reading
the case, the player being warned, the player being suspended - with the
caller saying where the bytes come from. Fetched on mount rather than with
the payload that named it: the bytes are the one heavy part, and the
decoder is the same one a live canvas uses, so what is shown is what the
room saw. Mount it under a key of the report when the case can change. */
export function ReportedDrawing({
  load,
  label,
  caption,
  className,
  testId,
}: {
  load: () => Promise<ArrayBuffer>;
  label: string;
  caption?: ReactNode;
  className?: string;
  testId?: string;
}) {
  const [actions, setActions] = useState<DecodedCanvasAction[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stale = false;
    load()
      .then((bytes) => {
        if (stale) return;
        const decoded = decodeCanvasHistory(bytes);
        if (decoded) setActions(decoded);
        else setError("This drawing could not be decoded.");
      })
      .catch(() => {
        if (!stale) setError("The drawing could not be loaded.");
      });
    return () => {
      stale = true;
    };
    // `load` is a closure over ids the parent keys this component by.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <figure className={`reported-drawing${className ? ` ${className}` : ""}`} data-testid={testId}>
      {actions ? (
        <CanvasSnapshot actions={actions} label={label} />
      ) : (
        <p className="reported-drawing-status" role={error ? "alert" : "status"}>
          {error ?? "Loading the drawing…"}
        </p>
      )}
      {caption && <figcaption className="reported-drawing-caption">{caption}</figcaption>}
    </figure>
  );
}
