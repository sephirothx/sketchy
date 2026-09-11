/** Every word the interface says, in German.

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

const { counted, number, ordinal, plural } = formattersFor("de", {"other":"."});


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
      return `Das Passwort muss mindestens ${count(detail, 12)} Zeichen lang sein.`;
    case "too_long":
      return `Das Passwort darf höchstens ${count(detail, 128)} Zeichen lang sein.`;
    case "common":
      return "Dieses Passwort gehört zu den meistgenutzten überhaupt. Bitte wähle ein anderes.";
    case "common_repeated":
      return "Das ist ein häufiges Passwort, nur wiederholt. Bitte wähle ein anderes.";
    case "short_repeated":
      return "Dieses Passwort ist nur ein kurzes, das sich wiederholt. Bitte wähle ein anderes.";
    case "too_few_characters":
      return `Dieses Passwort verwendet nur ${count(detail, 4)} verschiedene Zeichen. Bitte wähle ein anderes.`;
    case "keyboard_walk":
      return "Dieses Passwort ist größtenteils eine Tastenreihe der Reihe nach. Bitte wähle ein anderes.";
    case "contains_identity":
      return "Ein Passwort darf weder deinen Namen noch deine E-Mail-Adresse noch den Namen dieser Seite enthalten.";
    case "common_with_digits":
      return "Das ist ein häufiges Passwort mit angehängten Ziffern. Bitte wähle ein anderes.";
    default:
      return "Bitte wähle ein anderes Passwort.";
  }
}

/** *Create an account to …* - one refusal, said about the thing it refused. */
function accountRequired(params: MessageParams): string {
  switch (params.action) {
    case "avatar":
      return "Lege ein Konto an, um ein Bild zu wählen.";
    case "prompt_lists":
      return "Lege ein Konto an, um wiederverwendbare Begriffslisten zu speichern.";
    case "name_color":
      return "Lege ein Konto an, um eine Namensfarbe zu wählen.";
    case "password":
      return "Lege ein Konto an, um ein Passwort zu setzen.";
    case "second_factor":
      return "Lege ein Konto an, bevor du die Zwei-Faktor-Authentifizierung einrichtest.";
    case "friends":
      return "Lege ein Konto an, um Freunde hinzuzufügen.";
    default:
      return "Lege ein Konto an, um das zu tun.";
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
      return "gerade ein Server-Update läuft";
    case "too_few_players":
      return "weniger als zwei aktive Spieler übrig sind";
    case "prompt_lists_unavailable":
      return "die Begriffslisten nicht geladen werden konnten";
    case "everybody_left":
      return "alle gegangen sind, bevor es losgehen konnte";
    default:
      return "es nicht mehr weitergehen konnte";
  }
}

type Sentence = string | ((params: MessageParams) => string);

/** Why the server refused, said to the player.

One entry per `ErrorCode`; `Record` makes it exhaustive, so a code the server
adds without a sentence here fails the build rather than the player
(R-I18N-04). */
const REFUSALS: Record<ErrorCode, Sentence> = {
  // Payloads and arguments
  invalid_payload: "Sketchy konnte diese Anfrage nicht lesen.",
  invalid_nickname: "Dieser Name kann hier nicht verwendet werden.",
  invalid_name_color: "Wähle eine Farbe, die sowohl in der hellen als auch in der dunklen Spielerliste lesbar ist.",
  invalid_hint: "Dieser Hinweis ist ungültig.",
  invalid_letter: "Dieser Buchstabe ist ungültig.",
  invalid_prompt_lists: "Diese Begriffslisten lassen sich nicht zusammen verwenden.",
  invalid_custom_prompts: "Diese eigenen Begriffe konnten nicht gelesen werden.",
  max_players_below_seated: (params) =>
  `Die Höchstzahl darf nicht unter den ${count(params.seated, 2)} Spielern liegen, die schon im Raum sind.`,
  empty_message: "Schreib erst etwas.",

  // Rate and capacity
  too_fast: "Das geht zu schnell. Mach kurz langsamer.",
  seat_changing_too_fast: "Dieser Platz wechselt zu schnell den Besitzer. Versuch es in einer Minute noch einmal.",
  joining_too_fast: "Du betrittst zu schnell Räume. Versuch es in einer Minute noch einmal.",
  room_quota: "Du hast bereits so viele Räume offen, wie gleichzeitig möglich sind.",
  room_full: "Dieser Raum ist voll.",
  spectators_full: "Dieser Raum nimmt keine weiteren Zuschauer auf.",
  player_slots_full: "Alle Spielplätze sind belegt.",

  // Server and account state
  server_draining: "Sketchy startet neu. Versuch es gleich noch einmal.",
  server_paused: "Sketchy nimmt gerade keine neuen Räume an.",
  database_busy: "Sketchy erreicht seine Datenbank gerade nicht. Bitte versuch es noch einmal.",
  account_ended: "Dieses Konto ist nicht mehr aktiv.",
  account_required: accountRequired,
  identity_unavailable: "Sketchy konnte nicht bestätigen, wer du bist. Lade neu und versuch es noch einmal.",

  // Rooms
  not_in_room: "Du bist nicht in diesem Raum.",
  room_not_found: "Raum nicht gefunden.",
  room_ended: "Dieser Raum ist beendet.",
  could_not_create_room: "Der Raum konnte nicht erstellt werden.",
  no_session_to_resume: "In diesem Raum gibt es keine Sitzung von dir, die fortgesetzt werden könnte.",
  host_only: "Das kann nur der Gastgeber.",
  players_only: "Das können nur Spieler.",
  waiting_room_only: "Das gibt es nur im Warteraum.",
  already_a_player: "Du bist schon Spieler.",
  registered_name_fixed: "Registrierte Spieler spielen unter ihrem Benutzernamen.",
  name_taken_by_account: "Dieser Name gehört einem registrierten Spieler.",
  guests_cannot_choose_color: "Lege ein Konto an, um eine Namensfarbe zu wählen.",
  suggestion_inactive: "Dieser Vorschlag ist nicht mehr aktuell.",
  drawing_not_found: "Zeichnung nicht gefunden.",
  drawing_not_kept: "Diese Zeichnung wurde nicht aufbewahrt.",

  // Games and turns
  not_in_game: "Du bist in keiner laufenden Runde.",
  game_in_progress: "Das Spiel läuft bereits.",
  game_starting: "Das Spiel startet noch.",
  need_two_players: "Zum Starten braucht es zwei aktive Spieler.",
  room_not_startable: "Dieser Raum kann gerade kein Spiel starten.",
  prompt_not_ready: "Das Spiel ist noch nicht bereit für einen Begriff.",
  prompt_unavailable: "Dieser Begriff ist nicht mehr verfügbar.",
  hints_disabled: "Hinweise sind in diesem Raum abgeschaltet.",
  hint_spend_limit: "Du hast das Hinweis-Limit dieser Runde erreicht.",
  hint_unavailable: "Dieser Hinweis ist nicht verfügbar.",

  // Canvas
  drawer_only: "Das kann nur die zeichnende Person.",
  canvas_stale_generation: "Die Leinwand ist weiter. Wird nachgeholt.",
  canvas_sequence_committed: "Das wurde bereits gezeichnet.",
  canvas_out_of_sequence: "Zeichenschritte kamen in falscher Reihenfolge an. Wird nachgeholt.",
  canvas_out_of_sync: "Die Leinwand ist nicht synchron. Wird nachgeholt.",
  nothing_to_undo: "Es gibt nichts rückgängig zu machen.",

  // Votes and restarts
  spectators_cannot_vote: "Zuschauer können nicht abstimmen.",
  spectators_cannot_be_targets: "Über einen Zuschauer kann nicht abgestimmt werden.",
  invalid_vote_target: "Über diesen Spieler kannst du nicht abstimmen.",
  not_eligible: "Nur aktive Spieler können einen Neustart vorschlagen.",
  restart_vote_active: "Es läuft bereits eine Abstimmung über einen Neustart.",
  restart_vote_cooldown: "Über einen Neustart wurde gerade abgestimmt. Warte kurz, bevor du den nächsten vorschlägst.",
  no_restart_vote: "Es gibt keine Neustart-Abstimmung zu beantworten.",
  restart_vote_closed: "Diese Neustart-Abstimmung ist bereits beendet.",

  // Reactions
  spectators_cannot_react: "Zuschauer können nicht auf eine Zeichnung reagieren.",
  guests_cannot_react: "Lege ein Konto an, um auf eine Zeichnung zu reagieren.",
  reaction_not_visible: "Auf eine Zeichnung, die du nicht siehst, kannst du nicht reagieren.",
  own_drawing: "Auf deine eigene Zeichnung kannst du nicht reagieren.",
  game_still_saving: "Diese Runde wird noch gespeichert. Versuch es gleich noch einmal.",
  game_not_recorded: "Diese Runde wurde nicht aufgezeichnet.",
  reaction_not_accepted: "Diese Reaktion konnte nicht gesendet werden.",

  // Friends
  friends_unavailable: "Freunde sind gerade nicht verfügbar.",
  friend_refused: "Diese Freundschaftsanfrage konnte nicht abgeschlossen werden.",
  friend_not_in_game: "Dein Freund ist gerade in keiner Runde.",
  friend_in_several_games: "Dieser Freund ist in mehreren Runden. Bitte ihn um eine Einladung.",
  not_friends: "Du kannst nur der Runde eines Freundes beitreten.",
  friends_only_uninvited: "Nur Freunde des Gastgebers können dieser Runde ohne Einladung beitreten. Bitte ihn um eine Einladung.",
  invite_expired: "Diese Einladung ist abgelaufen.",

  // Moderation, from the reporter's side
  reporting_unavailable: "Meldungen sind auf diesem Server nicht verfügbar.",
  no_such_player: "Diesen Spieler gibt es nicht.",
  cannot_report: "Dieser Spieler kann nicht gemeldet werden.",
  already_reported: "Du hast das bereits gemeldet, und ein Moderator hat es noch nicht geprüft.",

  // Lobby chat
  name_required: "Wähle einen Namen, bevor du in der Lobby etwas sagst.",
  not_watching_lobby: "Du siehst der Lobby nicht mehr zu.",

  // Versioning
  protocol_mismatch: "Dieser Tab läuft mit einer älteren Version von Sketchy. Lade die Seite neu, um weiterzumachen.",

  // Sessions and accounts
  sign_in_required: "Melde dich zuerst an.",
  credentials_incorrect: "Benutzername oder Passwort ist falsch.",
  password_incorrect: "Das Passwort ist falsch.",
  account_suspended: "Dieses Konto ist gesperrt.",
  already_signed_in: "Du bist bereits bei einem Konto angemeldet.",
  username_taken: "Dieser Benutzername ist vergeben.",
  invalid_username: "Dieser Benutzername kann nicht verwendet werden.",
  weak_password: weakPassword,
  password_change_failed: "Das Passwort konnte nicht geändert werden.",
  session_not_found: "Dieses Gerät ist nicht mehr angemeldet.",
  session_replaced: "Diese Sitzung wurde ersetzt. Lade neu und versuch es noch einmal.",
  guest_progress_unlinked: "Der Gastfortschritt konnte nicht mit diesem Konto verknüpft werden.",
  not_taking_visitors: "Sketchy nimmt gerade keine neuen Besucher an. Bitte versuch es später noch einmal.",
  account_delete_refused: "Das Konto konnte gerade nicht gelöscht werden. Bitte versuch es noch einmal.",
  password_required_to_delete: "Gib dein Passwort ein, um das Konto zu löschen.",

  // Second factor and passkeys
  second_factor_required: "Gib den Code aus deiner Authenticator-App ein.",
  second_factor_passkey_only: "Melde dich mit deinem Passkey an.",
  second_factor_not_enrolled:
  "Dieses Konto braucht die Zwei-Faktor-Authentifizierung, bevor es sich anmelden kann. Bitte einen Administrator um Hilfe bei der Einrichtung.",
  second_factor_not_set_up: "Die Zwei-Faktor-Authentifizierung ist nicht eingerichtet.",
  second_factor_code_wrong: "Dieser Code stimmt nicht.",
  second_factor_throttled: "Zu viele falsche Codes. Bitte warte kurz und versuch es noch einmal.",
  step_up_required: "Bestätige, dass du es bist, bevor du das tust.",
  passkey_sign_in_required: "Melde dich mit deinem Passkey an.",
  passkey_not_registered: "Dieser Passkey ist hier nicht registriert.",
  passkey_not_found: "Diesen Passkey gibt es nicht.",
  passkey_refused:
  "Passkeys sind für Moderatoren- und Administratorenkonten. Du wirst gebeten, einen einzurichten, falls dir jemals eine Rolle angeboten wird.",
  last_factor: "Das ist der einzige Nachweis, dass du es bist. Füge einen weiteren hinzu, bevor du diesen entfernst.",
  second_factor_required_for_role: "Für die Rolle dieses Kontos ist die Zwei-Faktor-Authentifizierung erforderlich.",
  second_factor_not_proved:
  "Dieser Authenticator wurde noch nicht als deiner bestätigt. Nutze einen Passkey oder bestätige ihn mit deinem Passwort in den Einstellungen.",

  // Email, verification and recovery
  invalid_email: "Das sieht nicht nach einer E-Mail-Adresse aus.",
  email_in_use: "Diese Adresse wird bereits verwendet.",
  email_change_refused: "Diese Adresse kann diesem Konto nicht hinzugefügt werden.",
  verification_link_invalid: "Dieser Bestätigungslink ist abgelaufen oder wurde bereits verwendet.",
  reset_link_invalid: "Dieser Zurücksetzen-Link ist abgelaufen oder wurde bereits verwendet.",

  // Account data export
  export_not_found: "Export nicht gefunden.",
  export_expired: "Der Export ist abgelaufen.",
  export_not_ready: "Der Export ist noch nicht fertig.",
  export_unreadable: "Das Exportdokument konnte nicht gelesen werden. Fordere einen neuen Export an.",
  export_not_yet_allowed: "Du hast vor Kurzem einen Export angefordert. Versuch es später noch einmal.",
  export_refused: "Dieser Export konnte nicht gestartet werden. Bitte versuch es noch einmal.",

  // Rate limits reached over HTTP
  too_many_attempts: "Zu viele Versuche. Bitte warte kurz und versuch es noch einmal.",
  too_many_requests: "Zu viele Anfragen. Bitte warte kurz und versuch es noch einmal.",
  too_many_reports: "Zu viele Meldungen. Bitte warte, bevor du die nächste sendest.",
  too_many_bug_reports: "Zu viele Fehlerberichte. Bitte warte, bevor du den nächsten sendest.",
  too_many_pictures: "Zu viele Bilder. Bitte warte kurz und versuch es noch einmal.",

  // Pictures
  unsupported_picture_type: "Das ist kein WebP- oder PNG-Bild.",
  picture_not_found: "Dieses Bild gibt es nicht.",
  picture_refused: "Dieses Bild kann hier nicht verwendet werden.",

  // Bug reports
  screenshot_unreadable: "Der Screenshot konnte nicht gelesen werden.",
  screenshot_too_large: (params) =>
  `Dieser Screenshot ist zu groß. Das Limit liegt bei ${megabytes(params.limitBytes, "2 MB")}.`,
  screenshot_unsupported_type: "Ein Screenshot muss ein PNG- oder WebP-Bild sein.",
  bug_report_context_too_large: "Dieser Bericht trägt zu viel Kontext mit sich.",

  // Friends, over HTTP
  friends_throttled: "Du hast viele Freundschaftsanfragen gesendet. Versuch es später noch einmal.",
  that_is_you: "Das bist du.",

  // Profiles and history
  no_such_game: "Diese Runde gibt es nicht.",
  no_such_drawing: "Diese Zeichnung gibt es nicht.",
  drawing_unreadable: "Diese Zeichnung konnte nicht gelesen werden.",

  // Prompt lists
  prompt_list_not_found: "Begriffsliste nicht gefunden.",
  shared_prompt_list_not_found: "Keine geteilte Begriffsliste gefunden.",
  prompt_list_conflict: "Jemand anderes hat diese Liste geändert. Lade sie neu und versuch es noch einmal.",
  prompt_list_invalid: "Diese Begriffsliste konnte nicht gespeichert werden.",
  prompt_list_forbidden: "Diese Begriffsliste kannst du nicht ändern.",
  unknown_sort: "Danach kann Sketchy nicht sortieren.",
  timezone_required: "Gib zu diesem Datum eine Zeitzone an.",
  range_reversed: "Der Anfang des Zeitraums muss vor seinem Ende liegen.",

  // Room presets
  room_preset_not_found: "Raumvorlage nicht gefunden.",
  room_preset_conflict: "Du hast bereits eine Vorlage mit diesem Namen.",
  room_preset_unavailable: "Diese Vorlage kann gerade nicht verwendet werden.",
  room_preset_forbidden: "Diese Vorlage gehört dir nicht.",

  // Blocks
  cannot_block_yourself: "Du kannst dich nicht selbst blockieren.",
  block_list_full: (params) =>
  `Deine Blockierliste ist voll${
    typeof params.limit === "number" ? ` bei ${params.limit}` : ""
  }. Hebe zuerst eine Blockierung auf.`,

  // Settings
  setting_refused: "Diese Einstellung konnte nicht gespeichert werden.",

  // Role notices
  no_such_notice: "Diesen Hinweis gibt es nicht.",

  // Reporting, from the reporter's side
  cannot_report_yourself: "Du kannst dich nicht selbst melden.",
  cannot_report_own_prompt_list: "Du kannst deine eigene Begriffsliste nicht melden.",
  no_reportable_prompt_list: "Keine meldbare Begriffsliste gefunden.",
  prompt_not_in_list: "Dieser Begriff gehört nicht zu dieser Liste.",
  no_picture_to_report: "Dieser Spieler hat kein Bild, das man melden könnte.",
  no_such_game_context: "Diesen Rundenkontext gibt es nicht.",
  no_such_turn_context: "Diesen Zugkontext gibt es nicht.",
  turn_not_in_game: "Der Zug gehört nicht zu dieser Runde.",
  evidence_unavailable: "Eine oder mehrere ausgewählte Nachrichten sind nicht verfügbar.",
  evidence_mixed_scopes: "Lobby- und Raumnachrichten können nicht in einer Meldung gemischt werden.",
  evidence_several_rooms: "Ausgewählte Nachrichten müssen aus demselben Raum stammen.",
  evidence_not_theirs: "Belege müssen vom gemeldeten Spieler stammen.",
  evidence_not_received: "Du kannst keine Nachricht auswählen, die du nicht erhalten hast.",
  evidence_not_in_game: "Die ausgewählte Nachricht gehört nicht zu dieser Runde.",
  evidence_not_in_turn: "Die ausgewählte Nachricht gehört nicht zu diesem Zug.",
  no_such_warning: "Diese Verwarnung gibt es nicht.",
  no_drawing: "Keine Zeichnung.",};

