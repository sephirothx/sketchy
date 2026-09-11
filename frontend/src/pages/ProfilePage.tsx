import { useClock } from "../hooks/useClock";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AuthDialog } from "../components/AccountMenu";
import { authSubmitter, type AuthMode } from "../lib/authSubmit";
import { AppHeader } from "../components/AppHeader";
import { ChevronDownIcon, ChevronRightIcon, FlagIcon } from "../components/icons";
import { ReportAccountDialog } from "../components/ReportAccountDialog";
import { avatarInitial, identityColor } from "../lib/avatar";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { ApiError } from "../lib/api";
import { DrawingRecapGallery } from "../components/DrawingRecapGallery";
import { DrawingReactionControl } from "../components/DrawingReactionControl";
import { ReactionGlyph } from "../components/ReactionGlyph";
import type { DrawingRecapMetadata, DrawingReaction } from "../types";
import { compactTally, reactionEligibility, tallyReactions } from "../lib/reactions";
import {
  fetchGameDetail,
  fetchGameDrawing,
  fetchGames,
  fetchProfile,
  formatDuration,
  formatTimestamp,
  HISTORY_PAGE_SIZE,
  setHistoryReaction,
  type GameDetail,
  type GameTurn,
  type GameSummary,
  type PublicProfile,
  type HistoryReaction,
  type ProfileStats,
} from "../lib/profile";
import { lastSeenLabel } from "../lib/lastSeen";
import { useAuthStore } from "../store/authStore";
import { isFriend, profileFriendActionFor } from "../lib/friends";
import { useFriendsStore } from "../store/friendsStore";
import { FriendButton } from "../components/FriendButton";
import { FriendMarkIcon } from "../components/icons";
import { ui } from "../content/ui/index.ts";

/** History reactions in the shape the shared control reads: seat id as the reactor id. */
function asReactions(reactions: HistoryReaction[]): DrawingReaction[] {
  return reactions.map((reaction) => ({ playerId: reaction.seatId, emoji: reaction.emoji }));
}

/** The per-emoji counts of one turn, read-only, for the turn table. */
function ReactionTallyCell({ reactions }: { reactions: HistoryReaction[] }) {
  const chips = compactTally(tallyReactions(reactions));
  if (chips.length === 0) return null;
  return (
    <span
      className="profile-turn-reactions"
      aria-label={chips.map((chip) => `${chip.label} ${chip.count}`).join(", ")}
    >
      {chips.map((chip) => (
        <span key={chip.code} className="reaction-chip">
          <ReactionGlyph code={chip.code} size={14} />
          <span className="reaction-count">{chip.count}</span>
        </span>
      ))}
    </span>
  );
}

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

