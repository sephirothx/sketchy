import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { BugIcon, ImageIcon } from "./icons";
import {
  BUG_AREAS,
  BUG_SEVERITIES,
  collectClientContext,
  submitBugReport,
  type BugReportArea,
  type BugReportSeverity,
} from "../lib/bugReports";
import { canCaptureScreen, captureScreenshot, type CapturedScreenshot } from "../lib/screenCapture";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { useCanvasBudgetStore } from "../store/canvasBudgetStore";
import { useToast } from "../lib/toast";

const MAX_DETAILS = 4000;

function bytes(size: number): string {
  return size < 1024 * 1024
    ? `${Math.round(size / 1024)} KB`
    : `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

/** Report that the app is broken, from anywhere, as anyone.
 *
 * The diagnostics are shown rather than merely mentioned. Everything gathered
 * is listed in a disclosure the player can open before they send, because the
 * honest version of "we collect some technical details" is the details.
 */
export function BugReportDialog({ onClose }: { onClose: () => void }) {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const areaId = useId();
  const severityId = useId();
  const summaryId = useId();
  const detailsId = useId();

  const [area, setArea] = useState<BugReportArea>("drawing_and_canvas");
  const [severity, setSeverity] = useState<BugReportSeverity>("major");
  const [summary, setSummary] = useState("");
  const [details, setDetails] = useState("");
  const [descriptionOnly, setDescriptionOnly] = useState(false);
  const [shot, setShot] = useState<CapturedScreenshot | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const notify = useToast().notify;
  const roomCode = useGameStore((state) => state.code);
  const roomState = useGameStore((state) => state.roomState);
  const phase = useGameStore((state) => state.phase);
  const roundNumber = useGameStore((state) => state.roundNumber);
  const totalRounds = useGameStore((state) => state.totalRounds);
  const players = useGameStore((state) => state.players);
  const drawerId = useGameStore((state) => state.drawerId);
  const playerId = useGameStore((state) => state.playerId);
  const theme = useSettingsStore((state) => state.theme);
  const soundEffects = useSettingsStore((state) => state.soundEffects);
  const confettiEffects = useSettingsStore((state) => state.confettiEffects);
  const brushCursor = useSettingsStore((state) => state.brushCursor);
  const fillAvailable = useCanvasBudgetStore((state) => state.fillAvailable);
  const strokeAvailable = useCanvasBudgetStore((state) => state.strokeAvailable);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: cancelRef });

  // A preview URL is a live handle on the blob; letting the dialog close
  // without releasing it leaks the whole screenshot for the tab's lifetime.
  useEffect(() => () => {
    if (shot) URL.revokeObjectURL(shot.previewUrl);
  }, [shot]);

  const captureSupported = canCaptureScreen();

  async function attach() {
    if (capturing) return;
    setCapturing(true);
    setError(null);
    try {
      // The whole overlay, scrim included: hiding only the card would leave a
      // dimmed page, and the point is the screen as it really looks.
      const captured = await captureScreenshot({ hide: overlayRef.current });
      // Null means they closed the picker, which is an answer, not a failure.
      if (captured) {
        if (shot) URL.revokeObjectURL(shot.previewUrl);
        setShot(captured);
        setDescriptionOnly(false);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not take the screenshot.");
    } finally {
      setCapturing(false);
    }
  }

  function discard() {
    if (shot) URL.revokeObjectURL(shot.previewUrl);
    setShot(null);
  }

  const context = collectClientContext({
    roomCode,
    roomState,
    phase,
    roundNumber,
    totalRounds,
    playerCount: players.length,
    isDrawer: Boolean(playerId && drawerId === playerId),
    settings: { theme, soundEffects, confettiEffects, brushCursor },
    canvasBudget: { fill: fillAvailable, stroke: strokeAvailable },
    screenshot: shot ? { width: shot.width, height: shot.height, byteSize: shot.byteSize } : null,
  });

  const rows: [string, string][] = [
    ["Build", `${context.buildSha} · ${String(context.commitDate)}`],
    ["Page", context.route],
    ["Room", roomCode ? `${roomCode} · round ${roundNumber} of ${totalRounds}` : "Not in a room"],
    ["Screen", `${window.innerWidth} × ${window.innerHeight} · ${window.devicePixelRatio}×`],
    ["Browser", navigator.userAgent],
    [
      "Connection",
      (() => {
        const connection = context.connection as { connected: boolean; reconnects: number };
        return `${connection.connected ? "connected" : "offline"} · ${connection.reconnects} reconnect${connection.reconnects === 1 ? "" : "s"} this visit`;
      })(),
    ],
  ];
  const errors = context.recentErrors;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !summary.trim() || !details.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await submitBugReport({
        area,
        severity,
        summary: summary.trim(),
        details: details.trim(),
        // The checkbox drops the diagnostics and the picture together: a
        // player who does not want the details sent did not mean "except the
        // photograph of my screen".
        clientContext: descriptionOnly ? undefined : context,
        roomCode: descriptionOnly ? null : roomCode,
        screenshot: descriptionOnly ? null : shot?.base64 ?? null,
      });
      notify("Thanks — your report is with the people who run Sketchy.", "success");
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not send the report.");
    } finally {
      setBusy(false);
    }
  }

  return <div ref={overlayRef} className="modal-overlay" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <div ref={dialogRef} className="modal-card bug-report-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <div className="bug-report-head">
        <span className="bug-report-mark" aria-hidden="true"><BugIcon size={20} /></span>
        <div>
          <h2 id={titleId} className="modal-title">Report a bug</h2>
          <p className="modal-body">Something broken, not something someone said. This reaches the people who run Sketchy — never other players.</p>
        </div>
      </div>

      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        <div className="bug-report-row">
          <div>
            <label htmlFor={areaId}>Where</label>
            <select id={areaId} className="settings-select" value={area} onChange={(event) => setArea(event.target.value as BugReportArea)}>
              {BUG_AREAS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor={severityId}>How bad</label>
            <select id={severityId} className="settings-select" value={severity} onChange={(event) => setSeverity(event.target.value as BugReportSeverity)}>
              {BUG_SEVERITIES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </div>
        </div>

        <label htmlFor={summaryId}>One line summary</label>
        <input id={summaryId} type="text" value={summary} required maxLength={200}
          placeholder="What went wrong, in one line"
          onChange={(event) => setSummary(event.target.value)} />

        <label htmlFor={detailsId}>What happened</label>
        <textarea id={detailsId} className="report-details" rows={4} value={details} required maxLength={MAX_DETAILS}
          placeholder="What you did, what you expected, what happened instead."
          onChange={(event) => setDetails(event.target.value)} />
        <p className="bug-report-counter">{details.length} / {MAX_DETAILS}</p>

        {captureSupported && (
          <section className="bug-report-shot">
            <div className="bug-report-shot-head">
              <ImageIcon size={15} aria-hidden="true" />
              <strong>Screenshot</strong>
              <span className="bug-report-optional">Optional</span>
            </div>
            {shot ? (
              <div className="bug-report-shot-body">
                <img src={shot.previewUrl} alt="The screenshot that will be sent with this report" />
                <div>
                  <p className="bug-report-shot-meta">{shot.width} × {shot.height} · {shot.contentType.replace("image/", "").toUpperCase()} · {bytes(shot.byteSize)}</p>
                  <p className="auth-hint">This dialog hides itself while the shot is taken, so you get the page behind it. Look at it before you send — you chose what to share.</p>
                  <div className="bug-report-shot-actions">
                    <button type="button" onClick={() => void attach()} disabled={capturing}>Replace</button>
                    <button type="button" className="bug-report-remove" onClick={discard}>Remove</button>
                  </div>
                </div>
              </div>
            ) : (
              <>
                <button type="button" className="bug-report-attach" onClick={() => void attach()} disabled={capturing}>
                  {capturing ? "Waiting for the picker…" : "Attach a screenshot"}
                </button>
                <p className="auth-hint">Opens your browser's own picker — choose this tab. This dialog hides itself while the shot is taken, so you get the page behind it.</p>
              </>
            )}
          </section>
        )}

        <details className="bug-report-context">
          <summary>What we send with this</summary>
          <dl className="bug-context">
            {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
          </dl>
          {errors.length > 0 && (
            <>
              <p className="bug-report-subhead">Recent client errors</p>
              <ul className="bug-console-log">
                {errors.map((entry, index) => (
                  <li key={`${entry.at}-${index}`}><span>{entry.at.slice(11, 19)}</span>{entry.message}</li>
                ))}
              </ul>
            </>
          )}
          <p className="auth-hint">The last 20 errors your browser recorded. No page addresses beyond the path, nothing you typed into chat, and never the prompt in play.</p>
        </details>

        <label className="bug-report-plain">
          <input type="checkbox" checked={descriptionOnly}
            onChange={(event) => setDescriptionOnly(event.target.checked)} />
          <span>Send my description only
            <span>Drops the details above and any screenshot. We will still read it, but the bug is much harder to reproduce.</span>
          </span>
        </label>

        {error && <p className="auth-error" role="alert">{error}</p>}

        <div className="confirmation-dialog-actions">
          <button ref={cancelRef} type="button" className="confirmation-cancel-button" disabled={busy} onClick={onClose}>Cancel</button>
          <button type="submit" className="modal-button" disabled={busy || !summary.trim() || !details.trim()}>{busy ? "Sending…" : "Send report"}</button>
        </div>
      </form>
    </div>
  </div>;
}
