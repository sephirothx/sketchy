import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AuthDialog } from "../components/AccountMenu";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { AppHeader } from "../components/AppHeader";
import { DrawingReactionControl } from "../components/DrawingReactionControl";
import { ReplayCanvas } from "../components/ReplayCanvas";
import { ReportDrawingDialog } from "../components/ReportDrawingDialog";
import {
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClockIcon,
  CopyIcon,
  FlagIcon,
  ImageIcon,
  UndoIcon,
  UserIcon,
  XIcon,
} from "../components/icons";
import { EmptyState } from "../components/ui/EmptyState";
import { soloCopyFor } from "../content/solo/index.ts";
import { intlLocale } from "../content/ui/format.ts";
import { interfaceLocale, ui } from "../content/ui/index.ts";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { ApiError } from "../lib/api";
import { authSubmitter, type AuthMode } from "../lib/authSubmit";
import { formatDate } from "../lib/clock";
import { decodeCanvasHistory, type DecodedCanvasAction } from "../lib/canvasHistory";
import { judge } from "../lib/guessJudge";
import { reactionEligibility } from "../lib/reactions";
import { refusalText } from "../lib/refusals.ts";
import {
  decodeSoloForms,
  fetchSoloDrawing,
  fetchSoloMonth,
  fetchSoloRun,
  fetchSoloSummary,
  localDateKey,
  openDaily,
  reactToServe,
  reportServe,
  serveNext,
  settleServe,
  shareServe,
  startFreeRun,
  type SoloActiveRun,
  type SoloCalendarDay,
  type SoloDailyMark,
  type SoloDailyResult,
  type SoloDailyStats,
  type SoloMonth,
  type SoloOutcome,
  type SoloRun,
  type SoloServe,
  type SoloShare,
  type SoloSummary,
} from "../lib/solo";
import {
  SOLO_CLOCK_SECONDS,
  SOLO_REPLAY_SECONDS,
  dailyMarks,
  type DailyMark,
  forgetServeStart,
  serveStartedAt,
  untilLocalMidnight,
  watchLocalDate,
} from "../lib/soloPlay";
import { useToast } from "../lib/toast";
import { useAuthStore } from "../store/authStore";
import "../styles/lazy/solo.css";

/** The page's own words, in the language the interface is in now: read at
    each render, as `ui` is, so a language switch reaches them too. */
function words() {
  return soloCopyFor(interfaceLocale());
}

/**
 * Solo, `/solo` (#1434): a game of one. A registered player guesses drawings
 * from public games they were not in - the Daily, five the same for
 * everybody, or a free run of 5, 10 or unlimited - and never learns who drew
 * them. Play is local: the drawing replays over 20 s inside a 30 s clock,
 * each guess is judged here by the port of the room's judge, and only what a
 * drawing came to is reported (R-SOLO-05, R-SOLO-06).
 */
