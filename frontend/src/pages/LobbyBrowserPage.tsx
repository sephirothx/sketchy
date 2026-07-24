import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { emitWithAck, SERVER_URL } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import type { AckResponse, HintMode, RoomSummary } from "../types";

const POLL_INTERVAL_MS = 4000;

export function LobbyBrowserPage() {
  const navigate = useNavigate();
  const nickname = useGameStore((s) => s.nickname);
  const setNickname = useGameStore((s) => s.setNickname);
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
  const [joinCode, setJoinCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    if (!roomName.trim()) {
      setError("Please enter a room name");
      return;
    }
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
    });
    setBusy(false);
    if (res.ok && res.roomId && res.code && res.token) {
      setSession({ roomId: res.roomId, code: res.code, token: res.token });
      navigate(`/room/${res.code}`);
    } else {
      setError(res.error || "Failed to create room");
    }
  }

  async function handleJoinByCode() {
    if (!requireNickname()) return;
    if (!joinCode.trim()) {
      setError("Please enter a room code");
      return;
    }
    await joinRoom({ code: joinCode.trim().toUpperCase() });
  }

  async function handleJoinRoom(room: RoomSummary) {
    if (!requireNickname()) return;
    await joinRoom({ roomId: room.id });
  }

  async function joinRoom(target: { roomId?: string; code?: string }) {
    setBusy(true);
    setError(null);
    const res = await emitWithAck<AckResponse>("join_room", {
      nickname: nicknameInput.trim(),
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
      <h1>Sketchy</h1>
      <p className="subtitle">An online multiplayer drawing &amp; guessing game</p>

      <section className="panel">
        <label>
          Nickname
          <input
            value={nicknameInput}
            onChange={(e) => setNicknameInput(e.target.value)}
            maxLength={20}
            placeholder="Your name"
          />
        </label>
      </section>

      {error && <p className="error-banner">{error}</p>}

      <div className="lobby-columns">
        <section className="panel">
          <h2>Create a room</h2>
          <label>
            Room name
            <input
              value={roomName}
              onChange={(e) => setRoomName(e.target.value)}
              maxLength={40}
              placeholder="e.g. Friday game night"
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
              value={customWords}
              onChange={(e) => setCustomWords(e.target.value)}
              placeholder="e.g. cat, red panda, ice cream truck"
              maxLength={400000}
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
            Hint letters
            <select value={hintMode} onChange={(e) => setHintMode(e.target.value as HintMode)}>
              <option value="none">Off</option>
              <option value="checkpoints">Timed hints, shown to everyone</option>
              <option value="purchase">Players can buy hints with points</option>
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
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value)}
              maxLength={6}
              placeholder="ABC123"
            />
          </label>
          <button disabled={busy} onClick={handleJoinByCode}>
            Join by code
          </button>
        </section>
      </div>

      <section className="panel">
        <h2>Public rooms</h2>
        {rooms.length === 0 && <p>No public rooms yet. Create one!</p>}
        <ul className="room-list">
          {rooms.map((room) => (
            <li key={room.id} className="room-row">
              <span className="room-name">{room.name}</span>
              <span className="room-meta">
                {room.playerCount}/{room.maxPlayers} players &middot; {room.state} &middot;{" "}
                {room.rounds} {room.rounds === 1 ? "round" : "rounds"} &middot;{" "}
                {room.drawingSeconds}s to draw &middot;{" "}
                {room.customWordCount > 0
                  ? `${room.customWordCount} custom words${room.customWordsOnly ? " only" : " + default"}`
                  : "default words"}
                {room.hintMode !== "none" && (
                  <>
                    {" "}
                    &middot; {room.hintMode === "checkpoints" ? "timed hints" : "buyable hints"}
                  </>
                )}
              </span>
              <button
                disabled={busy || room.playerCount >= room.maxPlayers}
                onClick={() => handleJoinRoom(room)}
              >
                Join
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
