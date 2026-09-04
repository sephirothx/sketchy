import { useEffect, useId, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import {
  clampCrop,
  cropRect,
  initialCrop,
  maxZoomFor,
  viewportPlacement,
  type CropState,
} from "../lib/avatarCrop.ts";
import { AvatarInputError, encodePicture, loadPicture, type LoadedPicture } from "../lib/avatars";

/** The square the player frames the picture in, in CSS pixels. */
export const CROP_VIEWPORT = 272;
/** One wheel notch, and one keyboard press, zooms by this much. */
const ZOOM_STEP = 1.1;
/** One arrow press moves the framing by this many viewport pixels. */
const PAN_STEP = 12;

/**
 * Framing a picture before it becomes the player's (#573).
 *
 * The chosen file is shown behind a square viewport with a round mask over
 * it, because the disc is how everybody will see it. Drag to move it, the
 * slider or the wheel to zoom, then "Use picture" cuts exactly the square
 * shown and encodes it (lib/avatars.ts). Nothing leaves the browser until
 * then, and nothing about the framing does: only the 256-square is sent.
 */
export function PictureCropDialog({
  file,
  onUse,
  onCancel,
}: {
  file: File;
  /** Upload the encoded picture; a throw is shown here and the dialog stays. */
  onUse: (base64: string) => Promise<void>;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const useButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const sliderId = useId();

  const [loaded, setLoaded] = useState<LoadedPicture | null>(null);
  const [crop, setCrop] = useState<CropState>({ zoom: 1, centerX: 0, centerY: 0 });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ pointerId: number; x: number; y: number; from: CropState } | null>(null);

  useFocusTrap(dialogRef, { onEscape: onCancel, initialFocusRef: useButtonRef });

  useEffect(() => {
    let picture: LoadedPicture | null = null;
    let active = true;
    void loadPicture(file)
      .then((result) => {
        if (!active) {
          result.release();
          return;
        }
        picture = result;
        setLoaded(result);
        setCrop(initialCrop(result.width, result.height));
      })
      .catch((failure: unknown) => {
        if (active) {
          setError(
            failure instanceof AvatarInputError
              ? failure.message
              : "That file could not be read as a picture.",
          );
        }
      });
    return () => {
      active = false;
      picture?.release();
    };
  }, [file]);

  const width = loaded?.width ?? 1;
  const height = loaded?.height ?? 1;
  const maxZoom = loaded ? maxZoomFor(width, height) : 1;
  const placement = viewportPlacement(width, height, crop, CROP_VIEWPORT);

  function frame(next: CropState) {
    setCrop(clampCrop(width, height, next));
  }

  function zoomBy(factor: number) {
    frame({ ...crop, zoom: crop.zoom * factor });
  }

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (!loaded || busy) return;
    event.preventDefault();
    viewportRef.current?.setPointerCapture(event.pointerId);
    drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, from: crop };
    setDragging(true);
  }

  function moveDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    // The picture follows the finger: moving it right means the framed
    // centre moves left in the source.
    frame({
      ...current.from,
      centerX: current.from.centerX - (event.clientX - current.x) / placement.scale,
      centerY: current.from.centerY - (event.clientY - current.y) / placement.scale,
    });
  }

  function endDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    setDragging(false);
    viewportRef.current?.releasePointerCapture(event.pointerId);
  }

  function keyFrame(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!loaded) return;
    const step = PAN_STEP / placement.scale;
    const moves: Record<string, () => void> = {
      ArrowLeft: () => frame({ ...crop, centerX: crop.centerX - step }),
      ArrowRight: () => frame({ ...crop, centerX: crop.centerX + step }),
      ArrowUp: () => frame({ ...crop, centerY: crop.centerY - step }),
      ArrowDown: () => frame({ ...crop, centerY: crop.centerY + step }),
      "+": () => zoomBy(ZOOM_STEP),
      "=": () => zoomBy(ZOOM_STEP),
      "-": () => zoomBy(1 / ZOOM_STEP),
    };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    move();
  }

  async function use() {
    if (!loaded || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { base64 } = encodePicture(loaded.image, cropRect(width, height, crop));
      await onUse(base64);
    } catch (failure) {
      setError(
        failure instanceof AvatarInputError || failure instanceof ApiError
          ? failure.message
          : "Could not set that picture. Please try again.",
      );
      setBusy(false);
    }
  }

  // The wheel listener is attached by hand: React's is passive, and a
  // passive listener cannot stop the page behind the dialog from scrolling.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !loaded) return;
    function wheel(event: WheelEvent) {
      event.preventDefault();
      setCrop((current) =>
        clampCrop(width, height, {
          ...current,
          zoom: current.zoom * (event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP),
        }),
      );
    }
    viewport.addEventListener("wheel", wheel, { passive: false });
    return () => viewport.removeEventListener("wheel", wheel);
  }, [loaded, width, height]);

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card picture-crop-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">
          Frame your picture
        </h3>
        <p className="modal-body">
          Drag to move it and zoom to get closer. The circle is what everyone sees.
        </p>

        <div
          ref={viewportRef}
          className="picture-crop-viewport"
          style={{ width: CROP_VIEWPORT, height: CROP_VIEWPORT }}
          role="img"
          aria-label="The picture, framed. Arrow keys move it; plus and minus zoom."
          tabIndex={loaded ? 0 : -1}
          data-dragging={dragging ? "" : undefined}
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onKeyDown={keyFrame}
        >
          {loaded && (
            <img
              src={loaded.image.src}
              alt=""
              draggable={false}
              style={{
                width: width * placement.scale,
                height: height * placement.scale,
                left: placement.left,
                top: placement.top,
              }}
            />
          )}
          <span className="picture-crop-mask" aria-hidden="true" />
        </div>

        <div className="picture-crop-zoom">
          <label htmlFor={sliderId}>Zoom</label>
          <input
            id={sliderId}
            type="range"
            min={1}
            max={maxZoom}
            step={0.01}
            value={crop.zoom}
            disabled={!loaded || maxZoom <= 1}
            onChange={(event) => frame({ ...crop, zoom: Number(event.target.value) })}
          />
        </div>

        {error && (
          <p className="auth-error" role="alert">
            {error}
          </p>
        )}

        <button
          ref={useButtonRef}
          type="button"
          className="modal-button"
          disabled={!loaded || busy}
          onClick={() => void use()}
        >
          {busy ? "Uploading…" : "Use picture"}
        </button>
        <button type="button" className="modal-dismiss" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
