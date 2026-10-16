import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AuthDialog } from "../components/AccountMenu";
import { AppHeader } from "../components/AppHeader";
import { DrawingReactionControl } from "../components/DrawingReactionControl";
import { ReplayCanvas } from "../components/ReplayCanvas";
import { ReportDrawingDialog } from "../components/ReportDrawingDialog";
import { CopyIcon, FlagIcon, ImageIcon, UserIcon } from "../components/icons";
import { EmptyState } from "../components/ui/EmptyState";
import { soloCopyFor } from "../content/solo/index.ts";
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
  fetchActiveFreeRun,
  fetchSoloDrawing,
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
  type SoloDailyResult,
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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The drawing just settled, shown until Next: what it was, and what the
  // player can do with it now.
  const [card, setCard] = useState<SoloServe | null>(null);
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
      setSummary(await fetchSoloSummary(localDateKey()));
      setError(null);
    } catch (failure) {
      setError(refusalText(failure, words().couldNotLoad));
    }
  }, []);

  useEffect(() => {
    if (!hasResolved || !user || user.isAnonymous) return;
    let cancelled = false;
    fetchSoloSummary(today)
      .then((loaded) => {
        if (!cancelled) setSummary(loaded);
      })
      .catch((failure) => {
        if (!cancelled) setError(refusalText(failure, words().couldNotLoad));
      });
    return () => {
      cancelled = true;
    };
  }, [hasResolved, user, today]);

  const begin = async (action: () => Promise<SoloRun>) => {
    if (busy) return;
    setBusy(true);
    try {
      let next = await action();
      if (next.mode === "free" && !next.serves.some((serve) => serve.outcome === null)) {
        const served = await serveNext(next.runId, 2);
        next = { ...next, serves: [...next.serves, ...served] };
      }
      setCard(null);
      setSummaryOf(null);
      setRun(next);
    } catch (failure) {
      setError(refusalText(failure, words().couldNotLoad));
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
    setCard(answer.serve);
  };

  const next = async () => {
    if (!run || busy) return;
    if (run.state !== "active") {
      const key = run.length === null ? "unlimited" : run.length === 5 ? "5" : "10";
      setPreviousBest(summary?.bests[key]);
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
          serve={card}
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
          error={error}
          busy={busy}
          onDaily={() => void begin(() => openDaily(today))}
          onFree={(length) => void begin(() => startFreeRun(length))}
          onContinue={() =>
            void begin(async () => {
              const active = await fetchActiveFreeRun();
              if (!active) throw new Error(words().couldNotLoad);
              return active;
            })
          }
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

/** What Solo opens on: today's Daily, the free runs, the bests, the streak. */
function SoloHome({
  summary,
  error,
  busy,
  onDaily,
  onFree,
  onContinue,
}: {
  summary: SoloSummary | null;
  error: string | null;
  busy: boolean;
  onDaily: () => void;
  onFree: (length: 5 | 10 | null) => void;
  onContinue: () => void;
}) {
  const todayState = summary?.today.state ?? "not_started";
  const result = summary?.today.result ?? null;
  return (
    <div className="solo-home" aria-busy={summary === null && !error}>
      <div className="solo-head">
        <h1>{ui.solo.solo}</h1>
        <p>{words().intro}</p>
      </div>
      {error && <p className="lobby-action-error" role="alert">{error}</p>}

      <div className="solo-grid">
        <section className="surface-card solo-daily" data-testid="solo-daily">
          <div className="solo-card-head">
            <h2>{words().daily}</h2>
            {summary && summary.streak > 0 && (
              <span className="chip chip-warm" data-testid="solo-streak">
                {words().streak({ days: summary.streak })}
              </span>
            )}
          </div>
          <p className="solo-card-intro">{words().dailyIntro}</p>
          {todayState === "unavailable" ? (
            <p className="solo-note">{words().noDailyToday}</p>
          ) : todayState === "done" && result ? (
            <div className="solo-daily-done">
              <DailyMarks result={result} />
              <p className="solo-daily-points">{words().dailyDone({ points: result.points })}</p>
              <CopyResultButton result={result} />
              <NextDailyCountdown />
            </div>
          ) : (
            <button
              type="button"
              className="btn btn-warm btn-big solo-daily-play"
              data-testid="solo-play-daily"
              disabled={busy || summary === null}
              onClick={onDaily}
            >
              {todayState === "in_progress" && result
                ? words().continueDaily({ played: result.positionsPlayed })
                : todayState === "in_progress"
                  ? words().continueDaily({ played: 0 })
                  : words().playDaily}
            </button>
          )}
        </section>

        <section className="surface-card solo-free" data-testid="solo-free">
          <div className="solo-card-head">
            <h2>{words().freeRun}</h2>
          </div>
          <p className="solo-card-intro">{words().freeRunIntro}</p>
          {summary?.activeRunId && (
            <button
              type="button"
              className="btn btn-primary solo-continue"
              data-testid="solo-continue-run"
              disabled={busy}
              onClick={onContinue}
            >
              {words().continueRun}
            </button>
          )}
          <div className="solo-lengths" role="group" aria-label={words().freeRun}>
            {([5, 10, null] as const).map((length) => (
              <button
                key={String(length)}
                type="button"
                className="btn btn-secondary solo-length"
                data-testid={`solo-free-${length ?? "unlimited"}`}
                disabled={busy || summary === null}
                onClick={() => onFree(length)}
              >
                {length === null ? words().unlimited : words().drawingsCount({ count: length })}
              </button>
            ))}
          </div>
          <p className="solo-note solo-preview">{words().supporterPreview}</p>
        </section>
      </div>

      <div className="solo-grid">
        <section className="surface-card solo-bests" data-testid="solo-bests">
          <h2>{words().bests}</h2>
          <dl>
            {(
              [
                ["5", words().bestFive],
                ["10", words().bestTen],
                ["unlimited", words().bestUnlimited],
              ] as const
            ).map(([key, label]) => {
              const best = summary?.bests[key];
              return (
                <div key={key} className="solo-best">
                  <dt>{label}</dt>
                  <dd>
                    {best === undefined
                      ? words().noBestYet
                      : key === "unlimited"
                        ? words().inARow({ count: best })
                        : words().pointsValue({ points: best })}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>

        <section className="surface-card solo-history" data-testid="solo-history">
          <h2>{words().yourDailies}</h2>
          {summary && summary.history.length === 0 ? (
            <p className="solo-note">{words().noDailiesYet}</p>
          ) : (
            <ol>
              {(summary?.history ?? []).slice(0, 14).map((day) => (
                <li key={day.date} className="solo-history-day">
                  <span className="solo-history-date">{dayLabel(day.date)}</span>
                  <DailyMarks result={day} />
                  <span className="solo-history-points">{words().pointsValue({ points: day.points })}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
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
}: {
  run: SoloRun;
  serve: SoloServe;
  upcoming: SoloServe | null;
  onSettle: (outcome: SoloOutcome, seconds: number) => Promise<void>;
  onMissing: () => void;
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
        <span className="solo-play-position">{words().drawingOf({ position: serve.position, length: run.length })}</span>
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
 * What a drawing came to: the prompt, the points, and what the player may do
 * with it now - react, share it to the Gallery under its drawer's name, or
 * report it (R-SOLO-15). Never who drew it.
 */
function SoloCard({
  run,
  serve,
  onNext,
  busy,
  registered,
}: {
  run: SoloRun;
  serve: SoloServe;
  onNext: () => void;
  busy: boolean;
  registered: boolean;
}) {
  // The field the player was typing in is gone: the verdict takes focus, so
  // a screen reader says what the drawing came to.
  const verdict = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    verdict.current?.focus();
  }, []);
  const { notify } = useToast();
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [mine, setMine] = useState<string | null>(null);
  const [share, setShare] = useState<SoloShare | null>(null);
  const [reporting, setReporting] = useState(false);
  const solved = serve.outcome === "solved";
  const over = run.state !== "active";

  const toggleShare = async () => {
    try {
      setShare(await shareServe(serve.serveId, !(share?.sharedByMe ?? false)));
    } catch (failure) {
      notify(refusalText(failure, ui.shareControl.thatDrawingCouldNotBeShared), "error");
    }
  };

  return (
    <div className="solo-result" data-testid="solo-card">
      <div className="surface-card solo-result-card">
        <p
          ref={verdict}
          tabIndex={-1}
          className={`solo-verdict${solved ? " is-solved" : " is-missed"}`}
          data-testid="solo-verdict"
        >
          {solved ? words().gotIt : serve.outcome === "timed_out" ? words().timeUp : words().gaveUp}
        </p>
        <p className="solo-it-was">{words().itWas}</p>
        <h1 className="solo-prompt" data-testid="solo-prompt">{serve.prompt}</h1>
        {solved && serve.points !== null && (
          <p className="solo-points" data-testid="solo-points">{words().plusPoints({ points: serve.points })}</p>
        )}
        <p className="solo-note">{words().anonymity}</p>
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
          />
          {!share?.shareWithdrawn && (
            <button
              type="button"
              className={`btn btn-secondary btn-compact${share?.sharedByMe ? " is-pressed" : ""}`}
              aria-pressed={share?.sharedByMe ?? false}
              data-testid="solo-share"
              onClick={() => void toggleShare()}
            >
              <ImageIcon size={15} />
              {share?.sharedByMe ? words().sharedToGallery : words().shareToGallery}
            </button>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-compact btn-icon"
            aria-label={words().report}
            title={words().report}
            data-testid="solo-report"
            onClick={() => setReporting(true)}
          >
            <FlagIcon size={14} />
          </button>
        </div>
        {share?.sharedByMe && share.heldUntil && <p className="solo-note" data-testid="solo-share-held">{words().shareHeld}</p>}
        {share?.shareWithdrawn && <p className="solo-note">{words().shareTakenOut}</p>}
        <button type="button" className="btn btn-warm btn-big solo-next" data-testid="solo-next" disabled={busy} onClick={onNext}>
          {over ? words().seeResult : words().next}
        </button>
      </div>
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
