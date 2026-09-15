import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AuthDialog } from "../components/AccountMenu";
import { AppHeader } from "../components/AppHeader";
import type { CanvasRef } from "../components/Canvas";
import { DrawingReactionControl } from "../components/DrawingReactionControl";
import { ReplayCanvas } from "../components/ReplayCanvas";
import { ReportDrawingDialog } from "../components/ReportDrawingDialog";
import { DownloadIcon, FlagIcon, PlayIcon, PauseIcon, UndoIcon } from "../components/icons";
import { authSubmitter, type AuthMode } from "../lib/authSubmit";
import { decodeCanvasHistory } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { fetchGalleryDrawing, fetchGalleryEntry, galleryAge, type GalleryEntry } from "../lib/gallery";
import { setGalleryReaction } from "../lib/profile";
import { reactionEligibility } from "../lib/reactions";
import { refusalText } from "../lib/refusals.ts";
import { useAuthStore } from "../store/authStore";
import { ui } from "../content/ui/index.ts";

/**
 * One drawing's own page, `/gallery/{turnId}` (#524): the drawing replayed
 * the way the room saw it drawn, the prompt as the title, by whom and how
 * long ago, and the picker through the gallery door (R-GAL-06). It has a
 * link because a drawing worth a reaction is worth sending to somebody;
 * what it publishes is what the feed publishes and nothing more (R-GAL-03).
 */
