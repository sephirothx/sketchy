import { useId, useState, type FormEvent } from "react";
import {
  BrushIcon,
  BugDoodle,
  FillIcon,
  RectIcon,
  UndoIcon,
  Wordmark,
} from "../components/icons";
import {
  collectClientContext,
  roomSummary,
  submitBugReport,
  type CollectedContext,
} from "../lib/bugReports";
import {
  composeDetails,
  playerTextBudget,
  prefillCrashReport,
  type CrashScope,
} from "../lib/crashReport";
import { useCanvasBudgetStore } from "../store/canvasBudgetStore";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

/** Read something that may be the very thing that broke. The page must render
    with nothing rather than not render. */
function safely<T>(read: () => T, fallback: T): T {
  try {
    return read();
  } catch {
    return fallback;
  }
}

interface Props {
  scope: CrashScope;
  error: unknown;
  /** Null until the boundary's `componentDidCatch` has run; see `CaughtCrash`. */
  componentStack: string | null;
  onReload: () => void;
  onBackToLobby: () => void;
}

/** What a screen shows when its own code throws.

Drawn like the not-found page - the canvas is the illustration, a bug on it -
because it is the same object seen from the other side: a page nobody meant
to draw. Under it a bug report that is already written: the player has one
thing to add, what they were doing, and may send it with or without the
details, exactly as in the dialog they would otherwise have had to find
(R-BUG-01). The two ways out - Reload and Back to lobby - appear once the
report has gone, because a crash nobody hears about is a crash that stays.
They also appear if sending fails: a page that cannot be left is worse than a
report that was not filed.

Router-free on purpose: the boundary around `<App>` sits outside the router, so
the ways out arrive as callbacks and the header is the wordmark alone. Every
store read is guarded - the store may be what crashed - and a throw in here is
caught by nothing. */
export function CrashPage({ scope, error, componentStack, onReload, onBackToLobby }: Props) {
  const reportTitleId = useId();
  const detailsId = useId();
  const [playerText, setPlayerText] = useState("");
  const [descriptionOnly, setDescriptionOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const room = safely(() => {
    const state = useGameStore.getState();
    return {
      code: state.code,
      roomState: state.roomState,
      phase: state.phase,
      roundNumber: state.roundNumber,
      totalRounds: state.totalRounds,
      playerCount: state.players.length,
      isDrawer: Boolean(state.playerId && state.drawerId === state.playerId),
    };
  }, null);
  const settings = safely(() => {
    const state = useSettingsStore.getState();
    return {
      theme: state.theme,
      soundEffects: state.soundEffects,
      confettiEffects: state.confettiEffects,
      brushCursor: state.brushCursor,
    };
  }, null);
  const canvasBudget = safely(() => {
    const state = useCanvasBudgetStore.getState();
    return { fill: state.fillAvailable, stroke: state.strokeAvailable };
  }, null);

  const phase = room?.phase ?? null;
  const roomCode = room?.code ?? null;
  const prefill = prefillCrashReport({
    scope,
    route: window.location.pathname,
    error,
    componentStack,
    phase,
  });
  // Gathered on every render rather than once: the boundary writes the crash
  // into the error tail *after* the first render of this page (React commits
  // the fallback, then calls componentDidCatch), so what is listed under
  // "What we send" has to be re-read to show the crash on top - and it is
  // what is sent, because submit reads the latest.
  const context: CollectedContext | null = safely(
    () => collectClientContext({
      roomCode,
      roomState: room?.roomState,
      phase,
      roundNumber: room?.roundNumber,
      totalRounds: room?.totalRounds,
      playerCount: room?.playerCount,
      isDrawer: room?.isDrawer,
      settings,
      canvasBudget,
    }),
    null,
  );

  const budget = playerTextBudget(prefill.diagnosticBlock);
  const nothingToSend = descriptionOnly && !playerText.trim();
  const waysOutOpen = sent || failure !== null;

  const rows: [string, string][] = context
    ? [
      [ui.crashPage.summary, prefill.summary],
      [ui.crashPage.build, `${context.buildSha} · ${String(context.commitDate)}`],
      [ui.crashPage.page, context.route],
      [ui.crashPage.room, roomSummary(roomCode, room?.roundNumber, room?.totalRounds)],
      [ui.crashPage.screen, `${window.innerWidth} × ${window.innerHeight} · ${window.devicePixelRatio}×`],
      [ui.crashPage.browser, navigator.userAgent],
      [
        ui.crashPage.connection,
        (() => {
          const connection = context.connection as { connected: boolean; reconnects: number };
          return ui.bugReportDialog.connectionSummary(connection);
        })(),
      ],
    ]
    : [[ui.crashPage.summary, prefill.summary]];
  // Newest first here, unlike the dialog: the crash is the entry to read.
  const errors = [...(context?.recentErrors ?? [])].reverse();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || sent || nothingToSend) return;
    setBusy(true);
    setFailure(null);
    try {
      await submitBugReport({
        area: prefill.area,
        severity: prefill.severity,
        summary: prefill.summary,
        // The checkbox drops the diagnostic block with the context: the words
        // alone really means the words alone.
        details: composeDetails(playerText, descriptionOnly ? "" : prefill.diagnosticBlock),
        clientContext: descriptionOnly || !context ? undefined : context,
        roomCode: descriptionOnly ? null : roomCode,
      });
      setSent(true);
    } catch (caught) {
      setFailure(refusalText(caught, ui.crashPage.couldNotSendReport));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="not-found-page crash-page">
      <header className="lobby-header crash-header">
        <Wordmark size={34} decorative />
      </header>
      <main className="surface-card not-found-card crash-card">
        <div className="not-found-canvas">
          <BugDoodle />
        </div>
        <div className="not-found-tools" aria-hidden="true">
          <span><BrushIcon size={18} /></span>
          <span><FillIcon size={18} /></span>
          <span><RectIcon size={18} /></span>
          <span><UndoIcon size={18} /></span>
        </div>
        <h1>{ui.crashPage.bugCrawledOntoPage}</h1>
        <p>
          {scope === "room"
            ? ui.crashPage.thisRoomSScreenHit
            : ui.crashPage.thisScreenHitAnError}
        </p>
        <form className="auth-form crash-report" aria-labelledby={reportTitleId} onSubmit={(event) => void submit(event)}>
          <h2 id={reportTitleId}>{ui.crashPage.helpUsSquash}</h2>
          <p className="auth-hint">
            {ui.crashPage.reportReadySendErrorWhatThis}
          </p>

          <label htmlFor={detailsId}>
            {ui.crashPage.whatWereYouDoing} <span className="crash-optional">{ui.crashPage.optional}</span>
          </label>
          <textarea
            id={detailsId}
            className="report-details"
            rows={3}
            value={playerText}
            maxLength={budget}
            disabled={sent}
            placeholder={ui.crashPage.lastThingYouClickedTypedIf}
            onChange={(event) => setPlayerText(event.target.value)}
          />

          <details className="bug-report-context">
            <summary>{descriptionOnly ? ui.crashPage.whatWeAreLeavingOut : ui.crashPage.whatWeSendWithThis}</summary>
            <dl className="bug-context">
              {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
            {errors.length > 0 && (
              <>
                <p className="bug-report-subhead">{ui.crashPage.recentClientErrorsNewestFirst}</p>
                <ul className="bug-console-log">
                  {errors.map((entry, index) => (
                    <li key={`${entry.at}-${index}`}><span>{entry.at.slice(11, 19)}</span>{entry.message}</li>
                  ))}
                </ul>
              </>
            )}
            <p className="auth-hint">
              {descriptionOnly
                ? ui.crashPage.noneOfThisIsBeing
                : ui.crashPage.theCrashTheLast20}
            </p>
          </details>

          <label className="bug-report-plain">
            <input
              type="checkbox"
              checked={descriptionOnly}
              disabled={sent}
              onChange={(event) => setDescriptionOnly(event.target.checked)}
            />
            <span>{ui.crashPage.sendMyDescriptionOnly}
              <span>{ui.crashPage.dropsDetailsAboveWeWillStill}</span>
            </span>
          </label>

          {failure && <p className="auth-error" role="alert">{failure}</p>}
          {sent ? (
            <p className="crash-sent" role="status">{ui.crashPage.thanksYourReportWithPeopleWho}</p>
          ) : (
            <button type="submit" className="modal-button" disabled={busy || nothingToSend}>
              {busy ? (failure ? ui.crashPage.sendingAgain : ui.crashPage.sending) : (failure ? ui.crashPage.trySendingAgain : ui.crashPage.sendReport)}
            </button>
          )}
        </form>

        {waysOutOpen && (
          <div className="crash-actions">
            <button type="button" className="btn btn-primary" onClick={onReload}>
              {ui.crashPage.reload}
            </button>
            <button type="button" className="btn btn-secondary" onClick={onBackToLobby}>
              {ui.crashPage.backLobby}
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
