import { useEffect, useId, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { sessionFrom } from "../lib/roomEntryState";
import { startVisibilityAwarePolling } from "../lib/roomListPolling";
import { AppHeader } from "../components/AppHeader";
import { FirstRunIdentity } from "../components/FirstRunIdentity";
import { currentPlayerName } from "../store/authStore";
import { useAuthStore } from "../store/authStore";
import { getMyPersistentRooms, type PersistentRoomSummary } from "../lib/persistentRooms";
import { PublicRoomCard } from "../components/PublicRoomCard";
import { VersionBadge } from "../components/VersionBadge";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { ModalShell } from "../components/ui/ModalShell";
import { Button } from "../components/ui/Button";
import { AlertCircleIcon, ChevronDownIcon, EyeIcon, PlusIcon, SearchIcon } from "../components/icons";
import { promptLanguageLabel } from "../lib/promptLanguages";
import type { AckResponse, RoomSummary } from "../types";

const POLL_INTERVAL_MS = 4000;
const ROOM_FETCH_TIMEOUT_MS = 6000;
const ROOM_CODE_LENGTH = 6;

type RoomListStatus = "loading" | "loaded" | "error";
type PendingJoin = { key: string; mode: "join" | "spectate" };

function normalizeRoomCodeInput(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, ROOM_CODE_LENGTH);
}