export function SoloPage() {
  useDocumentTitle(ui.solo.solo);
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const register = useAuthStore((state) => state.register);
  const login = useAuthStore((state) => state.login);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const signedOut = hasResolved && user === null;
  const guest = Boolean(user?.isAnonymous);

  const [summary, setSummary] = useState<SoloSummary | null>(null);
  const [run, setRun] = useState<SoloRun | null>(null);
  // Why the last thing the player tried did not happen - cleared by their
  // next action - apart from why the page itself could not load, which the
  // next load that works clears.
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The drawing just settled, shown until Next: what it was, how long it
  // took, and what the player can do with it now.
  const [card, setCard] = useState<{
    serve: SoloServe;
    seconds: number;
    drawing: DecodedCanvasAction[] | null;
  } | null>(null);
  // The drawing in play, decoded: the card shows it as it settles, so it is
  // not fetched again.
  const shownDrawing = useRef<{ serveId: string; actions: DecodedCanvasAction[] } | null>(null);
  const [summaryOf, setSummaryOf] = useState<SoloRun | null>(null);
  // The best for the run's length before it ended: a new best beats it.
  const [previousBest, setPreviousBest] = useState<number | undefined>(undefined);
  // The player's own date, watched: the Daily rolls over at their midnight,
  // and a page left open across it - or a tab woken after it - must offer
  // the new one rather than yesterday's result (R-SOLO-12, #1495 review).
  const [today, setToday] = useState(() => localDateKey());
  useEffect(() => watchLocalDate(setToday), []);

  const loadSummary = useCallback(async () => {
    try {
      // An action's error stays: a refreshed page does not answer why it
      // did not happen. Their next action clears it.
      setSummary(await fetchSoloSummary(localDateKey()));
      setLoadError(null);
    } catch (failure) {
      setLoadError(refusalText(failure, words().couldNotLoad));
    }
  }, []);

  useEffect(() => {
    if (!hasResolved || !user || user.isAnonymous) return;
    let cancelled = false;
    fetchSoloSummary(today)
      .then((loaded) => {
        if (cancelled) return;
        setSummary(loaded);
        setLoadError(null);
      })
      .catch((failure) => {
        if (!cancelled) setLoadError(refusalText(failure, words().couldNotLoad));
      });
    return () => {
      cancelled = true;
    };
  }, [hasResolved, user, today]);

  const begin = async (action: () => Promise<SoloRun>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      let next = await action();
      if (next.state !== "active" && next.mode === "free") {
        // Ended elsewhere since the page last looked - finished, or started
        // over in another tab: its row was stale, and the page catches up.
        void loadSummary();
        return;
      }
      if (next.mode === "free" && !next.serves.some((serve) => serve.outcome === null)) {
        const served = await serveNext(next.runId, 2);
        next = { ...next, serves: [...next.serves, ...served] };
      }
      setCard(null);
      setSummaryOf(null);
      setRun(next);
    } catch (failure) {
      setError(refusalText(failure, words().couldNotLoad));
      // What was offered may have changed under it: a run ended by Start
      // over before the pool turned out empty, say.
      void loadSummary();
    } finally {
      setBusy(false);
    }
  };

  const settled = async (serve: SoloServe, outcome: SoloOutcome, seconds: number) => {
    if (!run) return;
    let answer: { serve: SoloServe; run: SoloRun };
    try {
      answer = await settleServe(serve.serveId, outcome, seconds);
    } catch (failure) {
      // A report that reached the server and lost its answer is refused the
      // second time (R-SOLO-06), and so is one for a run ended in another
      // tab: the server's run says which it was.
      if (!(failure instanceof ApiError) || (failure.status !== 404 && failure.status !== 409)) throw failure;
      const fresh = await fetchSoloRun(run.runId).catch(() => null);
      if (!fresh) throw failure;
      const kept = fresh.serves.find((candidate) => candidate.serveId === serve.serveId);
      if (!kept || kept.outcome === null) {
        if (fresh.state === "active") throw failure;
        // Ended elsewhere - abandoned, or an unlimited run's miss in another
        // tab - and this drawing went with it: what the run came to is all
        // there is to show.
        forgetServeStart(serve.serveId);
        setPreviousBest(summary?.bests[lengthKey(fresh.length as SoloLength)]);
        setCard(null);
        setSummaryOf(fresh);
        setRun(null);
        void loadSummary();
        return;
      }
      answer = { serve: kept, run: fresh };
    }
    forgetServeStart(serve.serveId);
    setRun((current) =>
      current?.runId === answer.run.runId
        ? {
            ...answer.run,
            // The server's list, and any drawing held ready that a top-up
            // added after the server read it.
            serves: [
              ...answer.run.serves,
              ...current.serves.filter(
                (held) => !answer.run.serves.some((listed) => listed.serveId === held.serveId),
              ),
            ].sort((left, right) => left.position - right.position),
          }
        : current,
    );
    const shown = shownDrawing.current;
    setCard({ serve: answer.serve, seconds, drawing: shown?.serveId === serve.serveId ? shown.actions : null });
  };

  const next = async () => {
    if (!run || busy) return;
    if (run.state !== "active") {
      setPreviousBest(summary?.bests[lengthKey(run.length as SoloLength)]);
      setCard(null);
      setSummaryOf(run);
      setRun(null);
      void loadSummary();
      return;
    }
    const open = run.serves.filter((serve) => serve.outcome === null).length;
    if (run.mode !== "free" || open > 0) {
      setCard(null);
      // One held ready and none behind it: the next is fetched while this
      // one is played, so it is on screen the moment it is needed.
      if (run.mode === "free" && open === 1) void topUp(run.runId, 1);
      return;
    }
    // Nothing held ready: the card stays, and nothing else can start, until
    // the next drawing is here.
    setBusy(true);
    try {
      const served = await serveNext(run.runId, 2);
      setRun((current) =>
        current?.runId === run.runId ? { ...current, serves: [...current.serves, ...served] } : current,
      );
      setCard(null);
    } catch (failure) {
      setError(refusalText(failure, words().couldNotLoad));
      setCard(null);
      setRun(null);
      void loadSummary();
    } finally {
      setBusy(false);
    }
  };

  const topUp = async (runId: string, count: 1 | 2) => {
    try {
      const served = await serveNext(runId, count);
      setRun((current) =>
        current?.runId === runId
          ? {
              ...current,
              serves: [
                ...current.serves,
                ...served.filter((serve) => !current.serves.some((held) => held.serveId === serve.serveId)),
              ],
            }
          : current,
      );
    } catch {
      // Nothing more to hold ready: Next asks again when it is needed.
    }
  };

  // Today's Daily, after a 404 on one of its drawings: the set may have
  // replaced it for everybody (R-SOLO-13), which opening it again picks up.
  const reopenDaily = async () => {
    if (!run || run.mode !== "daily" || !run.dailyDate) return;
    try {
      const fresh = await openDaily(run.dailyDate);
      setRun((current) => (current?.runId === fresh.runId ? fresh : current));
    } catch {
      // The drawing stays as it is, and can be given up.
    }
  };

  const playing = run?.serves.find((serve) => serve.outcome === null) ?? null;

  return (
    <div className="page solo-page" data-testid="solo-page">
      <AppHeader backLabel={words().backToLobby} />

      {signedOut || guest ? (
        <>
          <div className="solo-head">
            <h1>{ui.solo.solo}</h1>
            <p>{words().intro}</p>
          </div>
          <EmptyState
            testId="solo-account-required"
            title={signedOut ? words().signInToPlay : words().accountToPlay}
            body={signedOut ? words().signInBody : words().accountBody}
            action={
              signedOut ? (
                <button type="button" className="btn btn-secondary" onClick={() => navigate("/")}>
                  {words().backToLobby}
                </button>
              ) : (
                <button type="button" className="btn btn-primary" onClick={() => setAuthMode("claim")}>
                  {words().createAccount}
                </button>
              )
            }
          />
        </>
      ) : run && card ? (
        <SoloCard
          run={run}
          serve={card.serve}
          seconds={card.seconds}
          drawing={card.drawing}
          onNext={() => void next()}
          busy={busy}
          registered={Boolean(user && !user.isAnonymous)}
        />
      ) : run && playing ? (
        <SoloPlay
          key={playing.serveId}
          run={run}
          serve={playing}
          upcoming={run.serves.find((serve) => serve.outcome === null && serve !== playing) ?? null}
          onSettle={(outcome, seconds) => settled(playing, outcome, seconds)}
          onMissing={() => void reopenDaily()}
          onDrawing={(actions) => {
            shownDrawing.current = { serveId: playing.serveId, actions };
          }}
        />
      ) : summaryOf ? (
        <SoloSummaryView
          run={summaryOf}
          previousBest={previousBest}
          today={today}
          onBack={() => setSummaryOf(null)}
        />
      ) : (
        <SoloHome
          summary={summary}
          today={today}
          error={error ?? loadError}
          busy={busy}
          onDaily={() => void begin(() => openDaily(today))}
          onFree={(length) => void begin(() => startFreeRun(length))}
          onContinue={(runId) => void begin(() => fetchSoloRun(runId))}
        />
      )}

      {authMode && (
        <AuthDialog
          mode={authMode}
          suggestedUsername={authMode === "claim" ? user?.displayName ?? "" : ""}
          onClose={() => setAuthMode(null)}
          onSubmit={authSubmitter(authMode, login, register)}
          onSwitchMode={setAuthMode}
        />
      )}
    </div>
  );
}

/** What Solo opens on: today's Daily, a row for each free-run length with
    the run in play and the best, and the calendar of the player's Dailies. */
