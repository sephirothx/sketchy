import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AuthDialog } from "../components/AccountMenu";
import { AppHeader } from "../components/AppHeader";
import { DrawingReactionControl } from "../components/DrawingReactionControl";
import { ReplayCanvas } from "../components/ReplayCanvas";
import { ReportDrawingDialog } from "../components/ReportDrawingDialog";
import { CopyIcon, FlagIcon, ImageIcon, UserIcon } from "../components/icons";
import { EmptyState } from "../components/ui/EmptyState";
import { ui } from "../content/ui/index.ts";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { authSubmitter, type AuthMode } from "../lib/authSubmit";
import { decodeCanvasHistory, type DecodedCanvasAction } from "../lib/canvasHistory";
import { judge } from "../lib/guessJudge";
import { reactionEligibility } from "../lib/reactions";
import { refusalText } from "../lib/refusals.ts";
import {
  decodeSoloForms,
  fetchActiveFreeRun,
  fetchSoloDrawing,
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
} from "../lib/soloPlay";
import { useToast } from "../lib/toast";
import { useAuthStore } from "../store/authStore";
import "../styles/lazy/solo.css";

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
  const today = localDateKey();

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await fetchSoloSummary(localDateKey()));
      setError(null);
    } catch (failure) {
      setError(refusalText(failure, ui.solo.couldNotLoad));
    }
  }, []);

  useEffect(() => {
    if (!hasResolved || !user || user.isAnonymous) return;
    let cancelled = false;
    fetchSoloSummary(localDateKey())
      .then((loaded) => {
        if (!cancelled) setSummary(loaded);
      })
      .catch((failure) => {
        if (!cancelled) setError(refusalText(failure, ui.solo.couldNotLoad));
      });
    return () => {
      cancelled = true;
    };
  }, [hasResolved, user]);

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
      setError(refusalText(failure, ui.solo.couldNotLoad));
    } finally {
      setBusy(false);
    }
  };

  const settled = async (serve: SoloServe, outcome: SoloOutcome, seconds: number) => {
    if (!run) return;
    const answer = await settleServe(serve.serveId, outcome, seconds);
    forgetServeStart(serve.serveId);
    setRun((current) =>
      current
        ? {
            ...answer.run,
            // The server's run lists what it served; a drawing this page holds
            // ready that the server has not dropped stays.
            serves: answer.run.serves,
          }
        : current,
    );
    setCard(answer.serve);
  };

  const next = async () => {
    if (!run) return;
    setCard(null);
    if (run.state !== "active") {
      setSummaryOf(run);
      setRun(null);
      void loadSummary();
      return;
    }
    if (run.mode === "free" && !run.serves.some((serve) => serve.outcome === null)) {
      try {
        const served = await serveNext(run.runId, 2);
        setRun({ ...run, serves: [...run.serves, ...served] });
      } catch (failure) {
        setError(refusalText(failure, ui.solo.couldNotLoad));
        setRun(null);
        void loadSummary();
      }
    }
  };

  const playing = run?.serves.find((serve) => serve.outcome === null) ?? null;

  return (
    <div className="page solo-page" data-testid="solo-page">
      <AppHeader backLabel={ui.solo.backToLobby} />

      {signedOut || guest ? (
        <>
          <div className="solo-head">
            <h1>{ui.solo.solo}</h1>
            <p>{ui.solo.intro}</p>
          </div>
          <EmptyState
            testId="solo-account-required"
            title={signedOut ? ui.solo.signInToPlay : ui.solo.accountToPlay}
            body={signedOut ? ui.solo.signInBody : ui.solo.accountBody}
            action={
              signedOut ? (
                <button type="button" className="btn btn-secondary" onClick={() => navigate("/")}>
                  {ui.solo.backToLobby}
                </button>
              ) : (
                <button type="button" className="btn btn-primary" onClick={() => setAuthMode("claim")}>
                  {ui.solo.createAccount}
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
          registered={Boolean(user && !user.isAnonymous)}
        />
      ) : run && playing ? (
        <SoloPlay
          key={playing.serveId}
          run={run}
          serve={playing}
          upcoming={run.serves.find((serve) => serve.outcome === null && serve !== playing) ?? null}
          onSettle={(outcome, seconds) => settled(playing, outcome, seconds)}
        />
      ) : summaryOf ? (
        <SoloSummaryView
          run={summaryOf}
          summary={summary}
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
              if (!active) throw new Error(ui.solo.couldNotLoad);
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
        <p>{ui.solo.intro}</p>
      </div>
      {error && <p className="lobby-action-error" role="alert">{error}</p>}

      <div className="solo-grid">
        <section className="surface-card solo-daily" data-testid="solo-daily">
          <div className="solo-card-head">
            <h2>{ui.solo.daily}</h2>
            {summary && summary.streak > 0 && (
              <span className="chip chip-warm" data-testid="solo-streak">
                {ui.solo.streak({ days: summary.streak })}
              </span>
            )}
          </div>
          <p className="solo-card-intro">{ui.solo.dailyIntro}</p>
          {todayState === "unavailable" ? (
            <p className="solo-note">{ui.solo.noDailyToday}</p>
          ) : todayState === "done" && result ? (
            <div className="solo-daily-done">
              <DailyMarks result={result} />
              <p className="solo-daily-points">{ui.solo.dailyDone({ points: result.points })}</p>
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
                ? ui.solo.continueDaily({ played: result.positionsPlayed })
                : todayState === "in_progress"
                  ? ui.solo.continueDaily({ played: 0 })
                  : ui.solo.playDaily}
            </button>
          )}
        </section>

        <section className="surface-card solo-free" data-testid="solo-free">
          <div className="solo-card-head">
            <h2>{ui.solo.freeRun}</h2>
          </div>
          <p className="solo-card-intro">{ui.solo.freeRunIntro}</p>
          {summary?.activeRunId && (
            <button
              type="button"
              className="btn btn-primary solo-continue"
              data-testid="solo-continue-run"
              disabled={busy}
              onClick={onContinue}
            >
              {ui.solo.continueRun}
            </button>
          )}
          <div className="solo-lengths" role="group" aria-label={ui.solo.freeRun}>
            {([5, 10, null] as const).map((length) => (
              <button
                key={String(length)}
                type="button"
                className="btn btn-secondary solo-length"
                data-testid={`solo-free-${length ?? "unlimited"}`}
                disabled={busy || summary === null}
                onClick={() => onFree(length)}
              >
                {length === null ? ui.solo.unlimited : ui.solo.drawingsCount({ count: length })}
              </button>
            ))}
          </div>
          <p className="solo-note solo-preview">{ui.solo.supporterPreview}</p>
        </section>
      </div>

      <div className="solo-grid">
        <section className="surface-card solo-bests" data-testid="solo-bests">
          <h2>{ui.solo.bests}</h2>
          <dl>
            {(
              [
                ["5", ui.solo.bestFive],
                ["10", ui.solo.bestTen],
                ["unlimited", ui.solo.bestUnlimited],
              ] as const
            ).map(([key, label]) => {
              const best = summary?.bests[key];
              return (
                <div key={key} className="solo-best">
                  <dt>{label}</dt>
                  <dd>
                    {best === undefined
                      ? ui.solo.noBestYet
                      : key === "unlimited"
                        ? ui.solo.inARow({ count: best })
                        : ui.solo.pointsValue({ points: best })}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>

        <section className="surface-card solo-history" data-testid="solo-history">
          <h2>{ui.solo.yourDailies}</h2>
          {summary && summary.history.length === 0 ? (
            <p className="solo-note">{ui.solo.noDailiesYet}</p>
          ) : (
            <ol>
              {(summary?.history ?? []).slice(0, 14).map((day) => (
                <li key={day.date} className="solo-history-day">
                  <span className="solo-history-date">{day.date}</span>
                  <DailyMarks result={day} />
                  <span className="solo-history-points">{ui.solo.pointsValue({ points: day.points })}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}

/** One square per drawing of a Daily: named, missed, or still to play. */
function DailyMarks({ result }: { result: SoloDailyResult }) {
  const marks = dailyMarks(result);
  return (
    <span className="solo-marks" aria-label={ui.solo.youNamed({ solved: result.solved, total: 5 })}>
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
    const text = `${ui.solo.resultText({
      daily: ui.solo.daily,
      date: result.date,
      marks: symbols,
      points: result.points,
    })}\n${window.location.origin}/solo`;
    try {
      await navigator.clipboard.writeText(text);
      notify(ui.solo.copied, "success");
    } catch {
      notify(text, "info", 8000);
    }
  };
  return (
    <button type="button" className="btn btn-secondary btn-compact" data-testid="solo-copy-result" onClick={() => void copy()}>
      <CopyIcon size={15} />
      {ui.solo.copyResult}
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
  return <p className="solo-note solo-countdown" data-testid="solo-countdown">{ui.solo.nextDailyIn({ time })}</p>;
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
}: {
  run: SoloRun;
  serve: SoloServe;
  upcoming: SoloServe | null;
  onSettle: (outcome: SoloOutcome, seconds: number) => Promise<void>;
}) {
  const [actions, setActions] = useState<DecodedCanvasAction[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [fraction, setFraction] = useState(0);
  const [guess, setGuess] = useState("");
  const [feedback, setFeedback] = useState<{ text: string; tone: "close" | "miss" } | null>(null);
  const settling = useRef(false);
  const target = useMemo(() => (serve.forms ? decodeSoloForms(serve.serveId, serve.forms) : null), [serve]);

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
        const start = serveStartedAt(serve.serveId);
        setActions(decoded);
        setStartedAt(start);
        setFraction(Math.min(1, (Date.now() - start) / 1000 / SOLO_REPLAY_SECONDS));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    // The next one, so it is on screen the moment this one is over.
    if (upcoming) void fetchSoloDrawing(upcoming.serveId).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [serve.serveId, upcoming]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(timer);
  }, []);

  const elapsed = startedAt === null ? 0 : Math.max(0, (now - startedAt) / 1000);
  const remaining = Math.max(0, SOLO_CLOCK_SECONDS - elapsed);

  const settle = useCallback(
    async (outcome: SoloOutcome, seconds: number) => {
      if (settling.current) return;
      settling.current = true;
      try {
        await onSettle(outcome, Math.min(SOLO_CLOCK_SECONDS, seconds));
      } catch {
        settling.current = false;
      }
    },
    [onSettle],
  );

  useEffect(() => {
    if (startedAt !== null && remaining <= 0) void settle("timed_out", SOLO_CLOCK_SECONDS);
  }, [remaining, startedAt, settle]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = guess.trim();
    if (!text || !target || startedAt === null) return;
    const verdict = judge(text, target);
    if (verdict === "correct") {
      void settle("solved", elapsed);
      return;
    }
    setGuess("");
    setFeedback(
      verdict === "close"
        ? { text: ui.solo.veryClose, tone: "close" }
        : verdict === "partial"
          ? { text: ui.solo.someWordsRight, tone: "close" }
          : { text: ui.solo.notIt({ guess: text }), tone: "miss" },
    );
  };

  return (
    <div className="solo-play" data-testid="solo-play">
      <div className="solo-play-bar">
        <span className="solo-play-position">{ui.solo.drawingOf({ position: serve.position, length: run.length })}</span>
        <span
          className={`solo-clock${remaining <= 10 ? " is-low" : ""}`}
          data-testid="solo-clock"
          role="timer"
          aria-live="off"
        >
          {ui.solo.secondsLeft({ seconds: Math.ceil(remaining) })}
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
          <p className="solo-note">{ui.solo.couldNotLoadDrawing}</p>
        ) : (
          <div className="gallery-post-skeleton" />
        )}
      </div>
      <form className="solo-guess" onSubmit={submit}>
        <input
          type="search"
          className="solo-guess-input"
          data-testid="solo-guess"
          value={guess}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="send"
          maxLength={64}
          placeholder={ui.solo.typeYourGuess}
          aria-label={ui.solo.typeYourGuess}
          disabled={!actions}
          onChange={(change) => setGuess(change.target.value)}
          // A new guess is the player's attention; the last verdict goes.
          onFocus={() => setFeedback(null)}
          autoFocus
        />
        <button type="submit" className="btn btn-primary" disabled={!actions || !guess.trim()}>
          {ui.solo.guess}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          data-testid="solo-give-up"
          disabled={!actions}
          onClick={() => void settle("given_up", elapsed)}
        >
          {ui.solo.giveUp}
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
  registered,
}: {
  run: SoloRun;
  serve: SoloServe;
  onNext: () => void;
  registered: boolean;
}) {
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
        <p className={`solo-verdict${solved ? " is-solved" : " is-missed"}`} data-testid="solo-verdict">
          {solved ? ui.solo.gotIt : serve.outcome === "timed_out" ? ui.solo.timeUp : ui.solo.gaveUp}
        </p>
        <p className="solo-it-was">{ui.solo.itWas}</p>
        <h1 className="solo-prompt" data-testid="solo-prompt">{serve.prompt}</h1>
        {solved && serve.points !== null && (
          <p className="solo-points" data-testid="solo-points">{ui.solo.plusPoints({ points: serve.points })}</p>
        )}
        <p className="solo-note">{ui.solo.anonymity}</p>
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
              {share?.sharedByMe ? ui.solo.sharedToGallery : ui.solo.shareToGallery}
            </button>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-compact btn-icon"
            aria-label={ui.solo.report}
            title={ui.solo.report}
            data-testid="solo-report"
            onClick={() => setReporting(true)}
          >
            <FlagIcon size={14} />
          </button>
        </div>
        {share?.sharedByMe && share.heldUntil && <p className="solo-note" data-testid="solo-share-held">{ui.solo.shareHeld}</p>}
        {share?.shareWithdrawn && <p className="solo-note">{ui.solo.shareTakenOut}</p>}
        <button type="button" className="btn btn-warm btn-big solo-next" data-testid="solo-next" onClick={onNext}>
          {over ? ui.solo.seeResult : ui.solo.next}
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
  summary,
  today,
  onBack,
}: {
  run: SoloRun;
  summary: SoloSummary | null;
  today: string;
  onBack: () => void;
}) {
  const settledCount = run.serves.filter((serve) => serve.outcome !== null).length;
  const result = run.mode === "daily" && summary?.today.date === today ? summary.today.result : null;
  const key = run.length === null ? "unlimited" : run.length === 5 ? "5" : "10";
  const best = run.mode === "free" ? summary?.bests[key] : undefined;
  const value = run.length === null ? run.solved : run.points;
  return (
    <div className="solo-summary" data-testid="solo-summary">
      <div className="surface-card solo-result-card">
        <p className="solo-verdict is-solved">{run.mode === "daily" ? ui.solo.dailyComplete : ui.solo.runOver}</p>
        <h1 className="solo-prompt">{ui.solo.totalPoints({ points: run.points })}</h1>
        <p className="solo-it-was">{ui.solo.youNamed({ solved: run.solved, total: settledCount })}</p>
        {result && <DailyMarks result={result} />}
        {best !== undefined && best === value && value > 0 && (
          <p className="chip chip-warm solo-new-best" data-testid="solo-new-best">{ui.solo.newBest}</p>
        )}
        <div className="solo-result-actions">
          {result && <CopyResultButton result={result} />}
          {run.mode === "daily" && <NextDailyCountdown />}
        </div>
        <button type="button" className="btn btn-primary solo-next" data-testid="solo-back" onClick={onBack}>
          <UserIcon size={15} />
          {ui.solo.backToSolo}
        </button>
      </div>
    </div>
  );
}
