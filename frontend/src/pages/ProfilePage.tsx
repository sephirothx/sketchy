import { useClock } from "../hooks/useClock";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AuthDialog, type AuthMode } from "../components/AccountMenu";
import { AppHeader } from "../components/AppHeader";
import { ChevronDownIcon, ChevronRightIcon } from "../components/icons";
import { avatarInitial, identityColor } from "../lib/avatar";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { ApiError } from "../lib/api";
import { DrawingRecapGallery } from "../components/DrawingRecapGallery";
import type { DrawingRecapMetadata } from "../types";
import {
  fetchGameDetail,
  fetchGameDrawing,
  fetchGames,
  fetchProfile,
  formatDuration,
  formatTimestamp,
  HISTORY_PAGE_SIZE,
  type GameDetail,
  type GameTurn,
  type GameSummary,
  type ProfileStats,
} from "../lib/profile";
import { useAuthStore, type AuthUser } from "../store/authStore";

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="profile-stat">
      <span className="profile-stat-value">{value}</span>
      <span className="profile-stat-label">{label}</span>
    </div>
  );
}

/**
 * A player's name in the color they chose under Settings.
 *
 * Inside a link, a name with no color of its own would inherit the browser's
 * link color, which looks like a chosen color and never is - so
 * `identityColor` always resolves to something, and to the same value the
 * avatar beside it uses.
 */
function PlayerName({
  name,
  nameColor,
  isAnonymous,
}: {
  name: string;
  nameColor: string | null;
  isAnonymous: boolean;
}) {
  return (
    <span
      className={playerNameClass(isAnonymous)}
      style={playerNameStyle(identityColor(name, isAnonymous, nameColor), isAnonymous)}
    >
      {name}
    </span>
  );
}

/**
 * One game in the history list.
 *
 * Round detail is fetched only when the row is opened, and only once: a page of
 * games would otherwise pull every round of every game to show a list that
 * mostly stays collapsed.
 */
/** Why a turn has no drawing to show, in the words the state actually means. */
function drawingNote(turn: GameTurn): string {
  if (turn.drawingStatus === "unavailable") return "not kept";
  if (turn.drawingStatus === "deleted") return "erased";
  if (turn.strokeCount === 0) return "nothing drawn";
  return "—";
}