function SoloHome({
  summary,
  today,
  error,
  busy,
  onDaily,
  onFree,
  onContinue,
}: {
  summary: SoloSummary | null;
  today: string;
  error: string | null;
  busy: boolean;
  onDaily: () => void;
  onFree: (length: SoloLength) => void;
  onContinue: (runId: string) => void;
}) {
  return (
    <div className="solo-home" aria-busy={summary === null && !error}>
      <h1 className="visually-hidden">{ui.solo.solo}</h1>
      {error && <p className="lobby-action-error" role="alert">{error}</p>}
      <div className="solo-columns">
        <div className="solo-main">
          <DailyCard summary={summary} busy={busy} onDaily={onDaily} />
          <section className="surface-card solo-free" data-testid="solo-free" aria-labelledby="solo-free-title">
            <h2 id="solo-free-title">{words().freeRun}</h2>
            {FREE_LENGTHS.map((length) => (
              <FreeRunRow
                key={lengthKey(length)}
                length={length}
                run={summary?.activeRuns.find((active) => active.length === length) ?? null}
                best={summary?.bests[lengthKey(length)]}
                disabled={busy || summary === null}
                onStart={() => onFree(length)}
                onContinue={onContinue}
              />
            ))}
          </section>
        </div>
        <SoloCalendar
          today={today}
          todayHasDaily={summary === null ? null : summary.today.state !== "unavailable"}
          stats={summary?.stats ?? null}
        />
      </div>
    </div>
  );
}

type SoloLength = 5 | 10 | null;

/** Quick, Classic, Endless: the page's order, and the keys bests use. */
const FREE_LENGTHS: SoloLength[] = [5, 10, null];

function lengthKey(length: SoloLength): "5" | "10" | "unlimited" {
  return length === null ? "unlimited" : length === 5 ? "5" : "10";
}

function lengthName(length: SoloLength): string {
  return length === null ? words().endless : length === 5 ? words().quick : words().classic;
}

/** Today's Daily: its five as rings - named, missed, the one up next, the
    ones to come - and the one thing to do with it now. */
function DailyCard({ summary, busy, onDaily }: { summary: SoloSummary | null; busy: boolean; onDaily: () => void }) {
  const state = summary?.today.state ?? "not_started";
  const result = summary?.today.result ?? null;
  const marks = result ? dailyMarks(result) : (Array(5).fill("unplayed") as DailyMark[]);
  const next = state === "done" || state === "unavailable" ? -1 : marks.indexOf("unplayed");
  return (
    <section className="surface-card solo-daily" data-testid="solo-daily" aria-labelledby="solo-daily-title">
      <div className="solo-card-head">
        <h2 id="solo-daily-title">{words().daily}</h2>
        {summary && summary.streak > 0 && (
          <span className="chip chip-warm" data-testid="solo-streak">
            {words().streak({ days: summary.streak })}
          </span>
        )}
      </div>
      {state === "unavailable" ? (
        <p className="solo-note">{words().noDailyToday}</p>
      ) : (
        <ol
          className="solo-rings"
          aria-label={result ? words().youNamed({ solved: result.solved, total: 5 }) : words().daily}
        >
          {marks.map((mark, index) => (
            <li
              key={index}
              className={`solo-ring is-${mark}${index === next ? " is-next" : ""}`}
              aria-label={
                mark === "solved" ? words().named : mark === "missed" ? words().missed : String(index + 1)
              }
            >
              {mark === "solved" ? (
                <CheckIcon size={26} />
              ) : mark === "missed" ? (
                <XIcon size={24} />
              ) : (
                <span aria-hidden="true">{index + 1}</span>
              )}
            </li>
          ))}
        </ol>
      )}
      <div className="solo-daily-foot">
        {state === "done" && result ? (
          <>
            <span className="solo-daily-points">{words().dailyDone({ points: result.points })}</span>
            <CopyResultButton result={result} />
          </>
        ) : state === "unavailable" ? null : (
          <button
            type="button"
            className="btn btn-warm btn-big solo-daily-play"
            data-testid="solo-play-daily"
            disabled={busy || summary === null}
            onClick={onDaily}
          >
            {state === "in_progress"
              ? words().continueDaily({ left: 5 - (result?.positionsPlayed ?? 0) })
              : words().playDaily}
          </button>
        )}
        <NextDailyCountdown />
      </div>
    </section>
  );
}

/** One free-run length: its name, the run in play if there is one and how
    far it got, the best, and Start - or Start over and Continue. */
function FreeRunRow({
  length,
  run,
  best,
  disabled,
  onStart,
  onContinue,
}: {
  length: SoloLength;
  run: SoloActiveRun | null;
  best: number | undefined;
  disabled: boolean;
  onStart: () => void;
  onContinue: (runId: string) => void;
}) {
  const key = lengthKey(length);
  // Starting over ends the run in play: a 5 or 10 counts for nothing, so it
  // is asked first rather than lost to a tap beside Continue. Asked about
  // one run: if that run goes meanwhile, so does the question.
  const [confirmingRun, setConfirmingRun] = useState<string | null>(null);
  return (
    <div className={`solo-run${run ? " has-run" : ""}`} data-testid={`solo-run-${key}`}>
      <span className="solo-run-glyph" aria-hidden="true">
        {length === null ? "∞" : length}
      </span>
      <div className="solo-run-body">
        <div className="solo-run-title">
          <h3>{lengthName(length)}</h3>
          {run && (
            <span className="solo-run-progress" data-testid={`solo-run-progress-${key}`}>
              {length === null
                ? words().inARow({ count: run.solved })
                : words().runProgress({ played: run.outcomes.length, length, points: run.points })}
            </span>
          )}
        </div>
        {run && <RunStrip run={run} />}
      </div>
      <div className="solo-run-best">
        {best !== undefined && (
          <>
            <span className="section-label">{words().best}</span>
            <span className="solo-run-best-value" data-testid={`solo-best-${key}`}>
              {formatNumber(best)}
            </span>
          </>
        )}
      </div>
      <div className="solo-run-actions">
        {run ? (
          <>
            <button
              type="button"
              className="btn btn-secondary btn-icon"
              aria-label={words().startOverNamed({ name: lengthName(length) })}
              title={words().startOver}
              data-testid={`solo-restart-${key}`}
              disabled={disabled}
              onClick={() => setConfirmingRun(run.runId)}
            >
              <UndoIcon size={18} />
            </button>
            <button
              type="button"
              className="btn btn-primary solo-run-main"
              aria-label={words().continueNamed({ name: lengthName(length) })}
              data-testid={`solo-continue-${key}`}
              disabled={disabled}
              onClick={() => onContinue(run.runId)}
            >
              {words().continueRun}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn btn-secondary solo-run-main"
            aria-label={words().startNamed({ name: lengthName(length) })}
            data-testid={`solo-free-${key}`}
            disabled={disabled}
            onClick={onStart}
          >
            {words().start}
          </button>
        )}
      </div>
      {run && confirmingRun === run.runId && (
        <ConfirmationDialog
          title={words().startOverTitle({ name: lengthName(length) })}
          description={
            length === null
              ? run.solved > 0
                ? words().startOverEndless({ count: run.solved })
                : words().startOverEndlessNothing
              : words().startOverFinite({ played: run.outcomes.length, length, points: run.points })
          }
          confirmLabel={words().startOver}
          // An Endless run keeps what it reached as a result; a 5 or 10
          // loses everything it came to.
          tone={length === null ? "primary" : "danger"}
          onCancel={() => setConfirmingRun(null)}
          onConfirm={() => {
            setConfirmingRun(null);
            onStart();
          }}
        />
      )}
    </div>
  );
}

