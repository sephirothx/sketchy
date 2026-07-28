import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { emitWithAck, SERVER_URL } from "../lib/socket";
import { SettingsIcon } from "../components/SettingsIcon";
import { PublicRoomCard } from "../components/PublicRoomCard";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, HintMode, RoomSummary, ScoringMode } from "../types";

const POLL_INTERVAL_MS = 4000;

export function LobbyBrowserPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const nickname = useGameStore((s) => s.nickname);
  const setNickname = useGameStore((s) => s.setNickname);
  const openSettings = useSettingsStore((s) => s.openSettings);
  const setSession = useGameStore((s) => s.setSession);

  const [nicknameInput, setNicknameInput] = useState(nickname);
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [roomName, setRoomName] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [maxPlayers, setMaxPlayers] = useState(8);
  const [rounds, setRounds] = useState(3);
  const [drawingSeconds, setDrawingSeconds] = useState(80);
  const [customWords, setCustomWords] = useState("");
  const [customWordsOnly, setCustomWordsOnly] = useState(false);
  const [hintMode, setHintMode] = useState<HintMode>("none");
  const [scoringMode, setScoringMode] = useState<ScoringMode>("default");
  const [spectatorsSeeSolution, setSpectatorsSeeSolution] = useState(false);
  const [hideMaskedPrompt, setHideMaskedPrompt] = useState(false);
  const [joinCode, setJoinCode] = useState("");
  const [error, setError] = useState<string | null>(location.state?.error ?? null);
  const [busy, setBusy] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [hideFullRooms, setHideFullRooms] = useState(false);
  const [hideInProgressRooms, setHideInProgressRooms] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchRooms() {
      try {
        const res = await fetch(`${SERVER_URL}/api/rooms`);
        const data = await res.json();
        if (!cancelled) setRooms(data);
      } catch {
        // backend may be briefly unavailable; ignore and retry on next poll
      }
    }
    fetchRooms();
    const interval = setInterval(fetchRooms, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

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

  async function handleCreateRoom() {
    if (!requireNickname()) return;
    setBusy(true);
    setError(null);
    const res = await emitWithAck<AckResponse>("create_room", {
      nickname: nicknameInput.trim(),
      name: roomName.trim(),
      isPublic,
      maxPlayers,
      rounds,
      drawingSeconds,
      customWords: customWords.trim(),
      customWordsOnly,
      hintMode,
      scoringMode,
      spectatorsSeeSolution,
      hideMaskedPrompt,
    });
    setBusy(false);
    if (res.ok && res.roomId && res.code && res.token) {
      setSession({ roomId: res.roomId, code: res.code, token: res.token });
      navigate(`/room/${res.code}`);
    } else {
      setError(res.error || "Failed to create room");
    }
  }

  async function handleJoinByCode(asSpectator = false) {
    if (!requireNickname()) return;
    if (!joinCode.trim()) {
      setError("Please enter a room code");
      return;
    }
    await joinRoom({ code: joinCode.trim().toUpperCase() }, asSpectator);
  }

  async function handleJoinRoom(room: RoomSummary, asSpectator = false) {
    if (!requireNickname()) return;
    await joinRoom({ roomId: room.id }, asSpectator);
  }

  async function joinRoom(target: { roomId?: string; code?: string }, asSpectator = false) {
    setBusy(true);
    setError(null);
    const res = await emitWithAck<AckResponse>("join_room", {
      nickname: nicknameInput.trim(),
      asSpectator,
      ...target,
    });
    setBusy(false);
    if (res.ok && res.roomId && res.code && res.token) {
      setSession({ roomId: res.roomId, code: res.code, token: res.token });
      navigate(`/room/${res.code}`);
    } else {
      setError(res.error || "Failed to join room");
    }
  }

  return (
    <div className="lobby-page">
      <div className="lobby-header">
        <div>
          <h1>Sketchy</h1>
          <p className="subtitle">An online multiplayer drawing &amp; guessing game</p>
        </div>
        <button
          type="button"
          className="header-settings-button"
          onClick={openSettings}
          title="Game Settings"
        >
          <SettingsIcon size={16} />
          <span>Settings</span>
        </button>
      </div>

      <section className="panel">
        <label>
          Nickname
          <input
            type="search"
            value={nicknameInput}
            onChange={(e) => setNicknameInput(e.target.value)}
            maxLength={20}
            placeholder="Your name"
            autoComplete="off"
          />
        </label>
      </section>

      {error && (
        <div className="modal-overlay" onClick={() => setError(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-icon">🚫</div>
            <h3 className="modal-title">Notice</h3>
            <p className="modal-body">{error}</p>
            <button className="modal-button" onClick={() => setError(null)}>
              OK
            </button>
          </div>
        </div>
      )}

      <div className="lobby-columns">
        <section className="panel">
          <h2>Create a room</h2>
          <label>
            Room name (optional)
            <input
              type="search"
              value={roomName}
              onChange={(e) => setRoomName(e.target.value)}
              maxLength={40}
              placeholder="Leave blank for a random name!"
              autoComplete="off"
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
            />
            Public (listed below)
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={spectatorsSeeSolution}
              onChange={(e) => setSpectatorsSeeSolution(e.target.checked)}
            />
            Allow spectators to see the word (default: No)
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={hideMaskedPrompt}
              onChange={(e) => {
                const checked = e.target.checked;
                setHideMaskedPrompt(checked);
                if (checked) {
                  setHintMode("none");
                }
              }}
            />
            Always hide masked prompt to guessers (forces hints off)
          </label>
          <label>
            Max players
            <input
              type="number"
              min={2}
              max={12}
              value={maxPlayers}
              onChange={(e) => setMaxPlayers(Number(e.target.value))}
            />
          </label>
          <label>
            Rounds
            <input
              type="number"
              min={1}
              max={10}
              value={rounds}
              onChange={(e) => setRounds(Number(e.target.value))}
            />
          </label>
          <label>
            Drawing time (seconds)
            <input
              type="number"
              min={15}
              max={240}
              value={drawingSeconds}
              onChange={(e) => setDrawingSeconds(Number(e.target.value))}
            />
          </label>
          <label>
            Custom words (optional)
            <input
              type="search"
              value={customWords}
              onChange={(e) => setCustomWords(e.target.value)}
              placeholder="e.g. cat, red panda, ice cream truck"
              maxLength={400000}
              autoComplete="off"
            />
          </label>
          <p className="field-hint">
            Comma-separated words or expressions, up to 32 characters each.
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={customWordsOnly}
              disabled={!customWords.trim()}
              onChange={(e) => setCustomWordsOnly(e.target.checked)}
            />
            Only use custom words (skip the default word list)
          </label>
          <label>
            Scoring
            <select
              value={scoringMode}
              onChange={(e) => {
                const mode = e.target.value as ScoringMode;
                setScoringMode(mode);
                if (mode === "none" && (hintMode === "purchase" || hintMode === "wheel")) {
                  setHintMode("none");
                }
              }}
            >
              <option value="default">Default scoring</option>
              <option value="none">No scoring — just for fun</option>
            </select>
          </label>
          <label>
            Hint letters
            <select
              value={hintMode}
              disabled={hideMaskedPrompt}
              onChange={(e) => setHintMode(e.target.value as HintMode)}
            >
              <option value="none">Off</option>
              <option value="checkpoints">Timed hints, shown to everyone</option>
              <option value="purchase" disabled={scoringMode === "none"}>
                Players can buy hints with points
              </option>
              <option value="wheel" disabled={scoringMode === "none"}>
                Buy full letters, wheel-of-fortune style
              </option>
            </select>
          </label>
          <button disabled={busy} onClick={handleCreateRoom}>
            Create room
          </button>
        </section>

        <section className="panel">
          <h2>Join a private room</h2>
          <label>
            Room code
            <input
              type="search"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value)}
              maxLength={6}
              placeholder="ABC123"
              autoComplete="off"
            />
          </label>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button disabled={busy} onClick={() => handleJoinByCode(false)}>
              Join by code
            </button>
            <button disabled={busy} onClick={() => handleJoinByCode(true)}>
              Spectate
            </button>
          </div>
        </section>
      </div>

      <section className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1rem" }}>
          <h2>Public rooms</h2>
          <span style={{ fontSize: "0.85rem", color: "var(--text-muted, #94a3b8)" }}>
            {rooms.length > 0 ? `Showing ${filteredRooms.length} of ${rooms.length} rooms` : "0 rooms"}
          </span>
        </div>

        {rooms.length > 0 && (
          <div
            className="lobby-filter-bar"
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "0.75rem",
              alignItems: "center",
              marginBottom: "1rem",
              background: "rgba(0,0,0,0.15)",
              padding: "0.6rem 0.8rem",
              borderRadius: "8px",
            }}
          >
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="🔍 Search rooms by name or code..."
              style={{ flex: "1 1 200px", padding: "0.4rem 0.75rem", fontSize: "0.9rem" }}
            />
            <label className="checkbox-label" style={{ fontSize: "0.85rem", whiteSpace: "nowrap" }}>
              <input
                type="checkbox"
                checked={hideFullRooms}
                onChange={(e) => setHideFullRooms(e.target.checked)}
              />
              Hide full rooms
            </label>
            <label className="checkbox-label" style={{ fontSize: "0.85rem", whiteSpace: "nowrap" }}>
              <input
                type="checkbox"
                checked={hideInProgressRooms}
                onChange={(e) => setHideInProgressRooms(e.target.checked)}
              />
              Hide in-progress rooms
            </label>
          </div>
        )}

        {rooms.length === 0 ? (
          <p>No public rooms yet. Create one!</p>
        ) : filteredRooms.length === 0 ? (
          <p style={{ color: "var(--text-muted, #94a3b8)", fontStyle: "italic" }}>
            No public rooms match your search criteria.
          </p>
        ) : (
          <div className="room-list">
            {filteredRooms.map((room) => (
              <PublicRoomCard key={room.id} room={room} busy={busy} onJoin={(asSpectator) => void handleJoinRoom(room, asSpectator)} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