/** What the room says about itself. One entry per `AnnouncementCode`. */
const ANNOUNCEMENTS: Record<AnnouncementCode, (params: MessageParams) => string> = {
  nickname_changed: (p) =>
  `${text(p.previous)} heißt jetzt ${text(p.nickname)}.`,
  joined_as_player: (p) => `${text(p.nickname)} ist als Spieler beigetreten.`,
  kicked_by_vote: (p) => `${text(p.nickname)} wurde per Abstimmung rausgeworfen.`,
  marked_afk_by_vote: (p) => `${text(p.nickname)} wurde per Abstimmung als AFK markiert.`,

  restart_vote_started: (p) =>
  `${text(p.nickname)} hat eine Abstimmung über einen Neustart gestartet.`,
  restart_vote_passed: (p) =>
  `Die Neustart-Abstimmung wurde angenommen. Neustart in ${count(p.seconds, 5)} Sekunden.`,
  restart_vote_rejected: () => "Die Neustart-Abstimmung wurde abgelehnt.",
  restart_vote_expired: () => "Die Neustart-Abstimmung ist abgelaufen, ohne anzunehmen.",
  restart_vote_abandoned: () =>
  "Die Neustart-Abstimmung wurde abgebrochen, weil weniger als zwei aktive Spieler übrig sind.",
  restart_cancelled: (p) => `Der Neustart wurde abgebrochen, weil ${cancelReason(p.reason)}.`,
  game_restarted_by_vote: () => "Das Spiel wurde per Spielerabstimmung neu gestartet.",

  hint_letter_found: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} Pkt. – ${counted(count(p.count, 1), {
    one: "Mal",
    other: "Mal",
  })} gefunden!`,
  hint_letter_missing: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} Pkt. – nicht im Begriff.`,
  guess_very_close: (p) => `„${text(p.text)}“ ist ganz nah dran!`,
  guess_some_words_correct: () => "Einige Wörter stimmen",};

