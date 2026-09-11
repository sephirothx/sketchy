/** Every word the interface says, in Dutch.

Machine-drafted from [`en.ts`](./en.ts) and **not yet read by a native
speaker** - `reviewed.ts` is what tracks that, and this locale is at zero.
Completeness is the compiler's rule and is already met; quality is a separate
promise and is not yet made (R-I18N-07).

Its shape is `en.ts`'s, entry for entry, because it is generated from it: a
translation that dropped a key would fail `tsc` rather than reach a reader
as a blank. Translate the words; leave the holes, the plural categories and
the slot tokens exactly where they are. */
import { formattersFor } from "./format.ts";
import type { Catalogue } from "./index.ts";
import type { AnnouncementCode } from "../../lib/announcements.ts";
import type { ErrorCode } from "../../types.ts";

const { counted, number, ordinal, plural } = formattersFor("nl", {"other":"e"});


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
      return `Het wachtwoord moet minstens ${count(detail, 12)} tekens lang zijn.`;
    case "too_long":
      return `Het wachtwoord mag hoogstens ${count(detail, 128)} tekens lang zijn.`;
    case "common":
      return "Dit wachtwoord hoort bij de meest gebruikte die er zijn. Kies een ander.";
    case "common_repeated":
      return "Dat is een veelgebruikt wachtwoord, alleen herhaald. Kies een ander.";
    case "short_repeated":
      return "Dit wachtwoord is een kort wachtwoord dat herhaald wordt. Kies een ander.";
    case "too_few_characters":
      return `Dit wachtwoord gebruikt maar ${count(detail, 4)} verschillende tekens. Kies een ander.`;
    case "keyboard_walk":
      return "Dit wachtwoord is vooral een rij toetsen op volgorde. Kies een ander.";
    case "contains_identity":
      return "Een wachtwoord mag je naam, je e-mailadres of de naam van deze site niet bevatten.";
    case "common_with_digits":
      return "Dat is een veelgebruikt wachtwoord met cijfers erachter. Kies een ander.";
    default:
      return "Kies een ander wachtwoord.";
  }
}

/** *Create an account to …* - one refusal, said about the thing it refused. */
function accountRequired(params: MessageParams): string {
  switch (params.action) {
    case "avatar":
      return "Maak een account om een afbeelding te kiezen.";
    case "prompt_lists":
      return "Maak een account om herbruikbare woordenlijsten te bewaren.";
    case "name_color":
      return "Maak een account om een naamkleur te kiezen.";
    case "password":
      return "Maak een account om een wachtwoord in te stellen.";
    case "second_factor":
      return "Maak een account voordat je tweestapsverificatie instelt.";
    case "friends":
      return "Maak een account om vrienden toe te voegen.";
    default:
      return "Maak een account om dat te doen.";
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
      return "er een serverupdate bezig is";
    case "too_few_players":
      return "er minder dan twee actieve spelers over zijn";
    case "prompt_lists_unavailable":
      return "de woordenlijsten niet geladen konden worden";
    case "everybody_left":
      return "iedereen weg was voordat het kon beginnen";
    default:
      return "het niet meer door kon gaan";
  }
}

type Sentence = string | ((params: MessageParams) => string);

/** Why the server refused, said to the player.

One entry per `ErrorCode`; `Record` makes it exhaustive, so a code the server
adds without a sentence here fails the build rather than the player
(R-I18N-04). */
const REFUSALS: Record<ErrorCode, Sentence> = {
  // Payloads and arguments
  invalid_payload: "Sketchy kon dat verzoek niet lezen.",
  invalid_nickname: "Deze naam kan hier niet gebruikt worden.",
  invalid_name_color: "Kies een kleur die leesbaar is in zowel de lichte als de donkere spelerslijst.",
  invalid_hint: "Deze hint is ongeldig.",
  invalid_letter: "Deze letter is ongeldig.",
  invalid_prompt_lists: "Deze woordenlijsten kunnen niet samen gebruikt worden.",
  invalid_custom_prompts: "Deze eigen woorden konden niet gelezen worden.",
  max_players_below_seated: (params) =>
  `Het maximum aantal spelers kan niet lager zijn dan de ${count(params.seated, 2)} spelers die al in de kamer zitten.`,
  empty_message: "Typ eerst iets.",

  // Rate and capacity
  too_fast: "Je gaat te snel. Doe even rustig aan.",
  seat_changing_too_fast: "Deze plek wisselt te snel van eigenaar. Probeer het over een minuut nog eens.",
  joining_too_fast: "Je stapt te snel kamers binnen. Probeer het over een minuut nog eens.",
  room_quota: "Je hebt al net zoveel kamers open als tegelijk kan.",
  room_full: "Deze kamer is vol.",
  spectators_full: "Deze kamer neemt geen toeschouwers meer aan.",
  player_slots_full: "Alle spelersplekken zijn bezet.",

  // Server and account state
  server_draining: "Sketchy start opnieuw op. Probeer het zo nog eens.",
  server_paused: "Sketchy neemt op dit moment geen nieuwe kamers aan.",
  database_busy: "Sketchy kan zijn database niet goed bereiken. Probeer het nog eens.",
  account_ended: "Dit account is niet meer actief.",
  account_required: accountRequired,
  identity_unavailable: "Sketchy kon niet bevestigen wie je bent. Herlaad en probeer het nog eens.",

  // Rooms
  not_in_room: "Je zit niet in deze kamer.",
  room_not_found: "Kamer niet gevonden.",
  room_ended: "Deze kamer is afgelopen.",
  could_not_create_room: "De kamer kon niet aangemaakt worden.",
  no_session_to_resume: "Er is geen sessie van jou om in deze kamer te hervatten.",
  host_only: "Dat kan alleen de gastheer.",
  players_only: "Dat kunnen alleen spelers.",
  waiting_room_only: "Dat kan alleen in de wachtkamer.",
  already_a_player: "Je bent al speler.",
  registered_name_fixed: "Geregistreerde spelers spelen onder hun gebruikersnaam.",
  name_taken_by_account: "Deze naam hoort bij een geregistreerde speler.",
  guests_cannot_choose_color: "Maak een account om een naamkleur te kiezen.",
  suggestion_inactive: "Deze suggestie is niet meer actief.",
  drawing_not_found: "Tekening niet gevonden.",
  drawing_not_kept: "Deze tekening is niet bewaard.",

  // Games and turns
  not_in_game: "Je zit niet in een lopend spel.",
  game_in_progress: "Het spel is al bezig.",
  game_starting: "Het spel is nog aan het starten.",
  need_two_players: "Er zijn twee actieve spelers nodig om te beginnen.",
  room_not_startable: "Deze kamer kan nu geen spel starten.",
  prompt_not_ready: "Het spel is nog niet klaar voor een woord.",
  prompt_unavailable: "Dit woord is niet meer beschikbaar.",
  hints_disabled: "Hints staan uit in deze kamer.",
  hint_spend_limit: "Je hebt de hintlimiet van deze beurt bereikt.",
  hint_unavailable: "Deze hint is niet beschikbaar.",

  // Canvas
  drawer_only: "Dat kan alleen degene die tekent.",
  canvas_stale_generation: "Het canvas is verder. Bezig met bijwerken.",
  canvas_sequence_committed: "Dat is al getekend.",
  canvas_out_of_sequence: "Tekenacties kwamen in de verkeerde volgorde aan. Bezig met bijwerken.",
  canvas_out_of_sync: "Het canvas loopt niet gelijk. Bezig met bijwerken.",
  nothing_to_undo: "Er is niets om ongedaan te maken.",

  // Votes and restarts
  spectators_cannot_vote: "Toeschouwers kunnen niet stemmen.",
  spectators_cannot_be_targets: "Over een toeschouwer kan niet gestemd worden.",
  invalid_vote_target: "Over deze speler kun je niet stemmen.",
  not_eligible: "Alleen actieve spelers kunnen een herstart voorstellen.",
  restart_vote_active: "Er loopt al een stemming over een herstart.",
  restart_vote_cooldown: "Er is net over een herstart gestemd. Wacht even voordat je er nog een voorstelt.",
  no_restart_vote: "Er is geen herstartstemming om te beantwoorden.",
  restart_vote_closed: "Deze herstartstemming is al gesloten.",

  // Reactions
  spectators_cannot_react: "Toeschouwers kunnen niet op een tekening reageren.",
  guests_cannot_react: "Maak een account om op een tekening te reageren.",
  reaction_not_visible: "Je kunt niet reageren op een tekening die je niet ziet.",
  own_drawing: "Je kunt niet op je eigen tekening reageren.",
  game_still_saving: "Dit spel wordt nog opgeslagen. Probeer het zo nog eens.",
  game_not_recorded: "Dit spel is niet vastgelegd.",
  reaction_not_accepted: "Deze reactie kon niet verstuurd worden.",

  // Friends
  friends_unavailable: "Vrienden zijn op dit moment niet beschikbaar.",
  friend_refused: "Dit vriendschapsverzoek kon niet afgerond worden.",
  friend_not_in_game: "Je vriend zit op dit moment niet in een spel.",
  friend_in_several_games: "Deze vriend zit in meerdere spellen. Vraag om een uitnodiging.",
  not_friends: "Je kunt alleen bij het spel van een vriend komen.",
  friends_only_uninvited: "Alleen vrienden van de gastheer kunnen hier zonder uitnodiging bij. Vraag om een uitnodiging.",
  invite_expired: "Deze uitnodiging is verlopen.",

  // Moderation, from the reporter's side
  reporting_unavailable: "Melden is niet beschikbaar op deze server.",
  no_such_player: "Deze speler bestaat niet.",
  cannot_report: "Deze speler kan niet gemeld worden.",
  already_reported: "Je hebt dit al gemeld, en een moderator heeft het nog niet bekeken.",

  // Lobby chat
  name_required: "Kies een naam voordat je iets in de lobby zegt.",
  not_watching_lobby: "Je kijkt niet meer naar de lobby.",

  // Versioning
  protocol_mismatch: "Dit tabblad draait op een oudere versie van Sketchy. Herlaad de pagina om verder te gaan.",

  // Sessions and accounts
  sign_in_required: "Log eerst in.",
  credentials_incorrect: "Gebruikersnaam of wachtwoord klopt niet.",
  password_incorrect: "Het wachtwoord klopt niet.",
  account_suspended: "Dit account is geschorst.",
  already_signed_in: "Je bent al ingelogd op een account.",
  username_taken: "Deze gebruikersnaam is bezet.",
  invalid_username: "Deze gebruikersnaam kan niet gebruikt worden.",
  weak_password: weakPassword,
  password_change_failed: "Het wachtwoord kon niet gewijzigd worden.",
  session_not_found: "Dit apparaat is niet meer ingelogd.",
  session_replaced: "Deze sessie is vervangen. Herlaad en probeer het nog eens.",
  guest_progress_unlinked: "De gastvoortgang kon niet aan dit account gekoppeld worden.",
  not_taking_visitors: "Sketchy neemt op dit moment geen nieuwe bezoekers aan. Probeer het later nog eens.",
  account_delete_refused: "Het account kon nu niet verwijderd worden. Probeer het nog eens.",
  password_required_to_delete: "Voer je wachtwoord in om het account te verwijderen.",

  // Second factor and passkeys
  second_factor_required: "Voer de code uit je authenticatie-app in.",
  second_factor_passkey_only: "Log in met je passkey.",
  second_factor_not_enrolled:
  "Dit account heeft tweestapsverificatie nodig voordat het kan inloggen. Vraag een beheerder om hulp bij het instellen.",
  second_factor_not_set_up: "Tweestapsverificatie is niet ingesteld.",
  second_factor_code_wrong: "Deze code klopt niet.",
  second_factor_throttled: "Te veel codes waren fout. Wacht even en probeer het nog eens.",
  step_up_required: "Bevestig dat jij het bent voordat je dat doet.",
  passkey_sign_in_required: "Log in met je passkey.",
  passkey_not_registered: "Deze passkey is hier niet geregistreerd.",
  passkey_not_found: "Deze passkey bestaat niet.",
  passkey_refused:
  "Passkeys zijn voor moderator- en beheerdersaccounts. Je wordt gevraagd er een in te stellen als je ooit een rol krijgt aangeboden.",
  last_factor: "Dit is de enige manier waarop je kunt bewijzen dat jij het bent. Voeg er een toe voordat je deze weghaalt.",
  second_factor_required_for_role: "De rol van dit account vereist tweestapsverificatie.",
  second_factor_not_proved:
  "Deze authenticator is nog niet als de jouwe bevestigd. Gebruik een passkey, of bevestig hem met je wachtwoord in Instellingen.",

  // Email, verification and recovery
  invalid_email: "Dat lijkt geen e-mailadres.",
  email_in_use: "Dit adres is al in gebruik.",
  email_change_refused: "Dit adres kan niet aan dit account toegevoegd worden.",
  verification_link_invalid: "Deze bevestigingslink is verlopen of al gebruikt.",
  reset_link_invalid: "Deze herstellink is verlopen of al gebruikt.",

  // Account data export
  export_not_found: "Export niet gevonden.",
  export_expired: "De export is verlopen.",
  export_not_ready: "De export is nog niet klaar.",
  export_unreadable: "Het exportdocument kon niet gelezen worden. Vraag een nieuwe export aan.",
  export_not_yet_allowed: "Je hebt recent al een export aangevraagd. Probeer het later nog eens.",
  export_refused: "Deze export kon niet gestart worden. Probeer het nog eens.",

  // Rate limits reached over HTTP
  too_many_attempts: "Te veel pogingen. Wacht even en probeer het nog eens.",
  too_many_requests: "Te veel verzoeken. Wacht even en probeer het nog eens.",
  too_many_reports: "Te veel meldingen. Wacht even voordat je er nog een stuurt.",
  too_many_bug_reports: "Te veel bugmeldingen. Wacht even voordat je er nog een stuurt.",
  too_many_pictures: "Te veel afbeeldingen. Wacht even en probeer het nog eens.",

  // Pictures
  unsupported_picture_type: "Dat is geen WebP- of PNG-afbeelding.",
  picture_not_found: "Deze afbeelding bestaat niet.",
  picture_refused: "Deze afbeelding kan hier niet gebruikt worden.",

  // Bug reports
  screenshot_unreadable: "De schermafbeelding kon niet gelezen worden.",
  screenshot_too_large: (params) =>
  `Deze schermafbeelding is te groot. De limiet is ${megabytes(params.limitBytes, "2 MB")}.`,
  screenshot_unsupported_type: "Een schermafbeelding moet een PNG- of WebP-afbeelding zijn.",
  bug_report_context_too_large: "Deze melding draagt te veel context mee.",

  // Friends, over HTTP
  friends_throttled: "Je hebt veel vriendschapsverzoeken gestuurd. Probeer het later nog eens.",
  that_is_you: "Dat ben jij.",

  // Profiles and history
  no_such_game: "Dit spel bestaat niet.",
  no_such_drawing: "Deze tekening bestaat niet.",
  drawing_unreadable: "Deze tekening kon niet gelezen worden.",

  // Prompt lists
  prompt_list_not_found: "Woordenlijst niet gevonden.",
  shared_prompt_list_not_found: "Geen gedeelde woordenlijst gevonden.",
  prompt_list_conflict: "Iemand anders heeft die lijst gewijzigd. Herlaad hem en probeer het nog eens.",
  prompt_list_invalid: "Deze woordenlijst kon niet opgeslagen worden.",
  prompt_list_forbidden: "Deze woordenlijst is niet van jou om te wijzigen.",
  unknown_sort: "Sketchy kan daar niet op sorteren.",
  timezone_required: "Zet er een tijdzone bij die datum.",
  range_reversed: "Het begin van het bereik moet vóór het einde liggen.",

  // Room presets
  room_preset_not_found: "Kamervoorinstelling niet gevonden.",
  room_preset_conflict: "Je hebt al een voorinstelling met die naam.",
  room_preset_unavailable: "Deze voorinstelling kan nu niet gebruikt worden.",
  room_preset_forbidden: "Deze voorinstelling is niet van jou.",

  // Blocks
  cannot_block_yourself: "Je kunt jezelf niet blokkeren.",
  block_list_full: (params) =>
  `Je blokkeerlijst is vol${
    typeof params.limit === "number" ? ` bij ${params.limit}` : ""
  }. Deblokkeer eerst iemand.`,

  // Settings
  setting_refused: "Deze instelling kon niet opgeslagen worden.",

  // Role notices
  no_such_notice: "Deze melding bestaat niet.",

  // Reporting, from the reporter's side
  cannot_report_yourself: "Je kunt jezelf niet melden.",
  cannot_report_own_prompt_list: "Je kunt je eigen woordenlijst niet melden.",
  no_reportable_prompt_list: "Geen meldbare woordenlijst gevonden.",
  prompt_not_in_list: "Dit woord hoort niet bij deze lijst.",
  no_picture_to_report: "Deze speler heeft geen afbeelding om te melden.",
  no_such_game_context: "Deze spelcontext bestaat niet.",
  no_such_turn_context: "Deze beurtcontext bestaat niet.",
  turn_not_in_game: "De beurt hoort niet bij dat spel.",
  evidence_unavailable: "Een of meer geselecteerde berichten zijn niet beschikbaar.",
  evidence_mixed_scopes: "Lobby- en kamerberichten kunnen niet in één melding gemengd worden.",
  evidence_several_rooms: "Geselecteerde berichten moeten uit dezelfde kamer komen.",
  evidence_not_theirs: "Bewijs moet van de gemelde speler zijn.",
  evidence_not_received: "Je kunt geen bericht kiezen dat je niet ontvangen hebt.",
  evidence_not_in_game: "Het gekozen bericht hoort niet bij dat spel.",
  evidence_not_in_turn: "Het gekozen bericht hoort niet bij die beurt.",
  no_such_warning: "Deze waarschuwing bestaat niet.",
  no_drawing: "Geen tekening.",};

