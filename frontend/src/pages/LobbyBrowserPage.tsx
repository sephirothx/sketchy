import { useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { sessionFrom } from "../lib/roomEntryState";
import { startVisibilityAwarePolling } from "../lib/roomListPolling";
import { SettingsIcon } from "../components/SettingsIcon";
import { AccountMenu } from "../components/AccountMenu";
import { FirstRunIdentity } from "../components/FirstRunIdentity";
import { currentPlayerName } from "../store/authStore";
import { PublicRoomCard } from "../components/PublicRoomCard";
import { VersionBadge } from "../components/VersionBadge";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { useFocusTrap } from "../hooks/useFocusTrap";
import type { AckResponse, RoomSummary } from "../types";

const POLL_INTERVAL_MS = 4000;
const ROOM_FETCH_TIMEOUT_MS = 6000;

type RoomListStatus = "loading" | "loaded" | "error";
type PendingJoin = { key: string; mode: "join" | "spectate" };

function normalizeRoomCodeInput(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
}

function RemovedFromRoomDialog({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const okButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  useFocusTrap(dialogRef, {
    onEscape: onDismiss,
    initialFocusRef: okButtonRef,
  });

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onDismiss();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
      >
        <div className="modal-icon" aria-hidden="true">🚫</div>
        <h3 id={titleId} className="modal-title">Removed from room</h3>
        <p id={descriptionId} className="modal-body">{message}</p>
        <button ref={okButtonRef} type="button" className="modal-button" onClick={onDismiss}>
          OK
        </button>
      </div>
    </div>
  );
}

export function LobbyBrowserPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const openSettings = useSettingsStore((s) => s.openSettings);
  const nameColor = useSettingsStore((s) => s.nameColor);
  const colorblindSafeColors = useSettingsStore((s) => s.colorblindSafeColors);
  const setSession = useGameStore((s) => s.setSession);
  const setExitingRoom = useGameStore((s) => s.setExitingRoom);


  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [joinCode, setJoinCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [criticalError, setCriticalError] = useState<string | null>(location.state?.criticalError ?? null);
  const [pendingJoin, setPendingJoin] = useState<PendingJoin | null>(null);
  const [roomListStatus, setRoomListStatus] = useState<RoomListStatus>("loading");
  const [roomListError, setRoomListError] = useState<string | null>(null);
  const [roomRefreshError, setRoomRefreshError] = useState<string | null>(null);
  const [roomListRetry, setRoomListRetry] = useState(0);
  const hasLoadedRoomsRef = useRef(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [hideFullRooms, setHideFullRooms] = useState(false);
  const [hideInProgressRooms, setHideInProgressRooms] = useState(false);

  // Arriving at the lobby means any room exit has completed.
  useEffect(() => {
    setExitingRoom(false);
  }, [setExitingRoom]);

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
        const res = await fetch("/api/rooms", { signal: controller.signal });
        if (!res.ok) throw new Error(`Room list request failed with ${res.status}`);
        const data: unknown = await res.json();
        if (!Array.isArray(data)) throw new Error("Invalid room list response");
        if (!cancelled) {
          hasLoadedRoomsRef.current = true;
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

  const filteredRooms = rooms.filter((room) => {
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      const nameMatch = room.name.toLowerCase().includes(q);
      const codeMatch = room.code?.toLowerCase().includes(q);
      if (!nameMatch && !codeMatch) return false;
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
      <div className="lobby-header">
        <div>
          <h1>Sketchy</h1>
        </div>
        <div className="lobby-header-actions">
          <AccountMenu />
          <Link className="header-action-link" to="/prompt-lists">
            <span aria-hidden="true">📊</span>
            <span className="header-action-label">Prompt stats</span>
          </Link>
          <button
            type="button"
            className="header-settings-button"
            onClick={openSettings}
            title="Player settings"
            aria-label="Player settings"
          >
            <SettingsIcon size={16} />
            <span className="header-action-label">Settings</span>
          </button>
        </div>
      </div>

      {criticalError && (
        <RemovedFromRoomDialog
          message={criticalError}
          onDismiss={() => setCriticalError(null)}
        />
      )}



      <FirstRunIdentity />

      {error && <p className="lobby-action-error" role="alert">{error}</p>}

      <div className="lobby-columns">
        <section className="panel">
          <h2>Create a room</h2>
          <p className="create-room-lobby-copy">Choose the basics first, then add optional room settings only when you need them.</p>
          <button type="button" onClick={handleOpenCreateRoom}>Create room</button>
        </section>

        <section className="panel">
          <h2>Join a private room</h2>
          <label>
            Room code
            {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
            <input
              type="search"
              inputMode="text"
              value={joinCode}
              onChange={(e) => setJoinCode(normalizeRoomCodeInput(e.target.value))}
              maxLength={6}
              placeholder="ABC123"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              autoCorrect="off"
              enterKeyHint="go"
            />
          </label>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button disabled={Boolean(pendingJoin)} onClick={() => handleJoinByCode(false)}>
              {pendingJoin?.key === "private-code" && pendingJoin.mode === "join" ? "Joining…" : "Join by code"}
            </button>
            <button disabled={Boolean(pendingJoin)} onClick={() => handleJoinByCode(true)}>
              {pendingJoin?.key === "private-code" && pendingJoin.mode === "spectate" ? "Joining as spectator…" : "Spectate"}
            </button>
          </div>
        </section>
      </div>

      <section className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1rem" }}>
          <h2>Public rooms</h2>
          <span style={{ fontSize: "0.85rem", color: "var(--text-muted, #94a3b8)" }}>
            {roomListStatus === "loading" ? "Loading…" : rooms.length > 0 ? `Showing ${filteredRooms.length} of ${rooms.length} rooms` : "0 rooms"}
          </span>
        </div>

        {roomListStatus === "loaded" && rooms.length > 0 && (
          <div className="lobby-filter-bar">
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="🔍 Search rooms by name or code..."
              autoComplete="off"
              enterKeyHint="search"
            />
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={hideFullRooms}
                onChange={(e) => setHideFullRooms(e.target.checked)}
              />
              Hide full rooms
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={hideInProgressRooms}
                onChange={(e) => setHideInProgressRooms(e.target.checked)}
              />
              Hide in-progress rooms
            </label>
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
          <p style={{ color: "var(--text-muted, #94a3b8)", fontStyle: "italic" }}>
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
