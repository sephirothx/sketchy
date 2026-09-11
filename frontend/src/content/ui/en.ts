/** Every word the interface says, in English.

The reference catalogue: each other locale is a translation of this one, and
it is what the type checker measures them against.

**No component owns a sentence any more.** A literal in a player-facing
component is caught by `frontend/tests/catalogue.test.mjs`, because a
string that stays behind is a screen that stays English no matter what its
reader chose (R-I18N-05).

Entries with values are **functions**, not format strings: parameters and
plurals are then checked by the compiler, and there is no runtime message
parser to ship or to escape. `Intl.PluralRules` decides the plural category,
so a locale writes the categories its own language has rather than the two
English happens to need.

Grouped by the surface the words appear on rather than by page, so a sentence
used twice is one entry. Staff surfaces - the moderation queue, the operations
pages - are deliberately absent: they are English on purpose (R-I18N-01). */
import { formattersFor } from "./format.ts";
import type { AnnouncementCode } from "../../lib/announcements.ts";
import type { ErrorCode } from "../../types.ts";

const { counted, number, ordinal, plural } = formattersFor("en", {
  one: "st",
  two: "nd",
  few: "rd",
  other: "th",
});


/** Values a refusal or an announcement carries. Plain data, never words. */
export type MessageParams = Record<string, unknown>;