export function GalleryDrawingPage() {
  const navigate = useNavigate();
  const { turnId = "" } = useParams<{ turnId: string }>();
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const register = useAuthStore((state) => state.register);
  const login = useAuthStore((state) => state.login);
  const registered = Boolean(user && !user.isAnonymous);
  const signedOut = hasResolved && user === null;
  const reader = user?.id ?? "";

  const [entry, setEntry] = useState<{ reader: string; entry: GalleryEntry } | null>(null);
  const [actions, setActions] = useState<DecodedCanvasAction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [run, setRun] = useState(1);
  const [playing, setPlaying] = useState(true);
  const [progress, setProgress] = useState(0);
  const [reporting, setReporting] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const canvasRef = useRef<CanvasRef | null>(null);

  const shown = entry?.reader === reader ? entry.entry : null;

  useEffect(() => {
    if (!hasResolved || signedOut || !turnId) return;
    let cancelled = false;
    void Promise.all([fetchGalleryEntry(turnId), fetchGalleryDrawing(turnId)])
      .then(([fetched, bytes]) => {
        if (cancelled) return;
        setMissing(false);
        const decoded = decodeCanvasHistory(bytes);
        if (!decoded) {
          setError(ui.galleryPage.couldNotLoadThisDrawing);
          return;
        }
        setEntry({ reader, entry: fetched });
        setActions(decoded);
        setRun((count) => count + 1);
        setPlaying(true);
        setError(null);
      })
      .catch((loadError) => {
        if (cancelled) return;
        // The Gallery's one 404: erased, hidden, private, or never there.
        if ((loadError as { status?: number }).status === 404) setMissing(true);
        else setError(refusalText(loadError, ui.galleryPage.couldNotLoadThisDrawing));
      });
    return () => { cancelled = true; };
  }, [turnId, reader, hasResolved, signedOut]);

  const react = async (emoji: string | null) => {
    if (!shown) return;
    const result = await setGalleryReaction(shown.turnId, emoji);
    setEntry({ reader, entry: { ...shown, reactionCounts: result.reactionCounts, myReaction: result.myReaction } });
  };

  const finished = progress >= 1;
  const age = shown ? galleryAge(shown.finishedAt) : null;

  return (
    <div className="page gallery-page gallery-drawing-page">
      <AppHeader backLabel={ui.galleryPage.backToGallery} languageSwitch />

      {signedOut ? (
        <div className="gallery-empty-state" data-testid="gallery-signed-out">
          <p className="gallery-end-title">{ui.galleryPage.signInToSeeTheGallery}</p>
          <p className="gallery-end-body">{ui.galleryPage.signInBody}</p>
          <button type="button" className="btn btn-secondary" onClick={() => navigate("/")}>
            {ui.galleryPage.backToLobby}
          </button>
        </div>
      ) : missing ? (
        <div className="gallery-empty-state" data-testid="gallery-drawing-missing">
          <p className="gallery-end-title">{ui.galleryPage.notInTheGallery}</p>
          <p className="gallery-end-body">{ui.galleryPage.notInTheGalleryBody}</p>
          <button type="button" className="btn btn-secondary" onClick={() => navigate("/gallery")}>
            {ui.galleryPage.backToGallery}
          </button>
        </div>
      ) : (
        <article className="gallery-drawing" data-testid="gallery-drawing-page" aria-busy={shown === null && !error}>
          {error && <p className="lobby-action-error" role="alert">{error}</p>}
          <div className="surface-card gallery-drawing-card">
            <div className="gallery-drawing-canvas" data-testid="gallery-drawing-canvas">
              {actions
                ? <ReplayCanvas
                    ref={canvasRef}
                    actions={actions}
                    run={run}
                    playing={playing}
                    onProgress={setProgress}
                    onDone={() => setPlaying(false)}
                    downloadPrompt={shown?.prompt ?? null}
                    label={shown
                      ? ui.drawingRecapGallery.drawingLabel({ prompt: shown.prompt, drawer: shown.drawerDisplayName })
                      : undefined}
                  />
                : <div className="gallery-post-skeleton" />}
            </div>
            {/* The replay's controls sit on the mat under the picture: how
                far it has got, and one button that plays, pauses, or plays
                again - never three buttons for one thing. */}
            <div className="gallery-replay-bar" role="group" aria-label={ui.galleryPage.replay}>
              <button
                type="button"
                className="btn btn-secondary btn-compact"
                disabled={!actions}
                data-testid="gallery-replay-toggle"
                onClick={() => {
                  if (finished) {
                    setRun((count) => count + 1);
                    setPlaying(true);
                  } else {
                    setPlaying((value) => !value);
                  }
                }}
              >
                {finished
                  ? <><UndoIcon size={15} />{ui.galleryPage.playAgain}</>
                  : playing
                    ? <><PauseIcon size={15} />{ui.galleryPage.pause}</>
                    : <><PlayIcon size={15} />{ui.galleryPage.replay}</>}
              </button>
              <div
                className="gallery-replay-track"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(progress * 100)}
                aria-label={ui.galleryPage.replay}
              >
                <div className="gallery-replay-fill" style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-compact"
                disabled={!actions}
                onClick={() => canvasRef.current?.saveImage()}
              >
                <DownloadIcon size={15} />
                {ui.galleryPage.saveImage}
              </button>
            </div>
            <div className="gallery-post-mat">
              <div className="gallery-post-caption">
                <h1 className="gallery-post-prompt gallery-drawing-title">{shown?.prompt ?? "\u00a0"}</h1>
                {shown && (
                  <span className="gallery-post-byline">
                    {ui.galleryPage.byDrawerPrefix}{" "}
                    <strong
                      className="colored-player-name"
                      style={shown.drawerNameColor ? { color: shown.drawerNameColor } : undefined}
                    >
                      {shown.drawerDisplayName}
                    </strong>
                    <span className="gallery-post-dot" aria-hidden="true">·</span>
                    <span className="gallery-post-age">
                      {age ? ui.galleryPage.ago(age) : ui.galleryPage.justNow}
                    </span>
                  </span>
                )}
              </div>
              {shown && (
                <div className="gallery-post-actions">
                  <DrawingReactionControl
                    reactions={[]}
                    myReactorId={null}
                    counts={shown.reactionCounts}
                    mine={shown.myReaction}
                    eligibility={reactionEligibility({
                      isRegistered: registered,
                      isDrawer: shown.drawnByMe,
                    })}
                    onReact={react}
                    onRequestAccount={() => setAuthMode("claim")}
                    placement="panel"
                  />
                  {user && !shown.drawnByMe && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-compact btn-icon gallery-post-report"
                      aria-label={ui.reportDrawingDialog.reportThisDrawing}
                      title={ui.reportDrawingDialog.reportThisDrawing}
                      data-testid="gallery-report"
                      onClick={() => setReporting(true)}
                    >
                      <FlagIcon size={14} />
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        </article>
      )}

      {reporting && shown && (
        <ReportDrawingDialog turnId={shown.turnId} onClose={() => setReporting(false)} />
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