/** What the room says about itself. One entry per `AnnouncementCode`. */
const ANNOUNCEMENTS: Record<AnnouncementCode, (params: MessageParams) => string> = {
  nickname_changed: (p) =>
  `${text(p.previous)} heet nu ${text(p.nickname)}.`,
  joined_as_player: (p) => `${text(p.nickname)} doet mee als speler.`,
  kicked_by_vote: (p) => `${text(p.nickname)} is er door een stemming uit gezet.`,
  marked_afk_by_vote: (p) => `${text(p.nickname)} is door een stemming als afwezig gemarkeerd.`,

  restart_vote_started: (p) =>
  `${text(p.nickname)} is een stemming over een herstart begonnen.`,
  restart_vote_passed: (p) =>
  `De herstartstemming is aangenomen. Herstart over ${count(p.seconds, 5)} seconden.`,
  restart_vote_rejected: () => "De herstartstemming is afgewezen.",
  restart_vote_expired: () => "De herstartstemming is verlopen zonder te slagen.",
  restart_vote_abandoned: () =>
  "De herstartstemming is afgebroken omdat er minder dan twee actieve spelers over zijn.",
  restart_cancelled: (p) => `De herstart is afgebroken omdat ${cancelReason(p.reason)}.`,
  game_restarted_by_vote: () => "Het spel is opnieuw gestart door een stemming van de spelers.",

  hint_letter_found: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} ptn - ${counted(count(p.count, 1), {
    one: "keer",
    other: "keer",
  })} gevonden!`,
  hint_letter_missing: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} ptn - zit niet in het woord.`,
  guess_very_close: (p) => `„${text(p.text)}” zit er heel dichtbij!`,
  guess_some_words_correct: () => "Sommige woorden kloppen",};

