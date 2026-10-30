import { useEffect, useRef, useState } from "react";
import { roomCodeFromScan } from "../lib/scannedRoomCode";
import { QrScannerProblem, ScannerNotLoaded } from "./QrScannerProblem";
import { ui } from "../content/ui/index.ts";

/** The part of the Barcode Detection API used here; not in TypeScript's DOM
    library yet. */
interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>;
}
interface BarcodeDetectorClass {
  new (options: { formats: string[] }): BarcodeDetectorLike;
  getSupportedFormats(): Promise<string[]>;
}

type Read = (video: HTMLVideoElement) => Promise<string[]>;

/**
 * The browser's own QR reader where it has one (Chrome, Android), and jsQR
 * otherwise - Safari has none - fetched here, when somebody presses Scan,
 * rather than by every visit to the lobby (#1530).
 */
async function makeReader(): Promise<Read> {
  const Detector = (window as unknown as { BarcodeDetector?: BarcodeDetectorClass }).BarcodeDetector;
  if (Detector) {
    try {
      if ((await Detector.getSupportedFormats()).includes("qr_code")) {
        const detector = new Detector({ formats: ["qr_code"] });
        return async (video) => (await detector.detect(video)).map((code) => code.rawValue);
      }
    } catch {
      // A detector that cannot say what it reads is no detector: fall through.
    }
  }
  const { default: jsQR } = await import("jsqr");
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { willReadFrequently: true });
  return async (video) => {
    if (!context || !video.videoWidth) return [];
    // A 640px frame reads a code held at arm's length and keeps a phone's
    // main thread free: the full camera frame is four times the work.
    const scale = Math.min(1, 640 / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const frame = context.getImageData(0, 0, canvas.width, canvas.height);
    const found = jsQR(frame.data, frame.width, frame.height, { inversionAttempts: "dontInvert" });
    return found ? [found.data] : [];
  };
}

/** Why there is no camera view: refused by the player or the browser, none
    on the device, one that would not start (another app holding it), or a
    decoder that could not be fetched - which only a reload can fetch again. */
type Problem = "blocked" | "none" | "failed" | "unloaded";

/**
 * Join by code's camera view (#1530): reads a room's QR code and hands the
 * code over the moment it is read, so the sheet can join with nothing else
 * pressed. A code for anything but a room is said so and
 * ignored, and scanning goes on (lib/scannedRoomCode.ts).
 *
 * The camera runs only while this is on screen and the tab is visible: it
 * stops on a read, when the sheet goes back to typing or closes, and while
 * the tab is hidden, and starts again when it returns.
 */
export default function QrScanner({
  onCode,
  onTypeInstead,
}: {
  onCode: (code: string) => void;
  onTypeInstead: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const onCodeRef = useRef(onCode);
  useEffect(() => {
    onCodeRef.current = onCode;
  });
  const [attempt, setAttempt] = useState(0);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [notARoom, setNotARoom] = useState(false);
  const [hidden, setHidden] = useState(() => document.visibilityState === "hidden");

  useEffect(() => {
    const onVisibility = () => setHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    // Not while a problem is up: a tab coming back from the browser's
    // settings would otherwise ask for the camera again behind the message,
    // with no view to show it in. Try again is what asks.
    if (hidden || problem) return;
    let stopped = false;
    let stream: MediaStream | null = null;
    let timer = 0;
    let lastRefused = "";
    const stop = () => {
      stopped = true;
      window.clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
    };

    void (async () => {
      // The decoder before the camera: a chunk that does not arrive should
      // not have lit the camera for nothing.
      let read: Read;
      try {
        read = await makeReader();
      } catch {
        if (!stopped) setProblem("unloaded");
        return;
      }
      if (stopped) return;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
      } catch (error) {
        if (stopped) return;
        const name = (error as DOMException)?.name;
        setProblem(
          name === "NotAllowedError" || name === "SecurityError"
            ? "blocked"
            : name === "NotFoundError" || name === "OverconstrainedError"
              ? "none"
              : "failed",
        );
        return;
      }
      if (stopped) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const video = videoRef.current;
      if (!video) {
        stop();
        return;
      }
      video.srcObject = stream;
      await video.play().catch(() => {});
      if (stopped) return;
      const tick = async () => {
        if (stopped) return;
        let codes: string[] = [];
        try {
          if (video.readyState >= 2) codes = await read(video);
        } catch {
          // One frame that could not be read is not worth stopping for.
        }
        if (stopped) return;
        for (const text of codes) {
          const code = roomCodeFromScan(text);
          if (code) {
            stop();
            onCodeRef.current(code);
            return;
          }
          if (text !== lastRefused) {
            lastRefused = text;
            setNotARoom(true);
          }
        }
        timer = window.setTimeout(() => void tick(), 200);
      };
      void tick();
    })();

    return stop;
  }, [attempt, hidden, problem]);

  if (problem === "unloaded") return <ScannerNotLoaded onTypeInstead={onTypeInstead} />;
  if (problem) {
    const [title, body] = {
      blocked: [ui.qrScanner.cameraBlocked, ui.qrScanner.allowTheCamera],
      none: [ui.qrScanner.noCamera, ui.qrScanner.noCameraOffered],
      failed: [ui.qrScanner.cameraFailed, ui.qrScanner.cameraFailedBody],
    }[problem];
    return (
      <QrScannerProblem
        title={title}
        body={body}
        retryLabel={ui.qrScanner.tryAgain}
        onRetry={
          problem === "none"
            ? undefined
            : () => {
                // The view first, so the video is there when the stream is.
                setProblem(null);
                setAttempt((n) => n + 1);
              }
        }
        onTypeInstead={onTypeInstead}
      />
    );
  }

  return (
    <div className="qr-scanner">
      <div className="qr-scanner-view">
        <video ref={videoRef} playsInline muted aria-label={ui.qrScanner.cameraView} />
        <span className="qr-scanner-frame" aria-hidden="true" />
      </div>
      {/* One live region, mounted with the view, whose words change: one
          that arrives already holding its text is often not read out. */}
      <p className={notARoom ? "qr-scanner-warning" : "qr-scanner-hint"} role="status">
        {notARoom ? ui.qrScanner.notARoom : ui.qrScanner.pointTheCamera}
      </p>
    </div>
  );
}
