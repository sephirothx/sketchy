import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { emitEntry, emitTransient, socketRequestErrorMessage } from "../lib/socket";
import { sessionFrom } from "../lib/roomEntryState";
import { AppHeader } from "../components/AppHeader";
import { FirstRunIdentity } from "../components/FirstRunIdentity";
import { LobbyChatPanel } from "../components/LobbyChatPanel";
import { LobbyLinks } from "../components/LobbyLinks";
import { OnlinePlayersPanel } from "../components/OnlinePlayersPanel";
import { IdentityRequiredError, needsIdentity, useAuthStore } from "../store/authStore";
import { currentPlayerName } from "../store/authStore";
import { PublicRoomCard } from "../components/PublicRoomCard";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { useRoomsStore } from "../store/roomsStore";
import { useRoomEntryStore } from "../store/roomEntryStore";
import { ModalShell } from "../components/ui/ModalShell";
import { BottomSheet } from "../components/ui/BottomSheet";
import { EmptyState } from "../components/ui/EmptyState";
import { Button } from "../components/ui/Button";
import { useLobbyChannel } from "../hooks/useLobbyChannel";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { AlertCircleIcon, BoltIcon, PlusIcon, SearchIcon } from "../components/icons";
import {
  SUPPORTED_PROMPT_LANGUAGES,
  sortRoomsByLanguage,
} from "../lib/promptLanguages";
import {
  ANY_LANGUAGE,
  LanguagePicker,
  type LanguageChoice,
} from "../components/LanguagePicker";
import type { AckResponse, RoomSummary } from "../types";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

const ROOM_CODE_LENGTH = 6;

/** How many open rooms it takes before the list offers search and filters.
    With one room open a phone showed a search field, a Filters button and
    "Showing 1 of 1" above a list that fit on the screen: three controls with
    nothing to act on. Six is about where the list runs past a phone's first
    screen, and where finding one room by name starts to beat reading. */
const ROOM_FILTERS_FROM = 6;


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
      <h3 id={titleId} className="modal-title">{ui.lobbyBrowserPage.removedFromRoom}</h3>
      <p id={descriptionId} className="modal-body">{message}</p>
      <button ref={okButtonRef} type="button" className="modal-button" onClick={onDismiss}>
        {ui.lobbyBrowserPage.ok}
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
      <span className={hideLabel ? "visually-hidden" : undefined}>{ui.lobbyBrowserPage.roomCode}</span>
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
          placeholder={ui.lobbyBrowserPage.abc123}
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
  // Only the name check's own words are ours to show; an ApiError's message
  // is the server's English, for a log (R-I18N-01).
  if (error instanceof IdentityRequiredError) return error.message;
  return refusalText(error, ui.lobbyBrowserPage.couldNotSaveThatName);
}

