import type { AnnouncementCode } from "./lib/announcements.ts";

export interface PlayerInfo {
  playerId: string;
  nickname: string;
  nameColor?: string;
  /** The uploaded picture, content-addressed; absent for guests and initials. */
  avatarUrl?: string | null;
  /** Guests render in grey italics; the flag is what drives that styling. */
  isAnonymous?: boolean;
  score: number;
  connected: boolean;
  isHost: boolean;
  isSpectator: boolean;
  isAfk: boolean;
  kickVotes?: string[];
  afkVotes?: string[];
}

export interface ModerationState {
  eligibleVoterIds: string[];
  requiredVotes: number;
}

export interface RestartVoteState {
  status: "voting" | "approved";
  proposerId: string;
  proposerNickname: string;
  eligibleVoterIds: string[];
  yesVoterIds: string[];
  noVoterIds: string[];
  castVotes: Array<{ playerId: string; vote: boolean }>;
  requiredVotes: number;
  expiresAt: number;
  restartAt: number | null;
}

/** Unattributed room-level signal delivered only to the current host. */
export interface ColorblindSafeSuggestion {
  active: boolean;
}

export type HintMode = "none" | "checkpoints" | "purchase" | "wheel";
export type ScoringMode = "none" | "default" | "pressure";
export type ColorMode = "all" | "palette" | "colorblind_safe" | "black_and_white";
export type PromptLanguage = "de" | "en" | "es" | "fr" | "it" | "nl" | "pt";

export interface PromptListSummary {
  id: string;
  slug: string;
  name: string;
  description: string;
  language: PromptLanguage;
  promptCount: number;
  isBundled: boolean;
  version: number;
  visibility?: "private" | "unlisted" | "public";
  shareCode?: string | null;
}

export interface OwnedPromptEntry {
  conceptId: string;
  promptVersionId: string;
  prompt: string;
  aliases: string[];
  moderationState: "active" | "under_review" | "hidden";
}

export interface OwnedPromptList extends PromptListSummary {
  id: string;
  /** `public` is reached by publishing, never by saving (R-LIST-02). */
  visibility: "private" | "unlisted" | "public";
  shareCode: string | null;
  moderationState: "active" | "under_review" | "hidden";
  /** Curated tag slugs on the list's current revision, in vocabulary order. */
  tags: string[];
  /** How many people starred it. Who they are is disclosed to nobody. */
  starCount: number;
  /**
   * The exact revision this list was copied from, if it was one — a revision
   * rather than a list, because both go on being edited. It may name one that
   * is no longer served.
   */
  forkedFromRevisionId: string | null;
  createdAt: string;
  updatedAt: string;
  prompts: OwnedPromptEntry[];
}

/**
 * One row of the community catalogue: a list somebody published.
 *
 * Deliberately not an `OwnedPromptList`. The owner is a display name and
 * nothing more — a stable account id in a public listing is a join key for
 * anybody who collects the pages — and there are no prompts here, because the
 * catalogue is a listing rather than a way to read every published list's
 * contents.
 */
export interface CommunityPromptList {
  id: string;
  slug: string;
  name: string;
  description: string;
  language: PromptLanguage;
  promptCount: number;
  ownerDisplayName: string;
  tags: string[];
  starCount: number;
  /** Null when nobody is signed in: a different answer from `false`. */
  starredByMe: boolean | null;
  publishedAt: string;
  version: number;
}

/** One entry of the curated list-tag vocabulary owners choose from. */
export interface PromptTag {
  slug: string;
  name: string;
}

export interface SharedPromptEntry {
  promptVersionId: string;
  prompt: string;
}

export interface SharedPromptList extends PromptListSummary {
  prompts: SharedPromptEntry[];
}

