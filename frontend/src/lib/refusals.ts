/** What a refusal says to the player, written here rather than by the server.

Every refusal - a socket acknowledgement or an HTTP response - carries an
enumerated `errorCode` and, where a sentence needs a value, typed `params`.
The server also sends prose in `error`/`detail`, and nothing in this app
renders it: it is there for a log line, for the bug report a player attaches
to a complaint, and for an operator reading a response by hand (R-I18N-01).

That is the whole point of the split. The reader's language is known here and
nowhere else, so the sentence has to be written here. Until #762 this table is
the only catalogue the app has; when the catalogue lands, these entries move
into it unchanged and this module keeps only `refusalText`.

`params` carry **values, never fragments** - a count, a limit, a reason slug -
because a server-built noun phrase dropped into a sentence is prose with extra
steps, and it breaks in the first language that inflects. That is why
`weak_password` sends `reason: "keyboard_walk"` rather than the English
sentence it used to send. */
import type { ErrorCode } from "../types.ts";

/** The values a sentence may need. Always plain data, never rendered text. */
export type RefusalParams = Record<string, unknown>;

/** Anything that might be a refusal: an `ApiError`, an acknowledgement, a
    rejected promise. Read defensively - it crosses the wire. */
export type RefusalLike = {
  errorCode?: ErrorCode | string | null;
  params?: RefusalParams | null;
};

