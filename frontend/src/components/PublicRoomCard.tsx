import { memo, useState } from "react";
import { promptLanguageLabel } from "../lib/promptLanguages";
import { gameLength, changedRoomRules } from "../lib/roomCardFacts";
import { emitWithAck } from "../lib/socket";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { Avatar } from "./ui/Avatar";
import { ChevronDownIcon, ClockIcon, EyeIcon, Flag, RoundsIcon, UsersIcon } from "./icons";
import type { RoomSummary } from "../types";
import { useLocaleRerender } from "../hooks/useLocaleRerender";
import { ui } from "../content/ui/index.ts";

interface RosterEntry {
  nickname: string;
  nameColor?: string;
  avatarUrl?: string | null;
  isAnonymous?: boolean;
  isHost?: boolean;
}

interface PublicRoomCardProps {
  room: RoomSummary;
  busy: boolean;
  pendingMode: "join" | "spectate" | null;
  /** Stable across renders, so a card whose room did not change skips its
      render when the list's does (#991). */
  onJoin: (room: RoomSummary, asSpectator: boolean) => void;
  /** `row` on a wide lobby, where each room has a row of its own (#581). */
  layout?: "card" | "row";
}

/** How many changed rules a row shows before folding the rest into "+N more",
    so an unusual room's row stays about the height its name and status
    already give it. The chips wrap rather than clip, so a language with
    longer labels can take a third line, but never hides a rule it has not
    counted. */
const ROW_RULES_SHOWN = 3;

/**
 * One open room, as a card you can scan in a second - or, on a wide lobby, as
 * a row.
 *
 * The card's facts are the ones that decide whether to tap: what it is called,
 * what language the prompts are in, how full it is, and how long a game will
 * take (rounds x drawing time). Everything else it used to carry — a chip per
 * room rule, a capacity meter, the spectator count — priced the room rather
 * than described it, and on a phone it pushed the next room off the screen.
 *
 * The row is where those come back (#581). From 1500px each room has the full
 * width of the rooms panel, one to a row, and a row that said only what the
 * card says was a name at one end, two buttons at the other and 800px of
 * nothing between. So it lines the facts up in columns — seats, length, and
 * only the rules that differ from a new room's — where comparing rooms is a
 * glance down each column. Still nothing that names a player.
 */