/** Role-gated queue item returned to a moderator; never part of room state. */
export interface PromptContentModerationReport {
  id: string;
  reporterUserId: string | null;
  reportedOwnerUserId: string | null;
  promptListId: string | null;
  promptVersionId: string | null;
  targetType: "list" | "prompt";
  listName: string;
  prompt: string | null;
  reason: string;
  details: string;
  status: "pending" | "resolved" | "dismissed";
  reviewedByUserId: string | null;
  resolutionNote: string | null;
  moderationState: "active" | "under_review" | "hidden" | null;
  createdAt: string;
  updatedAt: string;
  reviewedAt: string | null;
}

/** How one prompt has actually played, as reported by the stats endpoint. */
export interface PromptStats {
  text: string;
  offerCount: number;
  pickCount: number;
  correctGuessCount: number;
  totalGuesserCount: number;
  pickRate: number;
  correctGuessRatio: number;
  /** False until enough guessers have faced it for the ratios to mean anything. */
  isRated: boolean;
}

export type PromptStatsSort = "hardest" | "easiest" | "most-picked";

export interface PromptStatsResponse {
  slug: string;
  sort: PromptStatsSort;
  /** Guessers a prompt must have faced before it is ranked at all. */
  minRatedGuessers: number;
  ratedCount: number;
  unratedCount: number;
  prompts: PromptStats[];
}

export interface RoomSummary {
  id: string;
  code: string;
  name: string;
  isPublic: boolean;
  playerCount: number;
  spectatorCount: number;
  maxPlayers: number;
  isFull: boolean;
  rounds: number;
  customPromptCount: number;
  customPromptsOnly: boolean;
  drawingSeconds: number;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
  allowedTools: DrawingToolGroup[];
  colorMode: ColorMode;
  promptLanguage: PromptLanguage;
  promptListSlugs?: string[];
  state: "waiting" | "playing";
}

export interface RoomStatePayload {
  id: string;
  code: string;
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  customPromptCount: number;
  customPromptsOnly: boolean;
  drawingSeconds: number;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
  allowedTools: DrawingToolGroup[];
  colorMode: ColorMode;
  promptLanguage: PromptLanguage;
  promptListSlugs?: string[];
  state: "waiting" | "playing";
  lastGameScores?: ScoreEntry[];
  lastGameHighlights?: GameHighlight[];
  lastGameDrawings?: DrawingRecapMetadata[];
  moderation: ModerationState;
  restartVote?: RestartVoteState | null;
  restartVoteCooldownUntil?: number;
  players: PlayerInfo[];
}

export interface EditableRoomSettings {
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  drawingSeconds: number;
  customPrompts: string;
  customPromptsOnly: boolean;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
  allowedTools: DrawingToolGroup[];
  colorMode: ColorMode;
  promptLanguage: PromptLanguage;
  promptListSlugs?: string[];
  promptListShareCodes?: string[];
}

export type GamePhase = "idle" | "choosing_prompt" | "drawing" | "turn_results" | "game_end";

export interface ChatMessage {
  id: string;
  retainedMessageId?: string;
  playerId?: string;
  nickname: string;
  nameColor?: string;
  /** The uploaded picture, content-addressed; absent for guests and initials. */
  avatarUrl?: string | null;
  isAnonymous?: boolean;
  /** What a player typed. Absent on a room-authored line, which carries a
      `code` instead so each client can write it in its own language
      (R-I18N-03). */
  text?: string;
  /** The room's own line, as a fact rather than a sentence. Mirrors
      `Announcement` in `backend/app/announcements.py`. */
  code?: AnnouncementCode;
  /** The values that line needs - a nickname, a count, a reason slug. */
  params?: Record<string, unknown>;
  correct: boolean;
  system?: boolean;
  close?: boolean;
  restricted?: boolean;
  isSpectator?: boolean;
}

export interface ScoreEntry {
  playerId: string;
  nickname: string;
  nameColor?: string;
  /** The uploaded picture, content-addressed; absent for guests and initials. */
  avatarUrl?: string | null;
  isAnonymous?: boolean;
  score: number;
}

export interface TurnScoreEntry extends ScoreEntry {
  delta: number;
  previousRank: number;
  newRank: number;
}

