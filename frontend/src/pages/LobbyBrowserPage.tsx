import { useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { emitWithAck, SERVER_URL, socketRequestErrorMessage } from "../lib/socket";
import { startVisibilityAwarePolling } from "../lib/roomListPolling";
import { SettingsIcon } from "../components/SettingsIcon";
import { PublicRoomCard } from "../components/PublicRoomCard";
import { VersionBadge } from "../components/VersionBadge";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, RoomSummary } from "../types";

const POLL_INTERVAL_MS = 4000;
const ROOM_FETCH_TIMEOUT_MS = 6000;

type RoomListStatus = "loading" | "loaded" | "error";
type PendingJoin = { key: string; mode: "join" | "spectate" };

function normalizeRoomCodeInput(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
}

export function LobbyBrowserPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const nickname = useGameStore((s) => s.nickname);
  const setNickname = useGameStore((s) => s.setNickname);
  const openSettings = useSettingsStore((s) => s.openSettings);
  const nameColor = useSettingsStore((s) => s.nameColor);
  const setSession = useGameStore((s) => s.setSession);

  const [nicknameInput, setNicknameInput] = useState(nickname);
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
        const res = await fetch(`${SERVER_URL}/api/rooms`, { signal: controller.signal });
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

  function requireNickname(): boolean {
    if (!nicknameInput.trim()) {
      setError("Please enter a nickname first");
      return false;
    }
    setNickname(nicknameInput.trim());
    return true;
  }

  function handleOpenCreateRoom() {
    if (!requireNickname()) return;
    navigate("/create");
  }

  async function handleJoinByCode(asSpectator = false) {
    if (!requireNickname()) return;
    if (!joinCode.trim()) {
      setError("Please enter a room code");
      return;
    }
    await joinRoom({ code: joinCode.trim().toUpperCase() }, asSpectator, "private-code");
  }

  async function handleJoinRoom(room: RoomSummary, asSpectator = false) {
    if (!requireNickname()) return;
    await joinRoom({ roomId: room.id }, asSpectator, room.id);
  }

  async function joinRoom(target: { roomId?: string; code?: string }, asSpectator: boolean, key: string) {
    if (pendingJoin) return;
    setPendingJoin({ key, mode: asSpectator ? "spectate" : "join" });
    setError(null);
    try {
      const res = await emitWithAck<AckResponse>("join_room", {
        nickname: nicknameInput.trim(),
        nameColor,
        asSpectator,
        ...target,
      });
      if (res.ok && res.roomId && res.code && res.playerId && res.reconnectSecret) {
        setSession({ roomId: res.roomId, code: res.code, playerId: res.playerId, reconnectSecret: res.reconnectSecret });
        navigate(`/room/${res.code}`);
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
        <button
          type="button"
          className="header-settings-button"
          onClick={openSettings}
          title="Game Settings"
          aria-label="Game Settings"
        >
          <SettingsIcon size={16} />
          <span className="header-action-label">Settings</span>
        </button>
      </div>

      <section className="panel">
        <label>
          Nickname
          {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
          <input
            type="search"
            inputMode="text"
            value={nicknameInput}
            onChange={(e) => setNicknameInput(e.target.value)}
            maxLength={20}
            placeholder="Your name"
            autoComplete="nickname"
            autoCapitalize="words"
            spellCheck={false}
            autoCorrect="off"
            enterKeyHint="done"
          />
        </label>
      </section>

      {criticalError && (
        <div className="modal-overlay" onClick={() => setCriticalError(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-icon">🚫</div>
            <h3 className="modal-title">Removed from room</h3>
            <p className="modal-body">{criticalError}</p>
            <button className="modal-button" onClick={() => setCriticalError(null)}>
              OK
            </button>
          </div>
        </div>
      )}

      {error && <p className="lobby-action-error" role="alert">{error}</p>}

      <div className="lobby-columns">
        <section className="panel">
          <h2>Create a room</h2>
          <p className="create-room-lobby-copy">Choose the basics first, then add optional rules only when you need them.</p>
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