/** Most segments an Endless strip draws: a long streak shows its latest. */
const ENDLESS_SEGMENTS = 10;

/** A run's drawings as segments: named, missed, still to come. */
function RunStrip({ run }: { run: SoloActiveRun }) {
  const segments: ("solved" | "missed" | "unplayed")[] = run.outcomes.map((outcome) =>
    outcome === "solved" ? "solved" : "missed",
  );
  const drawn =
    run.length === null
      ? segments.slice(-ENDLESS_SEGMENTS)
      : [...segments, ...Array<"unplayed">(Math.max(0, run.length - segments.length)).fill("unplayed")];
  return (
    <span className={`solo-strip${run.length === null ? " is-endless" : ""}`} aria-hidden="true">
      {drawn.map((segment, index) => (
        <span key={index} className={`solo-strip-segment is-${segment}`} />
      ))}
    </span>
  );
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(intlLocale(interfaceLocale())).format(value);
}

/** The first day of the week for the interface's language, 1 Monday to 7
    Sunday: Sunday for its English, which is American; Monday for the other
    seven, Portugal's and Spain's included. Fixed rather than asked of the
    browser: `Intl.Locale("pt")` is Brazil's week, and Firefox has no week
    info at all. 2024-01-01 was a Monday, so `new Date(2024, 0, start)` is
    that weekday. */
function weekStart(locale: string): number {
  return locale.split("-")[0] === "en" ? 7 : 1;
}

/** `YYYY-MM` of a `YYYY-MM-DD`. */
function monthOf(date: string): string {
  return date.slice(0, 7);
}

