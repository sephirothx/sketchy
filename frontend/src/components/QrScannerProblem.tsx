import { ui } from "../content/ui/index.ts";

/**
 * Why Join by code shows no camera view, and the ways on from there (#1530).
 *
 * In a module of its own, outside the scanner's lazily fetched chunk: it is
 * also what shows when that chunk is the thing that failed to arrive.
 */
export function QrScannerProblem({
  title,
  body,
  retryLabel,
  onRetry,
  onTypeInstead,
}: {
  title: string;
  body: string;
  retryLabel?: string;
  /** Omitted where there is nothing to retry - a device with no camera. */
  onRetry?: () => void;
  onTypeInstead: () => void;
}) {
  return (
    <div className="qr-scanner-problem" role="alert">
      <strong>{title}</strong>
      <p>{body}</p>
      <div className="qr-scanner-actions">
        {onRetry && (
          <button type="button" className="btn btn-secondary" onClick={onRetry}>
            {retryLabel}
          </button>
        )}
        <button type="button" className="btn btn-primary" onClick={onTypeInstead}>
          {ui.qrScanner.typeTheCode}
        </button>
      </div>
    </div>
  );
}

/** What a scanner or decoder chunk that did not arrive offers: a reload,
    since a browser keeps a failed dynamic import for the life of the page and
    a second `import()` of it fails at once (the reasoning LazyOverlay.tsx
    gives for its own notice). */
export function ScannerNotLoaded({ onTypeInstead }: { onTypeInstead: () => void }) {
  return (
    <QrScannerProblem
      title={ui.qrScanner.scannerNotLoaded}
      body={ui.qrScanner.scannerNotLoadedBody}
      retryLabel={ui.qrScanner.reload}
      onRetry={() => window.location.reload()}
      onTypeInstead={onTypeInstead}
    />
  );
}