export const NL: Catalogue = {
  refusals: REFUSALS,
  announcements: ANNOUNCEMENTS,

  /** What the document itself says: the tab, and what a link preview shows.

      Rendered into `index.html` for a crawler, which arrives before any
      script, and rewritten here for the reader once their locale is known. */
  document: {
    description: "Teken, raad en lach met vrienden!",
  },

  /** Shapes that belong to the language rather than to any one screen. */
  format: {
    /** `1st`, `2nd`, `3rd`; a language with no ordinal form gets the number. */
    ordinal: (p: { value: number }) => ordinal(p.value),
  },

  promptListDrafts: {
    promptsAdded: (p: { count: number }) =>
      `${counted(p.count, { one: "woord", other: "woorden" })} toegevoegd`,
    duplicatesAlreadyInTheList: (p: { duplicates: number }) =>
      `${p.duplicates} al in de lijst`,
    tooLongCountOverMaxListPrompt: (p: { tooLongCount: number; MAX_LIST_PROMPT_LENGTH: number }) =>
      `${p.tooLongCount} langer dan ${p.MAX_LIST_PROMPT_LENGTH} tekens`,
    overLimitPastTheMaxList: (p: { overLimit: number; MAX_LIST_PROMPTS: number }) =>
      `${p.overLimit} boven de limiet van ${p.MAX_LIST_PROMPTS}`,
    keptSkippedSkipped: (p: { kept: string; skipped: string }) =>
      `${p.kept}; overgeslagen: ${p.skipped}.`,
  },

  lastSeen: {
    online: "online",
    justNow: "net nog gezien",
    lastSeenAgo: (p: { count: number; unit: "minute" | "hour" | "day" }) => {
      const words = {
        minute: { one: "minuut", other: "minuten" },
        hour: { one: "uur", other: "uur" },
        day: { one: "dag", other: "dagen" },
      }[p.unit];
      return `${counted(p.count, words)} geleden gezien`;
    },
  },

  gameHighlights: {
    reactionCount: (p: { count: number }) =>
      counted(p.count, { one: "reactie", other: "reacties" }),
    hardestPrompt: "Moeilijkste woord",
    fastestGuess: "Snelste gok",
    bestDrawer: "Beste tekenaar",
    quickestOnAverage: "Gemiddeld het snelst",
    mostReactedDrawing: "Tekening met de meeste reacties",
  },

  versionBadge: {
    buildDetails: (p: { commitDate: string; builtAt: string }) =>
      `Commitdatum: ${p.commitDate} | Gebouwd: ${p.builtAt}`,
  },

  segmentedCodeInput: {
    digitPosition: (p: { label: string; index: number; length: number }) =>
      `${p.label}, cijfer ${p.index} van ${p.length}`,
  },

  roomSetupControls: {
    decrease: (p: { label: string }) => `${p.label} verlagen`,
    increase: (p: { label: string }) => `${p.label} verhogen`,
  },

  guessPips: {
    playerGuessState: (p: { nickname: string; isFriend: boolean; guessed: boolean }) =>
      `${p.nickname}${p.isFriend ? " (vriend)" : ""} ${p.guessed ? "heeft het geraden" : "is nog aan het raden"}`,
    gotOfGuessersCountGuessed: (p: { got: number; guessersCount: number }) =>
      `${p.got} van ${p.guessersCount} geraden`,
    summaryOpenPlayersAndScores: (p: { summary: string }) =>
      `${p.summary}. Spelers en scores openen.`,
  },

  accountDataDialog: {
    requestedOn: (p: { when: string; schemaVersion: number }) =>
      `Aangevraagd ${p.when} · formaat v${p.schemaVersion}`,
    exportAllowance: (p: { nextAllowed: string | null }) =>
      p.nextAllowed
        ? `Eén export per week; klaargezette exports verlopen na zeven dagen. Je kunt op ${p.nextAllowed} een nieuwe aanvragen.`
        : "Eén export per week; klaargezette exports verlopen na zeven dagen.",
    couldNotLoadYourDataExports: "Je data-exports konden niet geladen worden.",
    couldNotRequestYourDataExport: "Je data-export kon niet aangevraagd worden.",
    yourData: "Jouw gegevens",
    downloadPrivateJsonCopyYourAccount: "Download een privékopie in JSON van je account en je spelgegevens. Profielen en berichten van andere spelers zitten er niet in.",
    dataExports: "Data-exports",
    loadingExports: "Exports laden…",
    youHaveNotRequestedExportYet: "Je hebt nog geen export aangevraagd.",
    download: "Downloaden",
    close: "Sluiten",
    requesting: "Aanvragen…",
    requestExport: "Export aanvragen",
  },

  accountMenu: {
    noPasskeyWasUsed: "Er is geen passkey gebruikt. Je kunt met je wachtwoord inloggen.",
    signedInWithRequests: (p: { name: string; waiting: number }) =>
      `Ingelogd als ${p.name}. ${counted(p.waiting, {
        one: "vriendschapsverzoek wacht",
        other: "vriendschapsverzoeken wachten",
      })}.`,
    friends: "Vrienden",
    finishYourRole: (p: { role: "admin" | "moderator" }) =>
      `Maak je rol als ${p.role === "admin" ? "beheerder" : "moderator"} af`,
    agreeToRules: "Door een account te maken ga je ermee akkoord de {rules} te volgen.",
    reportBug: "Een bug melden",
    account: "Account",
    settings: "Instellingen",
    myProfile: "Mijn profiel",
    promptStats: "Woordstatistieken",
    createAccount: "Account maken",
    logIn: "Inloggen",
    myPromptLists: "Mijn woordenlijsten",
    rules: "Regels",
    logOut: "Uitloggen",
    thatDoesNotLookLikeEmail: "Dat lijkt geen e-mailadres.",
    somethingWentWrongPleaseTryAgain: "Er ging iets mis. Probeer het nog eens.",
    thatPasskeyWasNotAccepted: "Deze passkey is niet geaccepteerd.",
    thisAccountSignsWithPasskey: "Dit account logt in met een passkey.",
    or: "of",
    username: "Gebruikersnaam",
    password: "Wachtwoord",
    codeFromYourAuthenticatorApp: "Code uit je authenticatie-app",
    recoveryCodeWorksHereTooCan: "Een herstelcode werkt hier ook, en is één keer te gebruiken.",
    email: "E-mail",
    optional: "optioneel",
    letsYouResetYourPasswordLater: "Hiermee kun je later je wachtwoord herstellen. Verder wordt het nergens voor gebruikt.",
    rules2: "regels",
    forgotYourPassword: "Wachtwoord vergeten?",
    notNow: "Nu niet",
    createYourAccount: "Maak je account",
    createAnAccountToKeep: (p: { suggestedUsername: string }) =>
      `Maak een account om ${p.suggestedUsername} als gebruikersnaam te houden en je statistieken op elk apparaat te bewaren.`,
    keepYourUsernameAndYour: "Houd je gebruikersnaam en je statistieken op elk apparaat.",
    waitingForYourDevice: "Wachten op je apparaat…",
    signInWithAPasskey: "Inloggen met een passkey",
    pleaseWait: "Even geduld…",
    alreadyRegistered: "Al geregistreerd? ",
    newHere: "Nieuw hier? ",
    createAnAccount: "Account maken",
    guestIdentity: (p: { name: string }) =>
      `${p.name}. Je weergavenaam is niet opgeslagen.`,
    signedInAs: (p: { name: string }) =>
      `Ingelogd als ${p.name}`,
  },

  accountRecoveryPage: {
    thatConfirmationLinkCouldNotBe: "Deze bevestigingslink kon niet gebruikt worden.",
    somethingWentWrongPleaseTryAgain: "Er ging iets mis. Probeer het nog eens.",
    evenBestGuessersForgetSometimes: "Zelfs de beste raders vergeten weleens iets.",
    weRsquoLlSendSecureTime: "We sturen een veilige link met een korte houdbaarheid naar het\n            bevestigde e-mailadres van je account.",
    accountHelp: "Accounthulp",
    backLobby: "Terug naar de lobby",
    enterYourUsernameYourConfirmedEmail: "Vul je gebruikersnaam of je bevestigde e-mailadres in. Als het\n              account hersteld kan worden, is er een link onderweg.",
    usernameEmail: "Gebruikersnaam of e-mail",
    thatResetLinkHasExpiredHas: "Deze herstellink is verlopen of al gebruikt. Zulke links werken één\n              keer en gelden een uur.",
    sendNewOne: "Stuur een nieuwe",
    checkingThatLink: "Link controleren…",
    everySignedDeviceWillBeSigned: "Elk ingelogd apparaat wordt uitgelogd, ook de apparaten die je niet\n              herkende.",
    newPassword: "Nieuw wachtwoord",
    addressIsConfirmedYouCan: (p: { address: string }) =>
      `${p.address} is bevestigd. Je kunt dit account nu herstellen.`,
    yourPasswordIsSetAnd: "Je wachtwoord is ingesteld en je bent weer ingelogd.",
    resetYourPassword: "Wachtwoord opnieuw instellen",
    thatLinkNoLongerWorks: "Die link werkt niet meer",
    chooseANewPassword: "Kies een nieuw wachtwoord",
    confirmingYourEmail: "Je e-mail wordt bevestigd",
    pleaseWait: "Even geduld…",
    sendAResetLink: "Herstellink sturen",
    setPassword: "Wachtwoord instellen",
    oneMoment: "Een moment…",
    nothingToConfirm: "Niets te bevestigen.",
  },

  activeGameRoom: {
    leaveGame: "Spel verlaten",
    markedAfkByRoomVote: "De kamer heeft je door een stemming als afwezig gemarkeerd.",
    inviteLinkCopied: "Uitnodigingslink gekopieerd.",
    couldnTCopyLinkCopyFrom: "De link kon niet gekopieerd worden. Kopieer hem uit de adresbalk.",
    couldNotStartGamePleaseTry: "Het spel kon niet gestart worden. Probeer het nog eens.",
    couldNotStartRestartVote: "Er kon geen herstartstemming gestart worden.",
    couldNotRecordYourRestartVote: "Je herstartstem kon niet vastgelegd worden.",
    copyRoomInviteLink: "Uitnodigingslink van de kamer kopiëren",
    clickCopyRoomInviteLink: "Klik om de uitnodigingslink te kopiëren",
    roomMenu: "Kamermenu",
    afk: "Afwezig",
    saveImage: "Afbeelding opslaan",
    saveDrawnImageFile: "De tekening als bestand opslaan",
    playerSettings: "Spelerinstellingen",
    leaveRoom: "Kamer verlaten",
    leave: "Verlaten",
    players: "Spelers",
    youWereKickedFromThe: "Je bent uit de kamer gezet.",
    thisRoomWasOpenedIn: "Deze kamer is in een ander tabblad geopend.",
    startTheGame: "het spel starten",
    startARestartVote: "een herstartstemming beginnen",
    recordYourRestartVote: "je herstartstem uitbrengen",
    leaveDuringYourTurn: "Weggaan tijdens je beurt?",
    leaveActiveGame: "Lopend spel verlaten?",
    youReTheCurrentDrawer: "Jij tekent nu. Als je nu weggaat, wordt je beurt onderbroken en gaat het spel voor iedereen verder.",
    theGameIsStillIn: "Het spel is nog bezig. Je verlaat de kamer en geeft je plek in dit spel op.",
    restartVoteAvailableInRestartCooldownSeconds: (p: { restartCooldownSeconds: number }) =>
      `Herstartstemming mogelijk over ${p.restartCooldownSeconds} seconden`,
    proposeRestartingTheGame: "Voorstellen het spel te herstarten",
    restartVoteAvailableInRestartCooldownSeconds2: (p: { restartCooldownSeconds: number }) =>
      `Herstartstemming over ${p.restartCooldownSeconds} s`,
    proposeAVoteToRestart: "Een stemming voorstellen om het spel te herstarten",
    backFromAfk: "Terug van afwezig",
    goAfk: "Afwezig melden",
    closePlayers: "Spelers sluiten",
    acceptTheColorSuggestion: "de kleursuggestie accepteren",
    dismissTheColorSuggestion: "de kleursuggestie negeren",
    couldNotAcceptSuggestion: "De kleursuggestie kon niet worden geaccepteerd.",
    couldNotDismissSuggestion: "De kleursuggestie kon niet worden genegeerd.",
  },

  addEmailDialog: {
    followTheLink: (p: { address: string; replacing: boolean }) =>
      `Volg de link die naar ${p.address} is gestuurd. Tot die tijd hoort het adres niet bij je account en kun je er niets mee herstellen${
        p.replacing ? ", en het adres dat je had blijft staan." : "."
      }`,
    thatDoesNotLookLikeEmail: "Dat lijkt geen e-mailadres.",
    somethingWentWrongPleaseTryAgain: "Er ging iets mis. Probeer het nog eens.",
    done: "Klaar",
    usedOnlyResetYourPasswordTell: "Wordt alleen gebruikt om je wachtwoord te herstellen en om je te laten\n              weten of er iets met je account of met iets dat je deelde gebeurt.\n              Verder gaat hier nooit iets heen.",
    checkYourInbox: "Kijk in je inbox",
    changeYourEmailAddress: "Wijzig je e-mailadres",
    addAnEmailAddress: "Voeg een e-mailadres toe",
    newEmail: "Nieuw e-mailadres",
    email: "E-mail",
    pleaseWait: "Even geduld…",
    sendConfirmation: "Bevestiging sturen",
    close: "Sluiten",
    notNow: "Niet nu",
  },

  afkCheckDialog: {
    secondsUnit: (p: { count: number }) =>
      plural(p.count, { one: "seconde", other: "seconden" }),
    stillThere: "Ben je er nog?",
    youHaveBeenQuietWhileAnswer: "Je bent al een tijdje stil. Antwoord en je speelt door; anders zet de\n          kamer je op afwezig en gaat zonder jou verder.",
    stillTherePressButtonMoveMouse: "Ben je er nog? Druk op de knop, of beweeg de muis, om door te spelen.",
    iMHere: "Ik ben er",
  },

  app: {
    serverUpdateInProgress: (p: { seconds: number }) =>
      p.seconds > 0
        ? `Serverupdate bezig. Er kunnen geen nieuwe kamers of spellen starten; een lopend spel heeft nog ${counted(p.seconds, { one: "seconde", other: "seconden" })}.`
        : "Serverupdate bezig. Er kunnen geen nieuwe kamers of spellen starten; lopende spellen worden nu beëindigd.",
    thisTabOutDateCannotPlay: "Dit tabblad is verouderd en kan pas spelen als het herladen is.",
    reload: "Herladen",
    newRoomsArePausedMaintenanceGames: "Nieuwe kamers zijn gepauzeerd voor onderhoud. Spellen die al lopen gaan\n          gewoon door.",
    serverWasUpdatedBackAnyGame: "De server is bijgewerkt en is terug. Lopende spellen zijn beëindigd.",
    dismiss: "Sluiten",
  },

  appHeader: {
    playerSettings: "Spelerinstellingen",
  },

  bugReportDialog: {
    connectionSummary: (p: { connected: boolean; reconnects: number }) =>
      `${p.connected ? "verbonden" : "offline"} · ${counted(p.reconnects, {
        one: "herverbinding",
        other: "herverbindingen",
      })} dit bezoek`,
    couldNotTakeScreenshot: "De schermafbeelding kon niet gemaakt worden.",
    thanksYourReportWithPeopleWho: "Bedankt — je melding ligt bij de mensen die Sketchy draaien.",
    couldNotSendReport: "De melding kon niet verstuurd worden.",
    reportBug: "Een bug melden",
    somethingBrokenNotSomethingSomeoneSaid: "Iets dat stuk is, niet iets dat iemand zei. Dit komt bij de mensen die Sketchy draaien — nooit bij andere spelers.",
    where: "Waar",
    howBad: "Hoe erg",
    oneLineSummary: "Samenvatting in één regel",
    whatWentWrongOneLine: "Wat er misging, in één regel",
    whatHappened: "Wat er gebeurde",
    whatYouDidWhatYouExpected: "Wat je deed, wat je verwachtte, wat er in plaats daarvan gebeurde.",
    screenshot: "Schermafbeelding",
    optional: "Optioneel",
    screenshotThatWillBeSentWith: "De schermafbeelding die met deze melding meegaat",
    thisDialogHidesItselfWhileShot: "Dit venster verbergt zichzelf terwijl de opname wordt gemaakt, zodat je de pagina erachter krijgt. Bekijk hem voor je verstuurt — jij kiest wat je deelt.",
    replace: "Vervangen",
    remove: "Verwijderen",
    opensYourBrowserSOwnPicker: "Opent de kiezer van je browser — kies dit tabblad. Dit venster verbergt zichzelf tijdens de opname, zodat je de pagina erachter krijgt.",
    recentClientErrors: "Recente clientfouten",
    sendMyDescriptionOnly: "Alleen mijn beschrijving sturen",
    dropsDetailsAboveAnyScreenshotWe: "Laat de details hierboven en elke schermafbeelding vallen. We lezen het alsnog, maar de bug is dan veel lastiger na te doen.",
    cancel: "Annuleren",
    build: "Build",
    page: "Pagina",
    room: "Kamer",
    screen: "Scherm",
    browser: "Browser",
    connection: "Verbinding",
    waitingForThePicker: "Wachten op de kiezer…",
    attachAScreenshot: "Screenshot bijvoegen",
    whatWeAreLeavingOut: "Wat we weglaten",
    whatWeSendWithThis: "Wat we meesturen",
    noneOfThisIsBeing: "Niets hiervan wordt verstuurd — alleen je beschrijving hierboven.",
    theLast20ErrorsYour: "De laatste 20 fouten die je browser heeft vastgelegd. Geen paginaadressen verder dan het pad, niets wat je in de chat hebt getypt en nooit het woord dat in het spel is.",
    sending: "Versturen…",
    sendReport: "Melding versturen",
  },

  changePasswordDialog: {
    forgottenTheCurrentOne: "Het huidige vergeten?",
    twoNewPasswordsDoNotMatch: "De twee nieuwe wachtwoorden komen niet overeen.",
    passwordChangedEveryOtherDeviceHas: "Wachtwoord gewijzigd. Elk ander apparaat is uitgelogd.",
    couldNotChangePasswordPleaseTry: "Het wachtwoord kon niet gewijzigd worden. Probeer het nog eens.",
    ifThatAccountHasVerifiedEmail: "Als dat account een geverifieerd e-mailadres heeft, is er een link\n              onderweg om een nieuw wachtwoord in te stellen. Hij werkt één keer\n              en verloopt.",
    done: "Klaar",
    everyDeviceSignsOutWhenPassword: "Bij een wachtwoordwijziging logt elk apparaat uit, ook de apparaten die\n              je niet ingelogd wilde laten. Dit apparaat blijft.",
    currentPassword: "Huidig wachtwoord",
    newPassword: "Nieuw wachtwoord",
    newPasswordAgain: "Nieuw wachtwoord nogmaals",
    emailMeLinkInstead: "Stuur me liever een link",
    checkYourInbox: "Kijk in je inbox",
    changeYourPassword: "Wijzig je wachtwoord",
    pleaseWait: "Even geduld…",
    changePassword: "Wachtwoord wijzigen",
    close: "Sluiten",
    cancel: "Annuleren",
  },

  choosingPromptOverlay: {
    isChoosingPrompt: "{drawer} kiest een woord…",
    nextTurn: "Volgende beurt",
    drawingWillBeginAsSoonAs: "Het tekenen begint zodra de keuze gemaakt is.",
  },

  colorblindSafeSuggestionBanner: {
    colorblindSafeColorSuggestion: "Suggestie voor kleurenblindvriendelijke kleuren",
    playerThisRoomPlaysWithColorblind: "Een speler in deze kamer speelt met kleurenblindvriendelijke kleuren.",
    switchRoomPaletteFutureDrawings: "Het kleurenpalet van de kamer omzetten voor volgende tekeningen?",
    switchColors: "Kleuren omzetten",
    notNow: "Nu niet",
  },

  confirmationDialog: {
    cancel: "Annuleren",
  },

  crashPage: {
    couldNotSendReport: "De melding kon niet verstuurd worden.",
    bugCrawledOntoPage: "Er kroop een bug op de pagina",
    helpUsSquash: "Help ons hem te verpletteren",
    reportReadySendErrorWhatThis: "Er staat een melding klaar: de fout, en wat dit tabblad over zichzelf weet.\n            Hij komt bij de mensen die Sketchy draaien — nooit bij andere spelers.",
    whatWereYouDoing: "Wat was je aan het doen?",
    optional: "Optioneel",
    lastThingYouClickedTypedIf: "Het laatste dat je klikte of typte, als je het nog weet.",
    recentClientErrorsNewestFirst: "Recente clientfouten, nieuwste eerst",
    sendMyDescriptionOnly: "Alleen mijn beschrijving sturen",
    dropsDetailsAboveWeWillStill: "Laat de details hierboven vallen. We lezen het alsnog, maar de crash is dan veel lastiger te vinden.",
    thanksYourReportWithPeopleWho: "Bedankt — je melding ligt bij de mensen die Sketchy draaien.",
    reload: "Herladen",
    backLobby: "Terug naar de lobby",
    summary: "Samenvatting",
    build: "Build",
    page: "Pagina",
    room: "Kamer",
    screen: "Scherm",
    browser: "Browser",
    connection: "Verbinding",
    thisRoomSScreenHit: "Het scherm van deze kamer liep tegen een fout aan en moest stoppen. Je plek blijft even vrijgehouden: stuur de melding hieronder en herlaad dan om verder te gaan, of ga terug naar de lobby.",
    thisScreenHitAnError: "Dit scherm liep tegen een fout aan en moest stoppen. Je account en instellingen zijn veilig. Stuur de melding hieronder, dan kun je verder.",
    whatWeAreLeavingOut: "Wat we weglaten",
    whatWeSendWithThis: "Wat we meesturen",
    noneOfThisIsBeing: "Niets hiervan wordt verstuurd — alleen je beschrijving hierboven.",
    theCrashTheLast20: "De crash, de laatste 20 fouten die je browser heeft vastgelegd en waar op de pagina het gebeurde. Geen paginaadressen verder dan het pad, niets wat je in de chat hebt getypt en nooit het woord dat in het spel is.",
    sendingAgain: "Opnieuw versturen…",
    sending: "Versturen…",
    trySendingAgain: "Opnieuw proberen te versturen",
    sendReport: "Melding versturen",
  },

  createRoomPage: {
    setupTiming: "Deze opzet duurt {full} met een volle kamer van {capacity}",
    setupTimingFull: (p: { minutes: number }) =>
      `ongeveer ${counted(p.minutes, { one: "minuut", other: "minuten" })}`,
    setupTimingHalf: (p: { players: number }) => ` — eerder {half} als er ${p.players} meedoen`,
    couldNotLoadYourRoomPresets: "Je kamervoorinstellingen konden niet geladen worden.",
    couldNotApplyThatPreset: "Deze voorinstelling kon niet toegepast worden.",
    enterNameRoomPreset: "Geef de kamervoorinstelling een naam.",
    couldNotSaveThatPreset: "Deze voorinstelling kon niet opgeslagen worden.",
    couldNotUpdateThatPreset: "Deze voorinstelling kon niet bijgewerkt worden.",
    couldNotDeleteThatPreset: "Deze voorinstelling kon niet verwijderd worden.",
    fixCustomPromptEntriesMarkedAbove: "Verbeter de hierboven gemarkeerde eigen woorden voordat je de kamer maakt.",
    failedCreateRoom: "Kamer aanmaken mislukt",
    roomSetup: "Kameropzet",
    createRoom: "Een kamer maken",
    startFromSavedPreset: "Beginnen met een opgeslagen voorinstelling",
    startFromPreset: "Beginnen met een voorinstelling…",
    nameThisPreset: "Geef deze voorinstelling een naam",
    save: "Opslaan",
    cancel: "Annuleren",
    saveAsPreset: "Opslaan als voorinstelling",
    update: "Bijwerken",
    delete: "Verwijderen",
    undo: "Ongedaan maken",
    saveAsReusableList: "Opslaan als herbruikbare lijst",
    saveQuickPromptsAsA: "Bewaar snelle woorden als lijst en verwijder gedeelde codes voordat je een voorinstelling opslaat.",
    appliedName: (p: { name: string }) =>
      `‘${p.name}’ toegepast.`,
    savedName: (p: { name: string }) =>
      `‘${p.name}’ opgeslagen.`,
    updatedName: (p: { name: string }) =>
      `‘${p.name}’ bijgewerkt.`,
    deleteThisRoomSettingPreset: "Deze kamervoorinstelling verwijderen?",
    createTheRoom: "de kamer maken",
    noScoring: "Zonder punten",
    public: "Openbaar",
    private: "Privé",
    backToLobby: "Terug naar de lobby",
    leaveBlankForARandom: "Laat leeg voor een willekeurige naam!",
    creating: "Maken…",
    createRoom2: "Kamer maken",
  },

  customPromptsEditor: {
    usableCount: (p: { count: number }) =>
      counted(p.count, { one: "bruikbaar eigen woord", other: "bruikbare eigen woorden" }),
    duplicatesIgnored: (p: { count: number }) =>
      `${counted(p.count, { one: "dubbele", other: "dubbele" })} genegeerd`,
    entriesTooLong: (p: { count: number; limit: number }) =>
      `${counted(p.count, { one: "invoer is", other: "invoeren zijn" })} langer dan ${number(p.limit)} tekens`,
    entryLimit: (p: { limit: number }) => `Er zijn maar ${number(p.limit)} invoeren toegestaan`,
    customPromptsOptional: "Eigen woorden (optioneel)",
    onePromptPerLineSeparateEntries: "Eén woord per regel\nof scheid invoeren met komma’s",
    shortenRemoveOverlongEntriesBeforeCreating: "Kort de te lange invoeren in of haal ze weg voordat je de kamer maakt.",
  },

  customPromptsPreview: {
    resultsMatching: (p: { shown: number; total: number }) =>
      `${number(p.shown)} van de ${number(p.total)} woorden komen overeen`,
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "woord", other: "woorden" }),
    customPromptCount: (p: { count: number }) =>
      counted(p.count, { one: "eigen woord", other: "eigen woorden" }),
    inspectPrompts: (p: { count: number }) =>
      `${counted(p.count, { one: "eigen woord", other: "eigen woorden" })} bekijken`,
    couldNotLoadCustomPrompts: "De eigen woorden konden niet geladen worden",
    loadingCustomPrompts: "Eigen woorden laden…",
    roomPromptCollection: "Woordenverzameling van de kamer",
    readOnlyListSuppliedByRoom: "Alleen-lezen lijst van de gastheer.",
    findPrompt: "Een woord vinden",
    searchCustomPrompts: "Zoek in de eigen woorden…",
    filterPromptsByLength: "Woorden filteren op lengte",
    noCustomPromptsMatchTheseFilters: "Geen eigen woorden passen bij deze filters.",
    all: "Alle",
    allPromptLengths: "Alle woordlengtes",
    short: "Kort",
    n5CharactersOrFewer: "5 tekens of minder",
    medium: "Middel",
    n6To10Characters: "6 tot 10 tekens",
    long: "Lang",
    n11CharactersOrMore: "11 tekens of meer",
    loadTheCustomPrompts: "de eigen woorden laden",
  },

  deleteAccountDialog: {
    whatIsRemoved: (p: { isGuest: boolean }) =>
      `${
        p.isGuest
          ? "De naam, de punten en de geschiedenis die bij deze browser horen worden verwijderd."
          : "Je naam wordt verwijderd uit de spellen die je speelde."
      } De scores en tekeningen blijven, onder „Verwijderde speler”, want het zijn ook de spellen van anderen. Dit kan niet ongedaan gemaakt worden.`,
    typeToConfirm: (p: { word: string }) => `Typ ${p.word} om te bevestigen`,
    couldNotDeleteAccount: "Het account kon niet verwijderd worden.",
    password: "Wachtwoord",
    deleteThisGuest: "Deze gast verwijderen",
    deleteYourAccount: "Je account verwijderen",
    deleting: "Verwijderen…",
    deleteForGood: "Voorgoed verwijderen",
    keepPlaying: "Blijven spelen",
    keepMyAccount: "Mijn account houden",
  },

  drawingReactionControl: {
    reactionSummary: (p: { total: number; chips: string }) =>
      `${counted(p.total, { one: "reactie", other: "reacties" })}: ${p.chips}`,
    thatReactionCouldNotBeSent: "Deze reactie kon niet verstuurd worden.",
    reactThisDrawing: "Reageren op deze tekening",
    reactions: "Reacties",
    createAccountReact: "Maak een account om te reageren.",
    createAccount: "Account maken",
    noReactionsYet: "Nog geen reacties",
    reactToThisDrawingSummary: (p: { summary: string }) =>
      `Reageer op deze tekening. ${p.summary}`,
    labelYourReactionPressTo: (p: { label: string }) =>
      `${p.label}, jouw reactie. Druk om hem te verwijderen`,
  },

  drawingRecapGallery: {
    drawingLabel: (p: { prompt: string; drawer: string }) =>
      `Tekening van ${p.prompt} door ${p.drawer}`,
    drawnBy: "Getekend door {drawer} · Ronde {round} · Beurt {turn}",
    position: (p: { position: number; total: number }) => `${p.position} van ${p.total}`,
    thisDrawingCouldNotBeDecoded: "Deze tekening kon niet gedecodeerd worden.",
    drawingRecap: "Tekeningenoverzicht",
    saveImage: "Afbeelding opslaan",
    close: "Sluiten",
    thisDrawingWasNotKept: "Deze tekening is niet bewaard.",
    roomRanOutRoomLaterTurns: "De kamer had er geen ruimte meer voor. In plaats daarvan zijn latere beurten bewaard.",
    tryAgain: "Opnieuw proberen",
    loadingDrawing: "Tekening laden…",
    noDrawingWasCapturedThisTurn: "Voor deze beurt is geen tekening vastgelegd.",
    drawingRecapNavigation: "Navigatie van het tekeningenoverzicht",
    previous: "Vorige",
    next: "Volgende",
    loadThisDrawing: "deze tekening laden",
  },

  emailRecoveryReminder: {
    addEmail: "Een e-mailadres toevoegen",
    dismiss: "Sluiten",
    confirmPendingAddressToFinishSetting: (p: { pendingAddress: string }) =>
      `Bevestig ${p.pendingAddress} om accountherstel af te ronden.`,
    thisAccountHasNoEmail: "Dit account heeft geen e-mailadres, dus een vergeten wachtwoord kan niet opnieuw worden ingesteld.",
  },

  firstRunIdentity: {
    couldNotSaveThatNamePlease: "Deze naam kon niet opgeslagen worden. Probeer het nog eens.",
    keepYourUsernameYourStatsEvery: "Houd je gebruikersnaam en je statistieken op elk apparaat.",
    createAccount: "Een account maken",
    logIn: "Inloggen",
    or: "of",
    displayName: "Weergavenaam",
    beenHereBefore: "Al eens hier geweest?",
    playAsYourself: "Speel als jezelf",
    whatShouldWeCallYou: "Hoe mogen we je noemen?",
    justPlayingOncePickA: "Speel je maar één keer? Kies een weergavenaam",
    play: "Spelen",
    playAsGuest: "Spelen als gast",
  },

  friendButton: {
    requestSentTo: (p: { name: string }) => `Vriendschapsverzoek gestuurd naar ${p.name}`,
    addFriend: "Vriend toevoegen",
    acceptRequest: "Verzoek accepteren",
    requestSent: "Verzoek verstuurd",
  },

  friendInviteNotice: {
    couldNotJoinThatGame: "Dit spel kon niet betreden worden.",
    thatGameCouldNotBeJoined: "Dit spel kon niet betreden worden.",
    invitedYouTheirGame: "heeft je uitgenodigd voor zijn spel.",
    join: "Meedoen",
    dismissInvitation: "Uitnodiging sluiten",
  },

  friendsOverlay: {
    declineWarning: (p: { name: string }) =>
      `${p.name} kan het niet opnieuw vragen. Jij kunt hem later zelf een verzoek sturen.`,
    decline2: "Afwijzen",
    youWillBothStopBeingAble: "Jullie kunnen dan allebei niet meer zonder uitnodiging bij elkaars spellen. Ieder van jullie kan het opnieuw vragen.",
    remove2: "Verwijderen",
    removeConfirm: (p: { name: string }) => `${p.name} verwijderen?`,
    friends: "Vrienden",
    close: "Sluiten",
    closeFriends: "Vrienden sluiten",
    friendsNeedAccountGuestNameBelongs: "Voor vrienden heb je een account nodig. Een gastnaam hoort bij deze\n              browser en niet bij jou, dus over een maand zou er niemand meer\n              zijn om bevriend mee te zijn.",
    loading: "Laden…",
    noFriendsYetAddSomebodyFrom: "Nog geen vrienden. Voeg iemand toe vanuit de lobby, of vanuit een spel\n              waar jullie allebei in zitten.",
    requests: "Verzoeken",
    accept: "Accepteren",
    decline: "Afwijzen",
    sent: "Verstuurd",
    cancel: "Annuleren",
    remove: "Verwijderen",
    declineThisRequest: "Dit verzoek afwijzen?",
    recentlyPlayedWith: "Onlangs mee gespeeld",
  },

  gameEndOverlay: {
    continueLabel: "Verder",
    youFinished: (p: { points: number }) =>
      `Je bent {place} geworden met ${counted(p.points, { one: "punt", other: "punten" })}.`,
    continueToWaitingRoom: "Door naar de wachtkamer",
    continueWithCountdown: (p: { seconds: number }) =>
      `Door naar de wachtkamer, nog ${counted(p.seconds, { one: "seconde", other: "seconden" })}`,
    gameOver: "Spel afgelopen",
    you: "jij",
    friend: "Vriend",
    noScoresThisTimeJustRoom: "Deze keer geen punten — alleen een kamer vol schetsen en gokken.",
    keep: "Houden",
    asYourUsername: "als je gebruikersnaam",
    createAccount: "Account maken",
    highlights: "Hoogtepunten",
    drawings: "Tekeningen",
    stayHere: "Hier blijven",
    aGreatGameOfDrawing: "Een geweldig tekenspel",
    theRoomTakesTheCrown: "De hele kamer pakt de kroon!",
    winnersCountPlayersShareTheCrown: (p: { winnersCount: number }) =>
      `${p.winnersCount} spelers delen de kroon!`,
    takesTheCrown: " pakt de kroon!",
    shareTheCrown: " delen de kroon!",
  },

  gameHighlightsPanel: {
    lastGame: "Laatste spel",
    highlights: "Hoogtepunten",
    closeHighlights: "Hoogtepunten sluiten",
    thatGameWasTooShortSay: "Dat spel was te kort om er veel over te zeggen. Speel een langere en de\n            hoogtepunten verschijnen hier.",
    seeIt: "Bekijken",
    back: "Terug",
  },

  inviteEntryPage: {
    roomCode: (p: { code: string }) => `Kamer ${p.code}`,
    hereCount: (p: { here: number; capacity: number; full: boolean }) =>
      `${p.here}/${p.capacity} hier${p.full ? " · vol" : ""}`,
    roomSummary: (p: { rounds: number; seconds: number; hintMode: string }) =>
      `${counted(p.rounds, { one: "ronde", other: "rondes" })} · ${p.seconds}s · ${p.hintMode}`,
    checkingYourInvite: "Je uitnodiging controleren…",
    loadingRoomDetails: "Kamergegevens laden.",
    roomUnavailable: "Kamer niet beschikbaar",
    backLobby: "Terug naar de lobby",
    players: "Spelers",
    rounds: "Rondes",
    drawTime: "Tekentijd",
    scoring: "Punten",
    roomRules: "Kamerregels",
    thisGameAlreadyProgressJoiningAs: "Dit spel is al bezig. Als speler kom je in een latere beurt aan de beurt.",
    playerSlotsAreFullSpectatingStill: "De spelersplekken zijn vol. Toekijken kan nog wel.",
    promptDetailsHidden: "Woorddetails verborgen",
    timedHints: "Hints op tijd",
    buyableLetterHints: "Letterhints om te kopen",
    wheelOfFortune: "Rad van fortuin",
    noLetterHints: "Geen letterhints",
    publicRoom: "Openbare kamer",
    privateInvite: "Privé-uitnodiging",
    inProgress: "Bezig",
    waiting: "Wachten",
    full: " · Vol",
    noScoring: "Zonder punten",
    pressure: "Druk",
    default: "Standaard",
    everyToolAndColor: "Alle gereedschappen en kleuren",
    spectatorsCanSeeThePrompt: "Toeschouwers zien het woord",
    spectatorsGuessAlong: "Toeschouwers raden mee",
    defaultPromptList: "Standaard woordenlijst",
    roomFull: "Kamer vol",
    joining: "Deelnemen…",
    joinGameInProgress: "Meedoen aan lopend spel",
    joinGame: "Meedoen",
    spectate: "Kijken",
    customPromptsOnly: (p: { count: number }) =>
      `alleen ${counted(p.count, { one: "eigen woord", other: "eigen woorden" })}`,
    customPromptsPlusDefaults: (p: { count: number }) =>
      `${counted(p.count, { one: "eigen woord", other: "eigen woorden" })} plus standaardwoorden`,
  },

  inviteFriendsList: {
    invitationCouldNotBeSent: "Deze uitnodiging kon niet verstuurd worden.",
    invitationSent: (p: { name: string }) => `Uitnodiging gestuurd naar ${p.name}.`,
    thatInvitationCouldNotBeSent: "Deze uitnodiging kon niet verstuurd worden.",
    friendsLobby: "Vrienden in de lobby",
    invited: "Uitgenodigd",
    invite: "Uitnodigen",
  },

  languagePicker: {
    currentChoice: (p: { label: string; value: string }) => `${p.label}: ${p.value}`,
    everyLanguage: "Alle talen",
  },

  lobbyBrowserPage: {
    filterByLanguage: "Filteren op taal",
    filtersWithCount: (p: { count: number }) =>
      p.count > 0 ? `Filters · ${p.count}` : "Filters",
    showRooms: (p: { count: number }) =>
      `${counted(p.count, { one: "kamer", other: "kamers" })} tonen`,
    removedFromRoom: "Uit de kamer verwijderd",
    ok: "Oké",
    roomCode: "Kamercode",
    abc123: "ABC123",
    thereNoRoomCodeClipboard: "Er staat geen kamercode op het klembord.",
    sketchyCouldNotReadClipboardPaste: "Sketchy kon het klembord niet lezen. Plak in plaats daarvan in de vakjes.",
    pleaseEnterRoomCode: "Voer een kamercode in",
    failedJoinRoom: "Deelnemen aan de kamer mislukt",
    joinByCode: "Meedoen met een code",
    createRoom: "Kamer maken",
    publicRooms: "Openbare kamers",
    searchRoomsByNameCode: "Zoek kamers op naam of code",
    hideFull: "Volle verbergen",
    hideProgress: "Lopende verbergen",
    filters: "Filters",
    clearFilters: "Filters wissen",
    language: "Taal",
    hideFullRooms: "Volle kamers verbergen",
    hideGamesProgress: "Lopende spellen verbergen",
    loadingPublicRooms: "Openbare kamers laden…",
    noPublicRoomsYetCreateOne: "Nog geen openbare kamers. Maak er een!",
    noPublicRoomsMatchYourSearch: "Geen openbare kamers passen bij je zoekopdracht.",
    createRoom2: "Een kamer maken",
    joinWithCode: "Meedoen met een code",
    paste: "Plakken",
    couldNotSaveThatName: "Die naam kon niet worden opgeslagen. Probeer het nog eens.",
    joinAsASpectator: "als toeschouwer meedoen",
    joinTheRoom: "de kamer in gaan",
    loading: "Laden…",
    showingFilteredRoomsCountOfRoomsCount: (p: { filteredRoomsCount: number; roomsCount: number }) =>
      `${p.filteredRoomsCount} van ${p.roomsCount} getoond`,
    n0Rooms: "0 kamers",
    close: "Sluiten",
    joining: "Deelnemen…",
    joinTheRoom2: "De kamer in gaan",
    joiningAsSpectator: "Meedoen als toeschouwer…",
    watchWithoutPlaying: "Kijken zonder te spelen",
  },

  lobbyChatPanel: {
    reportThisLine: (p: { name: string }) => `Deze regel van ${p.name} melden`,
    couldNotSendThat: "Dat kon niet verstuurd worden.",
    chat: "Chat",
    lobbyChat: "Lobbychat",
    nobodyHasSaidAnythingYet: "Niemand heeft nog iets gezegd.",
    chooseNameChat: "Kies een naam om te chatten",
    saySomethingLobby: "Zeg iets tegen de lobby…",
    lobbyChatMessage: "Lobbychatbericht",
    send: "Versturen",
    couldNotSaveThatName: "Die naam kon niet worden opgeslagen. Probeer het nog eens.",
    sendTheMessage: "het bericht versturen",
  },

  lobbyPlayerMenu: {
    whatToDoAbout: (p: { name: string }) => `Wat te doen met ${p.name}`,
    openPlayerProfile: "Spelersprofiel openen",
    addAsFriend: "Als vriend toevoegen",
    report: "Melden",
  },

  myPromptListsPage: {
    listSummary: (p: { prompts: number; visibility: string; moderationState: string | null }) =>
      `${counted(p.prompts, { one: "woord", other: "woorden" })} · ${p.visibility}${
        p.moderationState ? ` · ${p.moderationState}` : ""
      }`,
    listUnderReview: (p: { state: string }) =>
      `Deze lijst is ${p.state} en kan niet in nieuwe spellen gebruikt worden. Bewerken zet hem niet automatisch terug; een moderator moet de lijst bekijken.`,
    needsReview: (p: { count: number }) => `Te beoordelen (${p.count})`,
    removePrompt: (p: { prompt: string }) => `${p.prompt} verwijderen`,
    couldNotLoadYourPromptLists: "Je woordenlijsten konden niet geladen worden.",
    couldNotOpenThatPromptList: "Deze woordenlijst kon niet geopend worden.",
    addAtLeastOnePromptBefore: "Voeg minstens één woord toe voordat je opslaat.",
    couldNotSaveThisPromptList: "Deze woordenlijst kon niet opgeslagen worden.",
    couldNotDeleteThisPromptList: "Deze woordenlijst kon niet verwijderd worden.",
    yourLibrary: "Je bibliotheek",
    reusablePromptLists: "Herbruikbare woordenlijsten",
    newList: "Nieuwe lijst",
    createAccountSaveReviseSharePrompt: "Maak een account om woordenlijsten te bewaren, te herzien en te delen. Snelle kamerwoorden blijven lokaal en vluchtig.",
    yourPromptLists: "Je woordenlijsten",
    loading: "Laden…",
    noSavedListsYet: "Nog geen opgeslagen lijsten.",
    name: "Naam",
    description: "Beschrijving",
    language: "Taal",
    visibility: "Zichtbaarheid",
    private: "Privé",
    anyoneWithCode: "Iedereen met de code",
    shareCode: "Deelcode",
    couldNotCopyShareCode: "De deelcode kon niet gekopieerd worden.",
    copy: "Kopiëren",
    addPrompts: "Woorden toevoegen",
    onePromptPerLineSeparateEntries: "Eén woord per regel\nof scheid invoeren met komma’s",
    addList: "Aan de lijst toevoegen",
    noPromptsYetPasteSomeAbove: "Nog geen woorden. Plak er hierboven een paar om te beginnen.",
    thisList: "In deze lijst",
    searchPrompts: "Woorden zoeken",
    nothingMatchesThatSearch: "Niets past bij die zoekopdracht.",
    deleteList: "Lijst verwijderen…",
    promptListSaved: "Woordenlijst opgeslagen.",
    deleteThisPromptListAnd: "Deze woordenlijst en al haar versies verwijderen?",
    promptListDeleted: "Woordenlijst verwijderd.",
    backToLobby: "Terug naar de lobby",
    promptsCountOfMaxListPrompts: (p: { promptsCount: number; MAX_LIST_PROMPTS: number }) =>
      `${p.promptsCount} van ${p.MAX_LIST_PROMPTS} woorden in deze lijst`,
    saving: "Opslaan…",
    saveList: "Lijst opslaan",
  },

  notFoundPage: {
    nobodyDrewThisPage: "Deze pagina heeft niemand getekend",
    thatLinkDoesnTLeadAnywhere: "Die link leidt nergens heen op Sketchy.",
    backLobby: "Terug naar de lobby",
  },

  onlinePlayersPanel: {
    couldNotJoinThatGame: "Dit spel kon niet betreden worden.",
    whoOnline: "Wie er online is",
    nobodyElseHereRightNow: "Er is op dit moment niemand anders.",
    friend: "Vriend",
    join: "Meedoen",
    inAGame: "In een spel",
    inTheLobby: "In de lobby",
  },

  pictureCropDialog: {
    fileNotAPicture: "Dit bestand kon niet als afbeelding gelezen worden.",
    couldNotSetThatPicturePlease: "Deze afbeelding kon niet ingesteld worden. Probeer het nog eens.",
    frameYourPicture: "Je afbeelding uitsnijden",
    dragMoveZoomGetCloserCircle: "Sleep om hem te verplaatsen en zoom in om dichterbij te komen. De cirkel is wat iedereen ziet.",
    pictureFramedArrowKeysMovePlus: "De uitgesneden afbeelding. Pijltjestoetsen verplaatsen; plus en min zoomen.",
    zoom: "Zoom",
    cancel: "Annuleren",
    uploading: "Uploaden…",
    usePicture: "Afbeelding gebruiken",
  },

  playerList: {
    requestCouldNotBeSent: "Dit verzoek kon niet verstuurd worden.",
    nowFriends: (p: { name: string }) => `Jij en ${p.name} zijn nu vrienden.`,
    friendRequestSent: (p: { name: string }) => `Vriendschapsverzoek gestuurd naar ${p.name}.`,
    nothingToDoAbout: (p: { name: string }) => `Er valt nu niets te doen met ${p.name}.`,
    rank: (p: { rank: number }) => `Plek ${p.rank}`,
    moderationFor: (p: { name: string }) => `Moderatie voor ${p.name}`,
    moderationActionsFor: (p: { name: string }) => `Moderatieacties voor ${p.name}`,
    thatRequestCouldNotBeSent: "Dit verzoek kon niet verstuurd worden.",
    drawing: "Tekent",
    gotIt: "Geraden ·",
    afk: "Afwezig",
    you: "(jij)",
    host: "Gastheer",
    friend: "Vriend",
    disconnected: "Verbinding verbroken",
    kick: "Eruit zetten",
    addFriend: "Vriend toevoegen",
    sendRequest: "Een verzoek sturen",
    report: "Melden",
    toAModerator: "Naar een moderator",
    voteAfkOrKickOr: "Stem afwezig of eruit, of meld",
    reportThisPlayer: "Deze speler melden",
    undoVote: "Stem intrekken",
    vote: "Stemmen",
    voteKindAfk: "Afwezig",
    voteKindKick: "Eruit",
    undoVoteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Stem ${p.kind} voor ${p.nickname} intrekken, ${p.count} van ${p.required}`,
    voteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Stem ${p.kind} voor ${p.nickname}, ${p.count} van ${p.required}`,
    votesFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Stemmen ${p.kind} voor ${p.nickname}, ${p.count} van ${p.required}`,
    votesForIncludingYours: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Stemmen ${p.kind} voor ${p.nickname}, ${p.count} van ${p.required}, inclusief die van jou`,
  },

  profilePage: {
    gamesPlayed: "Gespeelde spellen",
    gamesWon: "Gewonnen spellen",
    winRate: "Winstpercentage",
    averageScore: "Gemiddelde score",
    turnsPlayed: "Gespeelde beurten",
    promptsGuessed: "Geraden woorden",
    drawingsMade: "Gemaakte tekeningen",
    reactionsReceived: "Ontvangen reacties",
    totalScore: "Totale score",
    noSuchProfile: "Er is geen speler met dat profiel.",
    couldNotLoadProfile: "Dit profiel kon niet geladen worden. Probeer het nog eens.",
    gameMeta: (p: { finishedAt: string; rounds: number; players: number }) =>
      `${p.finishedAt} · ${counted(p.rounds, { one: "ronde", other: "rondes" })} · ${counted(p.players, { one: "speler", other: "spelers" })}`,
    seatScore: (p: { points: number }) => `${number(p.points)} ptn`,
    gameRules: (p: {
      scoringMode: string;
      scoringVersion: number;
      hintMode: string;
      seconds: number;
      promptSource: string;
    }) =>
      `Regels: ${p.scoringMode} puntentelling${
        p.scoringVersion > 0 ? ` v${p.scoringVersion}` : " (oude versie onbekend)"
      } · ${p.hintMode} hints · ${p.seconds} seconden · ${p.promptSource} woorden`,
    reportPlayer: (p: { name: string }) => `${p.name} melden`,
    privateRoom: "privékamer",
    thisGameDidNotFinishSo: "Dit spel is niet uitgespeeld, dus dit zijn de punten zoals ze stonden\n              toen het stopte en geen eindstand.",
    loadingTurns: "Beurten laden…",
    turnByTurn: "Beurt voor beurt",
    round: "Ronde",
    prompt: "Woord",
    drawnBy: "Getekend door",
    time: "Tijd",
    drawing: "Tekent",
    reactions: "Reacties",
    guesserOutcomes: "Resultaten van de raders",
    view: "Bekijken",
    couldNotLoadMoreGames: "Er konden geen spellen meer geladen worden.",
    loading: "Laden…",
    friend: "Vriend.",
    claimYourAccount: "Claim je account",
    yourGamesAreAlreadyBeingRecorded: "Je spellen worden al vastgelegd onder deze weergavenaam.\n                Maak een account om ze te houden en hem als gebruikersnaam op elk apparaat te gebruiken.",
    createAccount: "Account maken",
    statistics: "Statistieken",
    gameHistory: "Spelgeschiedenis",
    includeGamesThatFellApart: "Ook spellen die uiteenvielen",
    notKept: "niet bewaard",
    nothingDrawn: "niets getekend",
    onlyThePlayersInThis: "Alleen de spelers van dit spel kunnen de beurten zien.",
    couldNotLoadTheTurns: "De beurten van dit spel konden niet worden geladen.",
    cutShort: "afgebroken",
    noAttempt: "geen poging",
    joinedLate: "later ingestapt",
    notEligibleEligibilityReason: (p: { eligibilityReason: string }) =>
      `telt niet mee (${p.eligibilityReason})`,
    unknownPlayer: "Onbekende speler",
    backToLobby: "Terug naar de lobby",
    guestDisplayNameNotSaved: "Gast — weergavenaam niet opgeslagen",
    registeredPlayer: "Geregistreerde speler",
    noFinishedGamesYetPlay: "Nog geen afgeronde spellen. Speel er een en hij verschijnt hier.",
    noGamesToShowGames: "Geen spellen om te tonen. Spellen uit privékamers zijn alleen zichtbaar voor wie erbij was.",
    loadHistoryPageSizeMore: (p: { HISTORY_PAGE_SIZE: number }) =>
      `Nog ${p.HISTORY_PAGE_SIZE} laden`,
  },

  promptContentReportDialog: {
    reportList: (p: { name: string }) => `${p.name} melden`,
    couldNotSendReport: "De melding kon niet verstuurd worden.",
    reportsAreReviewedAfterSubmissionList: "Meldingen worden na het versturen bekeken. De lijst blijft beschikbaar tenzij een moderator hem verbergt.",
    content: "Inhoud",
    entireList: "Hele lijst",
    reason: "Reden",
    whatShouldModeratorKnow: "Wat moet de moderator weten?",
    cancel: "Annuleren",
    inappropriateContent: "Ongepaste inhoud",
    hatefulOrAbusiveContent: "Haatdragende of kwetsende inhoud",
    sexualContent: "Seksuele inhoud",
    violence: "Geweld",
    spam: "Spam",
    other: "Anders",
    sending: "Versturen…",
    sendReport: "Melding versturen",
  },

  promptDisplay: {
    couldNotDoAction: (p: { action: string }) =>
      `Dat is niet gelukt: ${p.action}.`,
    nextHintCost: (p: { cost: number }) => `Volgende hint: ${p.cost}`,
    hintSpendTotal: (p: { spent: number }) => `Totaal: ${p.spent}`,
    buyLetter: (p: { letter: string; price: number }) =>
      `„${p.letter}” kopen voor ${counted(p.price, { one: "punt", other: "punten" })}`,
    maskedPrompt: (p: { shape: string }) => `Verborgen woord, ${p.shape} letters`,
    buyThisLetter: (p: { cost: number }) =>
      `Deze letter kopen voor ${counted(p.cost, { one: "punt", other: "punten" })}`,
    letterCount: (p: { count: number }) =>
      counted(p.count, { one: "letter", other: "letters" }),
    yourTurn: "Jouw beurt",
    pickSomethingDraw: "Kies iets om te tekenen",
    autoPicksWhenTimeRunsOut: "Kiest vanzelf als de tijd om is.",
    hintSpendLimitReached: "Hintlimiet bereikt",
    deductedFromYourScoreIfYou: "Wordt van je punten afgetrokken als je het woord raadt",
    buyLetterRevealsEveryMatch: "Koop een letter — laat elke plek zien",
    selectThePrompt: "het woord kiezen",
    choosing: "Kiezen…",
    buyTheHint: "de hint kopen",
    buyTheLetterHint: "de letterhint kopen",
  },

  promptListPicker: {
    languageMismatch: (p: { listLanguage: string; roomLanguage: string }) =>
      `Die lijst is in het ${p.listLanguage}; deze kamer is in het ${p.roomLanguage}.`,
    choicesUnavailable: (p: { reason: string }) =>
      `De keuze uit woordenlijsten is niet beschikbaar (${p.reason}). Je huidige keuze blijft staan.`,
    noListsInLanguage: (p: { language: string }) =>
      `Nog geen woordenlijsten in het ${p.language} — deze kamer gebruikt eigen woorden.`,
    howListPlays: (p: { name: string }) => `Hoe woorden uit ${p.name} spelen`,
    reportList: (p: { name: string }) => `${p.name} melden`,
    failedLoadPromptLists: "Woordenlijsten laden mislukt",
    couldNotAddThatSharedList: "Deze gedeelde lijst kon niet toegevoegd worden.",
    loadingCuratedPromptLists: "Woordenlijsten laden…",
    promptLists: "Woordenlijsten",
    addUnlistedListByCode: "Een niet-vermelde lijst toevoegen met een code",
    namePromptCountPrompts: (p: { name: string; promptCount: number }) =>
      `${p.name} (${p.promptCount} woorden)`,
    adding: "Toevoegen…",
    add: "Toevoegen",
    reportSentForModeratorReview: "Melding naar de moderators gestuurd.",
  },

  promptStatsPage: {
    noSuchList: "Er is geen woordenlijst met die naam.",
    couldNotLoadStats: "Deze woordstatistieken konden niet geladen worden. Probeer het nog eens.",
    showMore: (p: { count: number }) => `Nog ${p.count} tonen`,
    showingOf: (p: { shown: number; total: number }) => `${p.shown} van de ${p.total} getoond`,
    couldNotLoadPromptListsPlease: "De woordenlijsten konden niet geladen worden. Probeer het nog eens.",
    serverWide: "Serverbreed",
    promptStats: "Woordstatistieken",
    everyPromptListHowHasActually: "Elk woord in de lijst, en hoe het echt gespeeld heeft in afgeronde\n          spellen op deze server.",
    promptList: "Woordenlijst",
    sort: "Sortering",
    period: "Periode",
    scoring: "Punten",
    hints: "Hints",
    findPrompt: "Een woord vinden",
    rollerCoaster: "achtbaan",
    loading: "Laden…",
    prompt: "Woord",
    howGoes: "Hoe het loopt",
    guessed: "Geraden",
    picked: "Gekozen",
    drawn: "Getekend",
    allTime: "Altijd",
    last30Days: "Laatste 30 dagen",
    last90Days: "Laatste 90 dagen",
    allScoringModes: "Alle puntenmodi",
    noScoring: "Zonder punten",
    defaultScoring: "Standaardpunten",
    pressureScoring: "Drukpunten",
    allHintModes: "Alle hintmodi",
    noHints: "Geen hints",
    checkpointHints: "Hints op tijd",
    purchasedHints: "Gekochte hints",
    letterWheel: "Letterrad",
    backToLobby: "Terug naar de lobby",
  },

  publicRoomCard: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "ronde", other: "rondes" }),
    promptLanguage: (p: { language: string }) => `Woordtaal: ${p.language}`,
    seeWhoThisRoom: "Zien wie er in deze kamer is",
    rounds: "Rondes",
    drawingTime: "Tekentijd",
    full: "Vol",
    inProgress: "Bezig",
    looking: "Zoeken…",
    nobodySeatedYet: "Er zit nog niemand.",
    host: "Gastheer",
    couldNotReadWhoIs: "Kon niet lezen wie er in deze kamer zit.",
    joining: "Deelnemen…",
    join: "Meedoen",
    spectate: "Kijken",
  },

  reactionRequests: {
    thatReactionCouldNotBeSent: "Deze reactie kon niet verstuurd worden.",
  },

  recapDrawings: {
    thisDrawingCouldNotBeLoaded: "Deze tekening kon niet geladen worden.",
  },

  reportAccountDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Een moderator ziet dit. Er gebeurt nu niets met ${p.name}, en er wordt niet verteld wie het meldde.`,
    theirPicture: (p: { name: string }) => `afbeelding van ${p.name}`,
    thatReportCouldNotBeSent: "Deze melding kon niet verstuurd worden. Probeer het nog eens.",
    whatWrongWith: "Wat er mis mee is",
    reportedTheirNameTheyHaveNo: "Gemeld om de naam. Er is geen afbeelding om te melden.",
    anythingElseOptional: "Nog iets (optioneel)",
    anythingModeratorShouldKnow: "Alles wat een moderator zou moeten weten",
    sentWithWhatAboutAttached: "Verstuurd, met het onderwerp erbij.",
    done: "Klaar",
    inappropriateName: "Ongepaste naam",
    inappropriatePicture: "Ongepaste afbeelding",
    reportSent: "Melding verstuurd",
    reportDisplayName: (p: { displayName: string }) =>
      `${p.displayName} melden`,
    thePictureOnTheAccount: "De afbeelding van het account wordt bijgevoegd zoals die nu is.",
    theNameOnTheAccount: "De naam van het account wordt bijgevoegd zoals die nu is.",
    sending: "Versturen…",
    sendReport: "Melding versturen",
    close: "Sluiten",
    cancel: "Annuleren",
  },

  reportedDrawing: {
    thisDrawingCouldNotBeDecoded: "Deze tekening kon niet gedecodeerd worden.",
    drawingCouldNotBeLoaded: "De tekening kon niet geladen worden.",
    loadingTheDrawing: "Tekening laden…",
  },

  reportLobbyLineDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Een moderator ziet deze regel. Er gebeurt nu niets met ${p.name}, en er wordt niet verteld wie het meldde.`,
    thatReportCouldNotBeSent: "Deze melding kon niet verstuurd worden. Probeer het nog eens.",
    whatWrongWith: "Wat er mis mee is",
    anythingElseOptional: "Nog iets (optioneel)",
    anythingModeratorShouldKnow: "Alles wat een moderator zou moeten weten",
    thisLineAttachedWithWhatLobby: "Deze regel zit erbij, met wat de lobby eromheen zei.",
    sentWithLineWhatWasSaid: "Verstuurd, met de regel en wat eromheen gezegd is.",
    done: "Klaar",
    harassmentOrAbuse: "Intimidatie of misbruik",
    spam: "Spam",
    inappropriateName: "Ongepaste naam",
    reportSent: "Melding verstuurd",
    reportDisplayName: (p: { displayName: string }) =>
      `${p.displayName} melden`,
    sending: "Versturen…",
    sendReport: "Melding versturen",
    close: "Sluiten",
    cancel: "Annuleren",
  },

  reportPlayerDialog: {
    reportCouldNotBeSent: "Deze melding kon niet verstuurd worden.",
    recentMessages: (p: { count: number }) =>
      `${p.count} van hun ${plural(p.count, { one: "recente bericht", other: "recente berichten" })}`,
    nothingHappensYet: (p: { name: string }) =>
      `Een moderator ziet dit. Er gebeurt nu niets met ${p.name}, en er wordt niet verteld wie het meldde.`,
    whatHappened: "Wat er gebeurde",
    anythingElseOptional: "Nog iets (optioneel)",
    whatTheySaidDrewWhen: "Wat ze zeiden of tekenden, en wanneer",
    theirRecentMessagesThisRoomAre: "Hun recente berichten in deze kamer gaan er automatisch bij,\n                met wat eromheen gezegd is, dus dit mag leeg blijven.",
    includeTheirDrawing: "Hun tekening meesturen",
    canvasAsRightNowSoModerator: "Het canvas zoals het nu is, zodat een moderator ziet wat\n                      jij zag.",
    done: "Klaar",
    sentWithTheirDrawingAnd: (p: { messages: string }) =>
      `Verstuurd, met hun tekening en ${p.messages} bijgevoegd.`,
    sentWithTheirDrawingAttached: "Verstuurd, met hun tekening bijgevoegd.",
    sentWithMessagesAttached: (p: { messages: string }) =>
      `Verstuurd, met ${p.messages} bijgevoegd.`,
    sentTheyHadSaidNothing: "Verstuurd. Deze speler had niets gezegd in deze kamer, dus er zijn geen berichten bijgevoegd.",
    baseTheTurnHadEnded: (p: { base: string }) =>
      `${p.base} De beurt was voorbij, dus de tekening kon niet worden bijgevoegd.`,
    harassmentOrAbuse: "Intimidatie of misbruik",
    offensiveDrawing: "Aanstootgevende tekening",
    inappropriateName: "Ongepaste naam",
    cheating: "Valsspelen",
    spam: "Spam",
    inappropriatePicture: "Ongepaste afbeelding",
    sendThatReport: "die melding versturen",
    reportNickname: (p: { nickname: string }) =>
      `${p.nickname} melden`,
    reportSent: "Melding verstuurd",
    sending: "Versturen…",
    sendReport: "Melding versturen",
    cancel: "Annuleren",
    close: "Sluiten",
  },

  reportsReviewedNotice: {
    reportsReviewed: (p: { count: number }) =>
      `${counted(p.count, { one: "melding die je stuurde is", other: "meldingen die je stuurde zijn" })} bekeken. Bedankt.`,
  },

  restartVoteBanner: {
    voteTally: (p: { yes: number; no: number; pending: number }) =>
      `${p.yes} voor, ${p.no} tegen, ${p.pending} open`,
    restartingIn: (p: { seconds: number }) =>
      `Herstart over ${counted(p.seconds, { one: "seconde", other: "seconden" })}`,
    restartApproved: "Herstart aangenomen!",
    seconds: "seconden",
    voteRestartGame: "Stemmen over een herstart",
    restart: "Herstarten",
    keepPlaying: "Doorspelen",
    onlyEligiblePlayersPresentWhenVote: "Alleen stemgerechtigde spelers die er waren toen de stemming begon, kunnen stemmen.",
    proposerNicknameProposedRestartingRemainingS: (p: { proposerNickname: string; remaining: number }) =>
      `${p.proposerNickname} stelt een herstart voor · ${p.remaining} s`,
    theCurrentGameIsRestarting: "Het spel wordt nu herstart.",
    yesYesNoNoPending: (p: { yes: number; no: number; pending: number; requiredVotes: number }) =>
      `${p.yes} ja · ${p.no} nee · ${p.pending} open · ${p.requiredVotes} nodig`,
  },

  roleChangeNotice: {
    youHaveBeenSignedOutEvery: "Je bent op elk apparaat uitgelogd zodat de wijziging effect heeft.\n            Log opnieuw in om verder te gaan.",
    setUpNow: "Nu instellen",
    later: "Later",
    oneMoment: "Een moment…",
    signInAgain: "Opnieuw inloggen",
    understood: "Begrepen",
  },

  roomChatPanel: {
    unreadMessages: (p: { count: number }) =>
      `${counted(p.count, { one: "nieuw bericht", other: "nieuwe berichten" })}`,
    correctWithPlace: (p: { place: string | null }) =>
      p.place ? `Goed · ${p.place}` : "Goed",
    couldNotSendMessage: "Bericht kon niet verstuurd worden",
    sent: "Verstuurd:",
    send: "Versturen",
    youReDrawingWatchGuessesCome: "Jij tekent — kijk hoe de gokken binnenkomen.",
    yourGuessTrimmedDidNot: (p: { trimmed: string }) =>
      `Je gok ‘${p.trimmed}’ heeft de server niet bereikt. Stuur hem opnieuw.`,
    sendTheMessage: "het bericht versturen",
    chatWhileYouWait: "Chat terwijl je wacht",
    gameChat: "Spelchat",
    guessAndChat: "Raden en chatten",
    guessesAndChat: "Gokken en chat",
    roomChat: "Kamerchat",
    sayHelloBeforeTheGame: "Zeg hallo voordat het spel begint.",
    noMessagesYet: "Nog geen berichten.",
    typeYourGuess: "Typ je gok...",
    typeAMessage: "Typ een bericht...",
  },

  roomEntryState: {
    thisRoomNoLongerAvailable: "Deze kamer is niet meer beschikbaar",
    couldNotJoinThisRoom: "Deelnemen aan deze kamer lukte niet",
    thatNameIsReservedPlease: "Die naam is gereserveerd. Kies een andere.",
    thisRoomHasEndedAsk: "Deze kamer is afgelopen. Vraag de gastheer om een nieuwe uitnodiging.",
    loadThisRoom: "deze kamer laden",
    enterANicknameToContinue: "Vul een bijnaam in om verder te gaan.",
    thePlayerSlotsJustFilled: "De spelersplekken zijn net vol, maar je kunt nog kijken.",
    joinAsASpectator: "als toeschouwer meedoen",
    joinThisRoom: "deze kamer in gaan",
    nicknameRule: "Gebruik 3–16 tekens: letters, cijfers, streepjes of lage streepjes. Geen spaties.",
  },

  roomMenuSheet: {
    startTheGameOver: "Het spel opnieuw beginnen",
    startOverCooldown: (p: { seconds: number }) => ` · over ${p.seconds}s`,
    room: "Kamer",
    playersScores: "Spelers en punten",
    copyInviteLink: "De uitnodigingslink kopiëren",
    saveThisDrawing: "Deze tekening opslaan",
    settings: "Instellingen",
    leaveRoom: "De kamer verlaten",
    iMBack: "Ik ben terug",
    goAwayForABit: "Even weg",
  },

  roomPlayersPanel: {
    spectatorCount: (p: { count: number }) =>
      counted(p.count, { one: "toeschouwer", other: "toeschouwers" }),
    spectatorsHeading: (p: { count: number }) => `Toeschouwers (${p.count})`,
    playersOfCapacity: (p: { here: number; capacity: number }) =>
      `${p.here} van de ${p.capacity} spelers`,
    readyCount: (p: { count: number }) => `${p.count} klaar`,
    couldNotJoinAsPlayer: "Meedoen als speler lukte niet",
    finalStandings: "Eindstand",
    players: "Spelers",
    joinAsAPlayer: "als speler meedoen",
    aPlayerSlotIsAvailable: "Er is een spelersplek vrij.",
    playerSlotsAreCurrentlyFull: "De spelersplekken zijn nu vol.",
    joining: "Deelnemen…",
    joinAsPlayer: "Meedoen als speler",
  },

  roomSettingsEditor: {
    couldNotLoadRoomRules: "De kamerregels konden niet geladen worden",
    roomRefusedThoseSettings: "De kamer weigerde die instellingen.",
    hostSettings: "Gastheerinstellingen",
    editRoomRules: "Kamerregels bewerken",
    loadingSettings: "Instellingen laden…",
    cancel: "Annuleren",
    loadRoomRules: "de kamerregels laden",
    saveRoomRules: "de kamerregels opslaan",
    saving: "Opslaan…",
    saveSettings: "Instellingen opslaan",
    saved: "Opgeslagen",
  },

  roomSetupForm: {
    language: "Taal",
    visibility: "Zichtbaarheid",
    maxPlayers: "Maximum aantal spelers",
    rounds: "Rondes",
    drawingTime: "Tekentijd",
    onlyUseCustomPrompts: "Alleen eigen woorden gebruiken",
    addUsableCustomPromptEnableThis: "Voeg een bruikbaar eigen woord toe om deze optie aan te zetten.",
    allowedTools: "Toegestane gereedschappen",
    colors: "Kleuren",
    scoring: "Punten",
    hints: "Hints",
    spectatorsCanSeePrompt: "Toeschouwers zien het woord",
    hideBlanks: "Lege plekken verbergen",
    alsoTurnsHintsOffWithNo: "Zet ook hints uit: zonder lege plekken valt er niets te onthullen.",
    promptTotal: (p: { count: number }) =>
      counted(p.count, { one: "woord", other: "woorden" }),
    basics: "Basis",
    roomName: "Kamernaam",
    public: "Openbaar",
    private: "Privé",
    prompts: "Woorden",
    drawing: "Tekent",
    scoringHints: "Punten en hints",
    hintsAreOffBecauseBlanksAre: "Hints staan uit omdat de lege plekken verborgen zijn.",
    pointPurchaseHintModesRequireScoring: "Hintmodi met punten kosten vereisen puntentelling.",
    allColors: "Alle kleuren",
    noScoring: "Zonder punten",
    listedInTheLobbyAnyone: "Zichtbaar in de lobby — iedereen kan binnenlopen.",
    joinableOnlyWithTheCode: "Alleen toegankelijk met de code of de uitnodigingslink.",
  },

  rulesPage: {
    sketchy: "Sketchy",
    theRules: "De regels",
    thisPage: "Op deze pagina",
    forExample: "Bijvoorbeeld",
    backToLobby: "Terug naar de lobby",
  },

  sessionManagerDialog: {
    lastUsed: (p: { when: string }) => `Laatst gebruikt ${p.when}`,
    signsOutOn: (p: { when: string }) => `Logt vanzelf uit ${p.when}`,
    usedElsewhere: (p: { when: string }) =>
      `Gebruikt vanuit een andere browser op ${p.when}. Trek dit apparaat in als jij dat niet was.`,
    couldNotLoadSignedDevices: "De ingelogde apparaten konden niet geladen worden.",
    couldNotRevokeDevice: "Het apparaat kon niet ingetrokken worden.",
    couldNotLogOutEverywhere: "Overal uitloggen lukte niet.",
    signedDevices: "Ingelogde apparaten",
    revokeAnyDeviceYouNoLonger: "Trek elk apparaat in dat je niet meer herkent. Apparaatnamen zijn grof en bewaren geen browserversies.\n          Een apparaat dat je niet meer gebruikt, logt zichzelf na negentig dagen uit.",
    loadingDevices: "Apparaten laden…",
    currentDevice: "Huidig apparaat",
    close: "Sluiten",
    revoking: "Intrekken…",
    revoke: "Intrekken",
    loggingOut: "Uitloggen…",
    logOutEverywhere: "Overal uitloggen",
  },

  settingsOverlay: {
    email: "E-mail",
    password: "Wachtwoord",
    twoFactorAuthentication: "Tweestapsverificatie",
    signedDevices: "Ingelogde apparaten",
    downloadEverything: "Alles downloaden",
    colorScheme: "Kleurenschema",
    appliesMomentYouPick: "Geldt zodra je het kiest.",
    languageYouPlay: "Taal waarin je speelt",
    roomsThisLanguageComeFirstLobby: "Kamers in deze taal staan voorop in de lobby, en een kamer die je maakt begint erin. Dit staat los van de taal waarin je Sketchy leest.",
    interfaceLanguage: "Taal waarin je leest",
    interfaceLanguageHint: "Elk woord van Sketchy zelf. Los van de taal waarin je speelt: in de ene lezen en in de andere spelen is heel gewoon.",
    timeFormat: "Tijdnotatie",
    howEveryClockReadsChatTimestamps: "Hoe elke klok leest: chattijden, inlogdata, meldingen. „Systeem” volgt je apparaat.",
    iHaveTroubleTellingColorsApart: "Ik kan kleuren moeilijk uit elkaar houden",
    nudgesHostsTowardRoomColorsThat: "Duwt gastheren richting kamerkleuren die met deuteranopie en protanopie te onderscheiden blijven, zonder te zeggen wie het vroeg. Er verandert niets vanzelf.",
    brushCursor: "Penseelcursor",
    crosshairPreciseAtPointOutlineShows: "Een draadkruis is precies op het punt; een omtrek laat zien hoe breed de streek wordt.",
    brushCursorStyle: "Stijl van de penseelcursor",
    soundEffects: "Geluidseffecten",
    chimesCorrectGuessStartRoundLast: "Tonen bij een goede gok, het begin van een ronde, de laatste tien seconden, en spelers die komen en gaan.",
    volume2: "Volume",
    confetti: "Confetti",
    burstWhenYouGuessRightAgain: "Een uitbarsting als je goed gokt, en nog een voor de winnaar aan het eind van een spel.",
    clickKeyRebindEachActionCan: "Klik op een toets om hem opnieuw toe te wijzen. Elke actie kan er twee hebben. Druk op Esc om te annuleren.",
    theseAreTheirSettings: (p: { name: string }) => `Dit zijn nu de instellingen van ${p.name}.`,
    guestLivesInThisBrowser: (p: { name: string }) =>
      `${p.name} bestaat alleen in deze browser. Een account houdt de naam, je punten en je geschiedenis op elk apparaat, en laat je een kleur kiezen.`,
    systemThemeNow: (p: { theme: "dark" | "light" }) => `Nu: ${p.theme}`,
    needsAccount: "Heeft een account nodig",
    choosePicture: "Een afbeelding kiezen",
    editPicture: "Afbeelding bewerken",
    picture: "Afbeelding",
    changePicture: "Afbeelding wijzigen",
    removePicture: "Afbeelding verwijderen",
    couldNotRemovePicture: "De afbeelding kon niet verwijderd worden.",
    couldNotChangeYourDisplayName: "Je weergavenaam kon niet gewijzigd worden.",
    couldNotChangeYourDisplayName2: "Je weergavenaam kon niet gewijzigd worden. Probeer het nog eens.",
    themeSoundShortcutsCameFromAccount: "Het thema, geluid en de\n            sneltoetsen komen uit het account. Wat deze browser had blijft ongemoeid en\n            komt terug als je uitlogt.",
    dismiss: "Sluiten",
    playingAsGuest: "Je speelt als gast",
    createAccount: "Een account maken",
    logIn: "Inloggen",
    you: "Jij",
    displayName: "Weergavenaam",
    cancel: "Annuleren",
    change: "Wijzigen",
    nameColor: "Naamkleur",
    signingIn: "Inloggen",
    changePassword: "Wachtwoord wijzigen",
    manage: "Beheren",
    yourData: "Jouw gegevens",
    requestExport: "Export aanvragen",
    delete: "Verwijderen…",
    display: "Weergave",
    theme: "Thema",
    accessibility: "Toegankelijkheid",
    theCanvas: "Het canvas",
    sound: "Geluid",
    volume: "Volume",
    effects: "Effecten",
    noKeyboardThisDevice: "Geen toetsenbord op dit apparaat",
    yourBindingsAreStillSavedStill: "Je sneltoetsen blijven bewaard en werken gewoon. Open Sketchy met een\n            toetsenbord eraan om ze te wijzigen.",
    drawingTools: "Tekengereedschap",
    resetDefaults: "Terug naar standaard",
    settings: "Instellingen",
    close: "Sluiten",
    closeSettings: "Instellingen sluiten",
    settingsSections: "Onderdelen van de instellingen",
    account: "Account",
    appearance: "Weergave",
    soundEffects2: "Geluid en effecten",
    shortcuts: "Sneltoetsen",
    red: "Rood",
    orange: "Oranje",
    yellow: "Geel",
    lime: "Limoen",
    green: "Groen",
    teal: "Blauwgroen",
    sky: "Hemelsblauw",
    blue: "Blauw",
    indigo: "Indigo",
    purple: "Paars",
    magenta: "Magenta",
    pink: "Roze",
    brown: "Bruin",
    light: "Licht",
    dark: "Donker",
    system: "Systeem",
    crosshair: "Vizier",
    outline: "Omtrek",
    space: "Spatie",
    hideTheFullAddress: "Volledig adres verbergen",
    showTheFullAddress: "Volledig adres tonen",
    hide: "Verbergen",
    showInFull: "Volledig tonen",
    verified: "Bevestigd",
    notVerified: "Niet bevestigd",
    saving: "Opslaan…",
    save: "Opslaan",
    aGuestHasNothingTo: "Een gast heeft niets te herstellen: er is geen wachtwoord om te vergeten.",
    withoutOneThereIsNo: "Zonder e-mailadres is er geen weg terug in dit account als het wachtwoord vergeten is.",
    addAnEmail: "E-mail toevoegen",
    guestsHaveNoPassword: "Gasten hebben geen wachtwoord.",
    changingItSignsEveryOther: "Wijzigen logt alle andere apparaten uit.",
    setThisUpAndThe: (p: { pendingRole: string }) =>
      `Stel dit in en de rol van ${p.pendingRole} die je is aangeboden gaat in.`,
    anAuthenticatorAppSCode: "Een code uit een authenticatie-app, bovenop je wachtwoord. Moderators en beheerders moeten er een hebben.",
    setUp: "Instellen",
    thisBrowserIsTheOnly: "Deze browser is de enige plek waar je bestaat.",
    everyBrowserStillHoldingA: "Elke browser die nog een sessie heeft, en een manier om er een te beëindigen.",
    worksForAGuestToo: "Werkt ook voor gasten: de spellen die je hebt gespeeld zijn van jou.",
    everyGameListAndSetting: "Elk spel, elke lijst en elke instelling die Sketchy over je bewaart, als één JSON-bestand.",
    deleteThisGuest: "Deze gast verwijderen",
    deleteYourAccount: "Je account verwijderen",
    removesTheNameThePoints: "Verwijdert de naam, de punten en de geschiedenis die bij deze browser horen.",
    gamesYouPlayedStayIn: "Spellen die je speelde blijven in de geschiedenis van anderen, zonder je naam.",
    clickToRebindTheSecond: "Klik om de tweede toets opnieuw toe te wijzen",
    clickToRebind: "Klik om opnieuw toe te wijzen",
    pressKey: "Druk op een toets…",
    key: "+ toets",
    none: "Geen",
  },

  stepUpDialog: {
    codeFromYourAuthenticatorApp2: "Code uit je authenticatie-app",
    passkeyNotUsed: "Deze passkey is niet gebruikt. Je kunt het nog eens proberen.",
    thatCodeWasNotAccepted: "Deze code is niet geaccepteerd.",
    thatPasskeyWasNotAccepted: "Deze passkey is niet geaccepteerd.",
    confirmYou: "Bevestig dat jij het bent",
    recoveryCode: "Herstelcode",
    codeFromYourAuthenticatorApp: "Code uit je authenticatie-app",
    cancel: "Annuleren",
    waitingForYourDevice: "Wachten op je apparaat…",
    useYourPasskey: "Je passkey gebruiken",
    useYourAuthenticatorApp: "Je authenticatie-app gebruiken",
    useARecoveryCode: "Een herstelcode gebruiken",
    checking: "Controleren…",
    confirm: "Bevestigen",
  },

  suspensionNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Jouw tekening van ${p.prompt}, zoals hij gemeld werd`,
    recordedAs: "Vastgelegd als {category}",
    yourAccountSuspended: "Je account is geschorst",
    youWereAskedDraw: "Jij moest tekenen",
    theMessageThisWasAbout: "Het bericht waar het om ging:",
    theMessagesThisWasAbout: "De berichten waar het om ging:",
    theDrawingThisWasAbout: "De tekening waar het om ging:",
    theDrawingsThisWasAbout: "De tekeningen waar het om ging:",
    signingOut: "Uitloggen…",
    signOut: "Uitloggen",
  },

  toastProvider: {
    notifications: "Meldingen",
    dismissNotification: "Melding sluiten",
  },

  toolbar: {
    colorOption: (p: { color: string }) => `kleur ${p.color}`,
    adjustSize: (p: { tool: string }) => `Grootte van ${p.tool} aanpassen`,
    sizeSnappingSlider: (p: { tool: string }) => `Schuifregelaar met stappen voor de grootte van ${p.tool}`,
    chooseToolCurrent: (p: { tool: string }) => `Gereedschap kiezen, nu: ${p.tool}`,
    chooseColorCurrent: (p: { color: string }) => `Kleur kiezen, nu ${p.color}`,
    sizeWithWidth: (p: { tool: string; width: number }) => `${p.tool}, grootte ${p.width}px`,
    sizeShortcutHint: (p: { tool: string; width: number }) =>
      `${p.tool}, grootte: ${p.width}px ([ / ])`,
    widthReadout: (p: { width: number }) => `${p.width}px`,
    colorSwatch: (p: { color: string }) => `Kleur ${p.color}`,
    drawingTools: "Tekengereedschap",
    chooseTool: "Gereedschap kiezen",
    chooseColor: "Kleur kiezen",
    undoLastStroke: "Laatste streek ongedaan maken",
    undo: "Ongedaan maken",
    clearCanvas: "Canvas leegmaken",
    chooseCustomColor: "Eigen kleur kiezen",
    colorPalette: "Kleurenpalet",
    canvasActions: "Canvasacties",
    undoLastStrokeCtrlZ: "Laatste streek ongedaan maken (Ctrl+Z)",
    clear: "Leegmaken",
    brush: "Penseel",
    fill: "Vullen",
    eraser: "Gum",
    rectangle: "Rechthoek",
    triangle: "Driehoek",
    ellipse: "Ellips",
    fillIsUnavailableForThe: "Vullen is de rest van deze beurt niet beschikbaar",
    drawingByHandIsUnavailable: "Uit de vrije hand tekenen is de rest van deze beurt niet beschikbaar",
  },

  turnResultsOverlay: {
    yourTurnWithHints: (p: { base: number; hintSpend: number; points: number; rank: number }) =>
      `Jouw beurt: +${p.base} -${p.hintSpend} hints = ${counted(p.points, { one: "punt", other: "punten" })} · nu #${p.rank}`,
    yourTurn: (p: { delta: number; rank: number }) =>
      `Jouw beurt: ${p.delta >= 0 ? "+" : ""}${p.delta} ${
        Math.abs(p.delta) === 1 ? "punt" : "punten"
      } · nu #${p.rank}`,
    promptWas: "Het woord was",
    noOneGuessedCorrectly: "Niemand heeft het geraden.",
    you: "(jij)",
    drewThisTurn: "Tekende deze beurt",
    nextTurn: "Volgende beurt",
    turnResults: "Resultaten van de beurt",
    turnComplete: "Beurt voorbij",
  },

  twoFactorDialog: {
    scanThisWithYourAuthenticatorApp: "Scan dit met je authenticatie-app om dit account toe te voegen",
    codeFromYourAuthenticatorApp: "Code uit je authenticatie-app",
    secondFactorState: (p: {
      recoveryCodesRemaining: number | null;
      confirmAuthenticator: boolean;
    }) =>
      [
        "Tweestapsverificatie staat aan.",
        p.recoveryCodesRemaining === null
          ? null
          : `Je hebt nog ${counted(p.recoveryCodesRemaining, {
              one: "herstelcode",
              other: "herstelcodes",
            })}.`,
        p.confirmAuthenticator
          ? "Voordat dit account een moderator- of beheerdersrol kan krijgen, bevestig met je wachtwoord en een code dat de authenticator van jou is."
          : null,
        "Elk van de wijzigingen hieronder vervangt een inloggegeven, dus elke wijziging vraagt om je wachtwoord.",
      ]
        .filter(Boolean)
        .join(" "),
    confirmAuthenticatorFirst:
      "Voordat dit account een moderator- of beheerdersrol kan krijgen, bevestig met je wachtwoord en een code dat de authenticator van jou is.",
    copied: (p: { what: string }) => `${p.what} gekopieerd.`,
    couldNotCopy: (p: { what: string }) =>
      `Kon ${p.what} niet kopiëren. Selecteer het en kopieer het met de hand.`,
    roleTaken: (p: { role: "admin" | "moderator" }) =>
      `Je bent nu ${p.role === "admin" ? "beheerder" : "moderator"}. Tweestapsverificatie staat aan, en de rol die erop wachtte is ingegaan. Je andere apparaten zijn uitgelogd; dit apparaat gaat door, en elke aanmelding van hieraf vraagt om een code.`,
    recoveryCodesLeft: (p: { count: number }) =>
      `Je hebt nog ${counted(p.count, { one: "herstelcode", other: "herstelcodes" })}.`,
    couldNotReadYourSecuritySettings: "Je beveiligingsinstellingen konden niet gelezen worden.",
    yourPasswordConfirmsAuthenticatorYours: "Je wachtwoord bevestigt dat de authenticator van jou is.",
    yourPasswordConfirmsThisPasskeyYours: "Je wachtwoord bevestigt dat deze passkey van jou is.",
    passkeyAdded: "Passkey toegevoegd.",
    thatPasskeyWasNotCreatedYou: "Deze passkey is niet aangemaakt. Je kunt het nog eens proberen.",
    yourPasswordNeededRemovePasskey: "Voor het verwijderen van een passkey is je wachtwoord nodig.",
    confirmedThisAccountCanNowBe: "Bevestigd. Dit account kan nu een teamrol krijgen.",
    twoFactorAuthentication: "Tweestapsverificatie",
    saveTheseRecoveryCodesNow: "Bewaar deze herstelcodes nu.",
    eachOneSignsYouOnceIf: "Elke code logt je één keer\n              in als je je authenticatie-app kwijtraakt. Ze worden niet nog eens\n              getoond — alleen hun hashes worden bewaard.",
    recoveryCodes: "Herstelcodes",
    downloadAsFile: "Als bestand downloaden",
    copyAll: "Alles kopiëren",
    iHaveSavedTheseSomewhereSafe: "Ik heb ze veilig opgeborgen",
    done: "Klaar",
    moderatorsAdministratorsSignWithPasskeyYour: "Moderatoren en beheerders loggen in met een passkey: je apparaat\n              bevestigt dat jij het bent — een vingerafdruk, je gezicht of de\n              pincode — en er wordt niets getypt dat weggegeven kan worden.",
    yourPassword: "Je wachtwoord",
    confirmsPasskeyBeingAddedByYou: "Bevestigt dat jij de passkey toevoegt.",
    useAuthenticatorAppInstead: "Liever een authenticatie-app gebruiken",
    scanCodeWithAuthenticatorAppThen: "Scan de code met een authenticatie-app en typ daarna de zes cijfers\n              die hij laat zien.",
    drawingCode: "Code tekenen…",
    pointYourAppAtThis: "Richt je app hierop.",
    setupKey: "Instelsleutel",
    copySetupKey: "De instelsleutel kopiëren",
    useThisIfYouCanT: "Gebruik dit als je niet kunt scannen.",
    confirmsAuthenticatorYours: "Bevestigt dat de authenticator van jou is.",
    codeFromYourApp: "Code uit je app",
    cancel: "Annuleren",
    passkeys: "Passkeys",
    thisDeviceOnly: "· alleen op dit apparaat",
    remove: "Verwijderen",
    confirmSYours: "Bevestigen dat hij van jou is",
    addPasskey: "Een passkey toevoegen",
    newRecoveryCodes: "Nieuwe herstelcodes",
    turnOff: "Uitschakelen",
    addAuthenticatorApp: "Een authenticatie-app toevoegen",
    close: "Sluiten",
    couldNotStartSettingThis: "Het instellen kon niet beginnen.",
    thatCodeWasNotAccepted: "Die code werd niet geaccepteerd.",
    couldNotAddThatPasskey: "Die passkey kon niet worden toegevoegd.",
    couldNotRemoveThatPasskey: "Die passkey kon niet worden verwijderd.",
    couldNotConfirmIt: "Het kon niet worden bevestigd.",
    couldNotReplaceYourRecovery: "Je herstelcodes konden niet worden vervangen.",
    couldNotTurnThisOff: "Dit kon niet worden uitgezet.",
    waitingForYourDevice: "Wachten op je apparaat…",
    setUpAPasskey: "Een passkey instellen",
    noPasskeyOnThisDevice: "Geen passkey op dit apparaat? ",
    thisBrowserCannotMakeA: "Deze browser kan geen passkey maken. ",
    checking: "Controleren…",
    confirm: "Bevestigen",
  },

  useFriendArrivalNotices: {
    wantsToBeFriends: (p: { name: string }) => `${p.name} wil vrienden worden.`,
    acceptedYourRequest: (p: { name: string }) => `${p.name} heeft je vriendschapsverzoek geaccepteerd.`,
    severalAccepted: (p: { count: number }) =>
      `${counted(p.count, { one: "persoon heeft", other: "personen hebben" })} je vriendschapsverzoeken geaccepteerd.`,
    accept: "Accepteren",
    open: "Openen",
    manyArrived: (p: { name: string; others: number }) =>
      `${p.name} en ${counted(p.others, { one: "iemand anders", other: "anderen" })} willen vrienden worden.`,
  },

  useRoomSessionReconnect: {
    joinRoomFailed: "join_room failed",
  },

  waitingRoomPanel: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "ronde", other: "rondes" }),
    needMorePlayers: (p: { count: number }) =>
      `${counted(p.count, { one: "Nog 1 speler nodig", other: "Nog meer spelers nodig" })}`,
    hostWillStart: (p: { rematch: boolean }): string =>
      p.rematch ? "{host} begint de revanche" : "{host} begint het spel",
    copied: (p: { what: string }) => `${p.what} gekopieerd.`,
    couldNotCopy: (p: { what: string }) =>
      `Kon ${p.what} niet kopiëren. Kopieer het uit de adresbalk.`,
    roomCodeLabel: (p: { code: string }) => `Kamercode ${p.code}`,
    rosterCount: (p: { here: number; capacity: number }) => `${p.here} van de ${p.capacity}`,
    inviteYourFriends: "Nodig je vrienden uit",
    shareLink: "Deel de link",
    copyCode: "Code kopiëren",
    inTheRoom: "In de kamer",
    you: "(jij)",
    host: "Gastheer",
    friend: "Vriend",
    invite: "Uitnodigen",
    edit: "Bewerken",
    viewHighlights: "Hoogtepunten bekijken",
    viewDrawings: "Tekeningen bekijken",
    spectatorsAfkAndDisconnectedPlayers: "Toeschouwers, afwezige en losgekoppelde spelers tellen niet mee voor de twee actieve spelers die een spel nodig heeft.",
    joinMySketchyRoomCode: (p: { code: string }) =>
      `Kom in mijn Sketchy-kamer: ${p.code}`,
    inviteLink: "Uitnodigingslink",
    customPromptsOnlyCustomPromptCount: (p: { customPromptCount: number }) =>
      `Alleen eigen woorden (${p.customPromptCount})`,
    customPromptCountCustomPromptsCuratedLists: (p: { customPromptCount: number }) =>
      `${p.customPromptCount} eigen woorden + samengestelde lijsten`,
    promptListSlugsCountCuratedPromptLists: (p: { promptListSlugsCount: number }) =>
      `${p.promptListSlugsCount} samengestelde woordenlijsten`,
    noScoring: "Zonder punten",
    spectatorsSeeThePrompt: "Toeschouwers zien het woord",
    publicRoom: "Openbare kamer",
    privateRoom: "Privékamer",
    betweenGames: "tussen spellen door",
    waitingForPlayers: "wacht op spelers",
    roomCode: "Kamercode",
    starting: "Starten…",
    rematch: "Revanche",
    startGame: "Spel starten",
    waitingForAHost: "Wacht op een gastheer",
  },

  warningNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Jouw tekening van ${p.prompt}, zoals hij gemeld werd`,
    recordedAs: "Vastgelegd als {category}",
    whatAWarningMeans:
      "Een melding over je gedrag is bekeken, en dit is de uitkomst. Er is niets beperkt, maar nog een melding kan tot schorsing van je account leiden.",
    youWereAskedDraw: "Jij moest tekenen",
    yourPictureWasRemoved: "Je afbeelding is verwijderd",
    aModeratorWarning: "Een waarschuwing van de moderatie",
    aReportAboutYourPicture: "Een melding over je afbeelding is bekeken, en dit is de uitkomst. Verder is er niets aan je account veranderd.",
    theMessageThisWasAbout: "Het bericht waar het om ging:",
    theMessagesThisWasAbout: "De berichten waar het om ging:",
    theDrawingThisWasAbout: "De tekening waar het om ging:",
    theDrawingsThisWasAbout: "De tekeningen waar het om ging:",
    oneMoment: "Een moment…",
    understood: "Begrepen",
  },
  connectionStatusBanner: {
    youReDisconnectedCheckYour: "Je verbinding is verbroken. Controleer je verbinding; Sketchy maakt vanzelf opnieuw verbinding.",
    couldnTReconnectToYour: "Kon niet opnieuw verbinden met je kamer. Herlaad de pagina om het nog eens te proberen.",
    connectionLostReconnecting: "Verbinding verbroken — opnieuw verbinden…",
  },
  accountData: {
    queued: "In de wachtrij",
    preparing: "Voorbereiden…",
    ready: "Klaar",
    tooLargeToPrepareHere: "Te groot om hier voor te bereiden",
    couldNotPrepare: "Kon niet worden voorbereid",
    yourDataIsLargerThan: "Je gegevens zijn groter dan deze server in één document voorbereidt. Vraag de beheerder de limiet te verhogen.",
    somethingWentWrongWhilePreparing: "Er ging iets mis bij het voorbereiden. Je kunt een nieuwe export aanvragen.",
  },
  recoveryCodeFile: {
    sketchyRecoveryCodes: "Sketchy-herstelcodes",
    accountUsername: (p: { username: string }) =>
      `Account: ${p.username}`,
    createdValue: (p: { value: string }) =>
      `Aangemaakt: ${p.value}`,
    eachCodeSignsYouIn: "Elke code logt je één keer in als je je authenticatie-app kwijtraakt.",
    keepThisFile: "Bewaar dit bestand ergens waar alleen jij bij kunt. Wie deze codes\nen je wachtwoord heeft, kan als jou inloggen.",
  },
  avatars: {
    chooseAPngJpegWebP: "Kies een PNG-, JPEG-, WebP- of GIF-afbeelding.",
    thatPictureIsTooLarge: "Die afbeelding is te groot om in te lezen: hoogstens 10 MB.",
    thatFileCouldNotBe: "Dat bestand kon niet als afbeelding worden gelezen.",
    thatPictureIsTooSmall: "Die afbeelding is te klein om iets mee te doen.",
    thisBrowserCannotResizePictures: "Deze browser kan geen afbeeldingen verkleinen.",
    thatPictureIsTooDetailed: "Die afbeelding is te gedetailleerd. Probeer een eenvoudigere of zoom in op een deel ervan.",
  },
  settingsSync: {
    thatChangeAppliesHereBut: "Die wijziging geldt hier, maar kon niet in je account worden opgeslagen. Je andere apparaten zien hem niet.",
  },
  promptStats: {
    hardestFirst: "Moeilijkste eerst",
    easiestFirst: "Makkelijkste eerst",
    mostPicked: "Vaakst gekozen",
    getsGuessed: "Wordt geraden",
    usuallyGuessed: "Meestal geraden",
    evenOdds: "Fifty-fifty",
    oftenMissed: "Vaak gemist",
    rarelyGuessed: "Zelden geraden",
    notPlayedEnough: "Te weinig gespeeld",
    allRanked: (p: { count: number }) =>
      `Alle ${p.count} woorden zijn vaak genoeg gespeeld om ze te rangschikken.`,
    noneRanked: (p: { unrated: number; guessers: number }) =>
      `Geen van deze ${p.unrated} woorden heeft al ${p.guessers} raders gehad, dus geen enkel woord is gerangschikt. Speel een paar spellen en hun moeilijkheid verschijnt hier.`,
    someRanked: (p: { rated: number; unrated: number; guessers: number }) =>
      `${p.rated} gerangschikt. ${plural(p.unrated, { one: `Nog ${p.unrated} woord is niet gerangschikt`, other: `Nog ${p.unrated} woorden zijn niet gerangschikt` })}: minder dan ${p.guessers} raders hebben ze gezien.`,
    noMatch: (p: { query: string }) =>
      `Geen woord past bij ‘${p.query}’.`,
    matching: (p: { count: number; query: string }) =>
      `${counted(p.count, { one: "woord past", other: "woorden passen" })} bij ‘${p.query}’.`,
  },
  gameHeaderStatus: {
    roundRoundNumberOfTotalRounds: (p: { roundNumber: number; totalRounds: number }) =>
      `Ronde ${p.roundNumber} van ${p.totalRounds}`,
  },
  gameRoomRegions: {
    theNextPlayer: "De volgende speler",
    drawingCanvasYouAreDrawing: "Tekenvlak. Jij tekent.",
    yourTurnToDraw: "Jij bent aan de beurt om te tekenen.",
    canvasSpectating: (p: { drawer: string }) =>
      `Tekenvlak. Je kijkt naar ${p.drawer}.`,
    canvasSomeoneDrawing: (p: { drawer: string }) =>
      `Tekenvlak. ${p.drawer} tekent.`,
    someoneIsDrawing: (p: { drawer: string }) =>
      `${p.drawer} tekent.`,
    theDrawer: "degene die tekent",
    aPlayer: "Iemand",
  },
  useToolbarState: {
    fillIsUnavailableForThe: "Vullen is de rest van deze beurt niet beschikbaar.",
    drawingByHandIsUnavailable: "Uit de vrije hand tekenen is de rest van deze beurt niet beschikbaar. Vormen werken nog wel.",
  },
  timer: {
    n10SecondsRemaining: "Nog 10 seconden",
    timeIsUp: "De tijd is om",
  },
  chatAnnouncements: {
    nicknameGuessedThePrompt: (p: { nickname: string }) =>
      `${p.nickname} heeft het woord geraden.`,
  },
  canvasSnapshot: {
    drawingOfDownloadPrompt: (p: { downloadPrompt: string }) =>
      `Tekening van ${p.downloadPrompt}`,
    savedDrawing: "Opgeslagen tekening",
  },
  roomSetup: {
    default: "Standaard",
    fasterGuessesEarnMore100: "Sneller raden levert meer op, 100–300 punten.",
    pressure: "Druk",
    pointsDecayEverySecondTwice: "Punten zakken elke seconde — twee keer zo snel zodra iemand het raadt.",
    noScoring: "Zonder punten",
    justDrawAndGuessNo: "Gewoon tekenen en raden. Geen stand.",
    timedHints: "Hints op tijd",
    lettersRevealToEveryoneAt: "Letters worden op vaste momenten voor iedereen onthuld.",
    noHints: "Geen hints",
    blanksOnlyAllTurnLong: "Alleen streepjes, de hele beurt lang.",
    buyLetters: "Letters kopen",
    revealALetterSlotJust: "Onthul een letter alleen voor jou — betaald met de punten van die beurt.",
    wheelOfFortune: "Rad van fortuin",
    pickALetterPayIts: "Kies een letter, betaal de prijs — klinkers kosten extra.",
    hiddenPrompt: "Verborgen woord",
  },
  screenCapture: {
    thisBrowserCouldNotEncode: "Deze browser kon de screenshot niet coderen.",
    theCaptureWasEmpty: "De opname was leeg.",
    thisBrowserCouldNotRead: "Deze browser kon de screenshot niet lezen.",
    thatScreenshotIsTooLarge: "Die screenshot is te groot om te versturen.",
  },
  accountRecovery: {
    youCanRecoverThisAccount: (p: { address: string }) =>
      `Je kunt dit account herstellen via ${p.address}.`,
    checkPendingAddressForAConfirmation: (p: { pendingAddress: string }) =>
      `Zoek in ${p.pendingAddress} naar een bevestigingslink. Tot je die volgt, is er geen weg terug in dit account.`,
    thisServerCannotSendEmail: "Deze server kan geen e-mail versturen, dus een kwijtgeraakt wachtwoord moet worden hersteld door wie de server beheert.",
    addAnEmailAddressSo: "Voeg een e-mailadres toe zodat je weer binnenkomt als je je wachtwoord vergeet.",
  },
  friends: {
    aFriend: "Een vriend",
  },
  lobbyPresence: {
    showingShownOfOnlineCount: (p: { shown: number; onlineCount: number }) =>
      `${p.shown} van ${p.onlineCount} getoond`,
  },
  authStore: {
    chooseANameToPlay: "Kies een naam om onder te spelen.",
  },
  passkeys: {
    noPasskeyWasCreated: "Er is geen passkey gemaakt.",
    noPasskeyWasUsed: "Er is geen passkey gebruikt.",
  },
  useGameSocketListeners: {
    nicknameJoinedTheRoom: (p: { nickname: string }) =>
      `${p.nickname} is de kamer binnengekomen`,
    gameStarted: "Het spel is begonnen!",
    drawerNicknameIsChoosingAPrompt: (p: { drawerNickname: string }) =>
      `${p.drawerNickname} kiest een woord...`,
    thePromptWasPrompt: (p: { prompt: string }) =>
      `Het woord was ‘${p.prompt}’`,
    gotIt: (p: { nickname: string; time: string | null; points: number | null }) =>
      `${p.nickname} heeft het geraden${p.time === null ? "" : ` · ${p.time}`}${p.points === null ? "" : ` (+${p.points})`}`,
  },
  settingsStore: {
    brushTool: "Penseel",
    fillTool: "Vullen",
    eraserTool: "Gum",
    rectangleTool: "Rechthoek",
    triangleTool: "Driehoek",
    ellipseTool: "Ellips",
    decreaseBrushSize: "Penseel kleiner",
    increaseBrushSize: "Penseel groter",
    undoStroke: "Streek ongedaan maken",
  },
  reactions: {
    loveIt: "Geweldig",
    funny: "Grappig",
    wow: "Wauw",
    fire: "Vuur",
    reaction: "Reactie",
  },
  drawingRules: {
    brush: "Penseel",
    theBrushAndTheEraser: "Het penseel en de gum.",
    fill: "Vullen",
    theFillTool: "Het vulgereedschap.",
    shapes: "Vormen",
    rectangleEllipseAndTriangle: "Rechthoek, ellips en driehoek.",
    allColors: "Alle kleuren",
    thePaletteAndTheCustom: "Het palet en de vrije kleurkiezer.",
    paletteOnly: "Alleen palet",
    theBuiltInSwatchesNo: "De vaste kleurstalen; geen eigen kleuren.",
    colorblindSafe: "Kleurenblindvriendelijk",
    colorsThatStayApartFor: "Kleuren die voor kleurenblinde spelers goed te onderscheiden blijven.",
    blackAndWhite: "Zwart-wit",
    blackAndWhiteOnly: "Alleen zwart en wit.",
    allTools: "Alle gereedschappen",
  },
  socket: {
    sketchyIsFullRightNow: "Sketchy zit nu vol. Probeer het over een paar minuten nog eens.",
    connectionLostWhileTryingTo: (p: { action: string }) =>
      `Verbinding verbroken bij: ${p.action}. Probeer het nog eens.`,
    theRequestToActionTimed: (p: { action: string }) =>
      `Time-out bij: ${p.action}. Probeer het nog eens.`,
    couldNotActionPleaseTry: (p: { action: string }) =>
      `Dat is niet gelukt: ${p.action}. Probeer het nog eens.`,
  },
  bugReports: {
    drawingAndCanvas: "Tekenen en tekenvlak",
    guessingAndChat: "Raden en chat",
    roundsScoringAndResults: "Rondes, punten en uitslagen",
    roomsAndLobby: "Kamers en lobby",
    promptLists: "Woordenlijsten",
    accountAndSettings: "Account en instellingen",
    connectionAndSync: "Verbinding en synchronisatie",
    performance: "Prestaties",
    accessibility: "Toegankelijkheid",
    somethingElse: "Iets anders",
    blocksPlayICouldNot: "Blokkeert het spel — ik kon niet verder",
    majorHardToPlayAround: "Ernstig — lastig omheen te spelen",
    minorWorthFixingOneDay: "Klein — ooit de moeite waard",
    notInARoom: "Niet in een kamer",
    codeNotInARound: (p: { code: string }) =>
      `${p.code} · niet in een ronde`,
    codeRoundRoundOfTotal: (p: { code: string; round: number; total: number }) =>
      `${p.code} · ronde ${p.round} van ${p.total}`,
  },
  suspension: {
    thisSuspensionHasNoEnd: "Deze schorsing heeft geen einddatum.",
    thisSuspensionHasEndedTry: "Deze schorsing is afgelopen; probeer opnieuw in te loggen.",
    thisSuspensionLastsUntilEnds: (p: { ends: string }) =>
      `Deze schorsing duurt tot ${p.ends}.`,
  },
  clock: {
    unknown: "Onbekend",
  },
  protocol: {
    theServerWasUpdated: "De server is bijgewerkt.",
  },
  passwordPolicy: {
    tooShort: (p: { count: number }) =>
      `Een wachtwoord heeft minstens ${p.count} tekens nodig.`,
  },
  operatorAccess: {
    administrator: "beheerder",
    moderator: "moderator",
    pendingTitle: "De moderatorrol wacht op je",
    pendingBody: "Een beheerder heeft je de moderatorrol aangeboden. Die gaat in zodra je tweestapsverificatie instelt: moderators loggen in met een code uit een authenticatie-app, en de rol begint zodra dat geregeld is. Je andere apparaten worden dan uitgelogd. Tot je het instelt verandert er niets, en het aanbod wacht in Instellingen als het nu niet uitkomt.",
    grantedTitle: "Je bent nu moderator",
    grantedBody: "Een beheerder heeft je de moderatorrol gegeven. In je accountmenu staat nu een onderdeel Moderatie: daar worden meldingen over spelers en woorden beoordeeld. Aan hoe je speelt verandert niets.",
    removedTitle: "Je bent geen moderator meer",
    removedBody: "Een beheerder heeft de moderatorrol van je account gehaald. Het onderdeel Moderatie is uit je menu verdwenen. Verder verandert er niets aan je account of je spellen.",
  },
  moderationCategories: {
    harassment: "intimidatie",
    offensive_drawing: "een aanstootgevende tekening",
    inappropriate_name: "een ongepaste naam",
    cheating: "valsspelen",
    spam: "spam",
    inappropriate_avatar: "een ongepaste afbeelding",
  },
  roomNotices: {
    kickedByVote: "Je bent per stemming uit de kamer gezet.",
    roomClosed: "Een beheerder heeft deze kamer gesloten.",
    removedByAdmin: "Een beheerder heeft je verwijderd.",
    accountDeleted: "Je account is verwijderd.",
    accountSuspended: "Je account is geschorst.",
  },
};