function count(value: unknown, fallback = 0): number {
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
function weakPassword(params: MessageParams): string {
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
function accountRequired(params: MessageParams): string {
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

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

/** Why an approved restart never happened, as its own half-sentence.

Kept apart from the line so the sentence around it can be reordered freely -
a language that puts the reason first has somewhere to put it. */
function cancelReason(reason: unknown): string {
  switch (reason) {
    case "server_update":
      return "a server update is in progress";
    case "too_few_players":
      return "fewer than two active players remain";
    case "prompt_lists_unavailable":
      return "the prompt lists could not be loaded";
    case "everybody_left":
      return "everybody left before it could begin";
    default:
      return "it could no longer go ahead";
  }
}

type Sentence = string | ((params: MessageParams) => string);

/** Why the server refused, said to the player.

One entry per `ErrorCode`; `Record` makes it exhaustive, so a code the server
adds without a sentence here fails the build rather than the player
(R-I18N-04). */
const REFUSALS: Record<ErrorCode, Sentence> = {
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
  no_drawing: "No drawing.",};

/** What the room says about itself. One entry per `AnnouncementCode`. */
const ANNOUNCEMENTS: Record<AnnouncementCode, (params: MessageParams) => string> = {
  nickname_changed: (p) =>
  `${text(p.previous)} is now known as ${text(p.nickname)}.`,
  joined_as_player: (p) => `${text(p.nickname)} joined as a player.`,
  kicked_by_vote: (p) => `${text(p.nickname)} was kicked by vote.`,
  marked_afk_by_vote: (p) => `${text(p.nickname)} was marked AFK by vote.`,

  restart_vote_started: (p) =>
  `${text(p.nickname)} started a vote to restart the game.`,
  restart_vote_passed: (p) =>
  `The restart vote passed. Restarting in ${count(p.seconds, 5)} seconds.`,
  restart_vote_rejected: () => "The restart vote was rejected.",
  restart_vote_expired: () => "The restart vote expired without passing.",
  restart_vote_abandoned: () =>
  "The restart vote was cancelled because fewer than two active players remain.",
  restart_cancelled: (p) => `The restart was cancelled because ${cancelReason(p.reason)}.`,
  game_restarted_by_vote: () => "The game was restarted by player vote.",

  hint_letter_found: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pts - found ${counted(count(p.count, 1), {
    one: "time",
    other: "times",
  })}!`,
  hint_letter_missing: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pts - not in the prompt.`,
  guess_very_close: (p) => `"${text(p.text)}" is very close!`,
  guess_some_words_correct: () => "Some words are correct",};

export const EN = {
  refusals: REFUSALS,
  announcements: ANNOUNCEMENTS,

  /** What the document itself says: the tab, and what a link preview shows.

      Rendered into `index.html` for a crawler, which arrives before any
      script, and rewritten here for the reader once their locale is known. */
  document: {
    description: "Draw, guess and laugh with friends!",
  },

  /** Shapes that belong to the language rather than to any one screen. */
  format: {
    /** `1st`, `2nd`, `3rd`; a language with no ordinal form gets the number. */
    ordinal: (p: { value: number }) => ordinal(p.value),
  },

  promptListDrafts: {
    promptsAdded: (p: { count: number }) =>
      `Added ${counted(p.count, { one: "prompt", other: "prompts" })}`,
    duplicatesAlreadyInTheList: (p: { duplicates: number }) => `${p.duplicates} already in the list`,
    tooLongCountOverMaxListPrompt:
      (p: { tooLongCount: number; MAX_LIST_PROMPT_LENGTH: number }) => `${p.tooLongCount} over ${p.MAX_LIST_PROMPT_LENGTH} characters`,
    overLimitPastTheMaxList:
      (p: { overLimit: number; MAX_LIST_PROMPTS: number }) => `${p.overLimit} past the ${p.MAX_LIST_PROMPTS} limit`,
    keptSkippedSkipped: (p: { kept: string; skipped: string }) => `${p.kept}; skipped ${p.skipped}.`,
  },

  lastSeen: {
    online: "online",
    justNow: "last seen just now",
    lastSeenAgo: (p: { count: number; unit: "minute" | "hour" | "day" }) => {
      const words = {
        minute: { one: "minute", other: "minutes" },
        hour: { one: "hour", other: "hours" },
        day: { one: "day", other: "days" },
      }[p.unit];
      return `last seen ${counted(p.count, words)} ago`;
    },
  },

  gameHighlights: {
    reactionCount: (p: { count: number }) =>
      counted(p.count, { one: "reaction", other: "reactions" }),
    hardestPrompt: "Hardest prompt",
    fastestGuess: "Fastest guess",
    bestDrawer: "Best drawer",
    quickestOnAverage: "Quickest on average",
    mostReactedDrawing: "Most reacted drawing",
  },

  versionBadge: {
    buildDetails: (p: { commitDate: string; builtAt: string }) =>
      `Commit date: ${p.commitDate} | Built: ${p.builtAt}`,
  },

  segmentedCodeInput: {
    digitPosition: (p: { label: string; index: number; length: number }) =>
      `${p.label}, digit ${p.index} of ${p.length}`,
  },

  roomSetupControls: {
    decrease: (p: { label: string }) => `Decrease ${p.label}`,
    increase: (p: { label: string }) => `Increase ${p.label}`,
  },

  guessPips: {
    playerGuessState: (p: { nickname: string; isFriend: boolean; guessed: boolean }) =>
      `${p.nickname}${p.isFriend ? " (friend)" : ""} ${p.guessed ? "guessed it" : "is still guessing"}`,
    gotOfGuessersCountGuessed:
      (p: { got: number; guessersCount: number }) => `${p.got} of ${p.guessersCount} guessed`,
    summaryOpenPlayersAndScores:
      (p: { summary: string }) => `${p.summary}. Open players and scores.`,
  },

  accountDataDialog: {
    requestedOn: (p: { when: string; schemaVersion: number }) =>
      `Requested ${p.when} · format v${p.schemaVersion}`,
    exportAllowance: (p: { nextAllowed: string | null }) =>
      p.nextAllowed
        ? `One export a week; ready exports expire after seven days. You can request another on ${p.nextAllowed}.`
        : "One export a week; ready exports expire after seven days.",
    couldNotLoadYourDataExports: "Could not load your data exports.",
    couldNotRequestYourDataExport: "Could not request your data export.",
    yourData: "Your data",
    downloadPrivateJsonCopyYourAccount: "Download a private JSON copy of your account and gameplay data. Other players’ profiles and messages are not included.",
    dataExports: "Data exports",
    loadingExports: "Loading exports…",
    youHaveNotRequestedExportYet: "You have not requested an export yet.",
    download: "Download",
    close: "Close",
    requesting: "Requesting…",
    requestExport: "Request export",
  },

  accountMenu: {
    noPasskeyWasUsed: "No passkey was used. You can sign in with your password instead.",
    signedInWithRequests: (p: { name: string; waiting: number }) =>
      `Signed in as ${p.name}. ${counted(p.waiting, {
        one: "friend request",
        other: "friend requests",
      })} waiting.`,
    friends: "Friends",
    finishYourRole: (p: { role: "admin" | "moderator" }) =>
      `Finish your ${p.role === "admin" ? "administrator" : "moderator"} role`,
    agreeToRules: "By creating an account you agree to follow the {rules}.",
    reportBug: "Report a bug",
    account: "Account",
    settings: "Settings",
    myProfile: "My profile",
    promptStats: "Prompt stats",
    createAccount: "Create account",
    logIn: "Log in",
    myPromptLists: "My prompt lists",
    rules: "Rules",
    logOut: "Log out",
    thatDoesNotLookLikeEmail: "That does not look like an email address.",
    somethingWentWrongPleaseTryAgain: "Something went wrong. Please try again.",
    thatPasskeyWasNotAccepted: "That passkey was not accepted.",
    thisAccountSignsWithPasskey: "This account signs in with a passkey.",
    or: "or",
    username: "Username",
    password: "Password",
    codeFromYourAuthenticatorApp: "Code from your authenticator app",
    recoveryCodeWorksHereTooCan: "A recovery code works here too, and can be used once.",
    email: "Email",
    optional: "optional",
    letsYouResetYourPasswordLater: "Lets you reset your password later. Used for nothing else.",
    rules2: "rules",
    forgotYourPassword: "Forgot your password?",
    notNow: "Not now",
    createYourAccount: "Create your account",
    createAnAccountToKeep:
      (p: { suggestedUsername: string }) => `Create an account to keep ${p.suggestedUsername} as your username and save your stats on every device.`,
    keepYourUsernameAndYour: "Keep your username and your stats on every device.",
    waitingForYourDevice: "Waiting for your device…",
    signInWithAPasskey: "Sign in with a passkey",
    pleaseWait: "Please wait…",
    alreadyRegistered: "Already registered? ",
    newHere: "New here? ",
    createAnAccount: "Create an account",
    guestIdentity: (p: { name: string }) => `${p.name}. Your display name is not saved.`,
    signedInAs: (p: { name: string }) => `Signed in as ${p.name}`,
  },

  accountRecoveryPage: {
    thatConfirmationLinkCouldNotBe: "That confirmation link could not be used.",
    somethingWentWrongPleaseTryAgain: "Something went wrong. Please try again.",
    evenBestGuessersForgetSometimes: "Even the best guessers forget sometimes.",
    weRsquoLlSendSecureTime: "We&rsquo;ll send a secure, time-limited link to the confirmed email\n            on your account.",
    accountHelp: "Account help",
    backLobby: "Back to the lobby",
    enterYourUsernameYourConfirmedEmail: "Enter your username or your confirmed email address. If the\n              account can be recovered, a link is on its way.",
    usernameEmail: "Username or email",
    thatResetLinkHasExpiredHas: "That reset link has expired or has already been used. Reset links\n              work once and last an hour.",
    sendNewOne: "Send a new one",
    checkingThatLink: "Checking that link…",
    everySignedDeviceWillBeSigned: "Every signed-in device will be signed out, including any you did\n              not recognise.",
    newPassword: "New password",
    addressIsConfirmedYouCan:
      (p: { address: string }) => `${p.address} is confirmed. You can now recover this account.`,
    yourPasswordIsSetAnd: "Your password is set and you are signed in again.",
    resetYourPassword: "Reset your password",
    thatLinkNoLongerWorks: "That link no longer works",
    chooseANewPassword: "Choose a new password",
    confirmingYourEmail: "Confirming your email",
    pleaseWait: "Please wait…",
    sendAResetLink: "Send a reset link",
    setPassword: "Set password",
    oneMoment: "One moment…",
    nothingToConfirm: "Nothing to confirm.",
    resetLinkOnItsWay:
      "If that account exists and has a confirmed email address, a reset link is on its way.",
  },

  activeGameRoom: {
    leaveGame: "Leave game",
    markedAfkByRoomVote: "You were marked AFK by room vote.",
    inviteLinkCopied: "Invite link copied.",
    couldnTCopyLinkCopyFrom: "Couldn’t copy the link. Copy it from the address bar.",
    couldNotStartGamePleaseTry: "Could not start the game. Please try again.",
    couldNotStartRestartVote: "Could not start a restart vote.",
    couldNotRecordYourRestartVote: "Could not record your restart vote.",
    copyRoomInviteLink: "Copy the room invite link",
    clickCopyRoomInviteLink: "Click to copy room invite link",
    roomMenu: "Room menu",
    afk: "AFK",
    saveImage: "Save image",
    saveDrawnImageFile: "Save drawn image to file",
    playerSettings: "Player settings",
    leaveRoom: "Leave room",
    leave: "Leave",
    players: "Players",
    youWereKickedFromThe: "You were kicked from the room.",
    thisRoomWasOpenedIn: "This room was opened in another tab.",
    startTheGame: "start the game",
    startARestartVote: "start a restart vote",
    recordYourRestartVote: "record your restart vote",
    leaveDuringYourTurn: "Leave during your turn?",
    leaveActiveGame: "Leave active game?",
    youReTheCurrentDrawer:
      "You’re the current drawer. Leaving now will interrupt your turn and advance the game for everyone.",
    theGameIsStillIn:
      "The game is still in progress. You’ll leave the room and give up your place in this game.",
    restartVoteAvailableInRestartCooldownSeconds:
      (p: { restartCooldownSeconds: number }) => `Restart vote available in ${p.restartCooldownSeconds} seconds`,
    proposeRestartingTheGame: "Propose restarting the game",
    restartVoteAvailableInRestartCooldownSeconds2:
      (p: { restartCooldownSeconds: number }) => `Restart vote available in ${p.restartCooldownSeconds}s`,
    proposeAVoteToRestart: "Propose a vote to restart the game",
    backFromAfk: "Back from AFK",
    goAfk: "Go AFK",
    closePlayers: "Close players",
    acceptTheColorSuggestion: "accept the color suggestion",
    dismissTheColorSuggestion: "dismiss the color suggestion",
    couldNotAcceptSuggestion: "Could not accept the color suggestion.",
    couldNotDismissSuggestion: "Could not dismiss the color suggestion.",
  },

  addEmailDialog: {
    followTheLink: (p: { address: string; replacing: boolean }) =>
      `Follow the link sent to ${p.address}. Until you do, the address is not attached to your account and cannot be used to recover it${
        p.replacing ? ", and the one you had stays in place." : "."
      }`,
    thatDoesNotLookLikeEmail: "That does not look like an email address.",
    somethingWentWrongPleaseTryAgain: "Something went wrong. Please try again.",
    done: "Done",
    usedOnlyResetYourPasswordTell: "Used only to reset your password and to tell you if your account\n              or something you shared is actioned. Nothing else is ever sent\n              here.",
    checkYourInbox: "Check your inbox",
    changeYourEmailAddress: "Change your email address",
    addAnEmailAddress: "Add an email address",
    newEmail: "New email",
    email: "Email",
    pleaseWait: "Please wait…",
    sendConfirmation: "Send confirmation",
    close: "Close",
    notNow: "Not now",
  },

  afkCheckDialog: {
    secondsUnit: (p: { count: number }) =>
      plural(p.count, { one: "second", other: "seconds" }),
    stillThere: "Still there?",
    youHaveBeenQuietWhileAnswer: "You have been quiet for a while. Answer and you keep playing;\n          otherwise the room will mark you AFK and carry on without you.",
    stillTherePressButtonMoveMouse: "Still there? Press the button, or move the mouse, to keep playing.",
    iMHere: "I’m here",
  },

  app: {
    serverUpdateInProgress: (p: { seconds: number }) =>
      p.seconds > 0
        ? `Server update in progress. No new rooms or games can start; a current game has ${counted(p.seconds, { one: "second", other: "seconds" })} to finish.`
        : "Server update in progress. No new rooms or games can start; any game still running is ending now.",
    thisTabOutDateCannotPlay: "This tab is out of date and cannot play until it is reloaded.",
    reload: "Reload",
    newRoomsArePausedMaintenanceGames: "New rooms are paused for maintenance. Games already running carry on\n          as normal.",
    serverWasUpdatedBackAnyGame: "The server was updated and is back. Any game in progress ended.",
    dismiss: "Dismiss",
  },

  appHeader: {
    playerSettings: "Player settings",
  },

  bugReportDialog: {
    connectionSummary: (p: { connected: boolean; reconnects: number }) =>
      `${p.connected ? "connected" : "offline"} · ${counted(p.reconnects, {
        one: "reconnect",
        other: "reconnects",
      })} this visit`,
    couldNotTakeScreenshot: "Could not take the screenshot.",
    thanksYourReportWithPeopleWho: "Thanks — your report is with the people who run Sketchy.",
    couldNotSendReport: "Could not send the report.",
    reportBug: "Report a bug",
    somethingBrokenNotSomethingSomeoneSaid: "Something broken, not something someone said. This reaches the people who run Sketchy — never other players.",
    where: "Where",
    howBad: "How bad",
    oneLineSummary: "One line summary",
    whatWentWrongOneLine: "What went wrong, in one line",
    whatHappened: "What happened",
    whatYouDidWhatYouExpected: "What you did, what you expected, what happened instead.",
    screenshot: "Screenshot",
    optional: "Optional",
    screenshotThatWillBeSentWith: "The screenshot that will be sent with this report",
    thisDialogHidesItselfWhileShot: "This dialog hides itself while the shot is taken, so you get the page behind it. Look at it before you send — you chose what to share.",
    replace: "Replace",
    remove: "Remove",
    opensYourBrowserSOwnPicker: "Opens your browser's own picker — choose this tab. This dialog hides itself while the shot is taken, so you get the page behind it.",
    recentClientErrors: "Recent client errors",
    sendMyDescriptionOnly: "Send my description only",
    dropsDetailsAboveAnyScreenshotWe: "Drops the details above and any screenshot. We will still read it, but the bug is much harder to reproduce.",
    cancel: "Cancel",
    build: "Build",
    page: "Page",
    room: "Room",
    screen: "Screen",
    browser: "Browser",
    connection: "Connection",
    waitingForThePicker: "Waiting for the picker…",
    attachAScreenshot: "Attach a screenshot",
    whatWeAreLeavingOut: "What we are leaving out",
    whatWeSendWithThis: "What we send with this",
    noneOfThisIsBeing: "None of this is being sent — only your description above.",
    theLast20ErrorsYour:
      "The last 20 errors your browser recorded. No page addresses beyond the path, nothing you typed into chat, and never the prompt in play.",
    sending: "Sending…",
    sendReport: "Send report",
  },

  changePasswordDialog: {
    forgottenTheCurrentOne: "Forgotten the current one?",
    twoNewPasswordsDoNotMatch: "The two new passwords do not match.",
    passwordChangedEveryOtherDeviceHas: "Password changed. Every other device has been signed out.",
    couldNotChangePasswordPleaseTry: "Could not change the password. Please try again.",
    ifThatAccountHasVerifiedEmail: "If that account has a verified email address, a link to set a new\n              password is on its way. It works once, and it expires.",
    done: "Done",
    everyDeviceSignsOutWhenPassword: "Every device signs out when the password changes, including any you\n              did not mean to leave signed in. This one stays.",
    currentPassword: "Current password",
    newPassword: "New password",
    newPasswordAgain: "New password again",
    emailMeLinkInstead: "Email me a link instead",
    checkYourInbox: "Check your inbox",
    changeYourPassword: "Change your password",
    pleaseWait: "Please wait…",
    changePassword: "Change password",
    close: "Close",
    cancel: "Cancel",
  },

  choosingPromptOverlay: {
    isChoosingPrompt: "{drawer} is choosing a prompt…",
    nextTurn: "Next turn",
    drawingWillBeginAsSoonAs: "Drawing will begin as soon as they choose.",
  },

  colorblindSafeSuggestionBanner: {
    colorblindSafeColorSuggestion: "Colorblind-safe color suggestion",
    playerThisRoomPlaysWithColorblind: "A player in this room plays with colorblind-safe colors.",
    switchRoomPaletteFutureDrawings: "Switch the room palette for future drawings?",
    switchColors: "Switch colors",
    notNow: "Not now",
  },

  confirmationDialog: {
    cancel: "Cancel",
  },

  crashPage: {
    couldNotSendReport: "Could not send the report.",
    bugCrawledOntoPage: "A bug crawled onto the page",
    helpUsSquash: "Help us squash it",
    reportReadySendErrorWhatThis: "A report is ready to send: the error, and what this tab knows about itself.\n            It reaches the people who run Sketchy — never other players.",
    whatWereYouDoing: "What were you doing?",
    optional: "Optional",
    lastThingYouClickedTypedIf: "The last thing you clicked or typed, if you remember.",
    recentClientErrorsNewestFirst: "Recent client errors, newest first",
    sendMyDescriptionOnly: "Send my description only",
    dropsDetailsAboveWeWillStill: "Drops the details above. We will still read it, but the crash is much harder to find.",
    thanksYourReportWithPeopleWho: "Thanks — your report is with the people who run Sketchy.",
    reload: "Reload",
    backLobby: "Back to lobby",
    summary: "Summary",
    build: "Build",
    page: "Page",
    room: "Room",
    screen: "Screen",
    browser: "Browser",
    connection: "Connection",
    thisRoomSScreenHit:
      "This room’s screen hit an error and had to stop. Your seat is held for a moment: send the report below, then reload to pick it back up or go back to the lobby.",
    thisScreenHitAnError:
      "This screen hit an error and had to stop. Your account and settings are safe. Send the report below, and you’ll be on your way.",
    whatWeAreLeavingOut: "What we are leaving out",
    whatWeSendWithThis: "What we send with this",
    noneOfThisIsBeing: "None of this is being sent — only your description above.",
    theCrashTheLast20:
      "The crash, the last 20 errors your browser recorded, and where in the page it happened. No page addresses beyond the path, nothing you typed into chat, and never the prompt in play.",
    sendingAgain: "Sending again…",
    sending: "Sending…",
    trySendingAgain: "Try sending again",
    sendReport: "Send report",
  },

  createRoomPage: {
    setupTiming: "This setup runs {full} with a full room of {capacity}",
    setupTimingFull: (p: { minutes: number }) =>
      `about ${counted(p.minutes, { one: "minute", other: "minutes" })}`,
    setupTimingHalf: (p: { players: number }) => ` — closer to {half} if ${p.players} join`,
    couldNotLoadYourRoomPresets: "Could not load your room presets.",
    couldNotApplyThatPreset: "Could not apply that preset.",
    enterNameRoomPreset: "Enter a name for the room preset.",
    couldNotSaveThatPreset: "Could not save that preset.",
    couldNotUpdateThatPreset: "Could not update that preset.",
    couldNotDeleteThatPreset: "Could not delete that preset.",
    fixCustomPromptEntriesMarkedAbove: "Fix the custom-prompt entries marked above before creating the room.",
    failedCreateRoom: "Failed to create room",
    roomSetup: "Room setup",
    createRoom: "Create a room",
    startFromSavedPreset: "Start from a saved preset",
    startFromPreset: "Start from a preset…",
    nameThisPreset: "Name this preset",
    save: "Save",
    cancel: "Cancel",
    saveAsPreset: "Save as preset",
    update: "Update",
    delete: "Delete",
    undo: "Undo",
    saveAsReusableList: "Save as reusable list",
    saveQuickPromptsAsA:
      "Save quick prompts as a list, and remove shared codes, before storing a preset.",
    appliedName: (p: { name: string }) => `Applied “${p.name}”.`,
    savedName: (p: { name: string }) => `Saved “${p.name}”.`,
    updatedName: (p: { name: string }) => `Updated “${p.name}”.`,
    deleteThisRoomSettingPreset: "Delete this room-setting preset?",
    createTheRoom: "create the room",
    noScoring: "No scoring",
    public: "Public",
    private: "Private",
    backToLobby: "Back to lobby",
    leaveBlankForARandom: "Leave blank for a random name!",
    creating: "Creating…",
    createRoom2: "Create room",
  },

  customPromptsEditor: {
    usableCount: (p: { count: number }) =>
      counted(p.count, { one: "usable custom prompt", other: "usable custom prompts" }),
    duplicatesIgnored: (p: { count: number }) =>
      `${counted(p.count, { one: "duplicate", other: "duplicates" })} ignored`,
    entriesTooLong: (p: { count: number; limit: number }) =>
      `${counted(p.count, { one: "entry is", other: "entries are" })} over ${number(p.limit)} characters`,
    entryLimit: (p: { limit: number }) => `Only ${number(p.limit)} entries are allowed`,
    customPromptsOptional: "Custom prompts (optional)",
    onePromptPerLineSeparateEntries: "One prompt per line\nor separate entries with commas",
    shortenRemoveOverlongEntriesBeforeCreating: "Shorten or remove overlong entries before creating the room.",
  },

  customPromptsPreview: {
    resultsMatching: (p: { shown: number; total: number }) =>
      `${number(p.shown)} of ${number(p.total)} prompts match`,
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "prompt", other: "prompts" }),
    customPromptCount: (p: { count: number }) =>
      counted(p.count, { one: "custom prompt", other: "custom prompts" }),
    inspectPrompts: (p: { count: number }) =>
      `Inspect ${counted(p.count, { one: "custom prompt", other: "custom prompts" })}`,
    couldNotLoadCustomPrompts: "Could not load the custom prompts",
    loadingCustomPrompts: "Loading custom prompts…",
    roomPromptCollection: "Room prompt collection",
    readOnlyListSuppliedByRoom: "Read-only list supplied by the room host.",
    findPrompt: "Find a prompt",
    searchCustomPrompts: "Search custom prompts…",
    filterPromptsByLength: "Filter prompts by length",
    noCustomPromptsMatchTheseFilters: "No custom prompts match these filters.",
    all: "All",
    allPromptLengths: "All prompt lengths",
    short: "Short",
    n5CharactersOrFewer: "5 characters or fewer",
    medium: "Medium",
    n6To10Characters: "6 to 10 characters",
    long: "Long",
    n11CharactersOrMore: "11 characters or more",
    loadTheCustomPrompts: "load the custom prompts",
  },

  deleteAccountDialog: {
    whatIsRemoved: (p: { isGuest: boolean }) =>
      `${
        p.isGuest
          ? "The name, the points and the history kept against this browser are removed."
          : "Your name is removed from the games you played."
      } The scores and drawings stay, under “Deleted player”, because they are other people’s games too. This cannot be undone.`,
    typeToConfirm: (p: { word: string }) => `Type ${p.word} to confirm`,
    couldNotDeleteAccount: "Could not delete the account.",
    password: "Password",
    deleteThisGuest: "Delete this guest",
    deleteYourAccount: "Delete your account",
    deleting: "Deleting…",
    deleteForGood: "Delete for good",
    keepPlaying: "Keep playing",
    keepMyAccount: "Keep my account",
  },

  drawingReactionControl: {
    reactionSummary: (p: { total: number; chips: string }) =>
      `${counted(p.total, { one: "reaction", other: "reactions" })}: ${p.chips}`,
    thatReactionCouldNotBeSent: "That reaction could not be sent.",
    reactThisDrawing: "React to this drawing",
    reactions: "Reactions",
    createAccountReact: "Create an account to react.",
    createAccount: "Create account",
    noReactionsYet: "No reactions yet",
    reactToThisDrawingSummary: (p: { summary: string }) => `React to this drawing. ${p.summary}`,
    labelYourReactionPressTo:
      (p: { label: string }) => `${p.label}, your reaction. Press to remove it`,
  },

  drawingRecapGallery: {
    drawingLabel: (p: { prompt: string; drawer: string }) =>
      `Drawing of ${p.prompt} by ${p.drawer}`,
    drawnBy: "Drawn by {drawer} · Round {round} · Turn {turn}",
    position: (p: { position: number; total: number }) => `${p.position} of ${p.total}`,
    thisDrawingCouldNotBeDecoded: "This drawing could not be decoded.",
    drawingRecap: "Drawing recap",
    saveImage: "Save image",
    close: "Close",
    thisDrawingWasNotKept: "This drawing was not kept.",
    roomRanOutRoomLaterTurns: "The room ran out of room for it. Later turns were kept instead.",
    tryAgain: "Try again",
    loadingDrawing: "Loading drawing…",
    noDrawingWasCapturedThisTurn: "No drawing was captured for this turn.",
    drawingRecapNavigation: "Drawing recap navigation",
    previous: "Previous",
    next: "Next",
    loadThisDrawing: "load this drawing",
  },

  emailRecoveryReminder: {
    addEmail: "Add an email",
    dismiss: "Dismiss",
    confirmPendingAddressToFinishSetting:
      (p: { pendingAddress: string }) => `Confirm ${p.pendingAddress} to finish setting up account recovery.`,
    thisAccountHasNoEmail:
      "This account has no email address, so a forgotten password cannot be reset.",
  },

  firstRunIdentity: {
    couldNotSaveThatNamePlease: "Could not save that name. Please try again.",
    keepYourUsernameYourStatsEvery: "Keep your username and your stats on every device.",
    createAccount: "Create an account",
    logIn: "Log in",
    or: "or",
    displayName: "Display name",
    beenHereBefore: "Been here before?",
    playAsYourself: "Play as yourself",
    whatShouldWeCallYou: "What should we call you?",
    justPlayingOncePickA: "Just playing once? Pick a display name",
    play: "Play",
    playAsGuest: "Play as guest",
  },

  friendButton: {
    requestSentTo: (p: { name: string }) => `Friend request sent to ${p.name}`,
    addFriend: "Add friend",
    acceptRequest: "Accept request",
    requestSent: "Request sent",
  },

  friendInviteNotice: {
    couldNotJoinThatGame: "That game could not be joined.",
    thatGameCouldNotBeJoined: "That game could not be joined.",
    invitedYouTheirGame: "invited you to their game.",
    join: "Join",
    dismissInvitation: "Dismiss invitation",
  },

  friendsOverlay: {
    declineWarning: (p: { name: string }) =>
      `${p.name} will not be able to ask again. You can still send them a request yourself later.`,
    decline2: "Decline",
    youWillBothStopBeingAble: "You will both stop being able to join each other's games without an invitation. Either of you can ask again.",
    remove2: "Remove",
    removeConfirm: (p: { name: string }) => `Remove ${p.name}?`,
    friends: "Friends",
    close: "Close",
    closeFriends: "Close friends",
    friendsNeedAccountGuestNameBelongs: "Friends need an account. A guest name belongs to this browser\n              rather than to you, so there would be nobody left to be friends\n              with a month from now.",
    loading: "Loading…",
    noFriendsYetAddSomebodyFrom: "No friends yet. Add somebody from the lobby, or from a game you\n              are both in.",
    requests: "Requests",
    accept: "Accept",
    decline: "Decline",
    sent: "Sent",
    cancel: "Cancel",
    remove: "Remove",
    declineThisRequest: "Decline this request?",
    recentlyPlayedWith: "Recently played with",
  },

  gameEndOverlay: {
    continueLabel: "Continue",
    youFinished: (p: { points: number }) =>
      `You finished {place} with ${counted(p.points, { one: "point", other: "points" })}.`,
    continueToWaitingRoom: "Continue to waiting room",
    continueWithCountdown: (p: { seconds: number }) =>
      `Continue to waiting room, ${counted(p.seconds, { one: "second", other: "seconds" })} left`,
    gameOver: "Game over",
    you: "you",
    friend: "Friend",
    noScoresThisTimeJustRoom: "No scores this time—just a room full of sketches and guesses.",
    keep: "Keep",
    asYourUsername: "as your username",
    createAccount: "Create account",
    highlights: "Highlights",
    drawings: "Drawings",
    stayHere: "Stay here",
    aGreatGameOfDrawing: "A great game of drawing",
    theRoomTakesTheCrown: "The room takes the crown!",
    winnersCountPlayersShareTheCrown:
      (p: { winnersCount: number }) => `${p.winnersCount} players share the crown!`,
    takesTheCrown: " takes the crown!",
    shareTheCrown: " share the crown!",
  },

  gameHighlightsPanel: {
    lastGame: "Last game",
    highlights: "Highlights",
    closeHighlights: "Close highlights",
    thatGameWasTooShortSay: "That game was too short to say much about. Play a longer one and the\n            highlights will show up here.",
    seeIt: "See it",
    back: "Back",
  },

  inviteEntryPage: {
    roomCode: (p: { code: string }) => `Room ${p.code}`,
    hereCount: (p: { here: number; capacity: number; full: boolean }) =>
      `${p.here}/${p.capacity} here${p.full ? " · full" : ""}`,
    roomSummary: (p: { rounds: number; seconds: number; hintMode: string }) =>
      `${counted(p.rounds, { one: "round", other: "rounds" })} · ${p.seconds}s · ${p.hintMode}`,
    checkingYourInvite: "Checking your invite…",
    loadingRoomDetails: "Loading room details.",
    roomUnavailable: "Room unavailable",
    backLobby: "Back to lobby",
    players: "Players",
    rounds: "Rounds",
    drawTime: "Draw time",
    scoring: "Scoring",
    roomRules: "Room rules",
    thisGameAlreadyProgressJoiningAs: "This game is already in progress. Joining as a player adds you to a future turn.",
    playerSlotsAreFullSpectatingStill: "Player slots are full. Spectating is still open.",
    promptDetailsHidden: "Prompt details hidden",
    timedHints: "Timed hints",
    buyableLetterHints: "Buyable letter hints",
    wheelOfFortune: "Wheel of Fortune",
    noLetterHints: "No letter hints",
    publicRoom: "Public room",
    privateInvite: "Private invite",
    inProgress: "In progress",
    waiting: "Waiting",
    full: " · Full",
    noScoring: "No scoring",
    pressure: "Pressure",
    default: "Default",
    everyToolAndColor: "Every tool and color",
    spectatorsCanSeeThePrompt: "Spectators can see the prompt",
    spectatorsGuessAlong: "Spectators guess along",
    defaultPromptList: "Default prompt list",
    roomFull: "Room full",
    joining: "Joining…",
    joinGameInProgress: "Join game in progress",
    joinGame: "Join game",
    spectate: "Spectate",
    customPromptsOnly: (p: { count: number }) =>
      `${counted(p.count, { one: "custom prompt", other: "custom prompts" })} only`,
    customPromptsPlusDefaults: (p: { count: number }) =>
      `${counted(p.count, { one: "custom prompt", other: "custom prompts" })} plus defaults`,
  },

  inviteFriendsList: {
    invitationCouldNotBeSent: "That invitation could not be sent.",
    invitationSent: (p: { name: string }) => `Invitation sent to ${p.name}.`,
    thatInvitationCouldNotBeSent: "That invitation could not be sent.",
    friendsLobby: "Friends in the lobby",
    invited: "Invited",
    invite: "Invite",
  },

  languagePicker: {
    currentChoice: (p: { label: string; value: string }) => `${p.label}: ${p.value}`,
    everyLanguage: "Every language",
  },

  lobbyBrowserPage: {
    filterByLanguage: "Filter by language",
    filtersWithCount: (p: { count: number }) =>
      p.count > 0 ? `Filters · ${p.count}` : "Filters",
    showRooms: (p: { count: number }) =>
      `Show ${counted(p.count, { one: "room", other: "rooms" })}`,
    removedFromRoom: "Removed from room",
    ok: "OK",
    roomCode: "Room code",
    abc123: "ABC123",
    thereNoRoomCodeClipboard: "There is no room code on the clipboard.",
    sketchyCouldNotReadClipboardPaste: "Sketchy could not read the clipboard. Paste into the boxes instead.",
    pleaseEnterRoomCode: "Please enter a room code",
    failedJoinRoom: "Failed to join room",
    joinByCode: "Join by code",
    createRoom: "Create room",
    publicRooms: "Public rooms",
    searchRoomsByNameCode: "Search rooms by name or code",
    hideFull: "Hide full",
    hideProgress: "Hide in progress",
    filters: "Filters",
    clearFilters: "Clear filters",
    language: "Language",
    hideFullRooms: "Hide full rooms",
    hideGamesProgress: "Hide games in progress",
    loadingPublicRooms: "Loading public rooms…",
    noPublicRoomsYetCreateOne: "No public rooms yet. Create one!",
    noPublicRoomsMatchYourSearch: "No public rooms match your search criteria.",
    createRoom2: "Create a room",
    joinWithCode: "Join with a code",
    paste: "Paste",
    couldNotSaveThatName: "Could not save that name. Please try again.",
    joinAsASpectator: "join as a spectator",
    joinTheRoom: "join the room",
    loading: "Loading…",
    showingFilteredRoomsCountOfRoomsCount:
      (p: { filteredRoomsCount: number; roomsCount: number }) => `Showing ${p.filteredRoomsCount} of ${p.roomsCount}`,
    n0Rooms: "0 rooms",
    close: "Close",
    joining: "Joining…",
    joinTheRoom2: "Join the room",
    joiningAsSpectator: "Joining as spectator…",
    watchWithoutPlaying: "Watch without playing",
  },

  lobbyChatPanel: {
    reportThisLine: (p: { name: string }) => `Report this line by ${p.name}`,
    couldNotSendThat: "Could not send that.",
    chat: "Chat",
    lobbyChat: "Lobby chat",
    nobodyHasSaidAnythingYet: "Nobody has said anything yet.",
    chooseNameChat: "Choose a name to chat",
    saySomethingLobby: "Say something to the lobby...",
    lobbyChatMessage: "Lobby chat message",
    send: "Send",
    couldNotSaveThatName: "Could not save that name. Please try again.",
    sendTheMessage: "send the message",
  },

  lobbyPlayerMenu: {
    whatToDoAbout: (p: { name: string }) => `What to do about ${p.name}`,
    openPlayerProfile: "Open player profile",
    addAsFriend: "Add as friend",
    report: "Report",
  },

  myPromptListsPage: {
    listSummary: (p: { prompts: number; visibility: string; moderationState: string | null }) =>
      `${counted(p.prompts, { one: "prompt", other: "prompts" })} · ${p.visibility}${
        p.moderationState ? ` · ${p.moderationState}` : ""
      }`,
    listUnderReview: (p: { state: string }) =>
      `This list is ${p.state} and cannot be used in new games. Editing does not automatically restore it; a moderator must review the list.`,
    needsReview: (p: { count: number }) => `Needs review (${p.count})`,
    removePrompt: (p: { prompt: string }) => `Remove ${p.prompt}`,
    couldNotLoadYourPromptLists: "Could not load your prompt lists.",
    couldNotOpenThatPromptList: "Could not open that prompt list.",
    addAtLeastOnePromptBefore: "Add at least one prompt before saving.",
    couldNotSaveThisPromptList: "Could not save this prompt list.",
    couldNotDeleteThisPromptList: "Could not delete this prompt list.",
    yourLibrary: "Your library",
    reusablePromptLists: "Reusable prompt lists",
    newList: "New list",
    createAccountSaveReviseSharePrompt: "Create an account to save, revise, and share prompt lists. Quick room prompts stay local and ephemeral.",
    yourPromptLists: "Your prompt lists",
    loading: "Loading…",
    noSavedListsYet: "No saved lists yet.",
    name: "Name",
    description: "Description",
    language: "Language",
    visibility: "Visibility",
    private: "Private",
    anyoneWithCode: "Anyone with code",
    shareCode: "Share code",
    couldNotCopyShareCode: "Could not copy the share code.",
    copy: "Copy",
    addPrompts: "Add prompts",
    onePromptPerLineSeparateEntries: "One prompt per line\nor separate entries with commas",
    addList: "Add to list",
    noPromptsYetPasteSomeAbove: "No prompts yet. Paste some above to get started.",
    thisList: "In this list",
    searchPrompts: "Search prompts",
    nothingMatchesThatSearch: "Nothing matches that search.",
    deleteList: "Delete list…",
    promptListSaved: "Prompt list saved.",
    deleteThisPromptListAnd: "Delete this prompt list and all of its revisions?",
    promptListDeleted: "Prompt list deleted.",
    backToLobby: "Back to lobby",
    promptsCountOfMaxListPrompts:
      (p: { promptsCount: number; MAX_LIST_PROMPTS: number }) => `${p.promptsCount} of ${p.MAX_LIST_PROMPTS} prompts in this list`,
    saving: "Saving…",
    saveList: "Save list",
  },

  notFoundPage: {
    nobodyDrewThisPage: "Nobody drew this page",
    thatLinkDoesnTLeadAnywhere: "That link doesn’t lead anywhere on Sketchy.",
    backLobby: "Back to lobby",
  },

  onlinePlayersPanel: {
    couldNotJoinThatGame: "Could not join that game.",
    whoOnline: "Who is online",
    nobodyElseHereRightNow: "Nobody else is here right now.",
    friend: "Friend",
    join: "Join",
    inAGame: "In a game",
    inTheLobby: "In the lobby",
  },

  pictureCropDialog: {
    fileNotAPicture: "That file could not be read as a picture.",
    couldNotSetThatPicturePlease: "Could not set that picture. Please try again.",
    frameYourPicture: "Frame your picture",
    dragMoveZoomGetCloserCircle: "Drag to move it and zoom to get closer. The circle is what everyone sees.",
    pictureFramedArrowKeysMovePlus: "The picture, framed. Arrow keys move it; plus and minus zoom.",
    zoom: "Zoom",
    cancel: "Cancel",
    uploading: "Uploading…",
    usePicture: "Use picture",
  },

  playerList: {
    requestCouldNotBeSent: "That request could not be sent.",
    nowFriends: (p: { name: string }) => `You and ${p.name} are now friends.`,
    friendRequestSent: (p: { name: string }) => `Friend request sent to ${p.name}.`,
    nothingToDoAbout: (p: { name: string }) => `Nothing to do about ${p.name} right now.`,
    rank: (p: { rank: number }) => `Rank ${p.rank}`,
    moderationFor: (p: { name: string }) => `Moderation for ${p.name}`,
    moderationActionsFor: (p: { name: string }) => `Moderation actions for ${p.name}`,
    thatRequestCouldNotBeSent: "That request could not be sent.",
    drawing: "Drawing",
    gotIt: "Got it ·",
    afk: "AFK",
    you: "(you)",
    host: "Host",
    friend: "Friend",
    disconnected: "Disconnected",
    kick: "Kick",
    addFriend: "Add friend",
    sendRequest: "Send a request",
    report: "Report",
    toAModerator: "To a moderator",
    voteAfkOrKickOr: "Vote AFK or kick, or report",
    reportThisPlayer: "Report this player",
    undoVote: "Undo vote",
    vote: "Vote",
    voteKindAfk: "AFK",
    voteKindKick: "Kick",
    undoVoteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Undo ${p.kind} vote for ${p.nickname}, ${p.count} of ${p.required}`,
    voteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Vote ${p.kind} for ${p.nickname}, ${p.count} of ${p.required}`,
    votesFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `${p.kind} votes for ${p.nickname}, ${p.count} of ${p.required}`,
    votesForIncludingYours: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `${p.kind} votes for ${p.nickname}, ${p.count} of ${p.required}, including yours`,
  },

  profilePage: {
    gamesPlayed: "Games played",
    gamesWon: "Games won",
    winRate: "Win rate",
    averageScore: "Average score",
    turnsPlayed: "Turns played",
    promptsGuessed: "Prompts guessed",
    drawingsMade: "Drawings made",
    reactionsReceived: "Reactions received",
    totalScore: "Total score",
    noSuchProfile: "There is no player with that profile.",
    couldNotLoadProfile: "Could not load this profile. Please try again.",
    gameMeta: (p: { finishedAt: string; rounds: number; players: number }) =>
      `${p.finishedAt} · ${counted(p.rounds, { one: "round", other: "rounds" })} · ${counted(p.players, { one: "player", other: "players" })}`,
    seatScore: (p: { points: number }) => `${number(p.points)} pts`,
    gameRules: (p: {
      scoringMode: string;
      scoringVersion: number;
      hintMode: string;
      seconds: number;
      promptSource: string;
    }) =>
      `Rules: ${p.scoringMode} scoring${
        p.scoringVersion > 0 ? ` v${p.scoringVersion}` : " (legacy version unknown)"
      } · ${p.hintMode} hints · ${p.seconds} seconds · ${p.promptSource} prompts`,
    reportPlayer: (p: { name: string }) => `Report ${p.name}`,
    privateRoom: "private room",
    thisGameDidNotFinishSo: "This game did not finish, so these are the scores as they stood\n              when it stopped rather than a final placing.",
    loadingTurns: "Loading turns…",
    turnByTurn: "Turn by turn",
    round: "Round",
    prompt: "Prompt",
    drawnBy: "Drawn by",
    time: "Time",
    drawing: "Drawing",
    reactions: "Reactions",
    guesserOutcomes: "Guesser outcomes",
    view: "View",
    couldNotLoadMoreGames: "Could not load more games.",
    loading: "Loading…",
    friend: "Friend.",
    claimYourAccount: "Claim your account",
    yourGamesAreAlreadyBeingRecorded: "Your games are already being recorded under this display name.\n                Create an account to keep them and use it as your username on every device.",
    createAccount: "Create account",
    statistics: "Statistics",
    gameHistory: "Game history",
    includeGamesThatFellApart: "Include games that fell apart",
    notKept: "not kept",
    nothingDrawn: "nothing drawn",
    onlyThePlayersInThis: "Only the players in this game can see its turns.",
    couldNotLoadTheTurns: "Could not load the turns for this game.",
    cutShort: "cut short",
    noAttempt: "no attempt",
    joinedLate: "joined late",
    notEligibleEligibilityReason:
      (p: { eligibilityReason: string }) => `not eligible (${p.eligibilityReason})`,
    unknownPlayer: "Unknown player",
    backToLobby: "Back to lobby",
    guestDisplayNameNotSaved: "Guest — display name not saved",
    registeredPlayer: "Registered player",
    noFinishedGamesYetPlay: "No finished games yet. Play one and it will show up here.",
    noGamesToShowGames:
      "No games to show. Games from private rooms are listed only for the players who were in them.",
    loadHistoryPageSizeMore:
      (p: { HISTORY_PAGE_SIZE: number }) => `Load ${p.HISTORY_PAGE_SIZE} more`,
  },

  promptContentReportDialog: {
    reportList: (p: { name: string }) => `Report ${p.name}`,
    couldNotSendReport: "Could not send the report.",
    reportsAreReviewedAfterSubmissionList: "Reports are reviewed after submission. The list stays available unless a moderator hides it.",
    content: "Content",
    entireList: "Entire list",
    reason: "Reason",
    whatShouldModeratorKnow: "What should the moderator know?",
    cancel: "Cancel",
    inappropriateContent: "Inappropriate content",
    hatefulOrAbusiveContent: "Hateful or abusive content",
    sexualContent: "Sexual content",
    violence: "Violence",
    spam: "Spam",
    other: "Other",
    sending: "Sending…",
    sendReport: "Send report",
  },

  promptDisplay: {
    couldNotDoAction: (p: { action: string }) => `Could not ${p.action}.`,
    nextHintCost: (p: { cost: number }) => `Next hint: ${p.cost}`,
    hintSpendTotal: (p: { spent: number }) => `Total: ${p.spent}`,
    buyLetter: (p: { letter: string; price: number }) =>
      `Buy "${p.letter}" for ${counted(p.price, { one: "point", other: "points" })}`,
    maskedPrompt: (p: { shape: string }) => `Masked prompt, ${p.shape} letters`,
    buyThisLetter: (p: { cost: number }) =>
      `Buy this letter for ${counted(p.cost, { one: "point", other: "points" })}`,
    letterCount: (p: { count: number }) =>
      counted(p.count, { one: "letter", other: "letters" }),
    yourTurn: "Your turn",
    pickSomethingDraw: "Pick something to draw",
    autoPicksWhenTimeRunsOut: "Auto-picks when time runs out.",
    hintSpendLimitReached: "Hint spend limit reached",
    deductedFromYourScoreIfYou: "Deducted from your score if you guess the prompt",
    buyLetterRevealsEveryMatch: "Buy a letter - reveals every match",
    selectThePrompt: "select the prompt",
    choosing: "Choosing…",
    buyTheHint: "buy the hint",
    buyTheLetterHint: "buy the letter hint",
  },

  promptListPicker: {
    languageMismatch: (p: { listLanguage: string; roomLanguage: string }) =>
      `That list is in ${p.listLanguage}; this room is in ${p.roomLanguage}.`,
    choicesUnavailable: (p: { reason: string }) =>
      `Prompt-list choices are unavailable (${p.reason}). Your current selection is unchanged.`,
    noListsInLanguage: (p: { language: string }) =>
      `No prompt lists in ${p.language} yet — this room draws on its own custom prompts.`,
    howListPlays: (p: { name: string }) => `How ${p.name} prompts play`,
    reportList: (p: { name: string }) => `Report ${p.name}`,
    failedLoadPromptLists: "Failed to load prompt lists",
    couldNotAddThatSharedList: "Could not add that shared list.",
    loadingCuratedPromptLists: "Loading curated prompt lists…",
    promptLists: "Prompt lists",
    addUnlistedListByCode: "Add an unlisted list by code",
    namePromptCountPrompts:
      (p: { name: string; promptCount: number }) => `${p.name} (${p.promptCount} prompts)`,
    adding: "Adding…",
    add: "Add",
    reportSentForModeratorReview: "Report sent for moderator review.",
  },

  promptStatsPage: {
    noSuchList: "There is no prompt list with that name.",
    couldNotLoadStats: "Could not load these prompt stats. Please try again.",
    showMore: (p: { count: number }) => `Show ${p.count} more`,
    showingOf: (p: { shown: number; total: number }) => `Showing ${p.shown} of ${p.total}`,
    couldNotLoadPromptListsPlease: "Could not load the prompt lists. Please try again.",
    serverWide: "Server-wide",
    promptStats: "Prompt stats",
    everyPromptListHowHasActually: "Every prompt in the list, and how it has actually played across finished\n          games on this server.",
    promptList: "Prompt list",
    sort: "Sort",
    period: "Period",
    scoring: "Scoring",
    hints: "Hints",
    findPrompt: "Find a prompt",
    rollerCoaster: "roller coaster",
    loading: "Loading…",
    prompt: "Prompt",
    howGoes: "How it goes",
    guessed: "Guessed",
    picked: "Picked",
    drawn: "Drawn",
    allTime: "All time",
    last30Days: "Last 30 days",
    last90Days: "Last 90 days",
    allScoringModes: "All scoring modes",
    noScoring: "No scoring",
    defaultScoring: "Default scoring",
    pressureScoring: "Pressure scoring",
    allHintModes: "All hint modes",
    noHints: "No hints",
    checkpointHints: "Checkpoint hints",
    purchasedHints: "Purchased hints",
    letterWheel: "Letter wheel",
    backToLobby: "Back to lobby",
  },

  publicRoomCard: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "round", other: "rounds" }),
    promptLanguage: (p: { language: string }) => `Prompt language: ${p.language}`,
    seeWhoThisRoom: "See who is in this room",
    rounds: "Rounds",
    drawingTime: "Drawing time",
    full: "Full",
    inProgress: "In progress",
    looking: "Looking…",
    nobodySeatedYet: "Nobody is seated yet.",
    host: "Host",
    couldNotReadWhoIs: "Could not read who is in this room.",
    joining: "Joining…",
    join: "Join",
    spectate: "Spectate",
  },

  reactionRequests: {
    thatReactionCouldNotBeSent: "That reaction could not be sent.",
  },

  recapDrawings: {
    thisDrawingCouldNotBeLoaded: "This drawing could not be loaded.",
  },

  reportAccountDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `A moderator will see this. Nothing happens to ${p.name} right now, and they are not told who reported them.`,
    theirPicture: (p: { name: string }) => `${p.name}'s picture`,
    thatReportCouldNotBeSent: "That report could not be sent. Please try again.",
    whatWrongWith: "What is wrong with it",
    reportedTheirNameTheyHaveNo: "Reported for their name. They have no picture to report.",
    anythingElseOptional: "Anything else (optional)",
    anythingModeratorShouldKnow: "Anything a moderator should know",
    sentWithWhatAboutAttached: "Sent, with what it is about attached.",
    done: "Done",
    inappropriateName: "Inappropriate name",
    inappropriatePicture: "Inappropriate picture",
    reportSent: "Report sent",
    reportDisplayName: (p: { displayName: string }) => `Report ${p.displayName}`,
    thePictureOnTheAccount: "The picture on the account is attached as it stands now.",
    theNameOnTheAccount: "The name on the account is attached as it stands now.",
    sending: "Sending…",
    sendReport: "Send report",
    close: "Close",
    cancel: "Cancel",
  },

  reportedDrawing: {
    thisDrawingCouldNotBeDecoded: "This drawing could not be decoded.",
    drawingCouldNotBeLoaded: "The drawing could not be loaded.",
    loadingTheDrawing: "Loading the drawing…",
  },

  reportLobbyLineDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `A moderator will see this line. Nothing happens to ${p.name} right now, and they are not told who reported them.`,
    thatReportCouldNotBeSent: "That report could not be sent. Please try again.",
    whatWrongWith: "What is wrong with it",
    anythingElseOptional: "Anything else (optional)",
    anythingModeratorShouldKnow: "Anything a moderator should know",
    thisLineAttachedWithWhatLobby: "This line is attached, with what the lobby said around it.",
    sentWithLineWhatWasSaid: "Sent, with the line and what was said around it attached.",
    done: "Done",
    harassmentOrAbuse: "Harassment or abuse",
    spam: "Spam",
    inappropriateName: "Inappropriate name",
    reportSent: "Report sent",
    reportDisplayName: (p: { displayName: string }) => `Report ${p.displayName}`,
    sending: "Sending…",
    sendReport: "Send report",
    close: "Close",
    cancel: "Cancel",
  },

  reportPlayerDialog: {
    reportCouldNotBeSent: "That report could not be sent.",
    recentMessages: (p: { count: number }) =>
      `${p.count} of their ${plural(p.count, { one: "recent message", other: "recent messages" })}`,
    nothingHappensYet: (p: { name: string }) =>
      `A moderator will see this. Nothing happens to ${p.name} right now, and they are not told who reported them.`,
    whatHappened: "What happened",
    anythingElseOptional: "Anything else (optional)",
    whatTheySaidDrewWhen: "What they said or drew, and when",
    theirRecentMessagesThisRoomAre: "Their recent messages in this room are attached automatically,\n                with what was said around them, so this can be left empty.",
    includeTheirDrawing: "Include their drawing",
    canvasAsRightNowSoModerator: "The canvas as it is right now, so a moderator sees what\n                      you saw.",
    done: "Done",
    sentWithTheirDrawingAnd:
      (p: { messages: string }) => `Sent, with their drawing and ${p.messages} attached.`,
    sentWithTheirDrawingAttached: "Sent, with their drawing attached.",
    sentWithMessagesAttached: (p: { messages: string }) => `Sent, with ${p.messages} attached.`,
    sentTheyHadSaidNothing:
      "Sent. They had said nothing in this room, so there are no messages attached.",
    baseTheTurnHadEnded:
      (p: { base: string }) => `${p.base} The turn had ended, so the drawing could not be attached.`,
    harassmentOrAbuse: "Harassment or abuse",
    offensiveDrawing: "Offensive drawing",
    inappropriateName: "Inappropriate name",
    cheating: "Cheating",
    spam: "Spam",
    inappropriatePicture: "Inappropriate picture",
    sendThatReport: "send that report",
    reportNickname: (p: { nickname: string }) => `Report ${p.nickname}`,
    reportSent: "Report sent",
    sending: "Sending…",
    sendReport: "Send report",
    cancel: "Cancel",
    close: "Close",
  },

  reportsReviewedNotice: {
    reportsReviewed: (p: { count: number }) =>
      `${counted(p.count, { one: "report you sent has", other: "reports you sent have" })} been reviewed. Thank you.`,
  },

  restartVoteBanner: {
    voteTally: (p: { yes: number; no: number; pending: number }) =>
      `${p.yes} yes, ${p.no} no, ${p.pending} pending`,
    restartingIn: (p: { seconds: number }) =>
      `Restarting in ${counted(p.seconds, { one: "second", other: "seconds" })}`,
    restartApproved: "Restart approved!",
    seconds: "seconds",
    voteRestartGame: "Vote to restart the game",
    restart: "Restart",
    keepPlaying: "Keep playing",
    onlyEligiblePlayersPresentWhenVote: "Only eligible players present when the vote started can vote.",
    proposerNicknameProposedRestartingRemainingS:
      (p: { proposerNickname: string; remaining: number }) => `${p.proposerNickname} proposed restarting · ${p.remaining}s`,
    theCurrentGameIsRestarting: "The current game is restarting now.",
    yesYesNoNoPending:
      (p: { yes: number; no: number; pending: number; requiredVotes: number }) => `${p.yes} yes · ${p.no} no · ${p.pending} pending · ${p.requiredVotes} needed`,
  },

  roleChangeNotice: {
    youHaveBeenSignedOutEvery: "You have been signed out on every device so the change can take\n            effect. Sign in again to carry on.",
    setUpNow: "Set it up now",
    later: "Later",
    oneMoment: "One moment…",
    signInAgain: "Sign in again",
    understood: "Understood",
  },

  roomChatPanel: {
    unreadMessages: (p: { count: number }) =>
      `${counted(p.count, { one: "new message", other: "new messages" })}`,
    correctWithPlace: (p: { place: string | null }) =>
      p.place ? `Correct · ${p.place}` : "Correct",
    couldNotSendMessage: "Could not send message",
    sent: "Sent:",
    send: "Send",
    youReDrawingWatchGuessesCome: "You’re drawing—watch the guesses come in.",
    yourGuessTrimmedDidNot:
      (p: { trimmed: string }) => `Your guess "${p.trimmed}" did not reach the server. Send it again.`,
    sendTheMessage: "send the message",
    chatWhileYouWait: "Chat while you wait",
    gameChat: "Game chat",
    guessAndChat: "Guess and chat",
    guessesAndChat: "Guesses and chat",
    roomChat: "Room chat",
    sayHelloBeforeTheGame: "Say hello before the game starts.",
    noMessagesYet: "No messages yet.",
    typeYourGuess: "Type your guess...",
    typeAMessage: "Type a message...",
  },

  roomEntryState: {
    thisRoomNoLongerAvailable: "This room is no longer available",
    couldNotJoinThisRoom: "Could not join this room",
    thatNameIsReservedPlease: "That name is reserved. Please choose another.",
    thisRoomHasEndedAsk: "This room has ended. Ask the host for a new invite.",
    loadThisRoom: "load this room",
    enterANicknameToContinue: "Enter a nickname to continue.",
    thePlayerSlotsJustFilled: "The player slots just filled up, but you can still spectate.",
    joinAsASpectator: "join as a spectator",
    joinThisRoom: "join this room",
    nicknameRule: "Use 3-16 characters: letters, numbers, hyphens or underscores. No spaces.",
  },

  roomMenuSheet: {
    startTheGameOver: "Start the game over",
    startOverCooldown: (p: { seconds: number }) => ` · in ${p.seconds}s`,
    room: "Room",
    playersScores: "Players and scores",
    copyInviteLink: "Copy the invite link",
    saveThisDrawing: "Save this drawing",
    settings: "Settings",
    leaveRoom: "Leave the room",
    iMBack: "I’m back",
    goAwayForABit: "Go away for a bit",
  },

  roomPlayersPanel: {
    spectatorCount: (p: { count: number }) =>
      counted(p.count, { one: "spectator", other: "spectators" }),
    spectatorsHeading: (p: { count: number }) => `Spectators (${p.count})`,
    playersOfCapacity: (p: { here: number; capacity: number }) =>
      `${p.here} of ${p.capacity} players`,
    readyCount: (p: { count: number }) => `${p.count} ready`,
    couldNotJoinAsPlayer: "Could not join as a player",
    finalStandings: "Final standings",
    players: "Players",
    joinAsAPlayer: "join as a player",
    aPlayerSlotIsAvailable: "A player slot is available.",
    playerSlotsAreCurrentlyFull: "Player slots are currently full.",
    joining: "Joining…",
    joinAsPlayer: "Join as player",
  },

  roomSettingsEditor: {
    couldNotLoadRoomRules: "Could not load room rules",
    roomRefusedThoseSettings: "The room refused those settings.",
    hostSettings: "Host settings",
    editRoomRules: "Edit room rules",
    loadingSettings: "Loading settings…",
    cancel: "Cancel",
    loadRoomRules: "load room rules",
    saveRoomRules: "save room rules",
    saving: "Saving…",
    saveSettings: "Save settings",
    saved: "Saved",
  },

  roomSetupForm: {
    language: "Language",
    visibility: "Visibility",
    maxPlayers: "Max players",
    rounds: "Rounds",
    drawingTime: "Drawing time",
    onlyUseCustomPrompts: "Only use custom prompts",
    addUsableCustomPromptEnableThis: "Add a usable custom prompt to enable this option.",
    allowedTools: "Allowed tools",
    colors: "Colors",
    scoring: "Scoring",
    hints: "Hints",
    spectatorsCanSeePrompt: "Spectators can see the prompt",
    hideBlanks: "Hide blanks",
    alsoTurnsHintsOffWithNo: "Also turns hints off: with no blanks there is nothing to reveal.",
    promptTotal: (p: { count: number }) =>
      counted(p.count, { one: "prompt", other: "prompts" }),
    basics: "Basics",
    roomName: "Room name",
    public: "Public",
    private: "Private",
    prompts: "Prompts",
    drawing: "Drawing",
    scoringHints: "Scoring and hints",
    hintsAreOffBecauseBlanksAre: "Hints are off because blanks are hidden.",
    pointPurchaseHintModesRequireScoring: "Point-purchase hint modes require scoring.",
    allColors: "All colors",
    noScoring: "No scoring",
    listedInTheLobbyAnyone: "Listed in the lobby — anyone can wander in.",
    joinableOnlyWithTheCode: "Joinable only with the code or invite link.",
  },

  rulesPage: {
    sketchy: "Sketchy",
    theRules: "The rules",
    thisPage: "On this page",
    forExample: "For example",
    backToLobby: "Back to lobby",
  },

  sessionManagerDialog: {
    lastUsed: (p: { when: string }) => `Last used ${p.when}`,
    signsOutOn: (p: { when: string }) => `Signs out on its own ${p.when}`,
    usedElsewhere: (p: { when: string }) =>
      `Used from a different browser on ${p.when}. Revoke this device if that was not you.`,
    couldNotLoadSignedDevices: "Could not load signed-in devices.",
    couldNotRevokeDevice: "Could not revoke device.",
    couldNotLogOutEverywhere: "Could not log out everywhere.",
    signedDevices: "Signed-in devices",
    revokeAnyDeviceYouNoLonger: "Revoke any device you no longer recognize. Device names are coarse and do not store browser versions.\n          A device you stop using signs itself out after ninety days.",
    loadingDevices: "Loading devices…",
    currentDevice: "Current device",
    close: "Close",
    revoking: "Revoking…",
    revoke: "Revoke",
    loggingOut: "Logging out…",
    logOutEverywhere: "Log out everywhere",
  },

  settingsOverlay: {
    email: "Email",
    password: "Password",
    twoFactorAuthentication: "Two-factor authentication",
    signedDevices: "Signed-in devices",
    downloadEverything: "Download everything",
    colorScheme: "Color scheme",
    appliesMomentYouPick: "Applies the moment you pick it.",
    languageYouPlay: "Language you play in",
    roomsThisLanguageComeFirstLobby: "Rooms in this language come first in the lobby, and a room you create starts in it. It is separate from the language you read Sketchy in.",
    interfaceLanguage: "Language you read in",
    interfaceLanguageHint: "Every word of Sketchy itself. Separate from the language you play in: reading in one and playing in another is perfectly ordinary.",
    timeFormat: "Time format",
    howEveryClockReadsChatTimestamps: "How every clock reads: chat timestamps, sign-in dates, notices. System follows your device.",
    iHaveTroubleTellingColorsApart: "I have trouble telling colors apart",
    nudgesHostsTowardRoomColorsThat: "Nudges hosts toward room colors that stay distinguishable with deuteranopia and protanopia, without telling them who asked. Nothing changes on its own.",
    brushCursor: "Brush cursor",
    crosshairPreciseAtPointOutlineShows: "A crosshair is precise at the point; an outline shows how wide the stroke will be.",
    brushCursorStyle: "Brush cursor style",
    soundEffects: "Sound effects",
    chimesCorrectGuessStartRoundLast: "Chimes for a correct guess, the start of a round, the last ten seconds, and players coming and going.",
    volume2: "Volume",
    confetti: "Confetti",
    burstWhenYouGuessRightAgain: "A burst when you guess right, and again for the winner at the end of a game.",
    clickKeyRebindEachActionCan: "Click a key to rebind it. Each action can hold two. Press Esc to cancel.",
    theseAreTheirSettings: (p: { name: string }) => `These are ${p.name}’s settings now.`,
    guestLivesInThisBrowser: (p: { name: string }) =>
      `${p.name} lives in this browser only. An account keeps the name, your points and your history on every device, and lets you pick a color.`,
    systemThemeNow: (p: { theme: "dark" | "light" }) => `Now: ${p.theme}`,
    needsAccount: "Needs an account",
    choosePicture: "Choose a picture",
    editPicture: "Edit picture",
    picture: "Picture",
    changePicture: "Change picture",
    removePicture: "Remove picture",
    couldNotRemovePicture: "Could not remove the picture.",
    couldNotChangeYourDisplayName: "Could not change your display name.",
    couldNotChangeYourDisplayName2: "Could not change your display name. Please try again.",
    themeSoundShortcutsCameFromAccount: "The theme, sound and\n            shortcuts came from the account. What this browser had is untouched, and\n            comes back if you log out.",
    dismiss: "Dismiss",
    playingAsGuest: "Playing as a guest",
    createAccount: "Create an account",
    logIn: "Log in",
    you: "You",
    displayName: "Display name",
    cancel: "Cancel",
    change: "Change",
    nameColor: "Name color",
    signingIn: "Signing in",
    changePassword: "Change password",
    manage: "Manage",
    yourData: "Your data",
    requestExport: "Request export",
    delete: "Delete…",
    display: "Display",
    theme: "Theme",
    accessibility: "Accessibility",
    theCanvas: "The canvas",
    sound: "Sound",
    volume: "Volume",
    effects: "Effects",
    noKeyboardThisDevice: "No keyboard on this device",
    yourBindingsAreStillSavedStill: "Your bindings are still saved and still work. Open Sketchy with a keyboard\n            attached to change them.",
    drawingTools: "Drawing tools",
    resetDefaults: "Reset to defaults",
    settings: "Settings",
    close: "Close",
    closeSettings: "Close settings",
    settingsSections: "Settings sections",
    account: "Account",
    appearance: "Appearance",
    soundEffects2: "Sound & effects",
    shortcuts: "Shortcuts",
    red: "Red",
    orange: "Orange",
    yellow: "Yellow",
    lime: "Lime",
    green: "Green",
    teal: "Teal",
    sky: "Sky",
    blue: "Blue",
    indigo: "Indigo",
    purple: "Purple",
    magenta: "Magenta",
    pink: "Pink",
    brown: "Brown",
    light: "Light",
    dark: "Dark",
    system: "System",
    crosshair: "Crosshair",
    outline: "Outline",
    space: "Space",
    hideTheFullAddress: "Hide the full address",
    showTheFullAddress: "Show the full address",
    hide: "Hide",
    showInFull: "Show in full",
    verified: "Verified",
    notVerified: "Not verified",
    saving: "Saving…",
    save: "Save",
    aGuestHasNothingTo: "A guest has nothing to recover: there is no password to forget.",
    withoutOneThereIsNo:
      "Without one there is no way back into this account if the password is forgotten.",
    addAnEmail: "Add an email",
    guestsHaveNoPassword: "Guests have no password.",
    changingItSignsEveryOther: "Changing it signs every other device out.",
    setThisUpAndThe:
      (p: { pendingRole: string }) => `Set this up and the ${p.pendingRole} role you have been offered takes effect.`,
    anAuthenticatorAppSCode:
      "An authenticator app's code, on top of your password. Moderators and administrators must have one.",
    setUp: "Set up",
    thisBrowserIsTheOnly: "This browser is the only place you exist.",
    everyBrowserStillHoldingA:
      "Every browser still holding a session, and a way to end any of them.",
    worksForAGuestToo: "Works for a guest too: the games you have played are yours.",
    everyGameListAndSetting:
      "Every game, list and setting Sketchy holds about you, as one JSON file.",
    deleteThisGuest: "Delete this guest",
    deleteYourAccount: "Delete your account",
    removesTheNameThePoints:
      "Removes the name, the points and the history kept against this browser.",
    gamesYouPlayedStayIn:
      "Games you played stay in other players’ histories, without your name on them.",
    clickToRebindTheSecond: "Click to rebind the second key",
    clickToRebind: "Click to rebind",
    pressKey: "Press key…",
    key: "+ key",
    none: "None",
  },

  stepUpDialog: {
    codeFromYourAuthenticatorApp2: "Code from your authenticator app",
    passkeyNotUsed: "That passkey was not used. You can try again.",
    thatCodeWasNotAccepted: "That code was not accepted.",
    thatPasskeyWasNotAccepted: "That passkey was not accepted.",
    confirmYou: "Confirm it is you",
    recoveryCode: "Recovery code",
    codeFromYourAuthenticatorApp: "Code from your authenticator app",
    cancel: "Cancel",
    waitingForYourDevice: "Waiting for your device…",
    useYourPasskey: "Use your passkey",
    useYourAuthenticatorApp: "Use your authenticator app",
    useARecoveryCode: "Use a recovery code",
    checking: "Checking…",
    confirm: "Confirm",
  },

  suspensionNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Your drawing of ${p.prompt}, as it was reported`,
    recordedAs: "Recorded as {category}",
    yourAccountSuspended: "Your account is suspended",
    youWereAskedDraw: "You were asked to draw",
    theMessageThisWasAbout: "The message this was about:",
    theMessagesThisWasAbout: "The messages this was about:",
    theDrawingThisWasAbout: "The drawing this was about:",
    theDrawingsThisWasAbout: "The drawings this was about:",
    signingOut: "Signing out…",
    signOut: "Sign out",
  },

  toastProvider: {
    notifications: "Notifications",
    dismissNotification: "Dismiss notification",
  },

  toolbar: {
    colorOption: (p: { color: string }) => `color ${p.color}`,
    adjustSize: (p: { tool: string }) => `Adjust ${p.tool} size`,
    sizeSnappingSlider: (p: { tool: string }) => `${p.tool} size snapping slider`,
    chooseToolCurrent: (p: { tool: string }) => `Choose tool, current: ${p.tool}`,
    chooseColorCurrent: (p: { color: string }) => `Choose color, current ${p.color}`,
    sizeWithWidth: (p: { tool: string; width: number }) => `${p.tool} size ${p.width}px`,
    sizeShortcutHint: (p: { tool: string; width: number }) =>
      `${p.tool} size: ${p.width}px ([ / ])`,
    widthReadout: (p: { width: number }) => `${p.width}px`,
    colorSwatch: (p: { color: string }) => `Color ${p.color}`,
    drawingTools: "Drawing tools",
    chooseTool: "Choose tool",
    chooseColor: "Choose color",
    undoLastStroke: "Undo last stroke",
    undo: "Undo",
    clearCanvas: "Clear canvas",
    chooseCustomColor: "Choose custom color",
    colorPalette: "Color palette",
    canvasActions: "Canvas actions",
    undoLastStrokeCtrlZ: "Undo last stroke (Ctrl+Z)",
    clear: "Clear",
    brush: "Brush",
    fill: "Fill",
    eraser: "Eraser",
    rectangle: "Rectangle",
    triangle: "Triangle",
    ellipse: "Ellipse",
    fillIsUnavailableForThe: "Fill is unavailable for the rest of this turn",
    drawingByHandIsUnavailable: "Drawing by hand is unavailable for the rest of this turn",
  },

  turnResultsOverlay: {
    yourTurnWithHints: (p: { base: number; hintSpend: number; points: number; rank: number }) =>
      `Your turn: +${p.base} -${p.hintSpend} hints = ${counted(p.points, { one: "point", other: "points" })} · now #${p.rank}`,
    yourTurn: (p: { delta: number; rank: number }) =>
      `Your turn: ${p.delta >= 0 ? "+" : ""}${p.delta} ${
        Math.abs(p.delta) === 1 ? "point" : "points"
      } · now #${p.rank}`,
    promptWas: "The prompt was",
    noOneGuessedCorrectly: "No one guessed correctly.",
    you: "(you)",
    drewThisTurn: "Drew this turn",
    nextTurn: "Next turn",
    turnResults: "Turn results",
    turnComplete: "Turn complete",
  },

  twoFactorDialog: {
    scanThisWithYourAuthenticatorApp: "Scan this with your authenticator app to add this account",
    codeFromYourAuthenticatorApp: "Code from your authenticator app",
    secondFactorState: (p: {
      recoveryCodesRemaining: number | null;
      confirmAuthenticator: boolean;
    }) =>
      [
        "Two-factor authentication is on.",
        p.recoveryCodesRemaining === null
          ? null
          : `You have ${counted(p.recoveryCodesRemaining, {
              one: "recovery code",
              other: "recovery codes",
            })} left.`,
        p.confirmAuthenticator
          ? "Before this account can be given a moderator or administrator role, confirm that the authenticator is yours with your password and a code from it."
          : null,
        "Each of the changes below swaps a credential, so each asks for your password.",
      ]
        .filter(Boolean)
        .join(" "),
    confirmAuthenticatorFirst:
      "Before this account can be given a moderator or administrator role, confirm that the authenticator is yours with your password and a code from it.",
    copied: (p: { what: string }) => `${p.what} copied.`,
    couldNotCopy: (p: { what: string }) =>
      `Couldn't copy the ${p.what}. Select it and copy by hand.`,
    roleTaken: (p: { role: "admin" | "moderator" }) =>
      `You are now ${p.role === "admin" ? "an administrator" : "a moderator"}. Two-factor authentication is on, and the role that was waiting for it has taken effect. Your other devices have been signed out; this one carries on, and each sign-in from here asks for a code.`,
    recoveryCodesLeft: (p: { count: number }) =>
      `You have ${counted(p.count, { one: "recovery code", other: "recovery codes" })} left.`,
    couldNotReadYourSecuritySettings: "Could not read your security settings.",
    yourPasswordConfirmsAuthenticatorYours: "Your password confirms the authenticator is yours.",
    yourPasswordConfirmsThisPasskeyYours: "Your password confirms this passkey is yours.",
    passkeyAdded: "Passkey added.",
    thatPasskeyWasNotCreatedYou: "That passkey was not created. You can try again.",
    yourPasswordNeededRemovePasskey: "Your password is needed to remove a passkey.",
    confirmedThisAccountCanNowBe: "Confirmed. This account can now be given a staff role.",
    twoFactorAuthentication: "Two-factor authentication",
    saveTheseRecoveryCodesNow: "Save these recovery codes now.",
    eachOneSignsYouOnceIf: "Each one signs you\n              in once if you lose your authenticator app. They are not shown\n              again — only their hashes are kept.",
    recoveryCodes: "Recovery codes",
    downloadAsFile: "Download as a file",
    copyAll: "Copy all",
    iHaveSavedTheseSomewhereSafe: "I have saved these somewhere safe",
    done: "Done",
    moderatorsAdministratorsSignWithPasskeyYour: "Moderators and administrators sign in with a passkey: your\n              device confirms it is you — a fingerprint, your face, or its\n              PIN — and nothing is typed that could be given away.",
    yourPassword: "Your password",
    confirmsPasskeyBeingAddedByYou: "Confirms the passkey is being added by you.",
    useAuthenticatorAppInstead: "Use an authenticator app instead",
    scanCodeWithAuthenticatorAppThen: "Scan the code with an authenticator app, then type the six digits\n              it shows back.",
    drawingCode: "Drawing the code…",
    pointYourAppAtThis: "Point your app at this.",
    setupKey: "Setup key",
    copySetupKey: "Copy the setup key",
    useThisIfYouCanT: "Use this if you can’t scan.",
    confirmsAuthenticatorYours: "Confirms the authenticator is yours.",
    codeFromYourApp: "Code from your app",
    cancel: "Cancel",
    passkeys: "Passkeys",
    thisDeviceOnly: "· on this device only",
    remove: "Remove",
    confirmSYours: "Confirm it’s yours",
    addPasskey: "Add a passkey",
    newRecoveryCodes: "New recovery codes",
    turnOff: "Turn off",
    addAuthenticatorApp: "Add an authenticator app",
    close: "Close",
    couldNotStartSettingThis: "Could not start setting this up.",
    thatCodeWasNotAccepted: "That code was not accepted.",
    couldNotAddThatPasskey: "Could not add that passkey.",
    couldNotRemoveThatPasskey: "Could not remove that passkey.",
    couldNotConfirmIt: "Could not confirm it.",
    couldNotReplaceYourRecovery: "Could not replace your recovery codes.",
    couldNotTurnThisOff: "Could not turn this off.",
    waitingForYourDevice: "Waiting for your device…",
    setUpAPasskey: "Set up a passkey",
    noPasskeyOnThisDevice: "No passkey on this device? ",
    thisBrowserCannotMakeA: "This browser cannot make a passkey. ",
    checking: "Checking…",
    confirm: "Confirm",
  },

  useFriendArrivalNotices: {
    wantsToBeFriends: (p: { name: string }) => `${p.name} wants to be friends.`,
    acceptedYourRequest: (p: { name: string }) => `${p.name} accepted your friend request.`,
    severalAccepted: (p: { count: number }) =>
      `${counted(p.count, { one: "person", other: "people" })} accepted your friend requests.`,
    accept: "Accept",
    open: "Open",
    manyArrived: (p: { name: string; others: number }) =>
      `${p.name} and ${counted(p.others, { one: "other", other: "others" })} want to be friends.`,
  },

  useRoomSessionReconnect: {
    joinRoomFailed: "join_room failed",
  },

  waitingRoomPanel: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "round", other: "rounds" }),
    needMorePlayers: (p: { count: number }) =>
      `Need ${counted(p.count, { one: "more player", other: "more players" })}`,
    hostWillStart: (p: { rematch: boolean }): string =>
      p.rematch ? "{host} will start the rematch" : "{host} will start the game",
    copied: (p: { what: string }) => `${p.what} copied.`,
    couldNotCopy: (p: { what: string }) =>
      `Couldn’t copy the ${p.what}. Copy it from the address bar.`,
    roomCodeLabel: (p: { code: string }) => `Room code ${p.code}`,
    rosterCount: (p: { here: number; capacity: number }) => `${p.here} of ${p.capacity}`,
    inviteYourFriends: "Invite your friends",
    shareLink: "Share the link",
    copyCode: "Copy code",
    inTheRoom: "In the room",
    you: "(you)",
    host: "Host",
    friend: "Friend",
    invite: "Invite",
    edit: "Edit",
    viewHighlights: "View highlights",
    viewDrawings: "View drawings",
    spectatorsAfkAndDisconnectedPlayers:
      "Spectators, AFK, and disconnected players do not count towards the two active players a game needs.",
    joinMySketchyRoomCode: (p: { code: string }) => `Join my Sketchy room: ${p.code}`,
    inviteLink: "Invite link",
    customPromptsOnlyCustomPromptCount:
      (p: { customPromptCount: number }) => `Custom prompts only (${p.customPromptCount})`,
    customPromptCountCustomPromptsCuratedLists:
      (p: { customPromptCount: number }) => `${p.customPromptCount} custom prompts + curated lists`,
    promptListSlugsCountCuratedPromptLists:
      (p: { promptListSlugsCount: number }) => `${p.promptListSlugsCount} curated prompt lists`,
    noScoring: "No scoring",
    spectatorsSeeThePrompt: "Spectators see the prompt",
    publicRoom: "Public room",
    privateRoom: "Private room",
    betweenGames: "between games",
    waitingForPlayers: "waiting for players",
    roomCode: "Room code",
    starting: "Starting…",
    rematch: "Rematch",
    startGame: "Start game",
    waitingForAHost: "Waiting for a host",
  },

  warningNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Your drawing of ${p.prompt}, as it was reported`,
    recordedAs: "Recorded as {category}",
    whatAWarningMeans:
      "A report about your behaviour was reviewed, and this is the outcome. Nothing is restricted, but a further report may lead to your account being suspended.",
    youWereAskedDraw: "You were asked to draw",
    yourPictureWasRemoved: "Your picture was removed",
    aModeratorWarning: "A moderator warning",
    aReportAboutYourPicture:
      "A report about your picture was reviewed, and this is the outcome. Nothing else on your account is affected.",
    theMessageThisWasAbout: "The message this was about:",
    theMessagesThisWasAbout: "The messages this was about:",
    theDrawingThisWasAbout: "The drawing this was about:",
    theDrawingsThisWasAbout: "The drawings this was about:",
    oneMoment: "One moment…",
    understood: "Understood",
  },
  connectionStatusBanner: {
    youReDisconnectedCheckYour:
      "You’re disconnected. Check your connection; Sketchy will reconnect automatically.",
    couldnTReconnectToYour: "Couldn’t reconnect to your room. Reload the page to try again.",
    connectionLostReconnecting: "Connection lost — reconnecting…",
  },
  accountData: {
    queued: "Queued",
    preparing: "Preparing…",
    ready: "Ready",
    tooLargeToPrepareHere: "Too large to prepare here",
    couldNotPrepare: "Could not prepare",
    yourDataIsLargerThan:
      "Your data is larger than this server prepares in one document. Ask the operator to raise the limit.",
    somethingWentWrongWhilePreparing:
      "Something went wrong while preparing it. You can request another export.",
  },
  recoveryCodeFile: {
    sketchyRecoveryCodes: "Sketchy recovery codes",
    accountUsername: (p: { username: string }) => `Account: ${p.username}`,
    createdValue: (p: { value: string }) => `Created: ${p.value}`,
    eachCodeSignsYouIn: "Each code signs you in once if you lose your authenticator app.",
    keepThisFile:
      "Keep this file somewhere only you can reach. Anyone holding these\ncodes and your password can sign in as you.",
  },
  avatars: {
    chooseAPngJpegWebP: "Choose a PNG, JPEG, WebP or GIF picture.",
    thatPictureIsTooLarge: "That picture is too large to read: 10 MB at most.",
    thatFileCouldNotBe: "That file could not be read as a picture.",
    thatPictureIsTooSmall: "That picture is too small to make anything of.",
    thisBrowserCannotResizePictures: "This browser cannot resize pictures.",
    thatPictureIsTooDetailed:
      "That picture is too detailed to fit. Try a simpler one, or zoom in on part of it.",
  },
  settingsSync: {
    thatChangeAppliesHereBut:
      "That change applies here, but could not be saved to your account. Your other devices will not see it.",
  },
  promptStats: {
    hardestFirst: "Hardest first",
    easiestFirst: "Easiest first",
    mostPicked: "Most picked",
    getsGuessed: "Gets guessed",
    usuallyGuessed: "Usually guessed",
    evenOdds: "Even odds",
    oftenMissed: "Often missed",
    rarelyGuessed: "Rarely guessed",
    notPlayedEnough: "Not played enough",
    allRanked: (p: { count: number }) => `All ${p.count} prompts have been played enough to rank.`,
    noneRanked: (p: { unrated: number; guessers: number }) =>
      `None of these ${p.unrated} prompts has faced ${p.guessers} guessers yet, so none of them is ranked. Play some games and their difficulty will show up here.`,
    someRanked: (p: { rated: number; unrated: number; guessers: number }) =>
      `${p.rated} ranked. ${p.unrated} more ${plural(p.unrated, { one: "prompt is", other: "prompts are" })} unranked: fewer than ${p.guessers} guessers have seen them.`,
    noMatch: (p: { query: string }) => `No prompt matches “${p.query}”.`,
    matching: (p: { count: number; query: string }) =>
      `${counted(p.count, { one: "prompt", other: "prompts" })} matching “${p.query}”.`,
  },
  gameHeaderStatus: {
    roundRoundNumberOfTotalRounds:
      (p: { roundNumber: number; totalRounds: number }) => `Round ${p.roundNumber} of ${p.totalRounds}`,
  },
  gameRoomRegions: {
    theNextPlayer: "The next player",
    drawingCanvasYouAreDrawing: "Drawing canvas. You are drawing.",
    yourTurnToDraw: "Your turn to draw.",
    canvasSpectating: (p: { drawer: string }) => `Drawing canvas. Spectating ${p.drawer}.`,
    canvasSomeoneDrawing: (p: { drawer: string }) => `Drawing canvas. ${p.drawer} is drawing.`,
    someoneIsDrawing: (p: { drawer: string }) => `${p.drawer} is drawing.`,
    theDrawer: "the drawer",
    aPlayer: "A player",
  },
  useToolbarState: {
    fillIsUnavailableForThe: "Fill is unavailable for the rest of this turn.",
    drawingByHandIsUnavailable:
      "Drawing by hand is unavailable for the rest of this turn. Shapes still work.",
  },
  timer: {
    n10SecondsRemaining: "10 seconds remaining",
    timeIsUp: "Time is up",
  },
  chatAnnouncements: {
    nicknameGuessedThePrompt: (p: { nickname: string }) => `${p.nickname} guessed the prompt.`,
  },
  canvasSnapshot: {
    drawingOfDownloadPrompt: (p: { downloadPrompt: string }) => `Drawing of ${p.downloadPrompt}`,
    savedDrawing: "Saved drawing",
  },
  roomSetup: {
    default: "Default",
    fasterGuessesEarnMore100: "Faster guesses earn more, 100–300 points.",
    pressure: "Pressure",
    pointsDecayEverySecondTwice: "Points decay every second — twice as fast once someone guesses.",
    noScoring: "No scoring",
    justDrawAndGuessNo: "Just draw and guess. No standings.",
    timedHints: "Timed hints",
    lettersRevealToEveryoneAt: "Letters reveal to everyone at fixed times.",
    noHints: "No hints",
    blanksOnlyAllTurnLong: "Blanks only, all turn long.",
    buyLetters: "Buy letters",
    revealALetterSlotJust: "Reveal a letter slot just for you — paid from that turn's points.",
    wheelOfFortune: "Wheel of Fortune",
    pickALetterPayIts: "Pick a letter, pay its price — vowels cost extra.",
    hiddenPrompt: "Hidden prompt",
  },
  screenCapture: {
    thisBrowserCouldNotEncode: "This browser could not encode the screenshot.",
    theCaptureWasEmpty: "The capture was empty.",
    thisBrowserCouldNotRead: "This browser could not read the screenshot.",
    thatScreenshotIsTooLarge: "That screenshot is too large to send.",
  },
  accountRecovery: {
    youCanRecoverThisAccount:
      (p: { address: string }) => `You can recover this account through ${p.address}.`,
    checkPendingAddressForAConfirmation:
      (p: { pendingAddress: string }) => `Check ${p.pendingAddress} for a confirmation link. Until you follow it, this account has no way back in.`,
    thisServerCannotSendEmail:
      "This server cannot send email, so a lost password has to be reset by whoever runs it.",
    addAnEmailAddressSo: "Add an email address so you can get back in if you forget your password.",
  },
  friends: {
    aFriend: "A friend",
  },
  lobbyPresence: {
    showingShownOfOnlineCount:
      (p: { shown: number; onlineCount: number }) => `Showing ${p.shown} of ${p.onlineCount}`,
  },
  authStore: {
    chooseANameToPlay: "Choose a name to play under.",
  },
  passkeys: {
    noPasskeyWasCreated: "No passkey was created.",
    noPasskeyWasUsed: "No passkey was used.",
  },
  useGameSocketListeners: {
    nicknameJoinedTheRoom: (p: { nickname: string }) => `${p.nickname} joined the room`,
    gameStarted: "Game started!",
    drawerNicknameIsChoosingAPrompt:
      (p: { drawerNickname: string }) => `${p.drawerNickname} is choosing a prompt...`,
    thePromptWasPrompt: (p: { prompt: string }) => `The prompt was "${p.prompt}"`,
    gotIt: (p: { nickname: string; time: string | null; points: number | null }) =>
      `${p.nickname} got it${p.time === null ? "" : ` · ${p.time}`}${p.points === null ? "" : ` (+${p.points})`}`,
  },
  settingsStore: {
    brushTool: "Brush tool",
    fillTool: "Fill tool",
    eraserTool: "Eraser tool",
    rectangleTool: "Rectangle tool",
    triangleTool: "Triangle tool",
    ellipseTool: "Ellipse tool",
    decreaseBrushSize: "Decrease brush size",
    increaseBrushSize: "Increase brush size",
    undoStroke: "Undo stroke",
  },
  reactions: {
    loveIt: "Love it",
    funny: "Funny",
    wow: "Wow",
    fire: "Fire",
    reaction: "Reaction",
  },
  drawingRules: {
    brush: "Brush",
    theBrushAndTheEraser: "The brush and the eraser.",
    fill: "Fill",
    theFillTool: "The fill tool.",
    shapes: "Shapes",
    rectangleEllipseAndTriangle: "Rectangle, ellipse, and triangle.",
    allColors: "All colors",
    thePaletteAndTheCustom: "The palette and the custom color picker.",
    paletteOnly: "Palette only",
    theBuiltInSwatchesNo: "The built-in swatches; no custom colors.",
    colorblindSafe: "Colorblind-safe",
    colorsThatStayApartFor: "Colors that stay apart for colorblind players.",
    blackAndWhite: "Black and white",
    blackAndWhiteOnly: "Black and white only.",
    allTools: "All tools",
  },
  socket: {
    sketchyIsFullRightNow: "Sketchy is full right now. Try again in a few minutes.",
    connectionLostWhileTryingTo:
      (p: { action: string }) => `Connection lost while trying to ${p.action}. Please try again.`,
    theRequestToActionTimed:
      (p: { action: string }) => `The request to ${p.action} timed out. Please try again.`,
    couldNotActionPleaseTry: (p: { action: string }) => `Could not ${p.action}. Please try again.`,
  },
  bugReports: {
    drawingAndCanvas: "Drawing and canvas",
    guessingAndChat: "Guessing and chat",
    roundsScoringAndResults: "Rounds, scoring and results",
    roomsAndLobby: "Rooms and lobby",
    promptLists: "Prompt lists",
    accountAndSettings: "Account and settings",
    connectionAndSync: "Connection and sync",
    performance: "Performance",
    accessibility: "Accessibility",
    somethingElse: "Something else",
    blocksPlayICouldNot: "Blocks play — I could not carry on",
    majorHardToPlayAround: "Major — hard to play around",
    minorWorthFixingOneDay: "Minor — worth fixing one day",
    notInARoom: "Not in a room",
    codeNotInARound: (p: { code: string }) => `${p.code} · not in a round`,
    codeRoundRoundOfTotal:
      (p: { code: string; round: number; total: number }) => `${p.code} · round ${p.round} of ${p.total}`,
  },
  suspension: {
    thisSuspensionHasNoEnd: "This suspension has no end date.",
    thisSuspensionHasEndedTry: "This suspension has ended; try signing in again.",
    thisSuspensionLastsUntilEnds: (p: { ends: string }) => `This suspension lasts until ${p.ends}.`,
  },
  clock: {
    unknown: "Unknown",
  },
  protocol: {
    theServerWasUpdated: "The server was updated.",
  },
  passwordPolicy: {
    tooShort: (p: { count: number }) => `A password needs at least ${p.count} characters.`,
  },
  operatorAccess: {
    administrator: "administrator",
    moderator: "moderator",
    pendingTitle: "The moderator role is waiting for you",
    pendingBody:
      "An administrator has offered you the moderator role. It takes effect once you set up two-factor authentication: moderators sign in with a code from an authenticator app, and the role starts the moment that is in place. Your other devices are signed out when it does. Nothing changes until you set it up, and the offer waits in Settings if now is not the time.",
    grantedTitle: "You are now a moderator",
    grantedBody:
      "An administrator gave you the moderator role. A Moderation entry has appeared in your account menu: it is where reports about players and prompts are reviewed. Nothing about how you play changes.",
    removedTitle: "You are no longer a moderator",
    removedBody:
      "An administrator removed the moderator role from your account. The Moderation entry has gone from your menu. Nothing else about your account or your games is affected.",
  },
  moderationCategories: {
    harassment: "harassment",
    offensive_drawing: "an offensive drawing",
    inappropriate_name: "an inappropriate name",
    cheating: "cheating",
    spam: "spam",
    inappropriate_avatar: "an inappropriate picture",
  },
  roomNotices: {
    kickedByVote: "You were kicked from the room by vote.",
    roomClosed: "An administrator closed this room.",
    removedByAdmin: "An administrator removed you.",
    accountDeleted: "Your account was deleted.",
    accountSuspended: "Your account was suspended.",
  },
};