function GameRow({
  game,
  viewerId,
  onRequestAccount,
}: {
  game: GameSummary;
  viewerId: string;
  /** Guests see how to become able to react; this opens the claim dialog. */
  onRequestAccount: () => void;
}) {
  const { timeFormat } = useClock();
  const currentUser = useAuthStore((s) => s.user);
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<GameDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [viewingIndex, setViewingIndex] = useState<number | null>(null);

  async function reactToTurn(turnId: string, emoji: string | null) {
    const result = await setHistoryReaction(game.id, turnId, emoji);
    setDetail((current) =>
      current
        ? {
            ...current,
            turns: current.turns.map((turn) =>
              turn.id === turnId ? { ...turn, reactions: result.reactions } : turn,
            ),
          }
        : current,
    );
  }

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
            {ui.profilePage.gameMeta({
              finishedAt,
              rounds: game.totalRounds,
              players: game.playerCount,
            })}
            {game.outcome !== "finished" && (
              <span className="profile-game-outcome">
                {game.outcome === "abandoned" ? "abandoned" : "cut short"}
              </span>
            )}
            {game.visibility === "private" && (
              <span className="profile-game-outcome">{ui.profilePage.privateRoom}</span>
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
            <span className="profile-game-score">{ui.profilePage.seatScore({ points: seat.finalScore })}</span>
          </span>
        )}
        <span className="profile-game-chevron" aria-hidden="true">
          {expanded ? <ChevronDownIcon size={16} /> : <ChevronRightIcon size={16} />}
        </span>
      </button>

      {expanded && (
        <div className="profile-game-body">
          <p className="profile-note">
            {ui.profilePage.gameRules({
              scoringMode: game.scoringMode,
              scoringVersion: game.scoringVersion,
              hintMode: game.hintMode,
              seconds: game.drawingSeconds,
              promptSource: game.promptSourceMode.replaceAll("_", " "),
            })}
          </p>
          {game.outcome !== "finished" && (
            <p className="profile-note">
              {ui.profilePage.thisGameDidNotFinishSo}
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
          {!detail && !detailError && <p className="profile-note">{ui.profilePage.loadingTurns}</p>}

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
              if (outcome.outcome === "correct") return `correct, ${outcome.pointsAwarded ?? 0}`;
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
                turnId: turn.id,
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
                renderReactions={(entry) => {
                  const turn = detail.turns[entry.index];
                  return (
                    <DrawingReactionControl
                      reactions={asReactions(turn.reactions)}
                      myReactorId={detail.mySeatId}
                      eligibility={reactionEligibility({
                        isRegistered: Boolean(currentUser && !currentUser.isAnonymous),
                        isDrawer: Boolean(turn.drawerSeatId) && turn.drawerSeatId === detail.mySeatId,
                        open: turn.drawingStatus === "ready",
                      })}
                      onReact={(emoji) => reactToTurn(turn.id, emoji)}
                      onRequestAccount={onRequestAccount}
                      placement="panel"
                    />
                  );
                }}
              />
            )}
            <table className="profile-turns">
              <caption className="visually-hidden">{ui.profilePage.turnByTurn}</caption>
              <thead>
                <tr>
                  <th scope="col">{ui.profilePage.round}</th>
                  <th scope="col">{ui.profilePage.prompt}</th>
                  <th scope="col">{ui.profilePage.drawnBy}</th>
                  <th scope="col">{ui.profilePage.time}</th>
                  <th scope="col">{ui.profilePage.drawing}</th>
                  <th scope="col">{ui.profilePage.reactions}</th>
                  <th scope="col">{ui.profilePage.guesserOutcomes}</th>
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
                          {ui.profilePage.view}
                        </button>
                      ) : (
                        <span className="profile-note">{drawingNote(turn)}</span>
                      )}
                    </td>
                    <td>
                      {turn.reactions.length > 0 ? (
                        <ReactionTallyCell reactions={turn.reactions} />
                      ) : (
                        <span className="profile-note">—</span>
                      )}
                    </td>
                    <td>
                      {turn.participantOutcomes.length > 0
                        ? turn.participantOutcomes.map((outcome, index) => (
                            <span key={outcome.seatId}>
                              {index > 0 && ", "}
                              {named(outcome.seatId, "Unknown player")} ({outcomeLabel(outcome)})
                            </span>
                          ))
                        : "unknown"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
        <AppHeader backLabel="Back to lobby" />
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

  const [subject, setSubject] = useState<PublicProfile | null>(null);
  const [stats, setStats] = useState<ProfileStats | null>(null);
  const [games, setGames] = useState<GameSummary[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  // Off by default: a history made mostly of rooms that collapsed is not what
  // anyone came looking for. Reachable, because a game somebody remembers
  // falling apart should still be findable.
  const [includeAbandoned, setIncludeAbandoned] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportingPicture, setReportingPicture] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const register = useAuthStore((s) => s.register);
  const login = useAuthStore((s) => s.login);
  const friendLists = useFriendsStore((s) => s.lists);
  // Nothing about a friendship is drawn until the lists are an answer about
  // *this* viewer. Empty lists and unread lists are the same shape, and
  // guessing wrong here is not cosmetic: an incoming request would be shown
  // as "Add friend", and pressing it accepts (asking back is how you say
  // yes) - so the page would have offered one thing and done another.
  const friendsKnown = useFriendsStore(
    (s) => s.loaded && s.ownerId === (currentUser?.id ?? null),
  );
  const viewerIsFriend = friendsKnown && isFriend(friendLists, userId);

  // Which list is current. Bumped when a reload starts and again when it
  // replaces the list, so a page fetched for the previous one - a "load
  // more" in flight while the viewer signed in or the abandoned filter
  // flipped, or one started at the old offset while the reload was still
  // out - is dropped rather than appended to a list it was never part of.
  const listGeneration = useRef(0);

  useEffect(() => {
    let cancelled = false;
    listGeneration.current += 1;
    void (async () => {
      try {
        const [profile, page] = await Promise.all([
          fetchProfile(userId),
          fetchGames(userId, 0, includeAbandoned),
        ]);
        if (cancelled) return;
        listGeneration.current += 1;
        setSubject(profile.user);
        setStats(profile.stats);
        setGames(page.games);
        setHasMore(page.hasMore);
      } catch (loadError) {
        if (cancelled) return;
        setError(
          loadError instanceof ApiError && loadError.status === 404
            ? ui.profilePage.noSuchProfile
            : ui.profilePage.couldNotLoadProfile,
        );
      }
    })();
    return () => {
      cancelled = true;
    };
    // The viewer is a dependency too: which games the server lists depends
    // on who is asking (#469), so signing in or claiming on this page has
    // to fetch the list again rather than keep the one a stranger got.
  }, [userId, includeAbandoned, currentUser?.id]);

  const loadMore = useCallback(async () => {
    if (loadingMore) return;
    const generation = listGeneration.current;
    setLoadingMore(true);
    try {
      const page = await fetchGames(userId, games.length, includeAbandoned);
      if (generation !== listGeneration.current) return;
      setGames((current) => [...current, ...page.games]);
      setHasMore(page.hasMore);
    } catch {
      if (generation !== listGeneration.current) return;
      setError(ui.profilePage.couldNotLoadMoreGames);
    } finally {
      setLoadingMore(false);
    }
  }, [userId, games.length, includeAbandoned, loadingMore]);

  const shownName = subject?.displayName ?? "";

  return (
    <div className="profile-page">
      <AppHeader backLabel="Back to lobby" />

      {!subject && !error && <p className="profile-note">{ui.profilePage.loading}</p>}
      {error && <p className="lobby-action-error" role="alert">{error}</p>}

      {subject && stats && (
        <>
          <header className="profile-identity">
            {/* The avatar wears the same color as the name it belongs to, and
                the friend mark if this is one — the same shape the lobby and
                the roster use, so "we are friends" looks identical wherever
                it is read. Its own markup rather than `<Avatar>`: this disc
                is 56px with the page's own type scale on it. */}
            <span className="avatar-frame" aria-hidden="true">
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
            {viewerIsFriend && (
              <span className="avatar-friend">
                <FriendMarkIcon size={22} />
              </span>
            )}
            </span>
            <div>
              <h1>
                {/* The disc's mark is decorative, so the heading carries the
                    word for a screen reader. */}
                {viewerIsFriend && <span className="visually-hidden">{ui.profilePage.friend} </span>}
                <PlayerName
                  name={shownName}
                  nameColor={subject.nameColor}
                  isAnonymous={subject.isAnonymous}
                />
              </h1>
              <p className="profile-subtitle">
                {subject.isAnonymous ? "Guest — display name not saved" : "Registered player"}
                {subject.createdAt && ` · joined ${formatTimestamp(subject.createdAt, timeFormat)}`}
                {lastSeenLabel(subject) && (
                  <>
                    {" · "}
                    <span className={subject.isOnline ? "profile-presence is-online" : "profile-presence"}>
                      {lastSeenLabel(subject)}
                    </span>
                  </>
                )}
              </p>
            </div>
            {/* The one place a person is reachable after the game they were
                in has ended. The lobby can only offer this to whoever is
                standing in it right now, and a profile is linked from every
                game's participant list (R-FRIEND-10). */}
            <FriendButton
              action={!friendsKnown ? "none" : profileFriendActionFor(
                { userId, isAnonymous: subject.isAnonymous },
                friendLists,
                currentUser
                  ? { userId: currentUser.id, isAnonymous: currentUser.isAnonymous }
                  : null,
                )}
              userId={userId}
              displayName={shownName}
            />
            {/* The other place an account's name and picture are actually
                looked at, and so the other place they have to be reportable
                from (R-AVA-06). Offered on the same terms as the lobby's:
                somebody else's registered account, and an identity of your
                own to report from (R-MOD-06). No picture is not a reason to
                withhold it - the name is always there to complain about. */}
            {!isOwnProfile &&
              !currentUser?.isAnonymous &&
              !subject.isAnonymous && (
                <button
                  type="button"
                  className="btn btn-ghost btn-compact profile-report-picture"
                  title={ui.profilePage.reportPlayer({ name: shownName })}
                  aria-label={ui.profilePage.reportPlayer({ name: shownName })}
                  onClick={() => setReportingPicture(true)}
                >
                  <FlagIcon size={14} />
                </button>
              )}
          </header>

          {reportingPicture && (
            <ReportAccountDialog
              userId={userId}
              displayName={shownName}
              avatarUrl={subject.avatarUrl}
              onClose={() => setReportingPicture(false)}
            />
          )}

          {isOwnProfile && subject.isAnonymous && (
            <section className="panel profile-claim">
              <h2>{ui.profilePage.claimYourAccount}</h2>
              <p>
                {ui.profilePage.yourGamesAreAlreadyBeingRecorded}
              </p>
              <button type="button" onClick={() => setAuthMode("claim")}>
                {ui.profilePage.createAccount}
              </button>
            </section>
          )}

          <section className="panel">
            <h2>{ui.profilePage.statistics}</h2>
            <div className="profile-stats">
              <StatTile label={ui.profilePage.gamesPlayed} value={String(stats.gamesPlayed)} />
              <StatTile label={ui.profilePage.gamesWon} value={String(stats.gamesWon)} />
              <StatTile
                label={ui.profilePage.winRate}
                value={`${Math.round(stats.winRate * 100)}%`}
              />
              <StatTile label={ui.profilePage.averageScore} value={String(Math.round(stats.averageScore))} />
            </div>
            <div className="profile-stats profile-stats-small">
              <StatTile label={ui.profilePage.turnsPlayed} value={String(stats.turnsPlayed)} />
              <StatTile label={ui.profilePage.promptsGuessed} value={String(stats.promptsGuessed)} />
              <StatTile label={ui.profilePage.drawingsMade} value={String(stats.drawingsMade)} />
              <StatTile label={ui.profilePage.reactionsReceived} value={String(stats.reactionsReceived)} />
              <StatTile label={ui.profilePage.totalScore} value={String(stats.totalScore)} />
            </div>
          </section>

          <section className="panel">
            <div className="profile-history-head">
              <h2>{ui.profilePage.gameHistory}</h2>
              <label className="profile-history-filter">
                <input
                  type="checkbox"
                  checked={includeAbandoned}
                  onChange={(change) => setIncludeAbandoned(change.target.checked)}
                />
                {ui.profilePage.includeGamesThatFellApart}
              </label>
            </div>
            {games.length === 0 ? (
              <p className="profile-note">
                {isOwnProfile
                  ? "No finished games yet. Play one and it will show up here."
                  : "No games to show. Games from private rooms are listed only for the players who were in them."}
              </p>
            ) : (
              <ul className="profile-games">
                {games.map((game) => (
                  <GameRow
                    key={game.id}
                    game={game}
                    viewerId={subject.id}
                    onRequestAccount={() => setAuthMode("claim")}
                  />
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
          onSubmit={async (credentials) => {
            const account = await authSubmitter(authMode, login, register)(credentials);
            // Claiming keeps the same user id, so this view never remounts and
            // would otherwise keep showing the guest it loaded - name, badge,
            // and an invitation to claim an account that now exists.
            // The claimed account is the one on the page and the tab is its
            // own socket, so it is online; the last-seen stamp is unchanged.
            if (account.id === userId) {
              setSubject((current) => ({
                ...account,
                isOnline: true,
                lastSeenAt: current?.lastSeenAt ?? null,
              }));
            }
            return account;
          }}
          onSwitchMode={setAuthMode}
        />
      )}
    </div>
  );
}