function count(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function megabytes(bytes: unknown, fallback: string): string {
  const value = typeof bytes === "number" && bytes > 0 ? bytes / 1_000_000 : null;
  if (value === null) return fallback;
  return value >= 1 ? `${Math.round(value)} MB` : `${Math.round(value / 1000)} KB`;
}

/** Why a password was refused. The server screens; the wording is ours.

Each reason is actionable on its own, which is the reason the screening sends
one at all: somebody told only "no" comes back with the same password and one
more digit (R-AUTH-19). */
function weakPassword(params: RefusalParams): string {
  const detail = params.detail;
  switch (params.reason) {
    case "too_short":
      return `Password must be at least ${count(detail, 12)} characters.`;
    case "too_long":
      return `Password must be at most ${count(detail, 128)} characters.`;
    case "common":
      return "That password is one of the most common ones in use. Please choose another.";
    case "common_repeated":
      return "That is a common password repeated. Please choose another.";
    case "short_repeated":
      return "That password is a short one repeated. Please choose another.";
    case "too_few_characters":
      return `That password uses only ${count(detail, 4)} different characters. Please choose another.`;
    case "keyboard_walk":
      return "That password is mostly a run of keys in order. Please choose another.";
    case "contains_identity":
      return "A password must not contain your name, your email address, or the name of this site.";
    case "common_with_digits":
      return "That is a common password with digits added. Please choose another.";
    default:
      return "Please choose a different password.";
  }
}

/** *Create an account to …* - one refusal, said about the thing it refused. */
function accountRequired(params: RefusalParams): string {
  switch (params.action) {
    case "avatar":
      return "Create an account to choose a picture.";
    case "prompt_lists":
      return "Create an account to save reusable prompt lists.";
    case "name_color":
      return "Create an account to choose a name color.";
    case "password":
      return "Create an account to set a password.";
    case "second_factor":
      return "Create an account before setting up two-factor authentication.";
    case "friends":
      return "Create an account to add friends.";
    default:
      return "Create an account to do that.";
  }
}

type Sentence = string | ((params: RefusalParams) => string);

/** Every code the server can refuse with, and what the player is told.

Ordered as `ErrorCode` is, so the two can be read side by side. A missing key
fails the build: `Record<ErrorCode, …>` is exhaustive, which is what stops a
new server code reaching a player as a blank. */
const SENTENCES: Record<ErrorCode, Sentence> = {
  // Payloads and arguments
  invalid_payload: "Sketchy could not read that request.",
  invalid_nickname: "That name cannot be used here.",
  invalid_name_color: "Pick a color that reads on both the light and the dark player list.",
  invalid_hint: "That hint is not valid.",
  invalid_letter: "That letter is not valid.",
  invalid_prompt_lists: "Those prompt lists cannot be used together.",
  invalid_custom_prompts: "Those custom prompts could not be read.",
  max_players_below_seated: (params) =>
    `Max players cannot be below the ${count(params.seated, 2)} players already in the room.`,
  empty_message: "Type something first.",

  // Rate and capacity
  too_fast: "You are doing that too quickly. Slow down a moment.",
  seat_changing_too_fast: "This seat is changing hands too quickly. Try again in a minute.",
  joining_too_fast: "You are joining rooms too quickly. Try again in a minute.",
  room_quota: "You have as many rooms open as you can have at once.",
  room_full: "This room is full.",
  spectators_full: "This room is not taking any more spectators.",
  player_slots_full: "Every player seat is taken.",

  // Server and account state
  server_draining: "Sketchy is restarting. Try again in a moment.",
  server_paused: "Sketchy is not taking new rooms right now.",
  database_busy: "Sketchy is having trouble reaching its database. Please try again.",
  account_ended: "This account is no longer active.",
  account_required: accountRequired,
  identity_unavailable: "Sketchy could not confirm who you are. Reload and try again.",

  // Rooms
  not_in_room: "You are not in this room.",
  room_not_found: "Room not found.",
  room_ended: "This room has ended.",
  could_not_create_room: "Could not create the room.",
  no_session_to_resume: "There is no session of yours to resume in this room.",
  host_only: "Only the host can do that.",
  players_only: "Only players can do that.",
  waiting_room_only: "That is only available in the waiting room.",
  already_a_player: "You are already a player.",
  registered_name_fixed: "Registered players play as their username.",
  name_taken_by_account: "That name belongs to a registered player.",
  guests_cannot_choose_color: "Create an account to choose a name color.",
  suggestion_inactive: "This suggestion is no longer active.",
  drawing_not_found: "Drawing not found.",
  drawing_not_kept: "This drawing was not kept.",

  // Games and turns
  not_in_game: "You are not in an active game.",
  game_in_progress: "The game is already in progress.",
  game_starting: "The game is still starting.",
  need_two_players: "Two active players are needed to start.",
  room_not_startable: "This room cannot start a game right now.",
  prompt_not_ready: "The game is not ready for a prompt yet.",
  prompt_unavailable: "That prompt is no longer available.",
  hints_disabled: "Hints are switched off in this room.",
  hint_spend_limit: "You have reached this turn's hint spend limit.",
  hint_unavailable: "That hint is not available.",

  // Canvas
  drawer_only: "Only the drawer can do that.",
  canvas_stale_generation: "The canvas has moved on. Catching up.",
  canvas_sequence_committed: "That has already been drawn.",
  canvas_out_of_sequence: "Drawing actions arrived out of order. Catching up.",
  canvas_out_of_sync: "The canvas is out of sync. Catching up.",
  nothing_to_undo: "There is nothing to undo.",

  // Votes and restarts
  spectators_cannot_vote: "Spectators cannot vote.",
  spectators_cannot_be_targets: "A spectator cannot be the subject of a vote.",
  invalid_vote_target: "You cannot vote on that player.",
  not_eligible: "Only active players can propose a restart.",
  restart_vote_active: "A restart vote is already running.",
  restart_vote_cooldown: "A restart was just voted on. Wait a moment before proposing another.",
  no_restart_vote: "There is no restart vote to answer.",
  restart_vote_closed: "That restart vote has already closed.",

  // Reactions
  spectators_cannot_react: "Spectators cannot react to a drawing.",
  guests_cannot_react: "Create an account to react to a drawing.",
  reaction_not_visible: "You cannot react to a drawing you cannot see.",
  own_drawing: "You cannot react to your own drawing.",
  game_still_saving: "That game is still being saved. Try again in a moment.",
  game_not_recorded: "That game was not recorded.",
  reaction_not_accepted: "That reaction could not be sent.",

  // Friends
  friends_unavailable: "Friends are unavailable right now.",
  friend_refused: "That friend request could not be completed.",
  friend_not_in_game: "Your friend is not in a game right now.",
  friend_in_several_games: "That friend is in more than one game. Ask them for an invite.",
  not_friends: "You can only join a friend's game.",
  friends_only_uninvited: "Only the host's friends can join this game uninvited. Ask them for an invite.",
  invite_expired: "That invitation has expired.",

  // Moderation, from the reporter's side
  reporting_unavailable: "Reporting is unavailable on this server.",
  no_such_player: "No such player.",
  cannot_report: "That player cannot be reported.",
  already_reported: "You have already reported this, and a moderator has not reviewed it yet.",

  // Lobby chat
  name_required: "Choose a name before saying anything in the lobby.",
  not_watching_lobby: "You are no longer watching the lobby.",

  // Versioning
  protocol_mismatch: "This tab is running an older version of Sketchy. Reload the page to continue.",

  // Sessions and accounts
  sign_in_required: "Sign in first.",
  credentials_incorrect: "Incorrect username or password.",
  password_incorrect: "Password is incorrect.",
  account_suspended: "This account is suspended.",
  already_signed_in: "You are already signed in to an account.",
  username_taken: "That username is taken.",
  invalid_username: "That username cannot be used.",
  weak_password: weakPassword,
  password_change_failed: "Could not change the password.",
  session_not_found: "That device is no longer signed in.",
  session_replaced: "This session has been replaced. Reload and try again.",
  guest_progress_unlinked: "Guest progress could not be linked to this account.",
  not_taking_visitors: "Sketchy is not taking new visitors right now. Please try again later.",
  account_delete_refused: "The account could not be deleted right now. Please try again.",
  password_required_to_delete: "Enter your password to delete the account.",

  // Second factor and passkeys
  second_factor_required: "Enter the code from your authenticator app.",
  second_factor_passkey_only: "Sign in with your passkey.",
  second_factor_not_enrolled:
    "This account needs two-factor authentication before it can sign in. Ask an administrator to help you enrol.",
  second_factor_not_set_up: "Two-factor authentication is not set up.",
  second_factor_code_wrong: "That code is not right.",
  second_factor_throttled: "Too many codes were wrong. Please wait and try again.",
  step_up_required: "Confirm it is you before doing that.",
  passkey_sign_in_required: "Sign in with your passkey.",
  passkey_not_registered: "That passkey is not registered here.",
  passkey_not_found: "No such passkey.",
  passkey_refused:
    "Passkeys are for moderator and administrator accounts. You will be asked to set one up if you are ever offered a role.",
  last_factor: "That is the only way you can prove it is you. Add another before removing this one.",
  second_factor_required_for_role: "Two-factor authentication is required for this account's role.",
  second_factor_not_proved:
    "This authenticator has not been confirmed as yours. Use a passkey, or confirm it with your password in Settings.",

  // Email, verification and recovery
  invalid_email: "That does not look like an email address.",
  email_in_use: "That address is already in use.",
  email_change_refused: "That address cannot be added to this account.",
  verification_link_invalid: "That confirmation link has expired or already been used.",
  reset_link_invalid: "That reset link has expired or already been used.",

  // Account data export
  export_not_found: "Export not found.",
  export_expired: "Export has expired.",
  export_not_ready: "Export is not ready.",
  export_unreadable: "Export document could not be read. Request a new export.",
  export_not_yet_allowed: "You have requested an export recently. Try again later.",
  export_refused: "That export could not be started. Please try again.",

  // Rate limits reached over HTTP
  too_many_attempts: "Too many attempts. Please wait and try again.",
  too_many_requests: "Too many requests. Please wait and try again.",
  too_many_reports: "Too many reports. Please wait before sending another.",
  too_many_bug_reports: "Too many bug reports. Please wait before sending another.",
  too_many_pictures: "Too many pictures. Please wait and try again.",

  // Pictures
  unsupported_picture_type: "That is not a WebP or PNG picture.",
  picture_not_found: "No such picture.",
  picture_refused: "That picture cannot be used here.",

  // Bug reports
  screenshot_unreadable: "The screenshot could not be read.",
  screenshot_too_large: (params) =>
    `That screenshot is too large. The limit is ${megabytes(params.limitBytes, "2 MB")}.`,
  screenshot_unsupported_type: "A screenshot must be a PNG or WebP image.",
  bug_report_context_too_large: "That report carries too much context.",

  // Friends, over HTTP
  friends_throttled: "You have sent a lot of friend requests. Try again later.",
  that_is_you: "That is you.",

  // Profiles and history
  no_such_game: "No such game.",
  no_such_drawing: "No such drawing.",
  drawing_unreadable: "That drawing could not be read.",

  // Prompt lists
  prompt_list_not_found: "Prompt list not found.",
  shared_prompt_list_not_found: "No shared prompt list found.",
  prompt_list_conflict: "Somebody else changed that list. Reload it and try again.",
  prompt_list_invalid: "That prompt list could not be saved.",
  prompt_list_forbidden: "That prompt list is not yours to change.",
  unknown_sort: "Sketchy cannot sort by that.",
  timezone_required: "Include a timezone with that date.",
  range_reversed: "The start of the range must come before its end.",

  // Room presets
  room_preset_not_found: "Room preset not found.",
  room_preset_conflict: "You already have a preset with that name.",
  room_preset_unavailable: "That preset cannot be used right now.",
  room_preset_forbidden: "That preset is not yours.",

  // Blocks
  cannot_block_yourself: "You cannot block yourself.",
  block_list_full: (params) =>
    `Your block list is full${
      typeof params.limit === "number" ? ` at ${params.limit}` : ""
    }. Unblock somebody first.`,

  // Settings
  setting_refused: "That setting could not be saved.",

  // Role notices
  no_such_notice: "No such notice.",

  // Reporting, from the reporter's side
  cannot_report_yourself: "You cannot report yourself.",
  cannot_report_own_prompt_list: "You cannot report your own prompt list.",
  no_reportable_prompt_list: "No reportable prompt list found.",
  prompt_not_in_list: "That prompt does not belong to this list.",
  no_picture_to_report: "That player has no picture to report.",
  no_such_game_context: "No such game context.",
  no_such_turn_context: "No such turn context.",
  turn_not_in_game: "The turn does not belong to that game.",
  evidence_unavailable: "One or more selected messages are unavailable.",
  evidence_mixed_scopes: "Lobby and room messages cannot be mixed in one report.",
  evidence_several_rooms: "Selected messages must come from one room instance.",
  evidence_not_theirs: "Evidence must be authored by the reported player.",
  evidence_not_received: "You cannot select a message you did not receive.",
  evidence_not_in_game: "Selected message does not belong to that game.",
  evidence_not_in_turn: "Selected message does not belong to that turn.",
  no_such_warning: "No such warning.",
  no_drawing: "No drawing.",
};

/** The code a refusal carries, if it carries one this app knows. */
export function refusalCode(problem: unknown): ErrorCode | null {
  const code = (problem as RefusalLike | null)?.errorCode;
  return typeof code === "string" && code in SENTENCES ? (code as ErrorCode) : null;
}

/** What to show the player for this refusal.

`fallback` covers the two cases a code cannot: a network failure with no
response at all, and a server newer than this bundle. Callers pass the
sentence that fits where they are - "Could not save that preset." - rather
than a generic apology. */
export function refusalText(problem: unknown, fallback: string): string {
  const code = refusalCode(problem);
  if (!code) return fallback;
  const sentence = SENTENCES[code];
  const params = (problem as RefusalLike).params ?? {};
  return typeof sentence === "function" ? sentence(params) : sentence;
}