export const PublicRoomCard = memo(function PublicRoomCard({ room, busy, pendingMode, onJoin, layout = "card" }: PublicRoomCardProps) {
  useLocaleRerender();
  const full = room.isFull || room.playerCount >= room.maxPlayers;
  const playing = room.state === "playing";
  const languageLabel = promptLanguageLabel(room.promptLanguage);

  // Who is in there is fetched for this room when it is asked for, never
  // carried by the room list - see Room.to_public_roster.
  const [roster, setRoster] = useState<RosterEntry[] | null>(null);
  const [rosterOpen, setRosterOpen] = useState(false);
  const [rosterError, setRosterError] = useState<string | null>(null);

  async function toggleRoster() {
    if (rosterOpen) {
      setRosterOpen(false);
      return;
    }
    setRosterOpen(true);
    setRosterError(null);
    try {
      const ack = await emitWithAck<{ ok: boolean; players?: RosterEntry[] }>(
        "get_room_preview",
        { code: room.code },
      );
      if (ack?.ok && Array.isArray(ack.players)) {
        setRoster(ack.players);
      } else {
        setRosterError(ui.publicRoomCard.couldNotReadWhoIs);
      }
    } catch {
      setRosterError(ui.publicRoomCard.couldNotReadWhoIs);
    }
  }

  // The flag rides on the name's line: it is part of what the room is rather
  // than one of the numbers describing it, and it buys the facts row back a
  // slot. The language's name is read out rather than printed, for anyone who
  // cannot see the flag or is unsure of it.
  const name = (
    <h3 className="public-room-name">
      <span className="public-room-name-text">{room.name}</span>
      <span className="public-room-language" title={ui.publicRoomCard.promptLanguage({ language: languageLabel })}>
        <Flag language={room.promptLanguage} />
        <span className="visually-hidden">{languageLabel}</span>
      </span>
    </h3>
  );

  const rosterPanel = rosterOpen && (
    <div className="public-room-roster">
      {rosterError && <p className="public-room-roster-note" role="alert">{rosterError}</p>}
      {!rosterError && roster === null && (
        <p className="public-room-roster-note">{ui.publicRoomCard.looking}</p>
      )}
      {!rosterError && roster !== null && roster.length === 0 && (
        <p className="public-room-roster-note">{ui.publicRoomCard.nobodySeatedYet}</p>
      )}
      {!rosterError && roster !== null && roster.length > 0 && (
        <ul>
          {roster.map((player, index) => (
            <li key={`${player.nickname}-${index}`}>
              <Avatar
                name={player.nickname}
                nameColor={player.nameColor}
                avatarUrl={player.avatarUrl}
                isAnonymous={player.isAnonymous}
                isHost={player.isHost}
                size={22}
              />
              <span
                className={playerNameClass(player.isAnonymous)}
                style={playerNameStyle(player.nameColor, player.isAnonymous)}
              >
                {player.nickname}
              </span>
              {player.isHost && <span className="visually-hidden">{ui.publicRoomCard.host}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  const actions = (
    <div className="public-room-actions">
      {!full && (
        <button
          type="button"
          className={`btn ${playing ? "btn-warm" : "btn-primary"} public-room-primary-action`}
          disabled={busy}
          onClick={() => onJoin(room, false)}
        >
          {pendingMode === "join" ? ui.publicRoomCard.joining : ui.publicRoomCard.join}
        </button>
      )}
      <button
        type="button"
        className="btn btn-secondary public-room-secondary-action"
        disabled={busy}
        onClick={() => onJoin(room, true)}
      >
        <EyeIcon size={14} />
        {pendingMode === "spectate" ? ui.publicRoomCard.joining : ui.publicRoomCard.spectate}
      </button>
    </div>
  );

  if (layout === "row") {
    const length = gameLength(room);
    const rules = changedRoomRules(room);
    const shownRules = rules.slice(0, ROW_RULES_SHOWN);
    const foldedRules = rules.slice(ROW_RULES_SHOWN);
    const open = Math.max(0, room.maxPlayers - room.playerCount);
    const status = full ? "full" : playing ? "playing" : "waiting";
    return (
      <article className="public-room-card is-row" data-testid="public-room-card">
        <div className="public-room-row-room">
          {name}
          <span className={`public-room-status is-${status}`}>
            {full ? ui.publicRoomCard.full : playing ? ui.publicRoomCard.inProgress : ui.publicRoomCard.waiting}
          </span>
        </div>
        {/* The seats are the control here too: they are how you find out who
            is sitting in them. */}
        <button
          type="button"
          className={`public-room-seats${rosterOpen ? " is-open" : ""}`}
          aria-expanded={rosterOpen}
          onClick={() => void toggleRoster()}
          title={ui.publicRoomCard.seeWhoThisRoom}
        >
          <span className="public-room-seat-pips" aria-hidden="true">
            {Array.from({ length: room.maxPlayers }, (_, index) => (
              <i key={index} className={index < room.playerCount ? "is-taken" : undefined} />
            ))}
          </span>
          <small>
            {room.playerCount}/{room.maxPlayers}
            {" · "}
            {open > 0 ? ui.publicRoomCard.seatsOpen({ count: open }) : ui.publicRoomCard.noSeatsOpen}
            {room.spectatorCount > 0 && ` · ${ui.publicRoomCard.watching({ count: room.spectatorCount })}`}
            <ChevronDownIcon size={12} />
          </small>
        </button>
        <div className="public-room-length">
          <strong>
            {length.low === length.high
              ? ui.publicRoomCard.gameLength({ minutes: length.high })
              : ui.publicRoomCard.gameLengthRange({ low: length.low, high: length.high })}
          </strong>
          <small>
            {ui.publicRoomCard.roundCount({ count: room.rounds })} · {room.drawingSeconds}s
          </small>
        </div>
        <ul className="public-room-rules" aria-label={ui.publicRoomCard.columnRoomRules}>
          {rules.length === 0 && <li className="chip chip-neutral">{ui.publicRoomCard.standardRules}</li>}
          {shownRules.map((rule) => <li key={rule} className="chip chip-primary">{rule}</li>)}
          {foldedRules.length > 0 && (
            <li className="chip chip-neutral public-room-rules-more" title={foldedRules.join(", ")}>
              <span aria-hidden="true">{ui.publicRoomCard.moreRules({ count: foldedRules.length })}</span>
              <span className="visually-hidden">{foldedRules.join(", ")}</span>
            </li>
          )}
        </ul>
        {actions}
        {rosterPanel}
      </article>
    );
  }

  return (
    <article className="public-room-card" data-testid="public-room-card">
      <div className="public-room-card-main">
        {name}
        <p className="public-room-facts">
          {/* The count is the control: tapping it is how you find out who
              those players are. */}
          <button
            type="button"
            className={`public-room-roster-toggle${rosterOpen ? " is-open" : ""}`}
            aria-expanded={rosterOpen}
            onClick={() => void toggleRoster()}
            title={ui.publicRoomCard.seeWhoThisRoom}
          >
            <UsersIcon size={14} />
            {room.playerCount}/{room.maxPlayers}
            <ChevronDownIcon size={12} />
          </button>
          <span title={ui.publicRoomCard.rounds}>
            <RoundsIcon size={14} />
            {ui.publicRoomCard.roundCount({ count: room.rounds })}
          </span>
          <span title={ui.publicRoomCard.drawingTime}>
            <ClockIcon size={14} />
            {room.drawingSeconds}s
          </span>
          {/* Not decoration: full removes the Join button, and a game already
              running means joining puts you in a later turn. */}
          {full && <strong className="public-room-flag">{ui.publicRoomCard.full}</strong>}
          {!full && playing && <strong className="public-room-flag is-playing">{ui.publicRoomCard.inProgress}</strong>}
        </p>
        {rosterPanel}
      </div>
      {actions}
    </article>
  );
});