function shiftMonth(month: string, by: number): string {
  const [year, number] = month.split("-").map(Number);
  const moved = new Date(year, number - 1 + by, 1);
  return `${moved.getFullYear()}-${String(moved.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * The player's Dailies a month at a time, back to their first: each date's
 * Daily as a ring of its five (CalendarMark), today ringed; and what all of
 * them came to.
 */
function SoloCalendar({
  today,
  todayHasDaily,
  stats,
}: {
  today: string;
  /** From the summary, which picks today's Daily: the month may not know of
      it yet, before anybody has opened it. Null until the summary is here. */
  todayHasDaily: boolean | null;
  stats: SoloDailyStats | null;
}) {
  // The month looked at, for the today it was picked on: a new day can be a
  // new month, and the calendar follows the player's today back to it.
  const [picked, setPicked] = useState(() => ({ today, month: monthOf(today) }));
  const month = picked.today === today ? picked.month : monthOf(today);
  const setMonth = (move: (current: string) => string) => setPicked({ today, month: move(month) });
  const [loaded, setLoaded] = useState<SoloMonth | null>(null);
  const [unreadFor, setUnreadFor] = useState<string | null>(null);
  const unread = unreadFor === `${today}/${month}`;
  useEffect(() => {
    let cancelled = false;
    fetchSoloMonth(today, month)
      .then((answer) => {
        if (!cancelled) setLoaded(answer);
      })
      .catch(() => {
        if (!cancelled) setUnreadFor(`${today}/${month}`);
      });
    return () => {
      cancelled = true;
    };
  }, [today, month]);

  // Intl's locale for the interface's language: Portugal's Portuguese, so
  // its numbers read as the page's words do.
  const locale = intlLocale(interfaceLocale());
  const [year, monthNumber] = month.split("-").map(Number);
  const first = new Date(year, monthNumber - 1, 1);
  const monthName = new Intl.DateTimeFormat(locale, {
    month: "long",
    ...(year === Number(today.slice(0, 4)) ? {} : { year: "numeric" }),
  }).format(first);
  // The month's own first letter only: "diciembre de 2025", not "De".
  const title = monthName.charAt(0).toLocaleUpperCase(locale) + monthName.slice(1);
  // The week starts where the interface's language starts it: Sunday in
  // American English, Monday in the other seven (`weekStart`).
  const start = weekStart(locale);
  const weekdays = Array.from({ length: 7 }, (_, index) =>
    new Intl.DateTimeFormat(locale, { weekday: "narrow" }).format(new Date(2024, 0, start + index)),
  );
  const lead = (first.getDay() - (start % 7) + 7) % 7;
  const daysIn = new Date(year, monthNumber, 0).getDate();
  const shown = loaded?.month === month ? loaded : null;
  const byDate = new Map((shown?.days ?? []).map((day) => [day.date, day]));
  const earliest = loaded?.first ?? null;
  const canGoBack = earliest !== null && monthOf(earliest) < month;
  const canGoForward = month < monthOf(today);
  const named = stats && stats.drawingsPlayed > 0 ? stats.drawingsNamed / stats.drawingsPlayed : null;

  return (
    <section className="surface-card solo-calendar" data-testid="solo-calendar" aria-labelledby="solo-calendar-title">
      <div className="solo-card-head">
        <h2 id="solo-calendar-title">{title}</h2>
        <div className="solo-calendar-nav">
          <button
            type="button"
            className="btn btn-secondary btn-icon btn-compact"
            aria-label={words().previousMonth}
            data-testid="solo-calendar-previous"
            disabled={!canGoBack}
            onClick={() => setMonth((current) => shiftMonth(current, -1))}
          >
            <ChevronLeftIcon size={16} />
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-icon btn-compact"
            aria-label={words().nextMonth}
            data-testid="solo-calendar-next"
            disabled={!canGoForward}
            onClick={() => setMonth((current) => shiftMonth(current, 1))}
          >
            <ChevronRightIcon size={16} />
          </button>
        </div>
      </div>
      <div className="solo-calendar-grid" role="list" aria-busy={shown === null && !unread}>
        {weekdays.map((weekday, index) => (
          <span key={`w${index}`} className="solo-calendar-weekday" aria-hidden="true">
            {weekday}
          </span>
        ))}
        {Array.from({ length: lead }, (_, index) => (
          <span key={`l${index}`} aria-hidden="true" />
        ))}
        {Array.from({ length: daysIn }, (_, index) => {
          const date = `${month}-${String(index + 1).padStart(2, "0")}`;
          const day = byDate.get(date);
          const look = calendarLook(date, day, today, earliest, todayHasDaily);
          return (
            <span
              key={date}
              role="listitem"
              className={`solo-calendar-day is-${look}${date === today ? " is-today" : ""}`}
              data-testid="solo-calendar-day"
              data-date={date}
              aria-current={date === today ? "date" : undefined}
              aria-label={words().calendarDay({ date: dayLabel(date), status: calendarStatus(look, day) })}
            >
              <CalendarMark look={look} marks={day?.result?.marks ?? []} playable={date === today} />
              <span className="solo-calendar-date">{index + 1}</span>
            </span>
          );
        })}
      </div>
      {unread && <p className="solo-note">{words().couldNotLoad}</p>}
      {stats && stats.dailiesPlayed > 0 && (
        <dl className="solo-calendar-stats" data-testid="solo-stats">
          <div>
            <dt>{words().dailiesPlayed}</dt>
            <dd>{formatNumber(stats.dailiesPlayed)}</dd>
          </div>
          <div>
            <dt>{words().namedShare}</dt>
            <dd>{new Intl.NumberFormat(locale, { style: "percent" }).format(named ?? 0)}</dd>
          </div>
          <div>
            <dt>{words().longestStreak}</dt>
            <dd>{formatNumber(stats.longestStreak)}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

type CalendarLook = "future" | "none" | "missed" | "open" | "perfect" | "finished" | "under-way";

/** How a date reads: one to come, one with no Daily for this player, a Daily
    they let pass or have still to play today, or one they played - all five
    named, finished with a miss, or under way. */
function calendarLook(
  date: string,
  day: SoloCalendarDay | undefined,
  today: string,
  earliest: string | null,
  todayHasDaily: boolean | null,
): CalendarLook {
  if (date > today) return "future";
  const result = day?.result ?? null;
  if (result) {
    if (!result.completed) return "under-way";
    return result.solved === 5 ? "perfect" : "finished";
  }
  if (date === today) return (todayHasDaily ?? Boolean(day?.daily)) ? "open" : "none";
  // Only a Daily there was, after the player's first: before it, Solo was
  // not theirs yet, and a missed day would be no news.
  if (day?.daily && earliest !== null && date > earliest) return "missed";
  return "none";
}

// The calendar's ring: the five of a Daily round its date, drawn in a 40-unit
// box. A finished ring closes, its arcs end to end; one under way keeps a gap
// between each - 18 degrees, square-ended, about 5 units: a gap a phone still
// shows - so what is left to play reads as the ring's grey part.
const RING_RADIUS = 18.4;
const RING_WIDTH = 3.2;
// A perfect day's sticker: a fuller star than the icon set's StarIcon, so it
// still reads as one at a calendar day's size.
const STAR_PATH = "M12 1.8l3.1 6.4 7 .9-5.1 4.9 1.3 7L12 17.6 5.7 21l1.3-7L1.9 9.1l7-.9z";

function ringArc(index: number, gap: number): string {
  const from = ((-90 + index * 72 + gap / 2) * Math.PI) / 180;
  const to = ((-90 + (index + 1) * 72 - gap / 2) * Math.PI) / 180;
  const point = (angle: number) =>
    `${(20 + RING_RADIUS * Math.cos(angle)).toFixed(2)} ${(20 + RING_RADIUS * Math.sin(angle)).toFixed(2)}`;
  return `M${point(from)} A${RING_RADIUS} ${RING_RADIUS} 0 0 1 ${point(to)}`;
}

/** A day's Daily, behind its date: filled once it is finished - a green
    disc with a gold star for all five named, a pale one inside its ring with
    a miss - and hollow while under way, its drawings still to play grey. A
    Daily not played is a dashed ring. Both are darker when the Daily can be
    played now (`playable`), so one that can no longer be played does not
    look like today's. */
function CalendarMark({ look, marks, playable }: { look: CalendarLook; marks: SoloDailyMark[]; playable: boolean }) {
  if (look === "future" || look === "none") return null;
  if (look === "missed" || look === "open") {
    return (
      <svg className="solo-calendar-mark" viewBox="0 0 40 40" aria-hidden="true">
        <circle
          className={`solo-calendar-unplayed-ring${playable ? " is-playable" : ""}`}
          cx="20"
          cy="20"
          r={RING_RADIUS}
        />
      </svg>
    );
  }
  if (look === "perfect") {
    // The star sits on the disc's edge, top right and tilted, like a sticker:
    // its centre on the 45 degree line, a little outside the circle.
    return (
      <svg className="solo-calendar-mark" viewBox="0 0 40 40" aria-hidden="true">
        <circle className="solo-calendar-disc" cx="20" cy="20" r={RING_RADIUS + RING_WIDTH / 2} />
        <g transform="translate(35.9 4.1) rotate(12) scale(0.9) translate(-12 -12)">
          <path className="solo-calendar-star" d={STAR_PATH} />
        </g>
      </svg>
    );
  }
  const finished = look === "finished";
  return (
    <svg className="solo-calendar-mark" viewBox="0 0 40 40" aria-hidden="true">
      {finished && <circle className="solo-calendar-fill" cx="20" cy="20" r={RING_RADIUS - RING_WIDTH / 2 + 0.6} />}
      {Array.from({ length: 5 }, (_, index) => {
        const outcome = marks[index]?.outcome;
        const look = outcome === undefined ? "unplayed" : outcome === "solved" ? "solved" : "missed";
        return (
          <path
            key={index}
            className={`solo-calendar-arc is-${look}${playable ? " is-playable" : ""}`}
            d={ringArc(index, finished ? 0 : 18)}
          />
        );
      })}
    </svg>
  );
}

function calendarStatus(look: CalendarLook, day: SoloCalendarDay | undefined): string {
  if (day?.result && !day.result.completed) return words().underWay({ played: day.result.positionsPlayed, total: 5 });
  if (day?.result) return words().youNamed({ solved: day.result.solved, total: 5 });
  if (look === "future") return words().stillToCome;
  if (look === "missed") return words().missedDay;
  if (look === "open") return words().toPlayToday;
  // A past day that had a Daily the player never played, before their
  // first: a Daily, not "no Daily".
  return day?.daily ? words().daily : words().noDaily;
}

/** A run's name, as its rows and its drawings are headed: the Daily, or the
    free run's length. */
function runName(run: SoloRun): string {
  return run.mode === "daily" ? words().daily : lengthName(run.length as SoloLength);
}

/** Above a drawing, in play or settled: which run and which drawing, and a
    dot for each of the run's - named, missed, this one, the ones to come. */
function RunHeader({ run, position }: { run: SoloRun; position: number }) {
  const cameTo = new Map(
    run.serves.filter((serve) => serve.outcome !== null).map((serve) => [serve.position, serve.outcome]),
  );
  const count = run.length ?? Math.max(position, ...cameTo.keys());
  const from = run.length === null ? Math.max(1, count - ENDLESS_SEGMENTS + 1) : 1;
  return (
    <div className="solo-run-head">
      <span className="solo-play-position">
        {runName(run)} · {words().drawingOf({ position, length: run.length })}
      </span>
      <span className="solo-dots" aria-hidden="true">
        {Array.from({ length: count - from + 1 }, (_, index) => {
          const at = from + index;
          const outcome = cameTo.get(at);
          const look = outcome === undefined ? "unplayed" : outcome === "solved" ? "solved" : "missed";
          return <span key={at} className={`solo-dot is-${look}${at === position ? " is-current" : ""}`} />;
        })}
      </span>
    </div>
  );
}

/** A Daily's date, `YYYY-MM-DD`, in the reader's own words. */
function dayLabel(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return formatDate(new Date(year, month - 1, day));
}

/** A Daily's result as the run that played it reads, before the server's
    summary has caught up: one mark per drawing settled. */
function resultOf(run: SoloRun): SoloDailyResult {
  const played = run.serves.filter((serve) => serve.outcome !== null);
  return {
    date: run.dailyDate ?? "",
    positionsPlayed: played.length,
    solved: run.solved,
    points: run.points,
    completed: played.length >= 5,
    marks: played.map((serve) => ({ outcome: serve.outcome as SoloOutcome, seconds: 0, late: false })),
  };
}

/** One square per drawing of a Daily: named, missed, or still to play. */
function DailyMarks({ result }: { result: SoloDailyResult }) {
  const marks = dailyMarks(result);
  return (
    <span className="solo-marks" role="img" aria-label={words().youNamed({ solved: result.solved, total: 5 })}>
      {marks.map((mark, index) => (
        <span key={index} className={`solo-mark is-${mark}`} aria-hidden="true" />
      ))}
    </span>
  );
}

function CopyResultButton({ result }: { result: SoloDailyResult }) {
  const { notify } = useToast();
  const copy = async () => {
    const symbols = dailyMarks(result)
      .map((mark) => (mark === "solved" ? "🟩" : mark === "missed" ? "🟥" : "⬜"))
      .join("");
    const text = `${words().resultText({
      daily: words().daily,
      date: result.date,
      marks: symbols,
      points: result.points,
    })}\n${window.location.origin}/solo`;
    try {
      await navigator.clipboard.writeText(text);
      notify(words().copied, "success");
    } catch {
      notify(text, "info", 8000);
    }
  };
  return (
    <button type="button" className="btn btn-secondary btn-compact" data-testid="solo-copy-result" onClick={() => void copy()}>
      <CopyIcon size={15} />
      {words().copyResult}
    </button>
  );
}

/** Until the player's own midnight, when the next Daily opens. */
function NextDailyCountdown() {
  const [left, setLeft] = useState(() => untilLocalMidnight());
  useEffect(() => {
    const timer = window.setInterval(() => setLeft(untilLocalMidnight()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const total = Math.max(0, Math.floor(left / 1000));
  const time = [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
  return <p className="solo-note solo-countdown" data-testid="solo-countdown">{words().nextDailyIn({ time })}</p>;
}

/**
 * One drawing in play: its replay over 20 s, the 30 s clock, the guess field
 * and Give up. The clock starts the first time the drawing is shown and is
 * remembered, so a reload continues it rather than starting again.
 */
function SoloPlay({
  run,
  serve,
  upcoming,
  onSettle,
  onMissing,
  onDrawing,
}: {
  run: SoloRun;
  serve: SoloServe;
  upcoming: SoloServe | null;
  onSettle: (outcome: SoloOutcome, seconds: number) => Promise<void>;
  onMissing: () => void;
  /** The drawing, decoded, for the card that follows to show. */
  onDrawing: (actions: DecodedCanvasAction[]) => void;
}) {
  const [actions, setActions] = useState<DecodedCanvasAction[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [fraction, setFraction] = useState(0);
  const [guess, setGuess] = useState("");
  const [feedback, setFeedback] = useState<{ text: string; tone: "close" | "miss" } | null>(null);
  // What the player decided and the server has not yet taken, to send again.
  const [unsaved, setUnsaved] = useState<{ outcome: SoloOutcome; seconds: number } | null>(null);
  const settling = useRef(false);
  // The player's decision, once made: it stands, and a retry or the clock
  // running out sends that, never another.
  const decided = useRef<{ outcome: SoloOutcome; seconds: number } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const target = useMemo(() => (serve.forms ? decodeSoloForms(serve.serveId, serve.forms) : null), [serve]);
  const upcomingId = upcoming?.serveId ?? null;
  const onDrawingRef = useRef(onDrawing);
  useEffect(() => {
    onDrawingRef.current = onDrawing;
  }, [onDrawing]);

  useEffect(() => {
    let cancelled = false;
    void fetchSoloDrawing(serve.serveId)
      .then((bytes) => {
        if (cancelled) return;
        const decoded = decodeCanvasHistory(bytes);
        if (!decoded) {
          setFailed(true);
          return;
        }
        const start = serveStartedAt(serve.serveId, serve.forms ?? "");
        setFailed(false);
        setActions(decoded);
        onDrawingRef.current(decoded);
        setStartedAt(start);
        setFraction(Math.min(1, (Date.now() - start) / 1000 / SOLO_REPLAY_SECONDS));
      })
      .catch((failure) => {
        if (cancelled) return;
        setFailed(true);
        // Gone for everybody: a Daily may have a replacement to pick up.
        if (failure instanceof ApiError && failure.status === 404) onMissing();
      });
    return () => {
      cancelled = true;
    };
    // onMissing is the parent's, recreated each render; a new attempt or a
    // new drawing is what fetches again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serve.serveId, serve.forms, attempt]);

  // The next one, so it is on screen the moment this one is over.
  useEffect(() => {
    if (upcomingId) void fetchSoloDrawing(upcomingId).catch(() => undefined);
  }, [upcomingId]);

  // The field is the player's attention once there is something to guess.
  useEffect(() => {
    if (actions) input.current?.focus();
  }, [actions]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(timer);
  }, []);

  const elapsed = startedAt === null ? 0 : Math.max(0, (now - startedAt) / 1000);
  const remaining = Math.max(0, SOLO_CLOCK_SECONDS - elapsed);

  const onSettleRef = useRef(onSettle);
  useEffect(() => {
    onSettleRef.current = onSettle;
  }, [onSettle]);

  const settle = useCallback(async (outcome: SoloOutcome, seconds: number) => {
    if (settling.current) return;
    settling.current = true;
    const choice = decided.current ?? {
      outcome,
      seconds: Math.min(SOLO_CLOCK_SECONDS, Math.max(0, seconds)),
    };
    decided.current = choice;
    try {
      await onSettleRef.current(choice.outcome, choice.seconds);
    } catch {
      // Said, with the way to send it again: the decision stands.
      setUnsaved(choice);
      settling.current = false;
    }
  }, []);

  const timedOut = startedAt !== null && remaining <= 0;
  useEffect(() => {
    // A decision already made is not overtaken by the clock.
    if (!timedOut || unsaved) return;
    // Out of the render that noticed it: the report may say it failed.
    const timer = window.setTimeout(() => void settle("timed_out", SOLO_CLOCK_SECONDS), 0);
    return () => window.clearTimeout(timer);
  }, [timedOut, unsaved, settle]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = guess.trim();
    if (!text || !target || startedAt === null || timedOut || unsaved) return;
    const verdict = judge(text, target);
    if (verdict === "correct") {
      void settle("solved", elapsed);
      return;
    }
    setGuess("");
    setFeedback(
      verdict === "close"
        ? { text: words().veryClose, tone: "close" }
        : verdict === "partial"
          ? { text: words().someWordsRight, tone: "close" }
          : { text: words().notIt({ guess: text }), tone: "miss" },
    );
  };

  return (
    <div className="solo-play" data-testid="solo-play">
      <div className="solo-play-bar">
        <span className="solo-play-position">
          {runName(run)} · {words().drawingOf({ position: serve.position, length: run.length })}
        </span>
        <span
          className={`solo-clock${remaining <= 10 ? " is-low" : ""}`}
          data-testid="solo-clock"
          role="timer"
          aria-live="off"
        >
          {words().secondsLeft({ seconds: Math.ceil(remaining) })}
        </span>
      </div>
      <div className="solo-clock-track" aria-hidden="true">
        <span style={{ transform: `scaleX(${remaining / SOLO_CLOCK_SECONDS})` }} />
      </div>
      <div className="surface-card solo-canvas" data-testid="solo-canvas">
        {actions ? (
          <ReplayCanvas
            actions={actions}
            fraction={fraction}
            playing={fraction < 1}
            onFraction={setFraction}
            durationSeconds={SOLO_REPLAY_SECONDS}
            label={ui.solo.solo}
          />
        ) : failed ? (
          <div className="solo-canvas-failed">
            <p className="solo-note">{words().couldNotLoadDrawing}</p>
            <button type="button" className="btn btn-secondary btn-compact" onClick={() => setAttempt((count) => count + 1)}>
              {words().tryAgain}
            </button>
          </div>
        ) : (
          <div className="solo-canvas-skeleton" />
        )}
      </div>
      {unsaved && (
        <div className="solo-unsaved" role="alert" data-testid="solo-unsaved">
          <span>{words().couldNotSaveAnswer}</span>
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => void settle(unsaved.outcome, unsaved.seconds)}
          >
            {words().tryAgain}
          </button>
        </div>
      )}
      <form className="solo-guess" onSubmit={submit}>
        <input
          ref={input}
          type="search"
          className="solo-guess-input"
          data-testid="solo-guess"
          value={guess}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="send"
          maxLength={64}
          placeholder={words().typeYourGuess}
          aria-label={words().typeYourGuess}
          disabled={!actions || timedOut || unsaved !== null}
          onChange={(change) => setGuess(change.target.value)}
          // A new guess is the player's attention; the last verdict goes.
          onFocus={() => setFeedback(null)}
        />
        <button type="submit" className="btn btn-primary" disabled={!actions || !guess.trim() || timedOut || unsaved !== null}>
          {words().guess}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          data-testid="solo-give-up"
          // A drawing that will not load can still be given up: it is the
          // only way past one that stopped being served (R-SOLO-13).
          disabled={(!actions && !failed) || timedOut || unsaved !== null}
          onClick={() => void settle("given_up", elapsed)}
        >
          {words().giveUp}
        </button>
      </form>
      <p
        className={`solo-feedback${feedback ? ` is-${feedback.tone}` : ""}`}
        data-testid="solo-feedback"
        role="status"
      >
        {feedback?.text ?? " "}
      </p>
    </div>
  );
}

/**
 * What a drawing came to, under the drawing itself, finished: what it was,
 * how long it took or why it ended, the points, and what the player may do
 * with it now - react, share it to the Gallery under its drawer's name, or
 * report it (R-SOLO-15). Never who drew it.
 */
function SoloCard({
  run,
  serve,
  seconds,
  drawing,
  onNext,
  busy,
  registered,
}: {
  run: SoloRun;
  serve: SoloServe;
  seconds: number;
  /** The drawing as it was played, decoded; fetched again if not given. */
  drawing: DecodedCanvasAction[] | null;
  onNext: () => void;
  busy: boolean;
  registered: boolean;
}) {
  // The field the player was typing in is gone: the verdict takes focus, so
  // a screen reader says what the drawing came to.
  const verdict = useRef<HTMLDivElement>(null);
  useEffect(() => {
    verdict.current?.focus();
  }, []);
  const { notify } = useToast();
  const [actions, setActions] = useState<DecodedCanvasAction[] | null>(drawing);
  const [unloadable, setUnloadable] = useState(false);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [mine, setMine] = useState<string | null>(null);
  const [share, setShare] = useState<SoloShare | null>(null);
  const [reporting, setReporting] = useState(false);
  const solved = serve.outcome === "solved";
  const over = run.state !== "active";

  useEffect(() => {
    if (actions) return;
    let cancelled = false;
    void fetchSoloDrawing(serve.serveId)
      .then((bytes) => {
        if (cancelled) return;
        const decoded = decodeCanvasHistory(bytes);
        if (decoded) setActions(decoded);
        else setUnloadable(true);
      })
      // Gone for everybody since (R-SOLO-13), or not to be had now: said,
      // rather than an empty frame.
      .catch(() => {
        if (!cancelled) setUnloadable(true);
      });
    return () => {
      cancelled = true;
    };
  }, [actions, serve.serveId]);

  const toggleShare = async () => {
    try {
      setShare(await shareServe(serve.serveId, !(share?.sharedByMe ?? false)));
    } catch (failure) {
      notify(refusalText(failure, ui.shareControl.thatDrawingCouldNotBeShared), "error");
    }
  };

  return (
    <div className="solo-result" data-testid="solo-card">
      <RunHeader run={run} position={serve.position} />
      <div className={`solo-result-frame ${solved ? "is-solved" : "is-missed"}`}>
        <div className="solo-canvas" data-testid="solo-card-drawing">
          {actions ? (
            <ReplayCanvas
              actions={actions}
              fraction={1}
              playing={false}
              onFraction={() => undefined}
              durationSeconds={SOLO_REPLAY_SECONDS}
              label={serve.prompt ?? ui.solo.solo}
            />
          ) : unloadable ? (
            <div className="solo-canvas-failed">
              <p className="solo-note">{words().couldNotLoadDrawing}</p>
            </div>
          ) : (
            <div className="solo-canvas-skeleton" />
          )}
        </div>
        <div className="solo-verdict-strip">
          <span className="solo-verdict-mark" aria-hidden="true">
            {solved ? <CheckIcon size={22} /> : <XIcon size={20} />}
          </span>
          <div ref={verdict} tabIndex={-1} className="solo-verdict-text">
            <span className="visually-hidden" data-testid="solo-verdict">
              {solved ? words().gotIt : serve.outcome === "timed_out" ? words().timeUp : words().gaveUp}
            </span>
            <h1 className="solo-prompt" data-testid="solo-prompt">{serve.prompt}</h1>
            {/* A miss's detail is its verdict again: said once. */}
            <span className="solo-verdict-detail" aria-hidden={solved ? undefined : true}>
              {solved ? (
                <>
                  <ClockIcon size={15} />
                  {words().secondsTaken({ seconds })}
                </>
              ) : serve.outcome === "timed_out" ? (
                words().timeUp
              ) : (
                words().gaveUp
              )}
            </span>
          </div>
          {solved && serve.points !== null && (
            <span className="solo-points" data-testid="solo-points">
              <span aria-hidden="true">+{formatNumber(serve.points)}</span>
              <span className="visually-hidden">{words().plusPoints({ points: serve.points })}</span>
            </span>
          )}
        </div>
      </div>
      <div className="solo-result-actions">
        <DrawingReactionControl
          reactions={[]}
          myReactorId={null}
          counts={counts}
          mine={mine}
          eligibility={reactionEligibility({ isRegistered: registered })}
          onReact={async (emoji) => {
            const answer = await reactToServe(serve.serveId, emoji);
            setCounts(answer.reactionCounts);
            setMine(answer.myReaction);
          }}
          placement="panel"
          label={words().react}
        />
        {!share?.shareWithdrawn && (
          <button
            type="button"
            className={`btn btn-secondary${share?.sharedByMe ? " is-pressed" : ""}`}
            aria-pressed={share?.sharedByMe ?? false}
            data-testid="solo-share"
            onClick={() => void toggleShare()}
          >
            <ImageIcon size={17} />
            {share?.sharedByMe ? words().shared : words().share}
          </button>
        )}
        <button
          type="button"
          className="btn btn-secondary"
          aria-label={words().report}
          data-testid="solo-report"
          onClick={() => setReporting(true)}
        >
          <FlagIcon size={16} />
          {words().reportShort}
        </button>
        <button type="button" className="btn btn-warm btn-big solo-next" data-testid="solo-next" disabled={busy} onClick={onNext}>
          {over ? words().seeResult : words().next}
        </button>
      </div>
      {share?.sharedByMe && share.heldUntil && <p className="solo-note" data-testid="solo-share-held">{words().shareHeld}</p>}
      {share?.shareWithdrawn && <p className="solo-note">{words().shareTakenOut}</p>}
      {reporting && (
        <ReportDrawingDialog submit={(details) => reportServe(serve.serveId, details)} onClose={() => setReporting(false)} />
      )}
    </div>
  );
}

/** A run that is over: what it came to, the best, and for a Daily its result to copy. */
function SoloSummaryView({
  run,
  previousBest,
  today,
  onBack,
}: {
  run: SoloRun;
  previousBest: number | undefined;
  today: string;
  onBack: () => void;
}) {
  const settledCount = run.serves.filter((serve) => serve.outcome !== null).length;
  const result = run.mode === "daily" && run.dailyDate === today ? resultOf(run) : null;
  const value = run.length === null ? run.solved : run.points;
  // Beaten, not tied: a run that only equals the best is not a new one.
  const newBest = run.mode === "free" && value > 0 && value > (previousBest ?? 0);
  const heading = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <div className="solo-summary" data-testid="solo-summary">
      <div className="surface-card solo-result-card">
        <p ref={heading} tabIndex={-1} className="solo-verdict is-solved">
          {run.mode === "daily" ? words().dailyComplete : words().runOver}
        </p>
        <h1 className="solo-prompt">{words().totalPoints({ points: run.points })}</h1>
        <p className="solo-it-was">{words().youNamed({ solved: run.solved, total: settledCount })}</p>
        {result && <DailyMarks result={result} />}
        {newBest && (
          <p className="chip chip-warm solo-new-best" data-testid="solo-new-best">{words().newBest}</p>
        )}
        <div className="solo-result-actions">
          {result && <CopyResultButton result={result} />}
          {run.mode === "daily" && <NextDailyCountdown />}
        </div>
        <button type="button" className="btn btn-primary solo-next" data-testid="solo-back" onClick={onBack}>
          <UserIcon size={15} />
          {words().backToSolo}
        </button>
      </div>
    </div>
  );
}
