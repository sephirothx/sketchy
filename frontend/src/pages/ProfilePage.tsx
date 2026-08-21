import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AccountMenu, AuthDialog, type AuthMode } from "../components/AccountMenu";
import { avatarInitial, identityColor } from "../lib/avatar";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { ApiError } from "../lib/api";
import {
  fetchGameDetail,
  fetchGames,
  fetchProfile,
  formatDuration,
  formatTimestamp,
  HISTORY_PAGE_SIZE,
  type GameDetail,
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
 * A player's name in the colour they chose under Settings.
 *
 * Inside a link, a name with no colour of its own would inherit the browser's
 * link colour, which looks like a chosen colour and never is - so
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
function GameRow({ game, viewerId }: { game: GameSummary; viewerId: string }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<GameDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const seat = game.participants.find((p) => p.userId === viewerId);
  const finishedAt = formatTimestamp(game.finishedAt);

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
        <span className="profile-game-title">
          <span className="profile-game-room">{game.roomName}</span>
          <span className="profile-game-meta">
            {finishedAt} · {game.totalRounds} rounds · {game.playerCount} players
          </span>
        </span>
        {seat && (
          <span className="profile-game-result">
            <span
              className={
                seat.finalRank === 1
                  ? "profile-game-rank is-winner"
                  : "profile-game-rank"
              }
            >
              #{seat.finalRank}
            </span>
            <span className="profile-game-score">{seat.finalScore} pts</span>
          </span>
        )}
        <span className="profile-game-chevron" aria-hidden="true">
          {expanded ? "▾" : "▸"}
        </span>
      </button>

      {expanded && (
        <div className="profile-game-body">
          <ol className="profile-standings">
            {game.participants.map((p) => (
              <li key={p.userId}>
                <span className="profile-standing-rank">#{p.finalRank}</span>
                <Link to={`/profile/${p.userId}`}>
                  <PlayerName
                    name={p.displayName}
                    nameColor={p.nameColor}
                    isAnonymous={p.isAnonymous}
                  />
                </Link>
                <span className="profile-standing-score">{p.finalScore}</span>
              </li>
            ))}
          </ol>

          {detailError && <p className="profile-note">{detailError}</p>}
          {!detail && !detailError && <p className="profile-note">Loading turns…</p>}

          {detail && (() => {
            // The rounds carry ids, the standings carry the colours: joining
            // them here keeps every name in a recap the same colour, without
            // the detail endpoint repeating what the summary already sent.
            const byUser = new Map(detail.participants.map((p) => [p.userId, p]));
            const named = (userId: string, fallbackName: string) => {
              const participant = byUser.get(userId);
              return (
                <PlayerName
                  name={participant?.displayName ?? fallbackName}
                  nameColor={participant?.nameColor ?? null}
                  isAnonymous={participant?.isAnonymous ?? true}
                />
              );
            };
            return (
            <table className="profile-rounds">
              <caption className="visually-hidden">Turn by turn</caption>
              <thead>
                <tr>
                  <th scope="col">Round</th>
                  <th scope="col">Prompt</th>
                  <th scope="col">Drawn by</th>
                  <th scope="col">Time</th>
                  <th scope="col">Guessed by</th>
                </tr>
              </thead>
              <tbody>
                {detail.rounds.map((round) => (
                  <tr key={`${round.roundNumber}-${round.turnNumber}`}>
                    <td>{round.roundNumber}</td>
                    <td className="profile-round-word">{round.word}</td>
                    <td>{named(round.drawerUserId, round.drawerDisplayName)}</td>
                    <td>{formatDuration(round.durationSeconds)}</td>
                    <td>
                      {round.guesses.length === 0
                        ? "nobody"
                        : round.guesses.map((g, index) => (
                            <span key={g.userId}>
                              {index > 0 && ", "}
                              {named(g.userId, g.displayName)} ({g.pointsAwarded})
                            </span>
                          ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            );
          })()}
        </div>
      )}
    </li>
  );
}

export function ProfilePage() {
  const params = useParams<{ userId?: string }>();
  const navigate = useNavigate();
  const viewer = useAuthStore((s) => s.user);
  const hasResolved = useAuthStore((s) => s.hasResolved);

  // No id in the path means "me", which is only knowable once the account has
  // resolved - so the view waits rather than fetching at an empty id.
  const userId = params.userId ?? viewer?.id ?? null;

  if (!userId) {
    return (
      <div className="profile-page">
        <ProfileTopBar onBack={() => navigate("/")} />
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

function ProfileTopBar({ onBack }: { onBack: () => void }) {
  return (
    <div className="profile-top-bar">
      <button type="button" className="back-link" onClick={onBack}>
        ← Back to lobby
      </button>
      <AccountMenu />
    </div>
  );
}

function ProfileView({ userId }: { userId: string }) {
  const navigate = useNavigate();
  const viewer = useAuthStore((s) => s.user);
  const isOwnProfile = userId === viewer?.id;

  const [subject, setSubject] = useState<AuthUser | null>(null);
  const [stats, setStats] = useState<ProfileStats | null>(null);
  const [games, setGames] = useState<GameSummary[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
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
          fetchGames(userId, 0),
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
  }, [userId]);

  const loadMore = useCallback(async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await fetchGames(userId, games.length);
      setGames((current) => [...current, ...page.games]);
      setHasMore(page.hasMore);
    } catch {
      setError("Could not load more games.");
    } finally {
      setLoadingMore(false);
    }
  }, [userId, games.length, loadingMore]);

  const shownName = subject
    ? (subject.isAnonymous ? subject.displayName : subject.username ?? subject.displayName)
    : "";

  return (
    <div className="profile-page">
      <ProfileTopBar onBack={() => navigate("/")} />

      {!subject && !error && <p className="profile-note">Loading…</p>}
      {error && <p className="lobby-action-error" role="alert">{error}</p>}

      {subject && stats && (
        <>
          <header className="profile-identity">
            {/* The avatar wears the same colour as the name it belongs to. */}
            <span
              className="profile-avatar"
              aria-hidden="true"
              style={{
                backgroundColor: identityColor(
                  shownName,
                  subject.isAnonymous,
                  subject.nameColor,
                ),
              }}
            >
              {avatarInitial(shownName)}
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
                {subject.isAnonymous ? "Guest — name not saved" : "Registered player"}
                {subject.createdAt && ` · joined ${formatTimestamp(subject.createdAt)}`}
              </p>
            </div>
          </header>

          {isOwnProfile && subject.isAnonymous && (
            <section className="panel profile-claim">
              <h2>Claim your account</h2>
              <p>
                Your games are already being recorded against this name. Claim it
                to keep them — and your name — on every device.
              </p>
              <button type="button" onClick={() => setAuthMode("claim")}>
                Claim my name
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
              <StatTile label="Turns played" value={String(stats.roundsPlayed)} />
              <StatTile label="Prompts guessed" value={String(stats.wordsGuessed)} />
              <StatTile label="Drawings made" value={String(stats.drawingsMade)} />
              <StatTile label="Total score" value={String(stats.totalScore)} />
            </div>
          </section>

          <section className="panel">
            <h2>Game history</h2>
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