export const DE: Catalogue = {
  refusals: REFUSALS,
  announcements: ANNOUNCEMENTS,

  /** What the document itself says: the tab, and what a link preview shows.

      Rendered into `index.html` for a crawler, which arrives before any
      script, and rewritten here for the reader once their locale is known. */
  document: {
    description: "Zeichnen, raten und mit Freunden lachen!",
  },

  /** Shapes that belong to the language rather than to any one screen. */
  format: {
    /** `1st`, `2nd`, `3rd`; a language with no ordinal form gets the number. */
    ordinal: (p: { value: number }) => ordinal(p.value),
  },

  promptListDrafts: {
    promptsAdded: (p: { count: number }) =>
      `${counted(p.count, { one: "Begriff", other: "Begriffe" })} hinzugefügt`,
  },

  lastSeen: {
    online: "online",
    justNow: "zuletzt gerade eben gesehen",
    lastSeenAgo: (p: { count: number; unit: "minute" | "hour" | "day" }) => {
      const words = {
        minute: { one: "Minute", other: "Minuten" },
        hour: { one: "Stunde", other: "Stunden" },
        day: { one: "Tag", other: "Tagen" },
      }[p.unit];
      return `zuletzt vor ${counted(p.count, words)} gesehen`;
    },
  },

  gameHighlights: {
    reactionCount: (p: { count: number }) =>
      counted(p.count, { one: "Reaktion", other: "Reaktionen" }),
  },

  versionBadge: {
    buildDetails: (p: { commitDate: string; builtAt: string }) =>
      `Commit-Datum: ${p.commitDate} | Gebaut: ${p.builtAt}`,
  },

  segmentedCodeInput: {
    digitPosition: (p: { label: string; index: number; length: number }) =>
      `${p.label}, Ziffer ${p.index} von ${p.length}`,
  },

  roomSetupControls: {
    decrease: (p: { label: string }) => `${p.label} verringern`,
    increase: (p: { label: string }) => `${p.label} erhöhen`,
  },

  guessPips: {
    playerGuessState: (p: { nickname: string; isFriend: boolean; guessed: boolean }) =>
      `${p.nickname}${p.isFriend ? " (Freund)" : ""} ${p.guessed ? "hat es erraten" : "rät noch"}`,
  },

  accountDataDialog: {
    requestedOn: (p: { when: string; schemaVersion: number }) =>
      `Angefordert ${p.when} · Format v${p.schemaVersion}`,
    exportAllowance: (p: { nextAllowed: string | null }) =>
      p.nextAllowed
        ? `Ein Export pro Woche; fertige Exporte verfallen nach sieben Tagen. Den nächsten kannst du am ${p.nextAllowed} anfordern.`
        : "Ein Export pro Woche; fertige Exporte verfallen nach sieben Tagen.",
    couldNotLoadYourDataExports: "Deine Datenexporte konnten nicht geladen werden.",
    couldNotRequestYourDataExport: "Dein Datenexport konnte nicht angefordert werden.",
    yourData: "Deine Daten",
    downloadPrivateJsonCopyYourAccount: "Lade eine private JSON-Kopie deiner Konto- und Spieldaten herunter. Profile und Nachrichten anderer Spieler sind nicht enthalten.",
    dataExports: "Datenexporte",
    loadingExports: "Exporte werden geladen …",
    youHaveNotRequestedExportYet: "Du hast noch keinen Export angefordert.",
    download: "Herunterladen",
    close: "Schließen",
  },

  accountMenu: {
    noPasskeyWasUsed: "Es wurde kein Passkey verwendet. Du kannst dich stattdessen mit deinem Passwort anmelden.",
    signedInWithRequests: (p: { name: string; waiting: number }) =>
      `Angemeldet als ${p.name}. ${counted(p.waiting, {
        one: "Freundschaftsanfrage wartet",
        other: "Freundschaftsanfragen warten",
      })}.`,
    friends: "Freunde",
    finishYourRole: (p: { role: "admin" | "moderator" }) =>
      `Schließe deine Rolle als ${p.role === "admin" ? "Administrator" : "Moderator"} ab`,
    agreeToRules: "Mit dem Anlegen eines Kontos stimmst du zu, die {rules} zu befolgen.",
    reportBug: "Fehler melden",
    account: "Konto",
    settings: "Einstellungen",
    myProfile: "Mein Profil",
    promptStats: "Begriffsstatistik",
    createAccount: "Konto anlegen",
    logIn: "Anmelden",
    myPromptLists: "Meine Begriffslisten",
    rules: "Regeln",
    logOut: "Abmelden",
    thatDoesNotLookLikeEmail: "Das sieht nicht nach einer E-Mail-Adresse aus.",
    somethingWentWrongPleaseTryAgain: "Etwas ist schiefgelaufen. Bitte versuch es noch einmal.",
    thatPasskeyWasNotAccepted: "Dieser Passkey wurde nicht akzeptiert.",
    thisAccountSignsWithPasskey: "Dieses Konto meldet sich mit einem Passkey an.",
    or: "oder",
    username: "Benutzername",
    password: "Passwort",
    codeFromYourAuthenticatorApp: "Code aus deiner Authenticator-App",
    recoveryCodeWorksHereTooCan: "Ein Wiederherstellungscode funktioniert hier auch und lässt sich einmal verwenden.",
    email: "E-Mail",
    optional: "optional",
    letsYouResetYourPasswordLater: "Damit kannst du später dein Passwort zurücksetzen. Sonst wird sie für nichts verwendet.",
    rules2: "Regeln",
    forgotYourPassword: "Passwort vergessen?",
    notNow: "Jetzt nicht",
  },

  accountRecoveryPage: {
    thatConfirmationLinkCouldNotBe: "Dieser Bestätigungslink konnte nicht verwendet werden.",
    somethingWentWrongPleaseTryAgain: "Etwas ist schiefgelaufen. Bitte versuch es noch einmal.",
    evenBestGuessersForgetSometimes: "Auch die besten Ratenden vergessen mal etwas.",
    weRsquoLlSendSecureTime: "Wir senden einen sicheren, zeitlich begrenzten Link an die bestätigte\n            E-Mail-Adresse deines Kontos.",
    accountHelp: "Kontohilfe",
    backLobby: "Zurück zur Lobby",
    enterYourUsernameYourConfirmedEmail: "Gib deinen Benutzernamen oder deine bestätigte E-Mail-Adresse ein. Wenn\n              das Konto wiederhergestellt werden kann, ist ein Link unterwegs.",
    usernameEmail: "Benutzername oder E-Mail",
    thatResetLinkHasExpiredHas: "Dieser Zurücksetzen-Link ist abgelaufen oder wurde bereits verwendet.\n              Solche Links funktionieren einmal und gelten eine Stunde.",
    sendNewOne: "Neuen senden",
    checkingThatLink: "Link wird geprüft …",
    everySignedDeviceWillBeSigned: "Alle angemeldeten Geräte werden abgemeldet, auch die, die du nicht\n              erkannt hast.",
    newPassword: "Neues Passwort",
  },

  activeGameRoom: {
    leaveGame: "Spiel verlassen",
    markedAfkByRoomVote: "Du wurdest per Raumabstimmung als AFK markiert.",
    couldNotChangeSuggestion: (p: { action: string }) =>
      `Der Farbvorschlag ließ sich nicht ${p.action}.`,
    inviteLinkCopied: "Einladungslink kopiert.",
    couldnTCopyLinkCopyFrom: "Der Link konnte nicht kopiert werden. Kopiere ihn aus der Adresszeile.",
    couldNotStartGamePleaseTry: "Das Spiel konnte nicht gestartet werden. Bitte versuch es noch einmal.",
    couldNotStartRestartVote: "Eine Neustart-Abstimmung konnte nicht gestartet werden.",
    couldNotRecordYourRestartVote: "Deine Stimme zum Neustart konnte nicht erfasst werden.",
    copyRoomInviteLink: "Einladungslink des Raums kopieren",
    clickCopyRoomInviteLink: "Klicken, um den Einladungslink zu kopieren",
    roomMenu: "Raummenü",
    afk: "AFK",
    saveImage: "Bild speichern",
    saveDrawnImageFile: "Gezeichnetes Bild als Datei speichern",
    playerSettings: "Spielereinstellungen",
    leaveRoom: "Raum verlassen",
    leave: "Verlassen",
    players: "Spieler",
  },

  addEmailDialog: {
    followTheLink: (p: { address: string; replacing: boolean }) =>
      `Folge dem Link an ${p.address}. Bis dahin gehört die Adresse nicht zu deinem Konto und kann es nicht wiederherstellen${
        p.replacing ? ", und die bisherige bleibt bestehen." : "."
      }`,
    thatDoesNotLookLikeEmail: "Das sieht nicht nach einer E-Mail-Adresse aus.",
    somethingWentWrongPleaseTryAgain: "Etwas ist schiefgelaufen. Bitte versuch es noch einmal.",
    done: "Fertig",
    usedOnlyResetYourPasswordTell: "Wird nur genutzt, um dein Passwort zurückzusetzen und dich zu\n              informieren, wenn dein Konto oder etwas von dir bearbeitet wird.\n              Sonst geht hier nie etwas raus.",
  },

  afkCheckDialog: {
    secondsUnit: (p: { count: number }) =>
      plural(p.count, { one: "Sekunde", other: "Sekunden" }),
    stillThere: "Noch da?",
    youHaveBeenQuietWhileAnswer: "Du bist schon eine Weile still. Antworte und du spielst weiter;\n          sonst markiert dich der Raum als AFK und macht ohne dich weiter.",
    stillTherePressButtonMoveMouse: "Noch da? Drück den Knopf oder beweg die Maus, um weiterzuspielen.",
    iMHere: "Ich bin da",
  },

  app: {
    serverUpdateInProgress: (p: { seconds: number }) =>
      p.seconds > 0
        ? `Server-Update läuft. Neue Räume und Runden können nicht starten; eine laufende Runde hat noch ${counted(p.seconds, { one: "Sekunde", other: "Sekunden" })}.`
        : "Server-Update läuft. Neue Räume und Runden können nicht starten; laufende Runden enden jetzt.",
    thisTabOutDateCannotPlay: "Dieser Tab ist veraltet und kann erst nach dem Neuladen wieder mitspielen.",
    reload: "Neu laden",
    newRoomsArePausedMaintenanceGames: "Neue Räume pausieren wegen Wartung. Bereits laufende Runden gehen ganz\n          normal weiter.",
    serverWasUpdatedBackAnyGame: "Der Server wurde aktualisiert und ist zurück. Laufende Runden wurden beendet.",
    dismiss: "Ausblenden",
  },

  appHeader: {
    playerSettings: "Spielereinstellungen",
  },

  bugReportDialog: {
    connectionSummary: (p: { connected: boolean; reconnects: number }) =>
      `${p.connected ? "verbunden" : "offline"} · ${counted(p.reconnects, {
        one: "Neuverbindung",
        other: "Neuverbindungen",
      })} in diesem Besuch`,
    couldNotTakeScreenshot: "Der Screenshot konnte nicht aufgenommen werden.",
    thanksYourReportWithPeopleWho: "Danke — dein Bericht liegt bei den Leuten, die Sketchy betreiben.",
    couldNotSendReport: "Der Bericht konnte nicht gesendet werden.",
    reportBug: "Fehler melden",
    somethingBrokenNotSomethingSomeoneSaid: "Etwas ist kaputt, nicht etwas, das jemand gesagt hat. Das geht an die Leute, die Sketchy betreiben — nie an andere Spieler.",
    where: "Wo",
    howBad: "Wie schlimm",
    oneLineSummary: "Zusammenfassung in einer Zeile",
    whatWentWrongOneLine: "Was schiefgelaufen ist, in einer Zeile",
    whatHappened: "Was passiert ist",
    whatYouDidWhatYouExpected: "Was du getan hast, was du erwartet hast, was stattdessen passiert ist.",
    screenshot: "Screenshot",
    optional: "Optional",
    screenshotThatWillBeSentWith: "Der Screenshot, der mit diesem Bericht gesendet wird",
    thisDialogHidesItselfWhileShot: "Dieses Fenster blendet sich während der Aufnahme aus, damit du die Seite dahinter bekommst. Sieh es dir vor dem Senden an — du entscheidest, was du teilst.",
    replace: "Ersetzen",
    remove: "Entfernen",
    opensYourBrowserSOwnPicker: "Öffnet die Auswahl deines Browsers — wähle diesen Tab. Dieses Fenster blendet sich während der Aufnahme aus, damit du die Seite dahinter bekommst.",
    recentClientErrors: "Letzte Client-Fehler",
    sendMyDescriptionOnly: "Nur meine Beschreibung senden",
    dropsDetailsAboveAnyScreenshotWe: "Verwirft die Angaben oben und jeden Screenshot. Wir lesen es trotzdem, aber der Fehler ist dann viel schwerer nachzustellen.",
    cancel: "Abbrechen",
  },

  changePasswordDialog: {
    forgottenTheCurrentOne: "Das aktuelle vergessen?",
    twoNewPasswordsDoNotMatch: "Die beiden neuen Passwörter stimmen nicht überein.",
    passwordChangedEveryOtherDeviceHas: "Passwort geändert. Alle anderen Geräte wurden abgemeldet.",
    couldNotChangePasswordPleaseTry: "Das Passwort konnte nicht geändert werden. Bitte versuch es noch einmal.",
    ifThatAccountHasVerifiedEmail: "Wenn dieses Konto eine bestätigte E-Mail-Adresse hat, ist ein Link für\n              ein neues Passwort unterwegs. Er funktioniert einmal und läuft ab.",
    done: "Fertig",
    everyDeviceSignsOutWhenPassword: "Beim Passwortwechsel werden alle Geräte abgemeldet, auch die, die du\n              nicht angemeldet lassen wolltest. Dieses bleibt.",
    currentPassword: "Aktuelles Passwort",
    newPassword: "Neues Passwort",
    newPasswordAgain: "Neues Passwort wiederholen",
    emailMeLinkInstead: "Schick mir stattdessen einen Link",
  },

  choosingPromptOverlay: {
    isChoosingPrompt: "{drawer} wählt gerade einen Begriff …",
    nextTurn: "Nächster Zug",
    drawingWillBeginAsSoonAs: "Gezeichnet wird, sobald die Wahl steht.",
  },

  colorblindSafeSuggestionBanner: {
    colorblindSafeColorSuggestion: "Vorschlag für farbenblindensichere Farben",
    playerThisRoomPlaysWithColorblind: "Ein Spieler in diesem Raum spielt mit farbenblindensicheren Farben.",
    switchRoomPaletteFutureDrawings: "Die Raumpalette für kommende Zeichnungen umstellen?",
    switchColors: "Farben umstellen",
    notNow: "Jetzt nicht",
  },

  confirmationDialog: {
    cancel: "Abbrechen",
  },

  crashPage: {
    couldNotSendReport: "Der Bericht konnte nicht gesendet werden.",
    bugCrawledOntoPage: "Ein Fehler hat sich auf die Seite verirrt",
    helpUsSquash: "Hilf uns, ihn zu beheben",
    reportReadySendErrorWhatThis: "Ein Bericht ist fertig: der Fehler und was dieser Tab über sich weiß.\n            Er geht an die Leute, die Sketchy betreiben — nie an andere Spieler.",
    whatWereYouDoing: "Was hast du gerade gemacht?",
    optional: "Optional",
    lastThingYouClickedTypedIf: "Das Letzte, was du geklickt oder getippt hast, falls du dich erinnerst.",
    recentClientErrorsNewestFirst: "Letzte Client-Fehler, neueste zuerst",
    sendMyDescriptionOnly: "Nur meine Beschreibung senden",
    dropsDetailsAboveWeWillStill: "Verwirft die Angaben oben. Wir lesen es trotzdem, aber der Absturz ist dann viel schwerer zu finden.",
    thanksYourReportWithPeopleWho: "Danke — dein Bericht liegt bei den Leuten, die Sketchy betreiben.",
    reload: "Neu laden",
    backLobby: "Zurück zur Lobby",
  },

  createRoomPage: {
    setupTiming: "Diese Einstellung dauert {full} bei vollem Raum mit {capacity}",
    setupTimingFull: (p: { minutes: number }) =>
      `etwa ${counted(p.minutes, { one: "Minute", other: "Minuten" })}`,
    setupTimingHalf: (p: { players: number }) => ` — eher {half}, wenn ${p.players} mitspielen`,
    couldNotLoadYourRoomPresets: "Deine Raumvorlagen konnten nicht geladen werden.",
    couldNotApplyThatPreset: "Diese Vorlage konnte nicht angewendet werden.",
    enterNameRoomPreset: "Gib der Raumvorlage einen Namen.",
    couldNotSaveThatPreset: "Diese Vorlage konnte nicht gespeichert werden.",
    couldNotUpdateThatPreset: "Diese Vorlage konnte nicht aktualisiert werden.",
    couldNotDeleteThatPreset: "Diese Vorlage konnte nicht gelöscht werden.",
    fixCustomPromptEntriesMarkedAbove: "Behebe die oben markierten eigenen Begriffe, bevor du den Raum erstellst.",
    failedCreateRoom: "Raum konnte nicht erstellt werden",
    roomSetup: "Raum einrichten",
    createRoom: "Raum erstellen",
    startFromSavedPreset: "Mit einer gespeicherten Vorlage beginnen",
    startFromPreset: "Mit einer Vorlage beginnen …",
    nameThisPreset: "Diese Vorlage benennen",
    save: "Speichern",
    cancel: "Abbrechen",
    saveAsPreset: "Als Vorlage speichern",
    update: "Aktualisieren",
    delete: "Löschen",
    undo: "Rückgängig",
    saveAsReusableList: "Als wiederverwendbare Liste speichern",
  },

  customPromptsEditor: {
    usableCount: (p: { count: number }) =>
      counted(p.count, { one: "verwendbarer eigener Begriff", other: "verwendbare eigene Begriffe" }),
    duplicatesIgnored: (p: { count: number }) =>
      `${counted(p.count, { one: "Dublette", other: "Dubletten" })} ignoriert`,
    entriesTooLong: (p: { count: number; limit: number }) =>
      `${counted(p.count, { one: "Eintrag ist", other: "Einträge sind" })} länger als ${number(p.limit)} Zeichen`,
    entryLimit: (p: { limit: number }) => `Es sind nur ${number(p.limit)} Einträge erlaubt`,
    customPromptsOptional: "Eigene Begriffe (optional)",
    onePromptPerLineSeparateEntries: "Ein Begriff pro Zeile\noder Einträge mit Komma trennen",
    shortenRemoveOverlongEntriesBeforeCreating: "Kürze oder entferne zu lange Einträge, bevor du den Raum erstellst.",
  },

  customPromptsPreview: {
    resultsMatching: (p: { shown: number; total: number }) =>
      `${number(p.shown)} von ${number(p.total)} Begriffen passen`,
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "Begriff", other: "Begriffe" }),
    customPromptCount: (p: { count: number }) =>
      counted(p.count, { one: "eigener Begriff", other: "eigene Begriffe" }),
    inspectPrompts: (p: { count: number }) =>
      `${counted(p.count, { one: "eigenen Begriff", other: "eigene Begriffe" })} ansehen`,
    couldNotLoadCustomPrompts: "Die eigenen Begriffe konnten nicht geladen werden",
    loadingCustomPrompts: "Eigene Begriffe werden geladen …",
    roomPromptCollection: "Begriffssammlung des Raums",
    readOnlyListSuppliedByRoom: "Schreibgeschützte Liste vom Gastgeber des Raums.",
    findPrompt: "Begriff finden",
    searchCustomPrompts: "Eigene Begriffe durchsuchen …",
    filterPromptsByLength: "Begriffe nach Länge filtern",
    noCustomPromptsMatchTheseFilters: "Keine eigenen Begriffe passen zu diesen Filtern.",
  },

  deleteAccountDialog: {
    whatIsRemoved: (p: { isGuest: boolean }) =>
      `${
        p.isGuest
          ? "Der Name, die Punkte und der Verlauf, die zu diesem Browser gehören, werden entfernt."
          : "Dein Name wird aus den Runden entfernt, die du gespielt hast."
      } Punkte und Zeichnungen bleiben unter „Gelöschter Spieler“, weil es auch die Runden anderer Leute sind. Das lässt sich nicht rückgängig machen.`,
    typeToConfirm: (p: { word: string }) => `Tippe ${p.word} zur Bestätigung`,
    couldNotDeleteAccount: "Das Konto konnte nicht gelöscht werden.",
    password: "Passwort",
  },

  drawingReactionControl: {
    reactionSummary: (p: { total: number; chips: string }) =>
      `${counted(p.total, { one: "Reaktion", other: "Reaktionen" })}: ${p.chips}`,
    thatReactionCouldNotBeSent: "Diese Reaktion konnte nicht gesendet werden.",
    reactThisDrawing: "Auf diese Zeichnung reagieren",
    reactions: "Reaktionen",
    createAccountReact: "Lege ein Konto an, um zu reagieren.",
    createAccount: "Konto anlegen",
  },

  drawingRecapGallery: {
    drawingLabel: (p: { prompt: string; drawer: string }) =>
      `Zeichnung von ${p.prompt} von ${p.drawer}`,
    drawnBy: "Gezeichnet von {drawer} · Runde {round} · Zug {turn}",
    position: (p: { position: number; total: number }) => `${p.position} von ${p.total}`,
    thisDrawingCouldNotBeDecoded: "Diese Zeichnung konnte nicht dekodiert werden.",
    drawingRecap: "Zeichnungsrückblick",
    saveImage: "Bild speichern",
    close: "Schließen",
    thisDrawingWasNotKept: "Diese Zeichnung wurde nicht aufbewahrt.",
    roomRanOutRoomLaterTurns: "Der Raum hatte keinen Platz mehr dafür. Stattdessen wurden spätere Züge behalten.",
    tryAgain: "Noch einmal versuchen",
    loadingDrawing: "Zeichnung wird geladen …",
    noDrawingWasCapturedThisTurn: "Für diesen Zug wurde keine Zeichnung aufgezeichnet.",
    drawingRecapNavigation: "Navigation im Zeichnungsrückblick",
    previous: "Zurück",
    next: "Weiter",
  },

  emailRecoveryReminder: {
    addEmail: "E-Mail hinzufügen",
    dismiss: "Ausblenden",
  },

  firstRunIdentity: {
    couldNotSaveThatNamePlease: "Dieser Name konnte nicht gespeichert werden. Bitte versuch es noch einmal.",
    keepYourUsernameYourStatsEvery: "Behalte deinen Benutzernamen und deine Statistik auf jedem Gerät.",
    createAccount: "Konto anlegen",
    logIn: "Anmelden",
    or: "oder",
    displayName: "Anzeigename",
  },

  friendButton: {
    requestSentTo: (p: { name: string }) => `Freundschaftsanfrage an ${p.name} gesendet`,
    addFriend: "Freund hinzufügen",
    acceptRequest: "Anfrage annehmen",
    requestSent: "Anfrage gesendet",
  },

  friendInviteNotice: {
    couldNotJoinThatGame: "Dieser Runde konnte nicht beigetreten werden.",
    thatGameCouldNotBeJoined: "Dieser Runde konnte nicht beigetreten werden.",
    invitedYouTheirGame: "hat dich in seine Runde eingeladen.",
    join: "Beitreten",
    dismissInvitation: "Einladung ausblenden",
  },

  friendsOverlay: {
    declineWarning: (p: { name: string }) =>
      `${p.name} kann dann nicht noch einmal fragen. Du kannst später selbst eine Anfrage schicken.`,
    decline2: "Ablehnen",
    youWillBothStopBeingAble: "Ihr könnt dann beide nicht mehr ohne Einladung in die Runden des anderen. Ihr könnt jederzeit wieder fragen.",
    remove2: "Entfernen",
    removeConfirm: (p: { name: string }) => `${p.name} entfernen?`,
    friends: "Freunde",
    close: "Schließen",
    closeFriends: "Freunde schließen",
    friendsNeedAccountGuestNameBelongs: "Für Freunde braucht es ein Konto. Ein Gastname gehört diesem Browser\n              und nicht dir, also wäre in einem Monat niemand mehr da, mit dem\n              man befreundet sein könnte.",
    loading: "Wird geladen …",
    noFriendsYetAddSomebodyFrom: "Noch keine Freunde. Füge jemanden aus der Lobby hinzu oder aus einer\n              Runde, in der ihr beide seid.",
    requests: "Anfragen",
    accept: "Annehmen",
    decline: "Ablehnen",
    sent: "Gesendet",
    cancel: "Abbrechen",
    remove: "Entfernen",
    declineThisRequest: "Diese Anfrage ablehnen?",
    recentlyPlayedWith: "Kürzlich zusammen gespielt",
  },

  gameEndOverlay: {
    continueLabel: "Weiter",
    youFinished: (p: { points: number }) =>
      `Du wurdest {place} mit ${counted(p.points, { one: "Punkt", other: "Punkten" })}.`,
    continueToWaitingRoom: "Weiter zum Warteraum",
    continueWithCountdown: (p: { seconds: number }) =>
      `Weiter zum Warteraum, noch ${counted(p.seconds, { one: "Sekunde", other: "Sekunden" })}`,
    gameOver: "Spiel vorbei",
    you: "du",
    friend: "Freund",
    noScoresThisTimeJustRoom: "Diesmal keine Punkte — nur ein Raum voller Skizzen und Vermutungen.",
    keep: "Behalten",
    asYourUsername: "als deinen Benutzernamen",
    createAccount: "Konto anlegen",
    highlights: "Höhepunkte",
    drawings: "Zeichnungen",
    stayHere: "Hierbleiben",
  },

  gameHighlightsPanel: {
    lastGame: "Letzte Runde",
    highlights: "Höhepunkte",
    closeHighlights: "Höhepunkte schließen",
    thatGameWasTooShortSay: "Diese Runde war zu kurz, um viel dazu zu sagen. Spiel eine längere, dann\n            erscheinen hier die Höhepunkte.",
    seeIt: "Ansehen",
    back: "Zurück",
  },

  inviteEntryPage: {
    roomCode: (p: { code: string }) => `Raum ${p.code}`,
    hereCount: (p: { here: number; capacity: number; full: boolean }) =>
      `${p.here}/${p.capacity} hier${p.full ? " · voll" : ""}`,
    roomSummary: (p: { rounds: number; seconds: number; hintMode: string }) =>
      `${counted(p.rounds, { one: "Runde", other: "Runden" })} · ${p.seconds}s · ${p.hintMode}`,
    checkingYourInvite: "Deine Einladung wird geprüft …",
    loadingRoomDetails: "Raumdetails werden geladen.",
    roomUnavailable: "Raum nicht verfügbar",
    backLobby: "Zurück zur Lobby",
    players: "Spieler",
    rounds: "Runden",
    drawTime: "Zeichenzeit",
    scoring: "Punkte",
    roomRules: "Raumregeln",
    thisGameAlreadyProgressJoiningAs: "Diese Runde läuft bereits. Als Spieler kommst du in einen späteren Zug.",
    playerSlotsAreFullSpectatingStill: "Alle Spielplätze sind belegt. Zuschauen geht noch.",
  },

  inviteFriendsList: {
    invitationCouldNotBeSent: "Diese Einladung konnte nicht gesendet werden.",
    invitationSent: (p: { name: string }) => `Einladung an ${p.name} gesendet.`,
    thatInvitationCouldNotBeSent: "Diese Einladung konnte nicht gesendet werden.",
    friendsLobby: "Freunde in der Lobby",
    invited: "Eingeladen",
    invite: "Einladen",
  },

  languagePicker: {
    currentChoice: (p: { label: string; value: string }) => `${p.label}: ${p.value}`,
    everyLanguage: "Alle Sprachen",
  },

  lobbyBrowserPage: {
    filterByLanguage: "Nach Sprache filtern",
    filtersWithCount: (p: { count: number }) =>
      p.count > 0 ? `Filter · ${p.count}` : "Filter",
    showRooms: (p: { count: number }) =>
      `${counted(p.count, { one: "Raum", other: "Räume" })} zeigen`,
    removedFromRoom: "Aus dem Raum entfernt",
    ok: "OK",
    roomCode: "Raumcode",
    abc123: "ABC123",
    thereNoRoomCodeClipboard: "In der Zwischenablage ist kein Raumcode.",
    sketchyCouldNotReadClipboardPaste: "Sketchy konnte die Zwischenablage nicht lesen. Füge stattdessen in die Felder ein.",
    pleaseEnterRoomCode: "Bitte gib einen Raumcode ein",
    failedJoinRoom: "Beitritt zum Raum fehlgeschlagen",
    joinByCode: "Mit Code beitreten",
    createRoom: "Raum erstellen",
    publicRooms: "Öffentliche Räume",
    searchRoomsByNameCode: "Räume nach Name oder Code suchen",
    hideFull: "Volle ausblenden",
    hideProgress: "Laufende ausblenden",
    filters: "Filter",
    clearFilters: "Filter zurücksetzen",
    language: "Sprache",
    hideFullRooms: "Volle Räume ausblenden",
    hideGamesProgress: "Laufende Runden ausblenden",
    loadingPublicRooms: "Öffentliche Räume werden geladen …",
    noPublicRoomsYetCreateOne: "Noch keine öffentlichen Räume. Erstelle einen!",
    noPublicRoomsMatchYourSearch: "Keine öffentlichen Räume passen zu deiner Suche.",
    createRoom2: "Raum erstellen",
    joinWithCode: "Mit einem Code beitreten",
    paste: "Einfügen",
  },

  lobbyChatPanel: {
    reportThisLine: (p: { name: string }) => `Diese Zeile von ${p.name} melden`,
    couldNotSendThat: "Das konnte nicht gesendet werden.",
    chat: "Chat",
    lobbyChat: "Lobby-Chat",
    nobodyHasSaidAnythingYet: "Noch hat niemand etwas gesagt.",
    chooseNameChat: "Wähle einen Namen zum Chatten",
    saySomethingLobby: "Sag etwas in die Lobby …",
    lobbyChatMessage: "Lobby-Chatnachricht",
    send: "Senden",
  },

  lobbyPlayerMenu: {
    whatToDoAbout: (p: { name: string }) => `Was tun mit ${p.name}`,
    openPlayerProfile: "Spielerprofil öffnen",
    addAsFriend: "Als Freund hinzufügen",
    report: "Melden",
  },

  myPromptListsPage: {
    listSummary: (p: { prompts: number; visibility: string; moderationState: string | null }) =>
      `${counted(p.prompts, { one: "Begriff", other: "Begriffe" })} · ${p.visibility}${
        p.moderationState ? ` · ${p.moderationState}` : ""
      }`,
    listUnderReview: (p: { state: string }) =>
      `Diese Liste ist ${p.state} und kann in neuen Runden nicht verwendet werden. Bearbeiten stellt sie nicht automatisch wieder her; ein Moderator muss sie prüfen.`,
    needsReview: (p: { count: number }) => `Zu prüfen (${p.count})`,
    removePrompt: (p: { prompt: string }) => `${p.prompt} entfernen`,
    couldNotLoadYourPromptLists: "Deine Begriffslisten konnten nicht geladen werden.",
    couldNotOpenThatPromptList: "Diese Begriffsliste konnte nicht geöffnet werden.",
    addAtLeastOnePromptBefore: "Füge mindestens einen Begriff hinzu, bevor du speicherst.",
    couldNotSaveThisPromptList: "Diese Begriffsliste konnte nicht gespeichert werden.",
    couldNotDeleteThisPromptList: "Diese Begriffsliste konnte nicht gelöscht werden.",
    yourLibrary: "Deine Sammlung",
    reusablePromptLists: "Wiederverwendbare Begriffslisten",
    newList: "Neue Liste",
    createAccountSaveReviseSharePrompt: "Lege ein Konto an, um Begriffslisten zu speichern, zu überarbeiten und zu teilen. Schnelle Raumbegriffe bleiben lokal und flüchtig.",
    yourPromptLists: "Deine Begriffslisten",
    loading: "Wird geladen …",
    noSavedListsYet: "Noch keine gespeicherten Listen.",
    name: "Name",
    description: "Beschreibung",
    language: "Sprache",
    visibility: "Sichtbarkeit",
    private: "Privat",
    anyoneWithCode: "Jeder mit Code",
    shareCode: "Teilen-Code",
    couldNotCopyShareCode: "Der Teilen-Code konnte nicht kopiert werden.",
    copy: "Kopieren",
    addPrompts: "Begriffe hinzufügen",
    onePromptPerLineSeparateEntries: "Ein Begriff pro Zeile\noder Einträge mit Komma trennen",
    addList: "Zur Liste hinzufügen",
    noPromptsYetPasteSomeAbove: "Noch keine Begriffe. Füge oben welche ein, um loszulegen.",
    thisList: "In dieser Liste",
    searchPrompts: "Begriffe suchen",
    nothingMatchesThatSearch: "Nichts passt zu dieser Suche.",
    deleteList: "Liste löschen …",
  },

  notFoundPage: {
    nobodyDrewThisPage: "Diese Seite hat niemand gezeichnet",
    thatLinkDoesnTLeadAnywhere: "Dieser Link führt nirgendwohin auf Sketchy.",
    backLobby: "Zurück zur Lobby",
  },

  onlinePlayersPanel: {
    couldNotJoinThatGame: "Dieser Runde konnte nicht beigetreten werden.",
    whoOnline: "Wer online ist",
    nobodyElseHereRightNow: "Gerade ist sonst niemand hier.",
    friend: "Freund",
    join: "Beitreten",
  },

  pictureCropDialog: {
    fileNotAPicture: "Diese Datei konnte nicht als Bild gelesen werden.",
    couldNotSetThatPicturePlease: "Dieses Bild konnte nicht gesetzt werden. Bitte versuch es noch einmal.",
    frameYourPicture: "Bild ausrichten",
    dragMoveZoomGetCloserCircle: "Ziehen zum Verschieben, zoomen zum Heranholen. Der Kreis ist das, was alle sehen.",
    pictureFramedArrowKeysMovePlus: "Das ausgerichtete Bild. Pfeiltasten verschieben, Plus und Minus zoomen.",
    zoom: "Zoom",
    cancel: "Abbrechen",
  },

  playerList: {
    requestCouldNotBeSent: "Diese Anfrage konnte nicht gesendet werden.",
    nowFriends: (p: { name: string }) => `Du und ${p.name} seid jetzt Freunde.`,
    friendRequestSent: (p: { name: string }) => `Freundschaftsanfrage an ${p.name} gesendet.`,
    nothingToDoAbout: (p: { name: string }) => `Mit ${p.name} ist gerade nichts zu tun.`,
    rank: (p: { rank: number }) => `Platz ${p.rank}`,
    moderationFor: (p: { name: string }) => `Moderation für ${p.name}`,
    moderationActionsFor: (p: { name: string }) => `Moderationsaktionen für ${p.name}`,
    thatRequestCouldNotBeSent: "Diese Anfrage konnte nicht gesendet werden.",
    drawing: "Zeichnet",
    gotIt: "Erraten ·",
    afk: "AFK",
    you: "(du)",
    host: "Gastgeber",
    friend: "Freund",
    disconnected: "Getrennt",
    kick: "Rauswerfen",
    addFriend: "Freund hinzufügen",
    sendRequest: "Anfrage senden",
    report: "Melden",
    toAModerator: "An einen Moderator",
  },

  profilePage: {
    gamesPlayed: "Gespielte Runden",
    gamesWon: "Gewonnene Runden",
    winRate: "Siegquote",
    averageScore: "Durchschnittliche Punkte",
    turnsPlayed: "Gespielte Züge",
    promptsGuessed: "Erratene Begriffe",
    drawingsMade: "Gemachte Zeichnungen",
    reactionsReceived: "Erhaltene Reaktionen",
    totalScore: "Gesamtpunkte",
    noSuchProfile: "Es gibt keinen Spieler mit diesem Profil.",
    couldNotLoadProfile: "Dieses Profil konnte nicht geladen werden. Bitte versuch es noch einmal.",
    gameMeta: (p: { finishedAt: string; rounds: number; players: number }) =>
      `${p.finishedAt} · ${counted(p.rounds, { one: "Runde", other: "Runden" })} · ${counted(p.players, { one: "Spieler", other: "Spieler" })}`,
    seatScore: (p: { points: number }) => `${number(p.points)} Pkt.`,
    gameRules: (p: {
      scoringMode: string;
      scoringVersion: number;
      hintMode: string;
      seconds: number;
      promptSource: string;
    }) =>
      `Regeln: Wertung ${p.scoringMode}${
        p.scoringVersion > 0 ? ` v${p.scoringVersion}` : " (alte Version unbekannt)"
      } · Hinweise ${p.hintMode} · ${p.seconds} Sekunden · Begriffe ${p.promptSource}`,
    reportPlayer: (p: { name: string }) => `${p.name} melden`,
    privateRoom: "privater Raum",
    thisGameDidNotFinishSo: "Diese Runde ist nicht zu Ende gegangen, das hier ist also der Punktestand\n              beim Abbruch und keine Endplatzierung.",
    loadingTurns: "Züge werden geladen …",
    turnByTurn: "Zug für Zug",
    round: "Runde",
    prompt: "Begriff",
    drawnBy: "Gezeichnet von",
    time: "Zeit",
    drawing: "Zeichnet",
    reactions: "Reaktionen",
    guesserOutcomes: "Ergebnisse der Ratenden",
    view: "Ansehen",
    couldNotLoadMoreGames: "Weitere Runden konnten nicht geladen werden.",
    loading: "Wird geladen …",
    friend: "Freund.",
    claimYourAccount: "Sichere dir dein Konto",
    yourGamesAreAlreadyBeingRecorded: "Deine Runden werden bereits unter diesem Anzeigenamen aufgezeichnet.\n                Lege ein Konto an, um sie zu behalten und den Namen auf jedem Gerät zu nutzen.",
    createAccount: "Konto anlegen",
    statistics: "Statistik",
    gameHistory: "Rundenverlauf",
    includeGamesThatFellApart: "Auch abgebrochene Runden zeigen",
  },

  promptContentReportDialog: {
    reportList: (p: { name: string }) => `${p.name} melden`,
    couldNotSendReport: "Der Bericht konnte nicht gesendet werden.",
    reportsAreReviewedAfterSubmissionList: "Meldungen werden nach dem Absenden geprüft. Die Liste bleibt verfügbar, sofern ein Moderator sie nicht ausblendet.",
    content: "Inhalt",
    entireList: "Ganze Liste",
    reason: "Grund",
    whatShouldModeratorKnow: "Was sollte der Moderator wissen?",
    cancel: "Abbrechen",
  },

  promptDisplay: {
    couldNotDoAction: (p: { action: string }) => `Konnte nicht ${p.action}.`,
    nextHintCost: (p: { cost: number }) => `Nächster Hinweis: ${p.cost}`,
    hintSpendTotal: (p: { spent: number }) => `Gesamt: ${p.spent}`,
    buyLetter: (p: { letter: string; price: number }) =>
      `„${p.letter}“ für ${counted(p.price, { one: "Punkt", other: "Punkte" })} kaufen`,
    maskedPrompt: (p: { shape: string }) => `Verdeckter Begriff, ${p.shape} Buchstaben`,
    buyThisLetter: (p: { cost: number }) =>
      `Diesen Buchstaben für ${counted(p.cost, { one: "Punkt", other: "Punkte" })} kaufen`,
    letterCount: (p: { count: number }) =>
      counted(p.count, { one: "Buchstabe", other: "Buchstaben" }),
    yourTurn: "Du bist dran",
    pickSomethingDraw: "Wähle etwas zum Zeichnen",
    autoPicksWhenTimeRunsOut: "Wählt automatisch, wenn die Zeit abläuft.",
    hintSpendLimitReached: "Hinweis-Limit erreicht",
    deductedFromYourScoreIfYou: "Wird von deinen Punkten abgezogen, wenn du den Begriff errätst",
    buyLetterRevealsEveryMatch: "Buchstaben kaufen – zeigt jedes Vorkommen",
  },

  promptListPicker: {
    languageMismatch: (p: { listLanguage: string; roomLanguage: string }) =>
      `Diese Liste ist auf ${p.listLanguage}; dieser Raum ist auf ${p.roomLanguage}.`,
    choicesUnavailable: (p: { reason: string }) =>
      `Die Auswahl der Begriffslisten ist nicht verfügbar (${p.reason}). Deine bisherige Auswahl bleibt.`,
    noListsInLanguage: (p: { language: string }) =>
      `Noch keine Begriffslisten auf ${p.language} — dieser Raum nutzt seine eigenen Begriffe.`,
    howListPlays: (p: { name: string }) => `Wie sich Begriffe aus ${p.name} spielen`,
    reportList: (p: { name: string }) => `${p.name} melden`,
    failedLoadPromptLists: "Begriffslisten konnten nicht geladen werden",
    couldNotAddThatSharedList: "Diese geteilte Liste konnte nicht hinzugefügt werden.",
    loadingCuratedPromptLists: "Kuratierte Begriffslisten werden geladen …",
    promptLists: "Begriffslisten",
    addUnlistedListByCode: "Nicht gelistete Liste per Code hinzufügen",
  },

  promptStatsPage: {
    noSuchList: "Es gibt keine Begriffsliste mit diesem Namen.",
    couldNotLoadStats: "Diese Begriffsstatistik konnte nicht geladen werden. Bitte versuch es noch einmal.",
    showMore: (p: { count: number }) => `${p.count} weitere zeigen`,
    showingOf: (p: { shown: number; total: number }) => `${p.shown} von ${p.total} werden gezeigt`,
    couldNotLoadPromptListsPlease: "Die Begriffslisten konnten nicht geladen werden. Bitte versuch es noch einmal.",
    serverWide: "Serverweit",
    promptStats: "Begriffsstatistik",
    everyPromptListHowHasActually: "Jeder Begriff der Liste und wie er in abgeschlossenen Runden auf diesem\n          Server tatsächlich gelaufen ist.",
    promptList: "Begriffsliste",
    sort: "Sortierung",
    period: "Zeitraum",
    scoring: "Punkte",
    hints: "Hinweise",
    findPrompt: "Begriff finden",
    rollerCoaster: "Achterbahn",
    loading: "Wird geladen …",
    prompt: "Begriff",
    howGoes: "Wie es läuft",
    guessed: "Erraten",
    picked: "Gewählt",
    drawn: "Gezeichnet",
  },

  publicRoomCard: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "Runde", other: "Runden" }),
    promptLanguage: (p: { language: string }) => `Begriffssprache: ${p.language}`,
    seeWhoThisRoom: "Sehen, wer in diesem Raum ist",
    rounds: "Runden",
    drawingTime: "Zeichenzeit",
    full: "Voll",
    inProgress: "Läuft",
    looking: "Wird gesucht …",
    nobodySeatedYet: "Noch sitzt niemand.",
    host: "Gastgeber",
  },

  reactionRequests: {
    thatReactionCouldNotBeSent: "Diese Reaktion konnte nicht gesendet werden.",
  },

  recapDrawings: {
    thisDrawingCouldNotBeLoaded: "Diese Zeichnung konnte nicht geladen werden.",
  },

  reportAccountDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Ein Moderator sieht das. Mit ${p.name} passiert gerade nichts, und es wird nicht verraten, wer gemeldet hat.`,
    theirPicture: (p: { name: string }) => `Bild von ${p.name}`,
    thatReportCouldNotBeSent: "Diese Meldung konnte nicht gesendet werden. Bitte versuch es noch einmal.",
    whatWrongWith: "Was daran nicht stimmt",
    reportedTheirNameTheyHaveNo: "Wegen des Namens gemeldet. Es gibt kein Bild zu melden.",
    anythingElseOptional: "Sonst noch etwas (optional)",
    anythingModeratorShouldKnow: "Alles, was ein Moderator wissen sollte",
    sentWithWhatAboutAttached: "Gesendet, mit dem Gegenstand der Meldung im Anhang.",
    done: "Fertig",
  },

  reportedDrawing: {
    thisDrawingCouldNotBeDecoded: "Diese Zeichnung konnte nicht dekodiert werden.",
    drawingCouldNotBeLoaded: "Die Zeichnung konnte nicht geladen werden.",
  },

  reportLobbyLineDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Ein Moderator sieht diese Zeile. Mit ${p.name} passiert gerade nichts, und es wird nicht verraten, wer gemeldet hat.`,
    thatReportCouldNotBeSent: "Diese Meldung konnte nicht gesendet werden. Bitte versuch es noch einmal.",
    whatWrongWith: "Was daran nicht stimmt",
    anythingElseOptional: "Sonst noch etwas (optional)",
    anythingModeratorShouldKnow: "Alles, was ein Moderator wissen sollte",
    thisLineAttachedWithWhatLobby: "Diese Zeile ist angehängt, samt dem, was in der Lobby drumherum gesagt wurde.",
    sentWithLineWhatWasSaid: "Gesendet, mit der Zeile und dem Gesagten drumherum im Anhang.",
    done: "Fertig",
  },

  reportPlayerDialog: {
    reportCouldNotBeSent: "Diese Meldung konnte nicht gesendet werden.",
    recentMessages: (p: { count: number }) =>
      `${p.count} ihrer ${plural(p.count, { one: "letzten Nachricht", other: "letzten Nachrichten" })}`,
    nothingHappensYet: (p: { name: string }) =>
      `Ein Moderator sieht das. Mit ${p.name} passiert gerade nichts, und es wird nicht verraten, wer gemeldet hat.`,
    whatHappened: "Was passiert ist",
    anythingElseOptional: "Sonst noch etwas (optional)",
    whatTheySaidDrewWhen: "Was sie gesagt oder gezeichnet haben, und wann",
    theirRecentMessagesThisRoomAre: "Ihre letzten Nachrichten in diesem Raum werden automatisch angehängt,\n                samt dem Gesagten drumherum, das hier kann also leer bleiben.",
    includeTheirDrawing: "Ihre Zeichnung mitschicken",
    canvasAsRightNowSoModerator: "Die Leinwand, wie sie gerade ist, damit ein Moderator sieht, was\n                      du gesehen hast.",
    done: "Fertig",
  },

  reportsReviewedNotice: {
    reportsReviewed: (p: { count: number }) =>
      `${counted(p.count, { one: "von dir gesendete Meldung wurde", other: "von dir gesendete Meldungen wurden" })} geprüft. Danke.`,
  },

  restartVoteBanner: {
    voteTally: (p: { yes: number; no: number; pending: number }) =>
      `${p.yes} dafür, ${p.no} dagegen, ${p.pending} offen`,
    restartingIn: (p: { seconds: number }) =>
      `Neustart in ${counted(p.seconds, { one: "Sekunde", other: "Sekunden" })}`,
    restartApproved: "Neustart angenommen!",
    seconds: "Sekunden",
    voteRestartGame: "Über einen Neustart abstimmen",
    restart: "Neustart",
    keepPlaying: "Weiterspielen",
    onlyEligiblePlayersPresentWhenVote: "Nur berechtigte Spieler, die beim Start der Abstimmung da waren, können abstimmen.",
  },

  roleChangeNotice: {
    youHaveBeenSignedOutEvery: "Du wurdest auf allen Geräten abgemeldet, damit die Änderung greift.\n            Melde dich wieder an, um weiterzumachen.",
    setUpNow: "Jetzt einrichten",
    later: "Später",
  },

  roomChatPanel: {
    unreadMessages: (p: { count: number }) =>
      `${counted(p.count, { one: "neue Nachricht", other: "neue Nachrichten" })}`,
    correctWithPlace: (p: { place: string | null }) =>
      p.place ? `Richtig · ${p.place}` : "Richtig",
    couldNotSendMessage: "Nachricht konnte nicht gesendet werden",
    sent: "Gesendet:",
    send: "Senden",
    youReDrawingWatchGuessesCome: "Du zeichnest – sieh zu, wie die Vermutungen eintreffen.",
  },

  roomEntryState: {
    thisRoomNoLongerAvailable: "Dieser Raum ist nicht mehr verfügbar",
    couldNotJoinThisRoom: "Diesem Raum konnte nicht beigetreten werden",
  },

  roomMenuSheet: {
    startTheGameOver: "Das Spiel neu starten",
    startOverCooldown: (p: { seconds: number }) => ` · in ${p.seconds}s`,
    room: "Raum",
    playersScores: "Spieler und Punkte",
    copyInviteLink: "Einladungslink kopieren",
    saveThisDrawing: "Diese Zeichnung speichern",
    settings: "Einstellungen",
    leaveRoom: "Den Raum verlassen",
  },

  roomPlayersPanel: {
    spectatorCount: (p: { count: number }) =>
      counted(p.count, { one: "Zuschauer", other: "Zuschauer" }),
    spectatorsHeading: (p: { count: number }) => `Zuschauer (${p.count})`,
    playersOfCapacity: (p: { here: number; capacity: number }) =>
      `${p.here} von ${p.capacity} Spielern`,
    readyCount: (p: { count: number }) => `${p.count} bereit`,
    couldNotJoinAsPlayer: "Beitritt als Spieler nicht möglich",
    finalStandings: "Endstand",
    players: "Spieler",
  },

  roomSettingsEditor: {
    couldNotLoadRoomRules: "Raumregeln konnten nicht geladen werden",
    roomRefusedThoseSettings: "Der Raum hat diese Einstellungen abgelehnt.",
    hostSettings: "Gastgeber-Einstellungen",
    editRoomRules: "Raumregeln bearbeiten",
    loadingSettings: "Einstellungen werden geladen …",
    cancel: "Abbrechen",
  },

  roomSetupForm: {
    language: "Sprache",
    visibility: "Sichtbarkeit",
    maxPlayers: "Maximale Spielerzahl",
    rounds: "Runden",
    drawingTime: "Zeichenzeit",
    onlyUseCustomPrompts: "Nur eigene Begriffe verwenden",
    addUsableCustomPromptEnableThis: "Füge einen verwendbaren eigenen Begriff hinzu, um diese Option zu aktivieren.",
    allowedTools: "Erlaubte Werkzeuge",
    colors: "Farben",
    scoring: "Punkte",
    hints: "Hinweise",
    spectatorsCanSeePrompt: "Zuschauer sehen den Begriff",
    hideBlanks: "Lücken verbergen",
    alsoTurnsHintsOffWithNo: "Schaltet auch Hinweise ab: ohne Lücken gibt es nichts aufzudecken.",
    promptTotal: (p: { count: number }) =>
      counted(p.count, { one: "Begriff", other: "Begriffe" }),
    basics: "Grundlagen",
    roomName: "Raumname",
    public: "Öffentlich",
    private: "Privat",
    prompts: "Begriffe",
    drawing: "Zeichnet",
    scoringHints: "Punkte und Hinweise",
    hintsAreOffBecauseBlanksAre: "Hinweise sind aus, weil die Lücken verborgen sind.",
    pointPurchaseHintModesRequireScoring: "Hinweismodi mit Punktekauf brauchen eine Punktewertung.",
  },

  rulesPage: {
    sketchy: "Sketchy",
    theRules: "Die Regeln",
    thisPage: "Auf dieser Seite",
    forExample: "Zum Beispiel",
  },

  sessionManagerDialog: {
    lastUsed: (p: { when: string }) => `Zuletzt genutzt ${p.when}`,
    signsOutOn: (p: { when: string }) => `Meldet sich von selbst ab ${p.when}`,
    usedElsewhere: (p: { when: string }) =>
      `Am ${p.when} aus einem anderen Browser genutzt. Melde dieses Gerät ab, wenn du das nicht warst.`,
    couldNotLoadSignedDevices: "Angemeldete Geräte konnten nicht geladen werden.",
    couldNotRevokeDevice: "Das Gerät konnte nicht abgemeldet werden.",
    couldNotLogOutEverywhere: "Abmelden auf allen Geräten nicht möglich.",
    signedDevices: "Angemeldete Geräte",
    revokeAnyDeviceYouNoLonger: "Melde jedes Gerät ab, das du nicht mehr kennst. Gerätenamen sind grob und speichern keine Browserversionen.\n          Ein Gerät, das du nicht mehr nutzt, meldet sich nach neunzig Tagen selbst ab.",
    loadingDevices: "Geräte werden geladen …",
    currentDevice: "Aktuelles Gerät",
    close: "Schließen",
  },

  settingsOverlay: {
    email: "E-Mail",
    password: "Passwort",
    twoFactorAuthentication: "Zwei-Faktor-Authentifizierung",
    signedDevices: "Angemeldete Geräte",
    downloadEverything: "Alles herunterladen",
    colorScheme: "Farbschema",
    appliesMomentYouPick: "Gilt sofort ab der Auswahl.",
    languageYouPlay: "Sprache, in der du spielst",
    roomsThisLanguageComeFirstLobby: "Räume in dieser Sprache stehen in der Lobby vorn, und ein Raum, den du erstellst, startet in ihr. Sie ist getrennt von der Sprache, in der du Sketchy liest.",
    interfaceLanguage: "Sprache, in der du liest",
    interfaceLanguageHint: "Jedes Wort von Sketchy selbst. Getrennt von der Sprache, in der du spielst: in der einen lesen und in der anderen spielen ist völlig normal.",
    timeFormat: "Zeitformat",
    howEveryClockReadsChatTimestamps: "Wie jede Uhr gelesen wird: Chat-Zeitstempel, Anmeldedaten, Hinweise. „System“ folgt deinem Gerät.",
    iHaveTroubleTellingColorsApart: "Ich kann Farben schwer auseinanderhalten",
    nudgesHostsTowardRoomColorsThat: "Legt Gastgebern Raumfarben nahe, die bei Deuteranopie und Protanopie unterscheidbar bleiben, ohne zu verraten, wer gefragt hat. Von allein ändert sich nichts.",
    brushCursor: "Pinselzeiger",
    crosshairPreciseAtPointOutlineShows: "Ein Fadenkreuz ist punktgenau; ein Umriss zeigt, wie breit der Strich wird.",
    brushCursorStyle: "Art des Pinselzeigers",
    soundEffects: "Soundeffekte",
    chimesCorrectGuessStartRoundLast: "Töne für eine richtige Antwort, den Rundenbeginn, die letzten zehn Sekunden und für kommende und gehende Spieler.",
    volume2: "Lautstärke",
    confetti: "Konfetti",
    burstWhenYouGuessRightAgain: "Ein Schwall, wenn du richtig rätst, und noch einmal für die Gewinnerin oder den Gewinner am Ende.",
    clickKeyRebindEachActionCan: "Klicke auf eine Taste, um sie neu zu belegen. Jede Aktion kann zwei halten. Esc bricht ab.",
    theseAreTheirSettings: (p: { name: string }) => `Das sind jetzt die Einstellungen von ${p.name}.`,
    guestLivesInThisBrowser: (p: { name: string }) =>
      `${p.name} lebt nur in diesem Browser. Ein Konto behält den Namen, deine Punkte und deinen Verlauf auf jedem Gerät und lässt dich eine Farbe wählen.`,
    systemThemeNow: (p: { theme: "dark" | "light" }) => `Jetzt: ${p.theme}`,
    needsAccount: "Braucht ein Konto",
    choosePicture: "Bild wählen",
    editPicture: "Bild bearbeiten",
    picture: "Bild",
    changePicture: "Bild ändern",
    removePicture: "Bild entfernen",
    couldNotRemovePicture: "Das Bild konnte nicht entfernt werden.",
    couldNotChangeYourDisplayName: "Dein Anzeigename konnte nicht geändert werden.",
    couldNotChangeYourDisplayName2: "Dein Anzeigename konnte nicht geändert werden. Bitte versuch es noch einmal.",
    themeSoundShortcutsCameFromAccount: "Design, Ton und Kürzel kamen aus dem Konto. Was dieser Browser hatte,\n            bleibt unberührt und kommt zurück, wenn du dich abmeldest.",
    dismiss: "Ausblenden",
    playingAsGuest: "Du spielst als Gast",
    createAccount: "Konto anlegen",
    logIn: "Anmelden",
    you: "Du",
    displayName: "Anzeigename",
    cancel: "Abbrechen",
    change: "Ändern",
    nameColor: "Namensfarbe",
    signingIn: "Anmeldung",
    changePassword: "Passwort ändern",
    manage: "Verwalten",
    yourData: "Deine Daten",
    requestExport: "Export anfordern",
    delete: "Löschen …",
    display: "Darstellung",
    theme: "Design",
    accessibility: "Barrierefreiheit",
    theCanvas: "Die Leinwand",
    sound: "Ton",
    volume: "Lautstärke",
    effects: "Effekte",
    noKeyboardThisDevice: "Keine Tastatur auf diesem Gerät",
    yourBindingsAreStillSavedStill: "Deine Kürzel sind weiterhin gespeichert und funktionieren. Öffne Sketchy mit\n            angeschlossener Tastatur, um sie zu ändern.",
    drawingTools: "Zeichenwerkzeuge",
    resetDefaults: "Auf Standard zurücksetzen",
    settings: "Einstellungen",
    close: "Schließen",
    closeSettings: "Einstellungen schließen",
    settingsSections: "Bereiche der Einstellungen",
  },

  stepUpDialog: {
    codeFromYourAuthenticatorApp2: "Code aus deiner Authenticator-App",
    passkeyNotUsed: "Dieser Passkey wurde nicht verwendet. Du kannst es noch einmal versuchen.",
    thatCodeWasNotAccepted: "Dieser Code wurde nicht akzeptiert.",
    thatPasskeyWasNotAccepted: "Dieser Passkey wurde nicht akzeptiert.",
    confirmYou: "Bestätige, dass du es bist",
    recoveryCode: "Wiederherstellungscode",
    codeFromYourAuthenticatorApp: "Code aus deiner Authenticator-App",
    cancel: "Abbrechen",
  },

  suspensionNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Deine Zeichnung von ${p.prompt}, so wie sie gemeldet wurde`,
    recordedAs: "Erfasst als {category}",
    yourAccountSuspended: "Dein Konto ist gesperrt",
    youWereAskedDraw: "Du solltest zeichnen",
  },

  toastProvider: {
    notifications: "Benachrichtigungen",
    dismissNotification: "Benachrichtigung ausblenden",
  },

  toolbar: {
    colorOption: (p: { color: string }) => `Farbe ${p.color}`,
    adjustSize: (p: { tool: string }) => `Größe von ${p.tool} anpassen`,
    sizeSnappingSlider: (p: { tool: string }) => `Größenregler mit Rasterung für ${p.tool}`,
    chooseToolCurrent: (p: { tool: string }) => `Werkzeug wählen, aktuell: ${p.tool}`,
    chooseColorCurrent: (p: { color: string }) => `Farbe wählen, aktuell ${p.color}`,
    sizeWithWidth: (p: { tool: string; width: number }) => `${p.tool}, Größe ${p.width}px`,
    sizeShortcutHint: (p: { tool: string; width: number }) =>
      `${p.tool}, Größe: ${p.width}px ([ / ])`,
    widthReadout: (p: { width: number }) => `${p.width}px`,
    colorSwatch: (p: { color: string }) => `Farbe ${p.color}`,
    drawingTools: "Zeichenwerkzeuge",
    chooseTool: "Werkzeug wählen",
    chooseColor: "Farbe wählen",
    undoLastStroke: "Letzten Strich rückgängig machen",
    undo: "Rückgängig",
    clearCanvas: "Leinwand leeren",
    chooseCustomColor: "Eigene Farbe wählen",
    colorPalette: "Farbpalette",
    canvasActions: "Aktionen für die Leinwand",
    undoLastStrokeCtrlZ: "Letzten Strich rückgängig machen (Strg+Z)",
    clear: "Leeren",
  },

  turnResultsOverlay: {
    yourTurnWithHints: (p: { base: number; hintSpend: number; points: number; rank: number }) =>
      `Dein Zug: +${p.base} -${p.hintSpend} Hinweise = ${counted(p.points, { one: "Punkt", other: "Punkte" })} · jetzt #${p.rank}`,
    yourTurn: (p: { delta: number; rank: number }) =>
      `Dein Zug: ${p.delta >= 0 ? "+" : ""}${p.delta} ${
        Math.abs(p.delta) === 1 ? "Punkt" : "Punkte"
      } · jetzt #${p.rank}`,
    promptWas: "Der Begriff war",
    noOneGuessedCorrectly: "Niemand hat richtig geraten.",
    you: "(du)",
    drewThisTurn: "Hat diesen Zug gezeichnet",
    nextTurn: "Nächster Zug",
  },

  twoFactorDialog: {
    scanThisWithYourAuthenticatorApp: "Scanne das mit deiner Authenticator-App, um dieses Konto hinzuzufügen",
    codeFromYourAuthenticatorApp: "Code aus deiner Authenticator-App",
    secondFactorState: (p: {
      recoveryCodesRemaining: number | null;
      confirmAuthenticator: boolean;
    }) =>
      [
        "Die Zwei-Faktor-Authentifizierung ist aktiv.",
        p.recoveryCodesRemaining === null
          ? null
          : `Du hast noch ${counted(p.recoveryCodesRemaining, {
              one: "Wiederherstellungscode",
              other: "Wiederherstellungscodes",
            })}.`,
        p.confirmAuthenticator
          ? "Bevor dieses Konto eine Moderatoren- oder Administratorenrolle bekommen kann, bestätige mit deinem Passwort und einem Code, dass der Authenticator dir gehört."
          : null,
        "Jede der Änderungen unten tauscht einen Zugangsnachweis aus, deshalb fragt jede nach deinem Passwort.",
      ]
        .filter(Boolean)
        .join(" "),
    confirmAuthenticatorFirst:
      "Bevor dieses Konto eine Moderatoren- oder Administratorenrolle bekommen kann, bestätige mit deinem Passwort und einem Code, dass der Authenticator dir gehört.",
    copied: (p: { what: string }) => `${p.what} kopiert.`,
    couldNotCopy: (p: { what: string }) =>
      `Konnte ${p.what} nicht kopieren. Markiere es und kopiere von Hand.`,
    roleTaken: (p: { role: "admin" | "moderator" }) =>
      `Du bist jetzt ${p.role === "admin" ? "Administrator" : "Moderator"}. Die Zwei-Faktor-Authentifizierung ist aktiv, und die wartende Rolle gilt ab sofort. Deine anderen Geräte wurden abgemeldet; dieses macht weiter, und jede Anmeldung von hier fragt nach einem Code.`,
    recoveryCodesLeft: (p: { count: number }) =>
      `Du hast noch ${counted(p.count, { one: "Wiederherstellungscode", other: "Wiederherstellungscodes" })}.`,
    couldNotReadYourSecuritySettings: "Deine Sicherheitseinstellungen konnten nicht gelesen werden.",
    yourPasswordConfirmsAuthenticatorYours: "Dein Passwort bestätigt, dass der Authenticator dir gehört.",
    yourPasswordConfirmsThisPasskeyYours: "Dein Passwort bestätigt, dass dieser Passkey dir gehört.",
    passkeyAdded: "Passkey hinzugefügt.",
    thatPasskeyWasNotCreatedYou: "Dieser Passkey wurde nicht erstellt. Du kannst es noch einmal versuchen.",
    yourPasswordNeededRemovePasskey: "Zum Entfernen eines Passkeys wird dein Passwort gebraucht.",
    confirmedThisAccountCanNowBe: "Bestätigt. Dieses Konto kann jetzt eine Team-Rolle bekommen.",
    twoFactorAuthentication: "Zwei-Faktor-Authentifizierung",
    saveTheseRecoveryCodesNow: "Speichere diese Wiederherstellungscodes jetzt.",
    eachOneSignsYouOnceIf: "Jeder meldet dich einmal an, falls du deine Authenticator-App verlierst.\n              Sie werden nicht noch einmal gezeigt — gespeichert werden nur\n              ihre Hashes.",
    recoveryCodes: "Wiederherstellungscodes",
    downloadAsFile: "Als Datei herunterladen",
    copyAll: "Alle kopieren",
    iHaveSavedTheseSomewhereSafe: "Ich habe sie sicher gespeichert",
    done: "Fertig",
    moderatorsAdministratorsSignWithPasskeyYour: "Moderatoren und Administratoren melden sich mit einem Passkey an: dein\n              Gerät bestätigt, dass du es bist — per Fingerabdruck, Gesicht oder\n              PIN — und es wird nichts getippt, das weitergegeben werden könnte.",
    yourPassword: "Dein Passwort",
    confirmsPasskeyBeingAddedByYou: "Bestätigt, dass du den Passkey hinzufügst.",
    useAuthenticatorAppInstead: "Stattdessen eine Authenticator-App nutzen",
    scanCodeWithAuthenticatorAppThen: "Scanne den Code mit einer Authenticator-App und tippe dann die sechs\n              Ziffern ein, die sie anzeigt.",
    drawingCode: "Code wird gezeichnet …",
    pointYourAppAtThis: "Richte deine App darauf.",
    setupKey: "Einrichtungsschlüssel",
    copySetupKey: "Einrichtungsschlüssel kopieren",
    useThisIfYouCanT: "Nimm das, wenn du nicht scannen kannst.",
    confirmsAuthenticatorYours: "Bestätigt, dass der Authenticator dir gehört.",
    codeFromYourApp: "Code aus deiner App",
    cancel: "Abbrechen",
    passkeys: "Passkeys",
    thisDeviceOnly: "· nur auf diesem Gerät",
    remove: "Entfernen",
    confirmSYours: "Bestätigen, dass er dir gehört",
    addPasskey: "Passkey hinzufügen",
    newRecoveryCodes: "Neue Wiederherstellungscodes",
    turnOff: "Ausschalten",
    addAuthenticatorApp: "Authenticator-App hinzufügen",
    close: "Schließen",
  },

  useFriendArrivalNotices: {
    wantsToBeFriends: (p: { name: string }) => `${p.name} möchte mit dir befreundet sein.`,
    acceptedYourRequest: (p: { name: string }) => `${p.name} hat deine Freundschaftsanfrage angenommen.`,
    severalAccepted: (p: { count: number }) =>
      `${counted(p.count, { one: "Person hat", other: "Personen haben" })} deine Freundschaftsanfragen angenommen.`,
  },

  useRoomSessionReconnect: {
    joinRoomFailed: "join_room failed",
  },

  waitingRoomPanel: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "Runde", other: "Runden" }),
    needMorePlayers: (p: { count: number }) =>
      `Es fehlen noch ${counted(p.count, { one: "Spieler", other: "Spieler" })}`,
    hostWillStart: (p: { rematch: boolean }): string =>
      p.rematch ? "{host} startet die Revanche" : "{host} startet das Spiel",
    copied: (p: { what: string }) => `${p.what} kopiert.`,
    couldNotCopy: (p: { what: string }) =>
      `Konnte ${p.what} nicht kopieren. Kopiere es aus der Adresszeile.`,
    roomCodeLabel: (p: { code: string }) => `Raumcode ${p.code}`,
    rosterCount: (p: { here: number; capacity: number }) => `${p.here} von ${p.capacity}`,
    inviteYourFriends: "Lade deine Freunde ein",
    shareLink: "Link teilen",
    copyCode: "Code kopieren",
    inTheRoom: "Im Raum",
    you: "(du)",
    host: "Gastgeber",
    friend: "Freund",
    invite: "Einladen",
    edit: "Bearbeiten",
    viewHighlights: "Höhepunkte ansehen",
    viewDrawings: "Zeichnungen ansehen",
  },

  warningNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Deine Zeichnung von ${p.prompt}, so wie sie gemeldet wurde`,
    recordedAs: "Erfasst als {category}",
    whatAWarningMeans:
      "Eine Meldung über dein Verhalten wurde geprüft, und das ist das Ergebnis. Nichts ist eingeschränkt, aber eine weitere Meldung kann zur Sperrung deines Kontos führen.",
    youWereAskedDraw: "Du solltest zeichnen",
  },
};
