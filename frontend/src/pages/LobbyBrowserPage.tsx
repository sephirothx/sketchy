import { useEffect, useId, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { sessionFrom } from "../lib/roomEntryState";
import { AppHeader } from "../components/AppHeader";
import { FirstRunIdentity } from "../components/FirstRunIdentity";
import { LobbyChatPanel } from "../components/LobbyChatPanel";
import { OnlinePlayersPanel } from "../components/OnlinePlayersPanel";
import { ApiError } from "../lib/api";
import { IdentityRequiredError, needsIdentity, useAuthStore } from "../store/authStore";
import { currentPlayerName } from "../store/authStore";
import { PublicRoomCard } from "../components/PublicRoomCard";
import { VersionBadge } from "../components/VersionBadge";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { useRoomsStore } from "../store/roomsStore";
import { ModalShell } from "../components/ui/ModalShell";
import { BottomSheet } from "../components/ui/BottomSheet";
import { Button } from "../components/ui/Button";
import { useLobbyChannel } from "../hooks/useLobbyChannel";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { AlertCircleIcon, ChevronDownIcon, PlusIcon, SearchIcon } from "../components/icons";
import { promptLanguageLabel } from "../lib/promptLanguages";
import type { AckResponse, RoomSummary } from "../types";

const ROOM_CODE_LENGTH = 6;

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
  inputRef,
  hideLabel = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** So the code sheet can open with the caret already in the field. */
  inputRef?: React.Ref<HTMLInputElement>;
  /** The sheet's own title already says what the field is for. */
  hideLabel?: boolean;
}) {
  const fieldId = useId();
  const activeIndex = Math.min(value.length, ROOM_CODE_LENGTH - 1);

  return (
    <label
      className={`room-code-label${hideLabel ? " is-unlabelled" : ""}`}
      htmlFor={fieldId}
    >
      <span className={hideLabel ? "visually-hidden" : undefined}>Room code</span>
      <span className="room-code-cells">
        {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
        <input
          ref={inputRef}
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

/**
 * What to show when becoming somebody failed.
 *
 * The server's own words where it has them: a name that belongs to a
 * registered player, or a provisioning ceiling that has been reached, are
 * both things a player can act on, and "please try again" tells them to do
 * the one thing that will not work.
 */
function identityMessage(error: unknown): string {
  if (error instanceof IdentityRequiredError || error instanceof ApiError) {
    return error.message;
  }
  return "Could not save that name. Please try again.";
}

export function LobbyBrowserPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const nameColor = useSettingsStore((s) => s.nameColor);
  const colorblindSafeColors = useSettingsStore((s) => s.colorblindSafeColors);
  const setSession = useGameStore((s) => s.setSession);
  const setExitingRoom = useGameStore((s) => s.setExitingRoom);
  // Pushed over the lobby channel rather than polled (#462). The store is
  // replaced by a snapshot and patched by deltas; nothing here refetches.
  const roomsState = useRoomsStore((state) => state.rooms);
  const rooms = roomsState.rooms;
  const [joinCode, setJoinCode] = useState("");
  const [codeSheetOpen, setCodeSheetOpen] = useState(false);
  const [filterSheetOpen, setFilterSheetOpen] = useState(false);

  /** A room code arrives from a message thread, so reading the clipboard is
   *  the shortest path. Where that is refused — no permission, an insecure
   *  origin, a browser that does not implement it — the field is focused so
   *  the platform's own paste is one long-press away. */
  async function pasteCode() {
    try {
      const text = await navigator.clipboard?.readText();
      const cleaned = normalizeRoomCodeInput(text ?? "");
      if (cleaned) {
        setJoinCode(cleaned);
        setError(null);
      } else {
        setError("There is no room code on the clipboard.");
      }
    } catch {
      setError("Sketchy could not read the clipboard. Paste into the boxes instead.");
    }
    codeFieldRef.current?.focus();
  }
  const codeFieldRef = useRef<HTMLInputElement | null>(null);
  // Only the lobby watches the presence channel: a player inside a room is
  // not reading this list and should not be paying for it mid-game.
  useLobbyChannel();
  const isNarrow = useMediaQuery("(max-width: 720px)");
  const [error, setError] = useState<string | null>(null);
  const [criticalError, setCriticalError] = useState<string | null>(location.state?.criticalError ?? null);
  const [pendingJoin, setPendingJoin] = useState<PendingJoin | null>(null);
  // The validator from the last successful fetch. A ref rather than state:

  const [searchQuery, setSearchQuery] = useState("");
  const [languageFilter, setLanguageFilter] = useState("all");
  const [hideFullRooms, setHideFullRooms] = useState(false);
  const [hideInProgressRooms, setHideInProgressRooms] = useState(false);
  // Drives the chip's badge, so a list narrowed by filters that are out of
  // sight in a sheet never looks like a list with nothing in it.
  const activeFilterCount =
    (languageFilter !== "all" ? 1 : 0) + (hideFullRooms ? 1 : 0) + (hideInProgressRooms ? 1 : 0);
  // Nothing here works without a name: the server provisions on naming,
  // needs an account to open a room, and needs a valid nickname to seat
  // anybody. The first-run block above asks for it.
  const awaitingName = useAuthStore((state) => needsIdentity(state.user));
  const ensureIdentity = useAuthStore((state) => state.ensureIdentity);

  // Arriving at the lobby means any room exit has completed.
  useEffect(() => {
    setExitingRoom(false);
  }, [setExitingRoom]);

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
  async function handleOpenCreateRoom() {
    // A visitor who typed a name and pressed this plainly means to play under
    // it, so provision from the draft rather than sending them back to a form
    // they have already filled in.
    if (awaitingName) {
      try {
        await ensureIdentity();
      } catch (identityError) {
        setError(identityMessage(identityError));
        return;
      }
    }
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
    // Every join arrives here - a public room card, a code, a spectate - so
    // this is where a visitor who typed a name and pressed one of those
    // instead of the block's own button becomes somebody.
    let playerName = currentPlayerName();
    if (awaitingName) {
      try {
        playerName = (await ensureIdentity()).displayName;
      } catch (identityError) {
        setError(identityMessage(identityError));
        setPendingJoin(null);
        return;
      }
    }
    try {
      const res = await emitWithAck<AckResponse>("join_room", {
        nickname: playerName,
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
      <AppHeader
        action={!isNarrow && (
          <Button
            variant="primary"
            compact
            iconLeft={<PlusIcon size={15} />}
            onClick={() => void handleOpenCreateRoom()}
          >
            Create room
          </Button>
        )}
      />

      {criticalError && (
        <RemovedFromRoomDialog
          message={criticalError}
          onDismiss={() => setCriticalError(null)}
        />
      )}



      <FirstRunIdentity />

      {error && !isNarrow && <p className="lobby-action-error" role="alert">{error}</p>}

      <section className="panel lobby-rooms-panel">
        <div className="lobby-rooms-heading">
          <h2>Public rooms</h2>
          <span className="lobby-rooms-count">
            {!roomsState.loaded ? "Loading…" : rooms.length > 0 ? `Showing ${filteredRooms.length} of ${rooms.length}` : "0 rooms"}
          </span>
          {!isNarrow && (
            <button
              type="button"
              className="btn btn-secondary btn-compact lobby-rooms-code-button"
              onClick={() => setCodeSheetOpen(true)}
            >
              Join by code
            </button>
          )}
        </div>

        {roomsState.loaded && rooms.length > 0 && (
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
            {/* Three controls in a row is three rows on a phone, and 110px of
                filtering before the first room. Behind one chip they cost a
                slot beside the search field, and the chip says how many are
                on so a filtered-looking list is never a mystery. */}
            {isNarrow ? (
              <button
                type="button"
                className={`lobby-filter-toggle lobby-filter-sheet-button${activeFilterCount > 0 ? " has-filters" : ""}`}
                aria-pressed={activeFilterCount > 0}
                onClick={() => setFilterSheetOpen(true)}
              >
                Filters{activeFilterCount > 0 ? ` · ${activeFilterCount}` : ""}
              </button>
            ) : (
              <>
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
              </>
            )}
          </div>
        )}

        {filterSheetOpen && (
          <BottomSheet
            title="Filters"
            testId="lobby-filter-sheet"
            onDismiss={() => setFilterSheetOpen(false)}
            footer={
              <>
                {activeFilterCount > 0 && (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setLanguageFilter("all");
                      setHideFullRooms(false);
                      setHideInProgressRooms(false);
                    }}
                  >
                    Clear filters
                  </button>
                )}
                <Button variant="primary" onClick={() => setFilterSheetOpen(false)}>
                  Show {filteredRooms.length} {filteredRooms.length === 1 ? "room" : "rooms"}
                </Button>
              </>
            }
          >
            <div className="lobby-filter-sheet">
              <label className="lobby-filter-row">
                <span>Prompt language</span>
                <span className="lobby-language-filter">
                  <select
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
              </label>
              <button
                type="button"
                className="lobby-filter-row is-toggle"
                aria-pressed={hideFullRooms}
                onClick={() => setHideFullRooms((v) => !v)}
              >
                <span>Hide full rooms</span>
                <span className={`lobby-filter-switch${hideFullRooms ? " is-on" : ""}`} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="lobby-filter-row is-toggle"
                aria-pressed={hideInProgressRooms}
                onClick={() => setHideInProgressRooms((v) => !v)}
              >
                <span>Hide games in progress</span>
                <span className={`lobby-filter-switch${hideInProgressRooms ? " is-on" : ""}`} aria-hidden="true" />
              </button>
            </div>
          </BottomSheet>
        )}

        {/* No retry, and no refresh error. There is nothing to re-ask: the
            channel re-subscribes itself on reconnect and on a missed delta,
            and a socket that is down is what `ConnectionStatusBanner` is for.
            The only states left are "not told yet" and "told". */}
        {!roomsState.loaded ? (
          <div className="room-list-loading" role="status">Loading public rooms…</div>
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
      {/* Two panels that are about the people here rather than the rooms, so
          they sit below the list rather than above it. They stack on a phone
          in the same order: the room browser is what the page is for. */}
      <div className="lobby-social">
        <LobbyChatPanel />

        <OnlinePlayersPanel />
      </div>

      {/* The way in is a fixed bar under the thumb on a phone, rather than the
          header controls a desktop gets: three actions beside the wordmark is
          what used to push this header onto two rows. */}
      {isNarrow && (
        <div className="lobby-dock">
          {/* The page-top alert is out of sight from down here, and behind the
              code sheet entirely, so on a phone the message follows the
              control. Only one of the three renders at a time. */}
          {error && !codeSheetOpen && (
            <p className="lobby-action-error" role="alert">{error}</p>
          )}
          <Button
            variant="primary"
            big
            iconLeft={<PlusIcon size={16} />}
            onClick={() => void handleOpenCreateRoom()}
          >
            Create a room
          </Button>
          <button
            type="button"
            className="btn btn-secondary lobby-dock-code"
            onClick={() => setCodeSheetOpen(true)}
          >
            Join with a code
          </button>
        </div>
      )}

      {codeSheetOpen && (
        <BottomSheet
          title="Join with a code"
          testId="lobby-code-sheet"
          closeLabel="Close"
          onDismiss={() => setCodeSheetOpen(false)}
          initialFocusRef={codeFieldRef}
          headerAction={
            <button
              type="button"
              className="chip chip-neutral room-code-paste"
              onClick={() => void pasteCode()}
            >
              Paste
            </button>
          }
          footer={
            <>
              {error && <p className="lobby-action-error" role="alert">{error}</p>}
              <Button
                variant="primary"
                disabled={Boolean(pendingJoin)}
                onClick={() => void handleJoinByCode(false)}
              >
                {pendingJoin?.key === "private-code" && pendingJoin.mode === "join" ? "Joining…" : "Join the room"}
              </Button>
              <button
                type="button"
                className="btn btn-ghost lobby-code-spectate"
                disabled={Boolean(pendingJoin)}
                onClick={() => void handleJoinByCode(true)}
              >
                {pendingJoin?.key === "private-code" && pendingJoin.mode === "spectate"
                  ? "Joining as spectator…"
                  : "Watch without playing"}
              </button>
            </>
          }
        >
          <RoomCodeInput
            value={joinCode}
            onChange={setJoinCode}
            onSubmit={() => void handleJoinByCode(false)}
            inputRef={codeFieldRef}
            hideLabel
          />
        </BottomSheet>
      )}

      <VersionBadge />
    </div>
  );
}