export function LobbyBrowserPage() {
  // The front door: the tab says the site's name and nothing else.
  useDocumentTitle(null);
  const navigate = useNavigate();
  const location = useLocation();
  const nameColor = useSettingsStore((s) => s.nameColor);
  const colorblindSafeColors = useSettingsStore((s) => s.colorblindSafeColors);
  const playerLanguage = useSettingsStore((s) => s.promptLanguage);
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
        setError(ui.lobbyBrowserPage.thereNoRoomCodeClipboard);
      }
    } catch {
      setError(ui.lobbyBrowserPage.sketchyCouldNotReadClipboardPaste);
    }
    codeFieldRef.current?.focus();
  }
  const codeFieldRef = useRef<HTMLInputElement | null>(null);
  // Only the lobby watches the presence channel: a player inside a room is
  // not reading this list and should not be paying for it mid-game.
  useLobbyChannel();
  const isNarrow = useMediaQuery("(max-width: 720px)");
  // A room to a row, with its facts in columns, once the rooms panel is wide
  // enough to hold them (#581). The same breakpoint the lobby's columns use.
  const isWide = useMediaQuery("(min-width: 1500px)");
  const [error, setError] = useState<string | null>(null);
  const [criticalError, setCriticalError] = useState<string | null>(location.state?.criticalError ?? null);
  // One entry at a time, whichever control started it - a room card, a code,
  // Quick play, or a friend's invitation from outside this page. Two in flight
  // would release each other's seats and race for the session and the route,
  // so every entry control is disabled while one is pending. The lock is the
  // app's, not this page's (store/roomEntryStore.ts).
  const pendingJoin = useRoomEntryStore((state) => state.pending);
  const beginEntry = useRoomEntryStore((state) => state.begin);
  const endEntry = useRoomEntryStore((state) => state.end);
  const quickPlayBusy = pendingJoin?.key === "quick-play";
  // An entry whose answer arrives after the lobby has gone (the player took
  // the header's way somewhere else meanwhile) must not drag them back into a
  // room - and a seat it did take is let go rather than left behind.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  // The validator from the last successful fetch. A ref rather than state:

  const [searchQuery, setSearchQuery] = useState("");
  const [languageFilter, setLanguageFilter] = useState<LanguageChoice>(ANY_LANGUAGE);
  const [hideFullRooms, setHideFullRooms] = useState(false);
  const [hideInProgressRooms, setHideInProgressRooms] = useState(false);
  // Drives the chip's badge, so a list narrowed by filters that are out of
  // sight in a sheet never looks like a list with nothing in it.
  const activeFilterCount =
    (languageFilter !== ANY_LANGUAGE ? 1 : 0) + (hideFullRooms ? 1 : 0) + (hideInProgressRooms ? 1 : 0);
  // Kept while anything narrows the list, or a list that a filter took below
  // the threshold would hide the very control that widens it again.
  const showRoomFilters =
    rooms.length >= ROOM_FILTERS_FROM || activeFilterCount > 0 || searchQuery.trim() !== "";
  // Everything that narrows the list, the search included: what a list with
  // nothing left in it offers to undo.
  function clearRoomFilters() {
    setSearchQuery("");
    setLanguageFilter(ANY_LANGUAGE);
    setHideFullRooms(false);
    setHideInProgressRooms(false);
  }
  // Nothing here works without a name: the server provisions on naming,
  // needs an account to open a room, and needs a valid nickname to seat
  // anybody. The first-run block above asks for it.
  const awaitingName = useAuthStore((state) => needsIdentity(state.user));
  const ensureIdentity = useAuthStore((state) => state.ensureIdentity);

  // Arriving at the lobby means any room exit has completed.
  useEffect(() => {
    setExitingRoom(false);
  }, [setExitingRoom]);

  // The languages the game has content in, not the ones that happen to have a
  // room open: a control that appears and disappears with the population reads
  // as a bug, and "no rooms in Dutch" is an answer worth being able to get.
  const roomLanguages = SUPPORTED_PROMPT_LANGUAGES;

  // Your language first, nobody hidden (R-PROMPT-11).
  // Memoised (#991): the room list's deltas arrive once a second, and the
  // search box and the chat beside it re-render the page on every keystroke.
  const filteredRooms = useMemo(() => sortRoomsByLanguage(rooms, playerLanguage).filter((room) => {
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      const nameMatch = room.name.toLowerCase().includes(q);
      const codeMatch = room.code?.toLowerCase().includes(q);
      if (!nameMatch && !codeMatch) return false;
    }
    if (languageFilter !== ANY_LANGUAGE && room.promptLanguage !== languageFilter) {
      return false;
    }
    if (hideFullRooms && room.playerCount >= room.maxPlayers) {
      return false;
    }
    if (hideInProgressRooms && room.state === "playing") {
      return false;
    }
    return true;
  }), [rooms, playerLanguage, searchQuery, languageFilter, hideFullRooms, hideInProgressRooms]);

  // No gate: every visitor already has a name, generated on their first load.
  async function handleOpenCreateRoom() {
    // An entry already in flight owns the socket and the route.
    if (useRoomEntryStore.getState().pending) return;
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

  /**
   * The one control that plays (#589, #931): into a room that is waiting with
   * a seat free, or into a new one on the standard rules when there is none.
   *
   * One command, decided by the server, which holds the rooms: the client's
   * walk over the lobby's list took a round trip per candidate, could not run
   * until a list had arrived - ten seconds after naming a first-time visitor,
   * whose naming reconnects the socket - and gave every presser in one moment
   * their own room, because each read the same list.
   */
  async function handleQuickPlay() {
    const token = beginEntry("quick-play");
    if (token === null) return;
    setError(null);
    try {
      let playerName = currentPlayerName();
      if (awaitingName) playerName = (await ensureIdentity()).displayName;
      const answer = await emitEntry<AckResponse>("quick_play", {
        nickname: playerName,
        nameColor,
        colorblindSafeColors,
        promptLanguage: playerLanguage,
      });
      const session = sessionFrom(answer);
      if (!mountedRef.current) {
        if (session) letGoOfAStraySeat();
        return;
      }
      if (session) {
        setSession(session);
        navigate(`/room/${session.code}`);
        return;
      }
      if (answer.errorCode === "name_in_use") useAuthStore.getState().markNameInUse();
      setError(refusalText(answer, ui.lobbyBrowserPage.couldNotFindOrOpenARoom));
    } catch (quickPlayError) {
      if (!mountedRef.current) return;
      if (quickPlayError instanceof IdentityRequiredError) setError(identityMessage(quickPlayError));
      else setError(socketRequestErrorMessage(quickPlayError, ui.lobbyBrowserPage.quickPlay));
    } finally {
      endEntry(token);
    }
  }

  async function handleJoinByCode(asSpectator = false) {
    if (!joinCode.trim()) {
      setError(ui.lobbyBrowserPage.pleaseEnterRoomCode);
      return;
    }
    await joinRoom({ code: joinCode.trim().toUpperCase() }, asSpectator, "private-code");
  }

  async function handleJoinRoom(room: RoomSummary, asSpectator = false) {
    await joinRoom({ roomId: room.id }, asSpectator, room.id);
  }

  async function joinRoom(target: { roomId?: string; code?: string }, asSpectator: boolean, key: string) {
    const token = beginEntry(key, asSpectator ? "spectate" : "join");
    if (token === null) return;
    setError(null);
    try {
      // Every join arrives here - a public room card, a code, a spectate - so
      // this is where a visitor who typed a name and pressed one of those
      // instead of the block's own button becomes somebody.
      let playerName = currentPlayerName();
      if (awaitingName) {
        try {
          playerName = (await ensureIdentity()).displayName;
        } catch (identityError) {
          if (mountedRef.current) setError(identityMessage(identityError));
          return;
        }
      }
      const res = await emitEntry<AckResponse>("join_room", {
        nickname: playerName,
        nameColor,
        colorblindSafeColors,
        asSpectator,
        ...target,
      });
      const session = sessionFrom(res);
      if (!mountedRef.current) {
        if (session) letGoOfAStraySeat();
        return;
      }
      if (session) {
        setSession(session);
        navigate(`/room/${session.code}`);
      } else {
        setError(refusalText(res, ui.lobbyBrowserPage.failedJoinRoom));
      }
    } catch (joinError) {
      if (!mountedRef.current) return;
      setError(socketRequestErrorMessage(joinError, asSpectator ? ui.lobbyBrowserPage.joinAsASpectator : ui.lobbyBrowserPage.joinTheRoom));
    } finally {
      endEntry(token);
    }
  }

  // One function for the page's lifetime, so a memoised card whose room did
  // not change is not re-rendered by a new closure (#991); it reaches the
  // current `handleJoinRoom` through a ref.
  const handleJoinRef = useRef<typeof handleJoinRoom | null>(null);
  useEffect(() => {
    handleJoinRef.current = handleJoinRoom;
  });
  const joinRoomCard = useCallback((room: RoomSummary, asSpectator: boolean) => {
    void handleJoinRef.current?.(room, asSpectator);
  }, []);

  /**
   * A seat taken by an answer that arrived after the lobby had gone. Safe to
   * release because the entry lock was held throughout: no other way in can
   * have seated this socket since - and, belt and braces, only while no room
   * is on screen, so it can never free a seat the player is looking at.
   */
  function letGoOfAStraySeat() {
    if (useGameStore.getState().roomId === null) emitTransient("leave_room");
  }

  return (
    <div className="lobby-page">
      <AppHeader languageSwitch />
      {/* The page's one heading. The wordmark above is a link, not a heading,
          and the lobby shows its name nowhere else: every panel below has its
          own. Out of the layout, so the grid and flex rows are untouched. */}
      <h1 className="visually-hidden">{ui.lobbyBrowserPage.lobby}</h1>

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
          <h2>{ui.lobbyBrowserPage.publicRooms}</h2>
          {/* Only when it says something the list does not: how many a filter
              left out. "0 rooms" beside "No public rooms yet", and "Showing 1
              of 1" above one room, only repeated what was under them. */}
          {roomsState.loaded && filteredRooms.length < rooms.length && (
            <span className="lobby-rooms-count">
              {ui.lobbyBrowserPage.showingFilteredRoomsCountOfRoomsCount({ filteredRoomsCount: filteredRooms.length, roomsCount: rooms.length })}
            </span>
          )}
          {/* The two ways into a room, beside the list of rooms rather than in
              the header - the pair a phone's dock already holds, in the same
              order of weight. The header is left to the person: language,
              settings, account. The catalogue and the Gallery are in the
              links at the foot of the page, and in the account menu. */}
          {!isNarrow && (
            <div className="lobby-rooms-actions">
              {/* The fast one of the three, and the only one that is a game
                  rather than a form (#589). */}
              <button
                type="button"
                className="btn btn-warm btn-compact lobby-quick-play"
                data-testid="quick-play"
                disabled={Boolean(pendingJoin)}
                onClick={() => void handleQuickPlay()}
              >
                <BoltIcon size={15} />
                {quickPlayBusy ? ui.lobbyBrowserPage.quickPlayBusy : ui.lobbyBrowserPage.quickPlay}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-compact"
                disabled={Boolean(pendingJoin)}
                onClick={() => setCodeSheetOpen(true)}
              >
                {ui.lobbyBrowserPage.joinByCode}
              </button>
              <Button
                variant="primary"
                compact
                iconLeft={<PlusIcon size={15} />}
                disabled={Boolean(pendingJoin)}
                onClick={() => void handleOpenCreateRoom()}
              >
                {ui.lobbyBrowserPage.createRoom}
              </Button>
            </div>
          )}
        </div>

        {roomsState.loaded && showRoomFilters && (
          <div className="lobby-filter-bar">
            <span className="lobby-room-search">
              <SearchIcon size={15} />
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={ui.lobbyBrowserPage.searchRoomsByNameCode}
                aria-label={ui.lobbyBrowserPage.searchRoomsByNameCode}
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
                {ui.lobbyBrowserPage.filtersWithCount({ count: activeFilterCount })}
              </button>
            ) : (
              <>
                <LanguagePicker
                  label={ui.lobbyBrowserPage.filterByLanguage}
                  value={languageFilter}
                  options={roomLanguages}
                  includeAny
                  compact
                  onChange={setLanguageFilter}
                />
                <button
                  type="button"
                  className="lobby-filter-toggle"
                  aria-pressed={hideFullRooms}
                  onClick={() => setHideFullRooms((v) => !v)}
                >
                  {ui.lobbyBrowserPage.hideFull}
                </button>
                <button
                  type="button"
                  className="lobby-filter-toggle"
                  aria-pressed={hideInProgressRooms}
                  onClick={() => setHideInProgressRooms((v) => !v)}
                >
                  {ui.lobbyBrowserPage.hideProgress}
                </button>
              </>
            )}
          </div>
        )}

        {filterSheetOpen && (
          <BottomSheet
            title={ui.lobbyBrowserPage.filters}
            testId="lobby-filter-sheet"
            onDismiss={() => setFilterSheetOpen(false)}
            footer={
              <>
                {activeFilterCount > 0 && (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setLanguageFilter(ANY_LANGUAGE);
                      setHideFullRooms(false);
                      setHideInProgressRooms(false);
                    }}
                  >
                    {ui.lobbyBrowserPage.clearFilters}
                  </button>
                )}
                <Button variant="primary" onClick={() => setFilterSheetOpen(false)}>
                  {ui.lobbyBrowserPage.showRooms({ count: filteredRooms.length })}
                </Button>
              </>
            }
          >
            <div className="lobby-filter-sheet">
              <div className="lobby-filter-row">
                <span>{ui.lobbyBrowserPage.language}</span>
                <LanguagePicker
                  label={ui.lobbyBrowserPage.filterByLanguage}
                  value={languageFilter}
                  options={roomLanguages}
                  includeAny
                  compact
                  onChange={setLanguageFilter}
                />
              </div>
              <button
                type="button"
                className="lobby-filter-row is-toggle"
                aria-pressed={hideFullRooms}
                onClick={() => setHideFullRooms((v) => !v)}
              >
                <span>{ui.lobbyBrowserPage.hideFullRooms}</span>
                <span className={`lobby-filter-switch${hideFullRooms ? " is-on" : ""}`} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="lobby-filter-row is-toggle"
                aria-pressed={hideInProgressRooms}
                onClick={() => setHideInProgressRooms((v) => !v)}
              >
                <span>{ui.lobbyBrowserPage.hideGamesProgress}</span>
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
          <p className="loading-note" role="status">{ui.lobbyBrowserPage.loadingPublicRooms}</p>
        ) : rooms.length === 0 ? (
          <EmptyState
            title={ui.lobbyBrowserPage.noPublicRoomsYet}
            body={ui.lobbyBrowserPage.noPublicRoomsYetBody}
          />
        ) : filteredRooms.length === 0 ? (
          <EmptyState
            compact
            className="lobby-no-matches"
            title={ui.lobbyBrowserPage.noPublicRoomsMatchYourSearch}
            action={
              <button type="button" className="btn btn-ghost btn-compact" onClick={clearRoomFilters}>
                {ui.lobbyBrowserPage.clearFilters}
              </button>
            }
          />
        ) : (
          <div className={`room-list${isWide ? " is-rows" : ""}`}>
            {/* Headings for the row's columns. Hidden from assistive tech:
                each row already says what its numbers are. */}
            {isWide && (
              <div className="room-list-columns" aria-hidden="true">
                <span>{ui.publicRoomCard.columnRoom}</span>
                <span>{ui.publicRoomCard.columnSeats}</span>
                <span>{ui.publicRoomCard.columnLength}</span>
                <span>{ui.publicRoomCard.columnRoomRules}</span>
              </div>
            )}
            {filteredRooms.map((room) => (
              <PublicRoomCard key={room.id} room={room} busy={Boolean(pendingJoin)} pendingMode={pendingJoin?.key === room.id ? pendingJoin.mode : null} onJoin={joinRoomCard} layout={isWide ? "row" : "card"} />
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

      {/* The rest of the site, from the page rather than only from the chip's
          menu, which a visitor with no name does not have yet. */}
      <LobbyLinks />

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
          <button
            type="button"
            className="btn btn-warm btn-big lobby-quick-play"
            data-testid="quick-play"
            disabled={Boolean(pendingJoin)}
            onClick={() => void handleQuickPlay()}
          >
            <BoltIcon size={16} />
            {quickPlayBusy ? ui.lobbyBrowserPage.quickPlayBusy : ui.lobbyBrowserPage.quickPlay}
          </button>
          <div className="lobby-dock-row">
            <Button
              variant="primary"
              iconLeft={<PlusIcon size={15} />}
              disabled={Boolean(pendingJoin)}
              onClick={() => void handleOpenCreateRoom()}
            >
              {ui.lobbyBrowserPage.createRoom2}
            </Button>
            <button
              type="button"
              className="btn btn-secondary lobby-dock-code"
              disabled={Boolean(pendingJoin)}
              onClick={() => setCodeSheetOpen(true)}
            >
              {ui.lobbyBrowserPage.joinWithCode}
            </button>
          </div>
        </div>
      )}

      {codeSheetOpen && (
        <BottomSheet
          title={ui.lobbyBrowserPage.joinWithCode}
          testId="lobby-code-sheet"
          closeLabel={ui.lobbyBrowserPage.close}
          onDismiss={() => setCodeSheetOpen(false)}
          initialFocusRef={codeFieldRef}
          headerAction={
            <button
              type="button"
              className="chip chip-neutral room-code-paste"
              onClick={() => void pasteCode()}
            >
              {ui.lobbyBrowserPage.paste}
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
                {pendingJoin?.key === "private-code" && pendingJoin.mode === "join" ? ui.lobbyBrowserPage.joining : ui.lobbyBrowserPage.joinTheRoom2}
              </Button>
              <button
                type="button"
                className="btn btn-ghost lobby-code-spectate"
                disabled={Boolean(pendingJoin)}
                onClick={() => void handleJoinByCode(true)}
              >
                {pendingJoin?.key === "private-code" && pendingJoin.mode === "spectate"
                  ? ui.lobbyBrowserPage.joiningAsSpectator
                  : ui.lobbyBrowserPage.watchWithoutPlaying}
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

    </div>
  );
}