/**
 * One reaction to a drawing, as the room carries it: the reactor's seat token
 * (never an account id) and the stable emoji code. The glyph is the client's
 * business - see `lib/reactions.ts` - so a code the server adds later still
 * arrives in one piece.
 */
export interface DrawingReaction {
  playerId: string;
  emoji: string;
}

/** Per-emoji counts for one drawing, keyed by code. */
export type ReactionTally = Record<string, number>;

/** The room-wide `drawing_reaction` broadcast. `emoji` is null when a reaction was taken back. */
export interface DrawingReactionEvent {
  turnId: string;
  playerId: string;
  nickname: string;
  nameColor?: string;
  isAnonymous?: boolean;
  emoji: string | null;
  tally: ReactionTally;
}

export interface ReactToDrawingResponse extends AckResponse {
  turnId?: string;
  emoji?: string | null;
  tally?: ReactionTally;
}

export interface TurnEndedPayload {
  prompt: string;
  /** The turn's durable id: what a reaction names. */
  turnId?: string;
  reactions?: DrawingReaction[];
  drawerId: string;
  drawerBonus: number;
  seconds?: number;
  guesses: {
    playerId: string;
    nickname: string;
    nameColor?: string;
    /** The uploaded picture, content-addressed; absent for guests and initials. */
    avatarUrl?: string | null;
    isAnonymous?: boolean;
    seconds: number;
  }[];
  scores: TurnScoreEntry[];
}

/**
 * How one player's turn score was arrived at: hints are bought on credit and
 * settled against the guess, so the gross figure can't be recovered from the
 * net one once the deduction clamps at zero.
 */
export interface GuessBreakdown {
  points: number;
  basePoints: number;
  hintSpend: number;
}

/**
 * One superlative from a finished game. Every kind is derived from guess counts
 * and timings alone - never from points - so the set means the same thing in a
 * no-scoring game as in a scored one. The server omits any highlight the game
 * gave it nothing to say about, so this list is often shorter than the union
 * of kinds and is sometimes empty.
 */
export type GameHighlight =
  | {
      kind: "hardest_prompt";
      prompt: string;
      correctGuessCount: number;
      totalGuesserCount: number;
    }
  | ({ kind: "fastest_guess"; prompt: string; seconds: number } & HighlightName)
  | ({ kind: "best_drawer"; guessRatio: number } & HighlightName)
  | ({ kind: "quickest_average"; seconds: number } & HighlightName)
  | ({
      kind: "most_reacted_drawing";
      prompt: string;
      reactionCount: number;
      /** Position in the recap, so the card can open that drawing. */
      drawingIndex: number;
      turnId: string;
    } & HighlightName);

/** The fields a highlight naming a player renders that name from. */
export interface HighlightName {
  nickname: string;
  nameColor?: string;
  /** The uploaded picture, content-addressed; absent for guests and initials. */
  avatarUrl?: string | null;
  isAnonymous?: boolean;
}

export interface GameEndedPayload {
  scores: ScoreEntry[];
  highlights?: GameHighlight[];
  drawings: DrawingRecapMetadata[];
}

export interface DrawingRecapMetadata {
  index: number;
  /** The durable turn id; absent only for entries a client synthesised itself. */
  turnId?: string;
  reactions?: DrawingReaction[];
  roundNumber: number;
  turnNumber: number;
  drawerId: string;
  drawerNickname: string;
  drawerNameColor?: string;
  prompt: string;
  actionCount: number;
  /** False once the room gave this bitmap up to stay inside its recap budget. */
  available?: boolean;
}

export interface DrawingRecapEntry extends DrawingRecapMetadata {
  canvas: unknown;
}

export interface DrawingRecapResponse extends AckResponse {
  drawing?: DrawingRecapEntry;
}

export interface StrokePoint {
  x: number;
  y: number;
}

export interface StrokeStartPayload {
  x: number;
  y: number;
  color: string;
  width: number;
}