function RemovedFromRoomDialog({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  const okButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  return (
    <ModalShell
      labelledBy={titleId}
      describedBy={descriptionId}
      onDismiss={onDismiss}
      initialFocusRef={okButtonRef}
    >
      <div className="modal-icon is-danger" aria-hidden="true">
        <AlertCircleIcon size={22} />
      </div>
      <h3 id={titleId} className="modal-title">Removed from room</h3>
      <p id={descriptionId} className="modal-body">{message}</p>
      <button ref={okButtonRef} type="button" className="modal-button" onClick={onDismiss}>
        OK
      </button>
    </ModalShell>
  );
}

/* One labeled input rendered as the mockup's six code cells: the real field
   stretches invisibly across the row, and the cells underneath mirror its
   value, so focus, paste, and autofill all behave like a plain text box. */
function RoomCodeInput({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const fieldId = useId();
  const activeIndex = Math.min(value.length, ROOM_CODE_LENGTH - 1);

  return (
    <label className="room-code-label" htmlFor={fieldId}>
      Room code
      <span className="room-code-cells">
        {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
        <input
          id={fieldId}
          className="room-code-field"
          type="search"
          inputMode="text"
          value={value}
          onChange={(e) => onChange(normalizeRoomCodeInput(e.target.value))}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSubmit();
          }}
          maxLength={ROOM_CODE_LENGTH}
          placeholder="ABC123"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          autoCorrect="off"
          enterKeyHint="go"
        />
        {Array.from({ length: ROOM_CODE_LENGTH }, (_, i) => (
          <span
            key={i}
            aria-hidden="true"
            className={`room-code-cell${value[i] ? " is-filled" : ""}${i === activeIndex ? " is-active" : ""}`}
          >
            {value[i] ?? ""}
          </span>
        ))}
      </span>
    </label>
  );
}

export function LobbyBrowserPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const nameColor = useSettingsStore((s) => s.nameColor);
  const colorblindSafeColors = useSettingsStore((s) => s.colorblindSafeColors);
  const setSession = useGameStore((s) => s.setSession);
  const setExitingRoom = useGameStore((s) => s.setExitingRoom);
  const authUser = useAuthStore((state) => state.user);


  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [persistentRooms, setPersistentRooms] = useState<PersistentRoomSummary[]>([]);
  const [joinCode, setJoinCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [criticalError, setCriticalError] = useState<string | null>(location.state?.criticalError ?? null);
  const [pendingJoin, setPendingJoin] = useState<PendingJoin | null>(null);
  const [roomListStatus, setRoomListStatus] = useState<RoomListStatus>("loading");
  const [roomListError, setRoomListError] = useState<string | null>(null);
  const [roomRefreshError, setRoomRefreshError] = useState<string | null>(null);
  const [roomListRetry, setRoomListRetry] = useState(0);
  const hasLoadedRoomsRef = useRef(false);
  // The validator from the last successful fetch. A ref rather than state:
  // changing it must not re-render, and the poll reads it at request time.
  const roomsEtagRef = useRef<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [languageFilter, setLanguageFilter] = useState("all");
  const [hideFullRooms, setHideFullRooms] = useState(false);
  const [hideInProgressRooms, setHideInProgressRooms] = useState(false);

  // Arriving at the lobby means any room exit has completed.
  useEffect(() => {
    setExitingRoom(false);
  }, [setExitingRoom]);

  useEffect(() => {
    let cancelled = false;
    if (!authUser || authUser.isAnonymous) {
      return;
    }
    void getMyPersistentRooms()
      .then((value) => {
        if (!cancelled) setPersistentRooms(value);
      })
      .catch(() => {
        if (!cancelled) setPersistentRooms([]);
      });
    return () => { cancelled = true; };
  }, [authUser]);

  const visiblePersistentRooms =
    authUser && !authUser.isAnonymous ? persistentRooms : [];

  useEffect(() => {
    // The polling controller stops new work; this flag also prevents an
    // already-running fetch from updating React state after effect cleanup.
    let cancelled = false;
    let activeController: AbortController | null = null;
    let activeTimeout: number | null = null;

    async function fetchRooms() {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), ROOM_FETCH_TIMEOUT_MS);
      activeController = controller;
      activeTimeout = timeout;
      try {
        const res = await fetch("/api/rooms", {
          signal: controller.signal,
          headers: roomsEtagRef.current ? { "If-None-Match": roomsEtagRef.current } : {},
        });
        if (res.status === 304) {
          // Nothing has changed since the last poll, and the server sent no
          // body to prove it. The rooms already on screen are current.
          if (!cancelled) {
            setRoomListStatus("loaded");
            setRoomRefreshError(null);
          }
          return;
        }
        if (!res.ok) throw new Error(`Room list request failed with ${res.status}`);
        const data: unknown = await res.json();
        if (!Array.isArray(data)) throw new Error("Invalid room list response");
        if (!cancelled) {
          hasLoadedRoomsRef.current = true;
          // Stored with the list it describes, never before it. This poll can
          // land after the effect has torn down, and the ref outlives the
          // effect - so recording a validator whose body was then dropped
          // would make every later poll answer 304 for rooms that were never
          // applied, leaving the lobby stale until the list happened to
          // change again.
          roomsEtagRef.current = res.headers.get("ETag");
          setRooms(data as RoomSummary[]);
          setRoomListStatus("loaded");
          setRoomListError(null);
          setRoomRefreshError(null);
        }
      } catch {
        if (!cancelled) {
          const message = "Could not load public rooms. Check your connection and try again.";
          if (hasLoadedRoomsRef.current) setRoomRefreshError(message);
          else {
            setRoomListStatus("error");
            setRoomListError(message);
          }
        }
      } finally {
        window.clearTimeout(timeout);
        if (activeController === controller) activeController = null;
        if (activeTimeout === timeout) activeTimeout = null;
      }
    }

    const stopPolling = startVisibilityAwarePolling(fetchRooms, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      stopPolling();
      if (activeTimeout !== null) window.clearTimeout(activeTimeout);
      activeController?.abort();
    };
  }, [roomListRetry]);

  function retryRoomList() {
    setRoomListError(null);
    setRoomRefreshError(null);
    if (!hasLoadedRoomsRef.current) setRoomListStatus("loading");
    setRoomListRetry((value) => value + 1);
  }

  const roomLanguages = [...new Set(rooms.map((room) => room.promptLanguage))].sort((a, b) =>
    promptLanguageLabel(a).localeCompare(promptLanguageLabel(b)),
  );

  const filteredRooms = rooms.filter((room) => {
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      const nameMatch = room.name.toLowerCase().includes(q);
      const codeMatch = room.code?.toLowerCase().includes(q);
      if (!nameMatch && !codeMatch) return false;
    }
    if (languageFilter !== "all" && room.promptLanguage !== languageFilter) {
      return false;
    }
    if (hideFullRooms && room.playerCount >= room.maxPlayers) {
      return false;
    }
    if (hideInProgressRooms && room.state === "playing") {
      return false;
    }
    return true;
  });

  // No gate: every visitor already has a name, generated on their first load.
  function handleOpenCreateRoom() {
    navigate("/create");
  }

  async function handleJoinByCode(asSpectator = false) {
    if (!joinCode.trim()) {
      setError("Please enter a room code");
      return;
    }
    await joinRoom({ code: joinCode.trim().toUpperCase() }, asSpectator, "private-code");
  }

  async function handleJoinRoom(room: RoomSummary, asSpectator = false) {
    await joinRoom({ roomId: room.id }, asSpectator, room.id);
  }

  async function joinRoom(target: { roomId?: string; code?: string }, asSpectator: boolean, key: string) {
    if (pendingJoin) return;
    setPendingJoin({ key, mode: asSpectator ? "spectate" : "join" });
    setError(null);
    try {
      const res = await emitWithAck<AckResponse>("join_room", {
        nickname: currentPlayerName(),
        nameColor,
        colorblindSafeColors,
        asSpectator,
        ...target,
      });
      const session = sessionFrom(res);
      if (session) {
        setSession(session);
        navigate(`/room/${session.code}`);
      } else {
        setError(res.error || "Failed to join room");
      }
    } catch (joinError) {
      setError(socketRequestErrorMessage(joinError, asSpectator ? "join as a spectator" : "join the room"));
    } finally {
      setPendingJoin(null);
    }
  }

  return (
    <div className="lobby-page">
      <AppHeader />

      {criticalError && (
        <RemovedFromRoomDialog
          message={criticalError}
          onDismiss={() => setCriticalError(null)}
        />
      )}



      <FirstRunIdentity />

      {error && <p className="lobby-action-error" role="alert">{error}</p>}

      <div className="lobby-columns">
        <section className="panel lobby-entry-panel">
          <h2>Start a game</h2>
          <p className="create-room-lobby-copy">Pick the basics, invite your friends, draw. Settings can change any time before the first round.</p>
          <div className="lobby-entry-actions">
            <Button variant="primary" big iconLeft={<PlusIcon size={16} />} onClick={handleOpenCreateRoom}>
              Create room
            </Button>
          </div>
        </section>

        <section className="panel lobby-entry-panel">
          <h2>Join with a code</h2>
          <RoomCodeInput
            value={joinCode}
            onChange={setJoinCode}
            onSubmit={() => void handleJoinByCode(false)}
          />
          <div className="lobby-entry-actions">
            <Button variant="primary" disabled={Boolean(pendingJoin)} onClick={() => void handleJoinByCode(false)}>
              {pendingJoin?.key === "private-code" && pendingJoin.mode === "join" ? "Joining…" : "Join by code"}
            </Button>
            <Button
              variant="secondary"
              disabled={Boolean(pendingJoin)}
              iconLeft={<EyeIcon size={14} />}
              onClick={() => void handleJoinByCode(true)}
            >
              {pendingJoin?.key === "private-code" && pendingJoin.mode === "spectate" ? "Joining as spectator…" : "Spectate"}
            </Button>
          </div>
        </section>
      </div>

      {visiblePersistentRooms.length > 0 && <section className="panel">
        <h2>My persistent rooms</h2>
        <div className="room-list">
          {visiblePersistentRooms.map((room) => <article className="public-room-card" key={room.id}>
            <div className="public-room-card-main"><strong>{room.name}</strong><p className="public-room-facts">{room.code} · {room.rounds} rounds · {room.drawingSeconds}s</p></div>
            <button className="btn btn-primary public-room-primary-action" disabled={Boolean(pendingJoin)} onClick={() => void joinRoom({ code: room.code }, false, `persistent-${room.id}`)}>
              {pendingJoin?.key === `persistent-${room.id}` ? "Joining…" : "Open room"}
            </button>
          </article>)}
        </div>
      </section>}

      <section className="panel">
        <div className="lobby-rooms-heading">
          <h2>Public rooms</h2>
          <span className="lobby-rooms-count">
            {roomListStatus === "loading" ? "Loading…" : rooms.length > 0 ? `Showing ${filteredRooms.length} of ${rooms.length}` : "0 rooms"}
          </span>
        </div>

        {roomListStatus === "loaded" && rooms.length > 0 && (
          <div className="lobby-filter-bar">
            <span className="lobby-room-search">
              <SearchIcon size={15} />
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search rooms by name or code"
                aria-label="Search rooms by name or code"
                autoComplete="off"
                enterKeyHint="search"
              />
            </span>
            <span className="lobby-language-filter">
              <select
                aria-label="Filter by prompt language"
                value={languageFilter}
                onChange={(e) => setLanguageFilter(e.target.value)}
              >
                <option value="all">All languages</option>
                {roomLanguages.map((language) => (
                  <option key={language} value={language}>{promptLanguageLabel(language)}</option>
                ))}
              </select>
              <ChevronDownIcon size={14} />
            </span>
            <button
              type="button"
              className="lobby-filter-toggle"
              aria-pressed={hideFullRooms}
              onClick={() => setHideFullRooms((v) => !v)}
            >
              Hide full
            </button>
            <button
              type="button"
              className="lobby-filter-toggle"
              aria-pressed={hideInProgressRooms}
              onClick={() => setHideInProgressRooms((v) => !v)}
            >
              Hide in progress
            </button>
          </div>
        )}

        {roomRefreshError && <div className="room-list-warning" role="status"><span>{roomRefreshError}</span><button type="button" onClick={retryRoomList}>Retry</button></div>}

        {roomListStatus === "loading" ? (
          <div className="room-list-loading" role="status">Loading public rooms…</div>
        ) : roomListStatus === "error" ? (
          <div className="room-list-error" role="alert"><p>{roomListError}</p><button type="button" onClick={retryRoomList}>Retry</button></div>
        ) : rooms.length === 0 ? (
          <p>No public rooms yet. Create one!</p>
        ) : filteredRooms.length === 0 ? (
          <p className="lobby-no-matches">
            No public rooms match your search criteria.
          </p>
        ) : (
          <div className="room-list">
            {filteredRooms.map((room) => (
              <PublicRoomCard key={room.id} room={room} busy={Boolean(pendingJoin)} pendingMode={pendingJoin?.key === room.id ? pendingJoin.mode : null} onJoin={(asSpectator) => void handleJoinRoom(room, asSpectator)} />
            ))}
          </div>
        )}
      </section>
      <VersionBadge />
    </div>
  );
}