function GameRow({ game, viewerId }: { game: GameSummary; viewerId: string }) {
  const { timeFormat } = useClock();
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<GameDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [viewingIndex, setViewingIndex] = useState<number | null>(null);

  const seat = game.participants.find((p) => p.userId === viewerId);
  const finishedAt = formatTimestamp(game.finishedAt, timeFormat);

  async function toggle() {
    const next = !expanded;
    setExpanded(next);
    if (!next || detail) return;
    // Reopening retries: the previous attempt may simply have been a dropped
    // connection, and the only other way back is a full reload.
    setDetailError(null);
    try {
      setDetail(await fetchGameDetail(game.id));
    } catch (error) {
      setDetailError(
        error instanceof ApiError && error.status === 404
          ? "Only the players in this game can see its turns."
          : "Could not load the turns for this game.",
      );
    }
  }

  return (
    <li className="profile-game">
      <button
        type="button"
        className="profile-game-header"
        onClick={toggle}
        aria-expanded={expanded}
      >
        <span
          className={`profile-game-place${
            seat?.finalRank != null && game.outcome === "finished" && seat.finalRank <= 3
              ? ` is-place-${seat.finalRank}`
              : ""
          }`}
          aria-hidden="true"
        >
          {seat?.finalRank != null && game.outcome === "finished" ? `#${seat.finalRank}` : "—"}
        </span>
        <span className="profile-game-title">
          <span className="profile-game-room">{game.roomName}</span>
          <span className="profile-game-meta">
            {finishedAt} · {game.totalRounds} rounds · {game.playerCount} players
            {game.outcome !== "finished" && (
              <span className="profile-game-outcome">
                {game.outcome === "abandoned" ? "abandoned" : "cut short"}
              </span>
            )}
          </span>
        </span>
        {seat && (
          <span className="profile-game-result">
            {/* No placing in a game that never finished. The points are a fact
                about turns that were played; a rank is a claim about how it
                ended, and this one did not end. */}
            {game.outcome === "finished" && (
              <span
                className={
                  seat.finalRank === 1
                    ? "profile-game-rank is-winner"
                    : "profile-game-rank"
                }
              >
                #{seat.finalRank}
              </span>
            )}
            <span className="profile-game-score">{seat.finalScore} pts</span>
          </span>
        )}
        <span className="profile-game-chevron" aria-hidden="true">
          {expanded ? <ChevronDownIcon size={16} /> : <ChevronRightIcon size={16} />}
        </span>
      </button>

      {expanded && (
        <div className="profile-game-body">
          <p className="profile-note">
            Rules: {game.scoringMode} scoring
            {game.scoringVersion > 0 ? ` v${game.scoringVersion}` : " (legacy version unknown)"}
            {` · ${game.hintMode} hints · ${game.drawingSeconds} seconds`}
            {` · ${game.promptSourceMode.replaceAll("_", " ")} prompts`}
          </p>
          {game.outcome !== "finished" && (
            <p className="profile-note">
              This game did not finish, so these are the scores as they stood
              when it stopped rather than a final placing.
            </p>
          )}
          <ol className="profile-standings">
            {game.participants.map((p) => (
              <li key={p.seatId}>
                {game.outcome === "finished" && (
                  <span className="profile-standing-rank">#{p.finalRank}</span>
                )}
                {p.userId ? <Link to={`/profile/${p.userId}`}>
                  <PlayerName
                    name={p.displayName}
                    nameColor={p.nameColor}
                    isAnonymous={p.isAnonymous}
                  />
                </Link> : (
                  <PlayerName
                    name={p.displayName}
                    nameColor={p.nameColor}
                    isAnonymous={p.isAnonymous}
                  />
                )}
                <span className="profile-standing-score">{p.finalScore}</span>
              </li>
            ))}
          </ol>

          {detailError && <p className="profile-note">{detailError}</p>}
          {!detail && !detailError && <p className="profile-note">Loading turns…</p>}

          {detail && (() => {
            // The rounds carry ids, the standings carry the colors: joining
            // them here keeps every name in a recap the same color, without
            // the detail endpoint repeating what the summary already sent.
            const bySeat = new Map(
              detail.participants.map((participant) => [participant.seatId, participant]),
            );
            const named = (
              seatId: string | null,
              fallbackName: string,
            ) => {
              const participant = seatId ? bySeat.get(seatId) : undefined;
              return (
                <PlayerName
                  name={participant?.displayName ?? fallbackName}
                  nameColor={participant?.nameColor ?? null}
                  isAnonymous={participant?.isAnonymous ?? true}
                />
              );
            };
            const outcomeLabel = (outcome: GameTurn["participantOutcomes"][number]) => {
              if (outcome.outcome === "correct") return "correct";
              if (outcome.outcome === "incorrect") {
                return `${outcome.wrongGuessCount} wrong`;
              }
              if (outcome.outcome === "no_attempt") return "no attempt";
              // Only games finished before a mid-turn arrival became an
              // ordinary guesser carry this reason.
              if (outcome.eligibilityReason === "joined_late") return "joined late";
              return `not eligible (${outcome.eligibilityReason})`;
            };
            // Every turn is offered, not only the ones with bytes to show: a
            // gallery that quietly skipped them would misreport how the game
            // went, and the viewer already renders why one is missing.
            const viewerEntries: DrawingRecapMetadata[] = detail.turns.map(
              (turn, index) => ({
                index,
                roundNumber: turn.roundNumber,
                turnNumber: turn.turnNumber,
                drawerId: turn.drawerSeatId ?? "",
                drawerNickname: turn.drawerDisplayName,
                drawerNameColor: turn.drawerNameColor ?? undefined,
                prompt: turn.prompt,
                actionCount: turn.strokeCount,
                available: turn.drawingStatus === "ready",
              }),
            );
            return (
            <>
            {viewingIndex !== null && (
              <DrawingRecapGallery
                entries={viewerEntries}
                initialIndex={viewingIndex}
                onClose={() => setViewingIndex(null)}
                loadEntry={(entry) =>
                  fetchGameDrawing(game.id, detail.turns[entry.index].id)
                }
              />
            )}
            <table className="profile-turns">
              <caption className="visually-hidden">Turn by turn</caption>
              <thead>
                <tr>
                  <th scope="col">Round</th>
                  <th scope="col">Prompt</th>
                  <th scope="col">Drawn by</th>
                  <th scope="col">Time</th>
                  <th scope="col">Drawing</th>
                  <th scope="col">Guesser outcomes</th>
                </tr>
              </thead>
              <tbody>
                {detail.turns.map((turn, turnIndex) => (
                  <tr key={turn.id}>
                    <td>{turn.roundNumber}</td>
                    <td className="profile-turn-prompt">{turn.prompt}</td>
                    <td>
                      <span style={{ color: turn.drawerNameColor ?? undefined }}>
                        {named(turn.drawerSeatId, turn.drawerDisplayName)}
                      </span>
                    </td>
                    <td>{formatDuration(turn.durationSeconds)}</td>
                    <td>
                      {turn.drawingStatus === "ready" ? (
                        <button
                          type="button"
                          className="profile-drawing-button"
                          onClick={() => setViewingIndex(turnIndex)}
                        >
                          View
                        </button>
                      ) : (
                        <span className="profile-note">{drawingNote(turn)}</span>
                      )}
                    </td>
                    <td>
                      {turn.participantOutcomes.length > 0
                        ? turn.participantOutcomes.map((outcome, index) => (
                            <span key={outcome.seatId}>
                              {index > 0 && ", "}
                              {named(outcome.seatId, "Unknown player")} ({
                                outcome.outcome === "correct"
                                  ? `correct, ${turn.guesses.find((guess) => guess.seatId === outcome.seatId)?.pointsAwarded ?? 0}`
                                  : outcomeLabel(outcome)
                              })
                            </span>
                          ))
                        : turn.guesses.length === 0
                          ? "unknown"
                          : turn.guesses.map((g, index) => (
                              <span key={g.seatId ?? `legacy-${index}`}>
                                {index > 0 && ", "}
                                <span style={{ color: g.nameColor ?? undefined }}>
                                  {named(g.seatId, g.displayName)}
                                </span>{" "}(correct, {g.pointsAwarded})
                              </span>
                            ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {detail.scoreLedgerVersion === 0 ? (
              <p className="profile-note">Score breakdown unavailable for this legacy game.</p>
            ) : detail.scoreEvents.length === 0 ? (
              <p className="profile-note">No score changed in this game.</p>
            ) : (
              <table className="profile-score-events">
                <caption>Score ledger</caption>
                <thead>
                  <tr>
                    <th scope="col">Order</th>
                    <th scope="col">Player</th>
                    <th scope="col">Reason</th>
                    <th scope="col">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.scoreEvents.map((event) => (
                    <tr key={event.id}>
                      <td>{event.eventOrder}</td>
                      <td>{named(event.participantSeatId, "Unknown player")}</td>
                      <td>{event.eventType.replaceAll("_", " ")}</td>
                      <td>{event.pointsDelta > 0 ? "+" : ""}{event.pointsDelta}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            </>
            );
          })()}
        </div>
      )}
    </li>
  );
}

export function ProfilePage() {
  const params = useParams<{ userId?: string }>();
  const currentUser = useAuthStore((s) => s.user);
  const hasResolved = useAuthStore((s) => s.hasResolved);

  // No id in the path means "me", which is only knowable once the account has
  // resolved - so the view waits rather than fetching at an empty id.
  const userId = params.userId ?? currentUser?.id ?? null;

  if (!userId) {
    return (
      <div className="profile-page">
        <AppHeader page="Profile" />
        <p className="profile-note">
          {hasResolved ? "There is no player with that profile." : "Loading…"}
        </p>
      </div>
    );
  }

  // Keyed on the subject so following a link to another profile starts from a
  // clean slate instead of showing the previous player's numbers while the new
  // ones load.
  return <ProfileView key={userId} userId={userId} />;
}



function ProfileView({ userId }: { userId: string }) {
  const { timeFormat } = useClock();
  const currentUser = useAuthStore((s) => s.user);
  const isOwnProfile = userId === currentUser?.id;

  const [subject, setSubject] = useState<AuthUser | null>(null);
  const [stats, setStats] = useState<ProfileStats | null>(null);
  const [games, setGames] = useState<GameSummary[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  // Off by default: a history made mostly of rooms that collapsed is not what
  // anyone came looking for. Reachable, because a game somebody remembers
  // falling apart should still be findable.
  const [includeAbandoned, setIncludeAbandoned] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const register = useAuthStore((s) => s.register);
  const login = useAuthStore((s) => s.login);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [profile, page] = await Promise.all([
          fetchProfile(userId),
          fetchGames(userId, 0, includeAbandoned),
        ]);
        if (cancelled) return;
        setSubject(profile.user);
        setStats(profile.stats);
        setGames(page.games);
        setHasMore(page.hasMore);
      } catch (loadError) {
        if (cancelled) return;
        setError(
          loadError instanceof ApiError && loadError.status === 404
            ? "There is no player with that profile."
            : "Could not load this profile. Please try again.",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, includeAbandoned]);

  const loadMore = useCallback(async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await fetchGames(userId, games.length, includeAbandoned);
      setGames((current) => [...current, ...page.games]);
      setHasMore(page.hasMore);
    } catch {
      setError("Could not load more games.");
    } finally {
      setLoadingMore(false);
    }
  }, [userId, games.length, includeAbandoned, loadingMore]);

  const shownName = subject
    ? (subject.isAnonymous ? subject.displayName : subject.username ?? subject.displayName)
    : "";

  return (
    <div className="profile-page">
      <AppHeader page="Profile" />

      {!subject && !error && <p className="profile-note">Loading…</p>}
      {error && <p className="lobby-action-error" role="alert">{error}</p>}

      {subject && stats && (
        <>
          <header className="profile-identity">
            {/* The avatar wears the same color as the name it belongs to. */}
            <span
              className={`profile-avatar avatar avatar-player${
                !subject.isAnonymous && subject.avatarUrl ? " has-picture" : ""
              }`}
              aria-hidden="true"
              style={{
                ["--player-color" as string]: identityColor(
                  shownName,
                  subject.isAnonymous,
                  subject.nameColor,
                ),
              }}
            >
              {!subject.isAnonymous && subject.avatarUrl ? (
                <img src={subject.avatarUrl} alt="" />
              ) : (
                avatarInitial(shownName)
              )}
            </span>
            <div>
              <h1>
                <PlayerName
                  name={shownName}
                  nameColor={subject.nameColor}
                  isAnonymous={subject.isAnonymous}
                />
              </h1>
              <p className="profile-subtitle">
                {subject.isAnonymous ? "Guest — display name not saved" : "Registered player"}
                {subject.createdAt && ` · joined ${formatTimestamp(subject.createdAt, timeFormat)}`}
              </p>
            </div>
          </header>

          {isOwnProfile && subject.isAnonymous && (
            <section className="panel profile-claim">
              <h2>Claim your account</h2>
              <p>
                Your games are already being recorded under this display name.
                Create an account to keep them and use it as your username on every device.
              </p>
              <button type="button" onClick={() => setAuthMode("claim")}>
                Create account
              </button>
            </section>
          )}

          <section className="panel">
            <h2>Statistics</h2>
            <div className="profile-stats">
              <StatTile label="Games played" value={String(stats.gamesPlayed)} />
              <StatTile label="Games won" value={String(stats.gamesWon)} />
              <StatTile
                label="Win rate"
                value={`${Math.round(stats.winRate * 100)}%`}
              />
              <StatTile label="Average score" value={String(Math.round(stats.averageScore))} />
            </div>
            <div className="profile-stats profile-stats-small">
              <StatTile label="Turns played" value={String(stats.turnsPlayed)} />
              <StatTile label="Prompts guessed" value={String(stats.promptsGuessed)} />
              <StatTile label="Drawings made" value={String(stats.drawingsMade)} />
              <StatTile label="Total score" value={String(stats.totalScore)} />
            </div>
          </section>

          <section className="panel">
            <div className="profile-history-head">
              <h2>Game history</h2>
              <label className="profile-history-filter">
                <input
                  type="checkbox"
                  checked={includeAbandoned}
                  onChange={(change) => setIncludeAbandoned(change.target.checked)}
                />
                Include games that fell apart
              </label>
            </div>
            {games.length === 0 ? (
              <p className="profile-note">
                {isOwnProfile
                  ? "No finished games yet. Play one and it will show up here."
                  : "This player has not finished a game yet."}
              </p>
            ) : (
              <ul className="profile-games">
                {games.map((game) => (
                  <GameRow key={game.id} game={game} viewerId={subject.id} />
                ))}
              </ul>
            )}
            {hasMore && (
              <button type="button" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : `Load ${HISTORY_PAGE_SIZE} more`}
              </button>
            )}
          </section>
        </>
      )}

      {authMode && (
        <AuthDialog
          mode={authMode}
          suggestedUsername={authMode === "claim" ? subject?.displayName ?? "" : ""}
          onClose={() => setAuthMode(null)}
          onSubmit={async (username, password) => {
            const account = await (authMode === "login" ? login : register)(
              username,
              password,
            );
            // Claiming keeps the same user id, so this view never remounts and
            // would otherwise keep showing the guest it loaded - name, badge,
            // and an invitation to claim an account that now exists.
            if (account.id === userId) setSubject(account);
            return account;
          }}
          onSwitchMode={setAuthMode}
        />
      )}
    </div>
  );
}