export interface StrokeMovePayload {
  points: StrokePoint[];
  /** The open path's last point, when the encoder is given it: unlocks the
  relative frame (#559). Never on the wire itself. */
  previous?: StrokePoint;
  /** This batch also closes the path (#603): the final points and the end
  as one frame, carrying the commit the way `draw_end` does. */
  ends?: boolean;
}

/** A `draw_move` frame's offsets before its predecessor is known (#559):
a delta pair, or an absolute pair where the step escaped. */
export type RelativePointRecord =
  | { dx: number; dy: number }
  | { x: number; y: number };

export interface RelativeMovePayload {
  records: RelativePointRecord[];
  ends?: boolean;
}

/** The chips a host toggles. The eraser rides with the brush - see `drawingRules.ts`. */
export type DrawingToolGroup = "brush" | "fill" | "shapes";

export type ShapeType = "rectangle" | "ellipse" | "triangle";

export type DrawTool = "brush" | "eraser" | ShapeType | "fill";

export interface StrokeShapePayload {
  shape: ShapeType;
  from: StrokePoint;
  to: StrokePoint;
  color: string;
  width: number;
}

export interface StrokeFillPayload {
  x: number;
  y: number;
  color: string;
}

export interface CanvasSyncPayload {
  v: number;
  a: unknown[];
}

/** Why the server refused a command. Mirrors `ErrorCode` in
`backend/app/handlers/refusals.py` member for member; a test on the backend
fails when the two drift. Branch on this, never on `error`, which is prose for
the player and changes whenever the copy does. */
export type ErrorCode =
  | "invalid_payload"
  | "invalid_nickname"
  | "invalid_name_color"
  | "invalid_hint"
  | "invalid_letter"
  | "invalid_prompt_lists"
  | "invalid_custom_prompts"
  | "max_players_below_seated"
  | "empty_message"
  | "too_fast"
  | "seat_changing_too_fast"
  | "joining_too_fast"
  | "room_quota"
  | "room_full"
  | "spectators_full"
  | "player_slots_full"
  | "server_draining"
  | "server_paused"
  | "database_busy"
  | "account_ended"
  | "account_required"
  | "identity_unavailable"
  | "not_in_room"
  | "room_not_found"
  | "room_ended"
  | "could_not_create_room"
  | "no_session_to_resume"
  | "host_only"
  | "players_only"
  | "waiting_room_only"
  | "already_a_player"
  | "registered_name_fixed"
  | "name_taken_by_account"
  | "guests_cannot_choose_color"
  | "suggestion_inactive"
  | "drawing_not_found"
  | "drawing_not_kept"
  | "not_in_game"
  | "game_in_progress"
  | "game_starting"
  | "need_two_players"
  | "room_not_startable"
  | "prompt_not_ready"
  | "prompt_unavailable"
  | "hints_disabled"
  | "hint_spend_limit"
  | "hint_unavailable"
  | "drawer_only"
  | "canvas_stale_generation"
  | "canvas_sequence_committed"
  | "canvas_out_of_sequence"
  | "canvas_out_of_sync"
  | "nothing_to_undo"
  | "spectators_cannot_vote"
  | "spectators_cannot_be_targets"
  | "invalid_vote_target"
  | "not_eligible"
  | "restart_vote_active"
  | "restart_vote_cooldown"
  | "no_restart_vote"
  | "restart_vote_closed"
  | "spectators_cannot_react"
  | "guests_cannot_react"
  | "reaction_not_visible"
  | "own_drawing"
  | "game_still_saving"
  | "game_not_recorded"
  | "reaction_not_accepted"
  | "friends_unavailable"
  | "friend_refused"
  | "friend_not_in_game"
  | "friend_in_several_games"
  | "not_friends"
  | "friends_only_uninvited"
  | "invite_expired"
  | "reporting_unavailable"
  | "no_such_player"
  | "cannot_report"
  | "already_reported"
  | "name_required"
  | "not_watching_lobby"
  | "protocol_mismatch"
  | "sign_in_required"
  | "credentials_incorrect"
  | "password_incorrect"
  | "account_suspended"
  | "already_signed_in"
  | "username_taken"
  | "invalid_username"
  | "weak_password"
  | "password_change_failed"
  | "session_not_found"
  | "session_replaced"
  | "guest_progress_unlinked"
  | "not_taking_visitors"
  | "account_delete_refused"
  | "password_required_to_delete"
  | "second_factor_required"
  | "second_factor_passkey_only"
  | "second_factor_not_enrolled"
  | "second_factor_not_set_up"
  | "second_factor_code_wrong"
  | "second_factor_throttled"
  | "step_up_required"
  | "passkey_sign_in_required"
  | "passkey_not_registered"
  | "passkey_not_found"
  | "passkey_refused"
  | "last_factor"
  | "second_factor_required_for_role"
  | "second_factor_not_proved"
  | "invalid_email"
  | "email_in_use"
  | "email_change_refused"
  | "verification_link_invalid"
  | "email_verification_required"
  | "reset_link_invalid"
  | "export_not_found"
  | "export_expired"
  | "export_not_ready"
  | "export_unreadable"
  | "export_not_yet_allowed"
  | "export_refused"
  | "too_many_attempts"
  | "too_many_requests"
  | "too_many_reports"
  | "too_many_bug_reports"
  | "too_many_pictures"
  | "unsupported_picture_type"
  | "picture_not_found"
  | "picture_refused"
  | "screenshot_unreadable"
  | "screenshot_too_large"
  | "screenshot_unsupported_type"
  | "bug_report_context_too_large"
  | "friends_throttled"
  | "that_is_you"
  | "no_such_game"
  | "no_such_drawing"
  | "drawing_unreadable"
  | "prompt_list_not_found"
  | "shared_prompt_list_not_found"
  | "prompt_list_conflict"
  | "prompt_list_invalid"
  | "prompt_list_forbidden"
  | "unknown_prompt_tag"
  | "prompt_list_hidden"
  | "prompt_list_allowance_reached"
  | "unknown_sort"
  | "timezone_required"
  | "range_reversed"
  | "room_preset_not_found"
  | "room_preset_conflict"
  | "room_preset_unavailable"
  | "room_preset_forbidden"
  | "cannot_block_yourself"
  | "block_list_full"
  | "setting_refused"
  | "no_such_notice"
  | "cannot_report_yourself"
  | "cannot_report_own_prompt_list"
  | "no_reportable_prompt_list"
  | "prompt_not_in_list"
  | "no_picture_to_report"
  | "no_such_game_context"
  | "no_such_turn_context"
  | "turn_not_in_game"
  | "evidence_unavailable"
  | "evidence_mixed_scopes"
  | "evidence_several_rooms"
  | "evidence_not_theirs"
  | "evidence_not_received"
  | "evidence_not_in_game"
  | "evidence_not_in_turn"
  | "no_such_warning"
  | "warning_unread"
  | "no_drawing";

export interface AckResponse {
  ok: boolean;
  roomId?: string;
  code?: string;
  playerId?: string;
  /** Set on every refusal. The only field a program should read. */
  errorCode?: ErrorCode;
  /** The player's sentence; shown, never compared. */
  error?: string;
  field?: string;
  /** When the server knows trying again could work: a command budget's window,
  a vote cooldown. Absent when it does not. */
  retryAfterMs?: number;
  isAnonymous?: boolean;
  needsRebind?: boolean;
}

export interface ServerShutdownNotice {
  contractVersion: 1;
  reason: "deployment";
  drainSeconds: number;
  startedAt: string;
}

export interface ServerPausedNotice {
  contractVersion: 1;
  paused: boolean;
  reason: "maintenance";
}

export interface RoomPreviewResponse extends AckResponse {
  room?: RoomSummary;
}
