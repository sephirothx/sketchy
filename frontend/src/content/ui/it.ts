/** Every word the interface says, in Italian.

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

const { counted, number, ordinal, plural } = formattersFor("it", {"other":"º"});


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
      return `La password deve avere almeno ${count(detail, 12)} caratteri.`;
    case "too_long":
      return `La password deve avere al massimo ${count(detail, 128)} caratteri.`;
    case "common":
      return "Questa password è fra le più usate in assoluto. Scegline un’altra.";
    case "common_repeated":
      return "È una password comune, solo ripetuta. Scegline un’altra.";
    case "short_repeated":
      return "Questa password è una password corta ripetuta. Scegline un’altra.";
    case "too_few_characters":
      return `Questa password usa solo ${count(detail, 4)} caratteri diversi. Scegline un’altra.`;
    case "keyboard_walk":
      return "Questa password è quasi solo una fila di tasti in ordine. Scegline un’altra.";
    case "contains_identity":
      return "Una password non può contenere il tuo nome, la tua email o il nome di questo sito.";
    case "common_with_digits":
      return "È una password comune con delle cifre aggiunte. Scegline un’altra.";
    default:
      return "Scegli una password diversa.";
  }
}

/** *Create an account to …* - one refusal, said about the thing it refused. */
function accountRequired(params: MessageParams): string {
  switch (params.action) {
    case "avatar":
      return "Crea un account per scegliere un’immagine.";
    case "prompt_lists":
      return "Crea un account per salvare liste di parole riutilizzabili.";
    case "name_color":
      return "Crea un account per scegliere un colore del nome.";
    case "password":
      return "Crea un account per impostare una password.";
    case "second_factor":
      return "Crea un account prima di attivare l’autenticazione a due fattori.";
    case "friends":
      return "Crea un account per aggiungere amici.";
    default:
      return "Crea un account per farlo.";
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
      return "è in corso un aggiornamento del server";
    case "too_few_players":
      return "restano meno di due giocatori attivi";
    case "prompt_lists_unavailable":
      return "non è stato possibile caricare le liste di parole";
    case "everybody_left":
      return "se ne sono andati tutti prima di cominciare";
    default:
      return "non poteva più andare avanti";
  }
}

type Sentence = string | ((params: MessageParams) => string);

/** Why the server refused, said to the player.

One entry per `ErrorCode`; `Record` makes it exhaustive, so a code the server
adds without a sentence here fails the build rather than the player
(R-I18N-04). */
const REFUSALS: Record<ErrorCode, Sentence> = {
  // Payloads and arguments
  invalid_payload: "Sketchy non è riuscito a leggere questa richiesta.",
  invalid_nickname: "Questo nome non si può usare qui.",
  invalid_name_color: "Scegli un colore leggibile sia nella lista chiara sia in quella scura.",
  invalid_hint: "Questo indizio non è valido.",
  invalid_letter: "Questa lettera non è valida.",
  invalid_prompt_lists: "Queste liste di parole non si possono usare insieme.",
  invalid_custom_prompts: "Non è stato possibile leggere queste parole personalizzate.",
  max_players_below_seated: (params) =>
  `Il massimo di giocatori non può essere inferiore ai ${count(params.seated, 2)} già presenti nella stanza.`,
  empty_message: "Scrivi prima qualcosa.",

  // Rate and capacity
  too_fast: "Stai andando troppo veloce. Rallenta un attimo.",
  seat_changing_too_fast: "Questo posto cambia mano troppo in fretta. Riprova tra un minuto.",
  joining_too_fast: "Entri nelle stanze troppo in fretta. Riprova tra un minuto.",
  room_quota: "Hai già tutte le stanze aperte che puoi avere insieme.",
  room_full: "Questa stanza è piena.",
  spectators_full: "Questa stanza non accetta altri spettatori.",
  player_slots_full: "Tutti i posti da giocatore sono occupati.",

  // Server and account state
  server_draining: "Sketchy si sta riavviando. Riprova tra un attimo.",
  server_paused: "Sketchy non accetta nuove stanze in questo momento.",
  database_busy: "Sketchy fatica a raggiungere il suo database. Riprova.",
  account_ended: "Questo account non è più attivo.",
  account_required: accountRequired,
  identity_unavailable: "Sketchy non è riuscito a confermare chi sei. Ricarica e riprova.",

  // Rooms
  not_in_room: "Non sei in questa stanza.",
  room_not_found: "Stanza non trovata.",
  room_ended: "Questa stanza è finita.",
  could_not_create_room: "Non è stato possibile creare la stanza.",
  no_session_to_resume: "Non c’è nessuna tua sessione da riprendere in questa stanza.",
  host_only: "Può farlo solo l’host.",
  players_only: "Possono farlo solo i giocatori.",
  waiting_room_only: "È disponibile solo nella sala d’attesa.",
  already_a_player: "Sei già un giocatore.",
  registered_name_fixed: "I giocatori registrati giocano con il loro nome utente.",
  name_taken_by_account: "Questo nome appartiene a un giocatore registrato.",
  guests_cannot_choose_color: "Crea un account per scegliere un colore del nome.",
  suggestion_inactive: "Questo suggerimento non è più attivo.",
  drawing_not_found: "Disegno non trovato.",
  drawing_not_kept: "Questo disegno non è stato conservato.",

  // Games and turns
  not_in_game: "Non sei in una partita attiva.",
  game_in_progress: "La partita è già in corso.",
  game_starting: "La partita sta ancora iniziando.",
  need_two_players: "Servono due giocatori attivi per cominciare.",
  room_not_startable: "Questa stanza non può iniziare una partita adesso.",
  prompt_not_ready: "La partita non è ancora pronta per una parola.",
  prompt_unavailable: "Questa parola non è più disponibile.",
  hints_disabled: "Gli indizi sono disattivati in questa stanza.",
  hint_spend_limit: "Hai raggiunto il limite di spesa in indizi di questo turno.",
  hint_unavailable: "Questo indizio non è disponibile.",

  // Canvas
  drawer_only: "Può farlo solo chi disegna.",
  canvas_stale_generation: "La tela è andata avanti. Recupero in corso.",
  canvas_sequence_committed: "È già stato disegnato.",
  canvas_out_of_sequence: "Le azioni di disegno sono arrivate fuori ordine. Recupero in corso.",
  canvas_out_of_sync: "La tela non è sincronizzata. Recupero in corso.",
  nothing_to_undo: "Non c’è niente da annullare.",

  // Votes and restarts
  spectators_cannot_vote: "Gli spettatori non possono votare.",
  spectators_cannot_be_targets: "Uno spettatore non può essere oggetto di un voto.",
  invalid_vote_target: "Non puoi votare su questo giocatore.",
  not_eligible: "Solo i giocatori attivi possono proporre un riavvio.",
  restart_vote_active: "C’è già una votazione di riavvio in corso.",
  restart_vote_cooldown: "Si è appena votato un riavvio. Aspetta un attimo prima di proporne un altro.",
  no_restart_vote: "Non c’è nessuna votazione di riavvio a cui rispondere.",
  restart_vote_closed: "Questa votazione di riavvio è già chiusa.",

  // Reactions
  spectators_cannot_react: "Gli spettatori non possono reagire a un disegno.",
  guests_cannot_react: "Crea un account per reagire a un disegno.",
  reaction_not_visible: "Non puoi reagire a un disegno che non vedi.",
  own_drawing: "Non puoi reagire al tuo disegno.",
  game_still_saving: "Questa partita si sta ancora salvando. Riprova tra un attimo.",
  game_not_recorded: "Questa partita non è stata registrata.",
  reaction_not_accepted: "Non è stato possibile inviare questa reazione.",

  // Friends
  friends_unavailable: "Gli amici non sono disponibili in questo momento.",
  friend_refused: "Non è stato possibile completare questa richiesta di amicizia.",
  friend_not_in_game: "Il tuo amico non è in una partita in questo momento.",
  friend_in_several_games: "Questo amico è in più partite. Chiedigli un invito.",
  not_friends: "Puoi entrare solo nella partita di un amico.",
  friends_only_uninvited: "Solo gli amici dell’host possono entrare senza invito. Chiediglielo.",
  invite_expired: "Questo invito è scaduto.",

  // Moderation, from the reporter's side
  reporting_unavailable: "Le segnalazioni non sono disponibili su questo server.",
  no_such_player: "Questo giocatore non esiste.",
  cannot_report: "Questo giocatore non può essere segnalato.",
  already_reported: "L’hai già segnalato, e un moderatore non l’ha ancora esaminato.",

  // Lobby chat
  name_required: "Scegli un nome prima di dire qualcosa nella lobby.",
  not_watching_lobby: "Non stai più guardando la lobby.",

  // Versioning
  protocol_mismatch: "Questa scheda usa una versione vecchia di Sketchy. Ricarica la pagina per continuare.",

  // Sessions and accounts
  sign_in_required: "Accedi prima.",
  credentials_incorrect: "Nome utente o password errati.",
  password_incorrect: "La password è errata.",
  account_suspended: "Questo account è sospeso.",
  already_signed_in: "Hai già effettuato l’accesso a un account.",
  username_taken: "Questo nome utente è già preso.",
  invalid_username: "Questo nome utente non si può usare.",
  weak_password: weakPassword,
  password_change_failed: "Non è stato possibile cambiare la password.",
  session_not_found: "Questo dispositivo non è più connesso.",
  session_replaced: "Questa sessione è stata sostituita. Ricarica e riprova.",
  guest_progress_unlinked: "Non è stato possibile collegare i progressi da ospite a questo account.",
  not_taking_visitors: "Sketchy non accetta nuovi visitatori in questo momento. Riprova più tardi.",
  account_delete_refused: "Non è stato possibile eliminare l’account adesso. Riprova.",
  password_required_to_delete: "Inserisci la password per eliminare l’account.",

  // Second factor and passkeys
  second_factor_required: "Inserisci il codice della tua app di autenticazione.",
  second_factor_passkey_only: "Accedi con la tua passkey.",
  second_factor_not_enrolled:
  "Questo account ha bisogno dell’autenticazione a due fattori prima di poter accedere. Chiedi aiuto a un amministratore per attivarla.",
  second_factor_not_set_up: "L’autenticazione a due fattori non è attiva.",
  second_factor_code_wrong: "Questo codice non è corretto.",
  second_factor_throttled: "Troppi codici sbagliati. Aspetta un attimo e riprova.",
  step_up_required: "Conferma che sei tu prima di farlo.",
  passkey_sign_in_required: "Accedi con la tua passkey.",
  passkey_not_registered: "Questa passkey non è registrata qui.",
  passkey_not_found: "Questa passkey non esiste.",
  passkey_refused:
  "Le passkey sono per account di moderatore e amministratore. Ti verrà chiesto di crearne una se un giorno ti verrà offerto un ruolo.",
  last_factor: "È l’unico modo che hai per dimostrare che sei tu. Aggiungine un altro prima di rimuovere questo.",
  second_factor_required_for_role: "Il ruolo di questo account richiede l’autenticazione a due fattori.",
  second_factor_not_proved:
  "Questo autenticatore non è ancora stato confermato come tuo. Usa una passkey, oppure confermalo con la password nelle impostazioni.",

  // Email, verification and recovery
  invalid_email: "Non sembra un indirizzo email.",
  email_in_use: "Questo indirizzo è già in uso.",
  email_change_refused: "Questo indirizzo non può essere aggiunto a questo account.",
  verification_link_invalid: "Questo link di conferma è scaduto o è già stato usato.",
  reset_link_invalid: "Questo link di reimpostazione è scaduto o è già stato usato.",

  // Account data export
  export_not_found: "Esportazione non trovata.",
  export_expired: "L’esportazione è scaduta.",
  export_not_ready: "L’esportazione non è pronta.",
  export_unreadable: "Non è stato possibile leggere il documento dell’esportazione. Chiedine una nuova.",
  export_not_yet_allowed: "Hai chiesto un’esportazione di recente. Riprova più tardi.",
  export_refused: "Non è stato possibile avviare questa esportazione. Riprova.",

  // Rate limits reached over HTTP
  too_many_attempts: "Troppi tentativi. Aspetta un attimo e riprova.",
  too_many_requests: "Troppe richieste. Aspetta un attimo e riprova.",
  too_many_reports: "Troppe segnalazioni. Aspetta prima di inviarne un’altra.",
  too_many_bug_reports: "Troppe segnalazioni di bug. Aspetta prima di inviarne un’altra.",
  too_many_pictures: "Troppe immagini. Aspetta un attimo e riprova.",

  // Pictures
  unsupported_picture_type: "Non è un’immagine WebP o PNG.",
  picture_not_found: "Questa immagine non esiste.",
  picture_refused: "Questa immagine non si può usare qui.",

  // Bug reports
  screenshot_unreadable: "Non è stato possibile leggere lo screenshot.",
  screenshot_too_large: (params) =>
  `Questo screenshot è troppo grande. Il limite è ${megabytes(params.limitBytes, "2 MB")}.`,
  screenshot_unsupported_type: "Uno screenshot deve essere un’immagine PNG o WebP.",
  bug_report_context_too_large: "Questa segnalazione porta con sé troppo contesto.",

  // Friends, over HTTP
  friends_throttled: "Hai inviato molte richieste di amicizia. Riprova più tardi.",
  that_is_you: "Sei tu.",

  // Profiles and history
  no_such_game: "Questa partita non esiste.",
  no_such_drawing: "Questo disegno non esiste.",
  drawing_unreadable: "Non è stato possibile leggere questo disegno.",

  // Prompt lists
  prompt_list_not_found: "Lista di parole non trovata.",
  shared_prompt_list_not_found: "Nessuna lista di parole condivisa trovata.",
  prompt_list_conflict: "Qualcun altro ha modificato questa lista. Ricaricala e riprova.",
  prompt_list_invalid: "Non è stato possibile salvare questa lista di parole.",
  prompt_list_forbidden: "Questa lista di parole non è tua da modificare.",
  unknown_prompt_tag: (params: Record<string, unknown>) => {
    const tag = String(params.tag ?? "");
    return `«${tag}» non è un’etichetta che una lista può avere.`;
  },
  unknown_sort: "Sketchy non può ordinare per questo.",
  timezone_required: "Indica un fuso orario insieme a questa data.",
  range_reversed: "L’inizio dell’intervallo deve precedere la sua fine.",

  // Room presets
  room_preset_not_found: "Preimpostazione della stanza non trovata.",
  room_preset_conflict: "Hai già una preimpostazione con questo nome.",
  room_preset_unavailable: "Questa preimpostazione non si può usare adesso.",
  room_preset_forbidden: "Questa preimpostazione non è tua.",

  // Blocks
  cannot_block_yourself: "Non puoi bloccare te stesso.",
  block_list_full: (params) =>
  `La tua lista dei bloccati è piena${
    typeof params.limit === "number" ? ` a ${params.limit}` : ""
  }. Sblocca prima qualcuno.`,

  // Settings
  setting_refused: "Non è stato possibile salvare questa impostazione.",

  // Role notices
  no_such_notice: "Questo avviso non esiste.",

  // Reporting, from the reporter's side
  cannot_report_yourself: "Non puoi segnalare te stesso.",
  cannot_report_own_prompt_list: "Non puoi segnalare la tua lista di parole.",
  no_reportable_prompt_list: "Nessuna lista di parole segnalabile trovata.",
  prompt_not_in_list: "Questa parola non appartiene a questa lista.",
  no_picture_to_report: "Questo giocatore non ha un’immagine da segnalare.",
  no_such_game_context: "Questo contesto di partita non esiste.",
  no_such_turn_context: "Questo contesto di turno non esiste.",
  turn_not_in_game: "Il turno non appartiene a questa partita.",
  evidence_unavailable: "Uno o più messaggi selezionati non sono disponibili.",
  evidence_mixed_scopes: "I messaggi della lobby e quelli della stanza non si possono mischiare in una segnalazione.",
  evidence_several_rooms: "I messaggi selezionati devono venire dalla stessa stanza.",
  evidence_not_theirs: "Le prove devono essere del giocatore segnalato.",
  evidence_not_received: "Non puoi selezionare un messaggio che non hai ricevuto.",
  evidence_not_in_game: "Il messaggio selezionato non appartiene a questa partita.",
  evidence_not_in_turn: "Il messaggio selezionato non appartiene a questo turno.",
  no_such_warning: "Questo avvertimento non esiste.",
  no_drawing: "Nessun disegno.",};

/** What the room says about itself. One entry per `AnnouncementCode`. */
const ANNOUNCEMENTS: Record<AnnouncementCode, (params: MessageParams) => string> = {
  nickname_changed: (p) =>
  `${text(p.previous)} ora si chiama ${text(p.nickname)}.`,
  joined_as_player: (p) => `${text(p.nickname)} è entrato come giocatore.`,
  kicked_by_vote: (p) => `${text(p.nickname)} è stato espulso per votazione.`,
  marked_afk_by_vote: (p) => `${text(p.nickname)} è stato segnato come assente per votazione.`,

  restart_vote_started: (p) =>
  `${text(p.nickname)} ha avviato una votazione per riavviare la partita.`,
  restart_vote_passed: (p) =>
  `La votazione di riavvio è passata. Riavvio tra ${count(p.seconds, 5)} secondi.`,
  restart_vote_rejected: () => "La votazione di riavvio è stata respinta.",
  restart_vote_expired: () => "La votazione di riavvio è scaduta senza passare.",
  restart_vote_abandoned: () =>
  "La votazione di riavvio è stata annullata perché restano meno di due giocatori attivi.",
  restart_cancelled: (p) => `Il riavvio è stato annullato perché ${cancelReason(p.reason)}.`,
  game_restarted_by_vote: () => "La partita è stata riavviata per votazione dei giocatori.",

  hint_letter_found: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pt - trovata ${counted(count(p.count, 1), {
    one: "volta",
    other: "volte",
  })}!`,
  hint_letter_missing: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pt - non è nella parola.`,
  guess_very_close: (p) => `«${text(p.text)}» ci va molto vicino!`,
  guess_some_words_correct: () => "Alcune parole sono giuste",};

export const IT: Catalogue = {
  refusals: REFUSALS,
  announcements: ANNOUNCEMENTS,

  /** What the document itself says: the tab, and what a link preview shows.

      Rendered into `index.html` for a crawler, which arrives before any
      script, and rewritten here for the reader once their locale is known. */
  document: {
    description: "Disegna, indovina e ridi con gli amici!",
  },

  /** Shapes that belong to the language rather than to any one screen. */
  format: {
    /** `1st`, `2nd`, `3rd`; a language with no ordinal form gets the number. */
    ordinal: (p: { value: number }) => ordinal(p.value),
  },

  promptListDrafts: {
    promptsAdded: (p: { count: number }) =>
      `${counted(p.count, { one: "parola aggiunta", other: "parole aggiunte" })}`,
    duplicatesAlreadyInTheList: (p: { duplicates: number }) =>
      `${p.duplicates} già nella lista`,
    tooLongCountOverMaxListPrompt: (p: { tooLongCount: number; MAX_LIST_PROMPT_LENGTH: number }) =>
      `${p.tooLongCount} oltre i ${p.MAX_LIST_PROMPT_LENGTH} caratteri`,
    overLimitPastTheMaxList: (p: { overLimit: number; MAX_LIST_PROMPTS: number }) =>
      `${p.overLimit} oltre il limite di ${p.MAX_LIST_PROMPTS}`,
    keptSkippedSkipped: (p: { kept: string; skipped: string }) =>
      `${p.kept}; saltate: ${p.skipped}.`,
  },

  lastSeen: {
    online: "online",
    justNow: "visto proprio ora",
    lastSeenAgo: (p: { count: number; unit: "minute" | "hour" | "day" }) => {
      const words = {
        minute: { one: "minuto", other: "minuti" },
        hour: { one: "ora", other: "ore" },
        day: { one: "giorno", other: "giorni" },
      }[p.unit];
      return `visto ${counted(p.count, words)} fa`;
    },
  },

  gameHighlights: {
    reactionCount: (p: { count: number }) =>
      counted(p.count, { one: "reazione", other: "reazioni" }),
    hardestPrompt: "Parola più difficile",
    fastestGuess: "Risposta più veloce",
    bestDrawer: "Miglior disegnatore",
    quickestOnAverage: "Più veloce in media",
    mostReactedDrawing: "Disegno con più reazioni",
    guessedItOf: (p: { correct: number; total: number }) =>
      plural(p.correct, { one: `${p.correct} su ${p.total} l’ha indovinata`, other: `${p.correct} su ${p.total} l’hanno indovinata` }),
    percentGuessed: (p: { percent: string }) =>
      `${p.percent} indovinato`,
  },

  versionBadge: {
    buildDetails: (p: { commitDate: string; builtAt: string }) =>
      `Data del commit: ${p.commitDate} | Build: ${p.builtAt}`,
  },

  segmentedCodeInput: {
    digitPosition: (p: { label: string; index: number; length: number }) =>
      `${p.label}, cifra ${p.index} di ${p.length}`,
  },

  roomSetupControls: {
    decrease: (p: { label: string }) => `Riduci ${p.label}`,
    increase: (p: { label: string }) => `Aumenta ${p.label}`,
  },

  guessPips: {
    playerGuessState: (p: { nickname: string; isFriend: boolean; guessed: boolean }) =>
      `${p.nickname}${p.isFriend ? " (amico)" : ""} ${p.guessed ? "ha indovinato" : "sta ancora provando"}`,
    gotOfGuessersCountGuessed: (p: { got: number; guessersCount: number }) =>
      `${p.got} su ${p.guessersCount} hanno indovinato`,
    summaryOpenPlayersAndScores: (p: { summary: string }) =>
      `${p.summary}. Apri giocatori e punteggi.`,
  },

  accountDataDialog: {
    requestedOn: (p: { when: string; schemaVersion: number }) =>
      `Richiesta ${p.when} · formato v${p.schemaVersion}`,
    exportAllowance: (p: { nextAllowed: string | null }) =>
      p.nextAllowed
        ? `Un’esportazione a settimana; quelle pronte scadono dopo sette giorni. Puoi chiederne un’altra il ${p.nextAllowed}.`
        : "Un’esportazione a settimana; quelle pronte scadono dopo sette giorni.",
    couldNotLoadYourDataExports: "Non è stato possibile caricare le tue esportazioni.",
    couldNotRequestYourDataExport: "Non è stato possibile richiedere la tua esportazione.",
    yourData: "I tuoi dati",
    downloadPrivateJsonCopyYourAccount: "Scarica una copia privata in JSON del tuo account e dei tuoi dati di gioco. I profili e i messaggi degli altri giocatori non sono inclusi.",
    dataExports: "Esportazioni dei dati",
    loadingExports: "Caricamento esportazioni…",
    youHaveNotRequestedExportYet: "Non hai ancora chiesto nessuna esportazione.",
    download: "Scarica",
    close: "Chiudi",
    requesting: "Richiesta in corso…",
    requestExport: "Richiedi l’esportazione",
  },

  accountMenu: {
    noPasskeyWasUsed: "Non è stata usata nessuna passkey. Puoi accedere con la password.",
    signedInWithRequests: (p: { name: string; waiting: number }) =>
      `Hai effettuato l’accesso come ${p.name}. ${counted(p.waiting, {
        one: "richiesta di amicizia",
        other: "richieste di amicizia",
      })} in attesa.`,
    friends: "Amici",
    finishYourRole: (p: { role: "admin" | "moderator" }) =>
      `Completa il tuo ruolo di ${p.role === "admin" ? "amministratore" : "moderatore"}`,
    agreeToRules: "Creando un account accetti di seguire le {rules}.",
    reportBug: "Segnala un bug",
    account: "Account",
    settings: "Impostazioni",
    myProfile: "Il mio profilo",
    promptStats: "Statistiche parole",
    createAccount: "Crea account",
    logIn: "Accedi",
    myPromptLists: "Le mie liste di parole",
    rules: "Regole",
    logOut: "Esci",
    thatDoesNotLookLikeEmail: "Non sembra un indirizzo email.",
    somethingWentWrongPleaseTryAgain: "Qualcosa è andato storto. Riprova.",
    thatPasskeyWasNotAccepted: "Questa passkey non è stata accettata.",
    thisAccountSignsWithPasskey: "Questo account accede con una passkey.",
    or: "oppure",
    username: "Nome utente",
    password: "Password",
    codeFromYourAuthenticatorApp: "Codice dalla tua app di autenticazione",
    recoveryCodeWorksHereTooCan: "Anche un codice di recupero funziona qui, e si può usare una volta.",
    email: "Email",
    optional: "facoltativo",
    letsYouResetYourPasswordLater: "Ti permette di reimpostare la password più avanti. Non serve ad altro.",
    rules2: "regole",
    forgotYourPassword: "Password dimenticata?",
    notNow: "Non ora",
    createYourAccount: "Crea il tuo account",
    createAnAccountToKeep: (p: { suggestedUsername: string }) =>
      `Crea un account per tenere ${p.suggestedUsername} come nome utente e salvare le tue statistiche su ogni dispositivo.`,
    keepYourUsernameAndYour: "Tieni il tuo nome utente e le tue statistiche su ogni dispositivo.",
    waitingForYourDevice: "In attesa del tuo dispositivo…",
    signInWithAPasskey: "Accedi con una passkey",
    pleaseWait: "Attendi…",
    alreadyRegistered: "Già registrato? ",
    newHere: "Nuovo qui? ",
    createAnAccount: "Crea un account",
    guestIdentity: (p: { name: string }) =>
      `${p.name}. Il tuo nome visualizzato non è salvato.`,
    signedInAs: (p: { name: string }) =>
      `Accesso come ${p.name}`,
  },

  accountRecoveryPage: {
    thatConfirmationLinkCouldNotBe: "Non è stato possibile usare questo link di conferma.",
    somethingWentWrongPleaseTryAgain: "Qualcosa è andato storto. Riprova.",
    evenBestGuessersForgetSometimes: "Anche i migliori indovini a volte dimenticano.",
    weRsquoLlSendSecureTime: "Invieremo un link sicuro e a tempo all’indirizzo email confermato\n            del tuo account.",
    accountHelp: "Aiuto sull’account",
    backLobby: "Torna alla lobby",
    enterYourUsernameYourConfirmedEmail: "Inserisci il tuo nome utente o il tuo indirizzo confermato. Se\n              l’account è recuperabile, un link è già in viaggio.",
    usernameEmail: "Nome utente o email",
    thatResetLinkHasExpiredHas: "Questo link di reimpostazione è scaduto o è già stato usato. Questi\n              link funzionano una volta e durano un’ora.",
    sendNewOne: "Inviane uno nuovo",
    checkingThatLink: "Controllo del link…",
    everySignedDeviceWillBeSigned: "Tutti i dispositivi connessi verranno disconnessi, compresi quelli\n              che non hai riconosciuto.",
    newPassword: "Nuova password",
    addressIsConfirmedYouCan: (p: { address: string }) =>
      `${p.address} è confermato. Ora puoi recuperare questo account.`,
    yourPasswordIsSetAnd: "La tua password è impostata e hai di nuovo effettuato l’accesso.",
    resetYourPassword: "Reimposta la password",
    thatLinkNoLongerWorks: "Questo link non funziona più",
    chooseANewPassword: "Scegli una nuova password",
    confirmingYourEmail: "Conferma della tua email",
    pleaseWait: "Attendi…",
    sendAResetLink: "Invia un link di reimpostazione",
    setPassword: "Imposta la password",
    oneMoment: "Un momento…",
    nothingToConfirm: "Niente da confermare.",
    resetLinkOnItsWay:
      "Se quell’account esiste e ha un indirizzo email confermato, un link di reimpostazione è in arrivo.",
  },

  activeGameRoom: {
    leaveGame: "Esci dalla partita",
    markedAfkByRoomVote: "La stanza ti ha segnato come assente per votazione.",
    inviteLinkCopied: "Link d’invito copiato.",
    couldnTCopyLinkCopyFrom: "Non è stato possibile copiare il link. Copialo dalla barra degli indirizzi.",
    couldNotStartGamePleaseTry: "Non è stato possibile iniziare la partita. Riprova.",
    couldNotStartRestartVote: "Non è stato possibile avviare una votazione di riavvio.",
    couldNotRecordYourRestartVote: "Non è stato possibile registrare il tuo voto.",
    copyRoomInviteLink: "Copia il link d’invito della stanza",
    clickCopyRoomInviteLink: "Clicca per copiare il link d’invito",
    roomMenu: "Menu della stanza",
    afk: "Assente",
    saveImage: "Salva immagine",
    saveDrawnImageFile: "Salva il disegno in un file",
    playerSettings: "Impostazioni del giocatore",
    leaveRoom: "Esci dalla stanza",
    leave: "Esci",
    players: "Giocatori",
    youWereKickedFromThe: "Sei stato espulso dalla stanza.",
    thisRoomWasOpenedIn: "Questa stanza è stata aperta in un’altra scheda.",
    startTheGame: "avviare la partita",
    startARestartVote: "avviare una votazione per ricominciare",
    recordYourRestartVote: "registrare il tuo voto per ricominciare",
    leaveDuringYourTurn: "Uscire durante il tuo turno?",
    leaveActiveGame: "Uscire dalla partita in corso?",
    youReTheCurrentDrawer: "Stai disegnando tu. Se esci ora interromperai il tuo turno e la partita andrà avanti per tutti.",
    theGameIsStillIn: "La partita è ancora in corso. Uscirai dalla stanza e perderai il tuo posto in questa partita.",
    restartVoteAvailableInRestartCooldownSeconds: (p: { restartCooldownSeconds: number }) =>
      `Votazione per ricominciare disponibile tra ${p.restartCooldownSeconds} secondi`,
    proposeRestartingTheGame: "Proponi di ricominciare la partita",
    restartVoteAvailableInRestartCooldownSeconds2: (p: { restartCooldownSeconds: number }) =>
      `Votazione per ricominciare tra ${p.restartCooldownSeconds} s`,
    proposeAVoteToRestart: "Proponi una votazione per ricominciare la partita",
    backFromAfk: "Sono tornato",
    goAfk: "Segnami assente",
    closePlayers: "Chiudi giocatori",
    acceptTheColorSuggestion: "accettare il suggerimento sui colori",
    dismissTheColorSuggestion: "ignorare il suggerimento sui colori",
    couldNotAcceptSuggestion: "Impossibile accettare il suggerimento sui colori.",
    couldNotDismissSuggestion: "Impossibile ignorare il suggerimento sui colori.",
  },

  addEmailDialog: {
    followTheLink: (p: { address: string; replacing: boolean }) =>
      `Segui il link inviato a ${p.address}. Finché non lo fai, l’indirizzo non è collegato al tuo account e non serve a recuperarlo${
        p.replacing ? ", e quello che avevi resta al suo posto." : "."
      }`,
    thatDoesNotLookLikeEmail: "Non sembra un indirizzo email.",
    somethingWentWrongPleaseTryAgain: "Qualcosa è andato storto. Riprova.",
    done: "Fatto",
    usedOnlyResetYourPasswordTell: "Serve solo a reimpostare la password e ad avvisarti se sul tuo account\n              o su qualcosa che hai condiviso viene presa una decisione. Qui non\n              arriva mai nient’altro.",
    checkYourInbox: "Controlla la tua casella di posta",
    changeYourEmailAddress: "Cambia il tuo indirizzo email",
    addAnEmailAddress: "Aggiungi un indirizzo email",
    newEmail: "Nuova email",
    email: "Email",
    pleaseWait: "Attendi…",
    sendConfirmation: "Invia conferma",
    close: "Chiudi",
    notNow: "Non ora",
  },

  afkCheckDialog: {
    secondsUnit: (p: { count: number }) =>
      plural(p.count, { one: "secondo", other: "secondi" }),
    stillThere: "Ci sei ancora?",
    youHaveBeenQuietWhileAnswer: "Sei in silenzio da un po’. Rispondi e continui a giocare; altrimenti\n          la stanza ti segnerà come assente e andrà avanti senza di te.",
    stillTherePressButtonMoveMouse: "Ci sei ancora? Premi il pulsante, o muovi il mouse, per continuare a giocare.",
    iMHere: "Sono qui",
  },

  app: {
    serverUpdateInProgress: (p: { seconds: number }) =>
      p.seconds > 0
        ? `Aggiornamento del server in corso. Non possono partire nuove stanze o partite; a una partita in corso restano ${counted(p.seconds, { one: "secondo", other: "secondi" })}.`
        : "Aggiornamento del server in corso. Non possono partire nuove stanze o partite; le partite ancora in corso stanno finendo.",
    thisTabOutDateCannotPlay: "Questa scheda non è aggiornata e non può giocare finché non viene ricaricata.",
    reload: "Ricarica",
    newRoomsArePausedMaintenanceGames: "Le nuove stanze sono in pausa per manutenzione. Le partite già in corso\n          proseguono normalmente.",
    serverWasUpdatedBackAnyGame: "Il server è stato aggiornato ed è tornato. Le partite in corso sono finite.",
    dismiss: "Chiudi",
  },

  appHeader: {
    playerSettings: "Impostazioni del giocatore",
  },

  bugReportDialog: {
    connectionSummary: (p: { connected: boolean; reconnects: number }) =>
      `${p.connected ? "connesso" : "offline"} · ${counted(p.reconnects, {
        one: "riconnessione",
        other: "riconnessioni",
      })} in questa visita`,
    couldNotTakeScreenshot: "Non è stato possibile fare lo screenshot.",
    thanksYourReportWithPeopleWho: "Grazie — la tua segnalazione è arrivata a chi gestisce Sketchy.",
    couldNotSendReport: "Non è stato possibile inviare la segnalazione.",
    reportBug: "Segnala un bug",
    somethingBrokenNotSomethingSomeoneSaid: "Qualcosa di rotto, non qualcosa che qualcuno ha detto. Arriva a chi gestisce Sketchy — mai agli altri giocatori.",
    where: "Dove",
    howBad: "Quanto è grave",
    oneLineSummary: "Riassunto in una riga",
    whatWentWrongOneLine: "Cosa non ha funzionato, in una riga",
    whatHappened: "Cosa è successo",
    whatYouDidWhatYouExpected: "Cosa hai fatto, cosa ti aspettavi, cosa è successo invece.",
    screenshot: "Screenshot",
    optional: "Facoltativo",
    screenshotThatWillBeSentWith: "Lo screenshot che verrà inviato con questa segnalazione",
    thisDialogHidesItselfWhileShot: "Questa finestra si nasconde mentre viene scattato, così ottieni la pagina dietro. Guardalo prima di inviare — decidi tu cosa condividere.",
    replace: "Sostituisci",
    remove: "Rimuovi",
    opensYourBrowserSOwnPicker: "Apre il selettore del tuo browser — scegli questa scheda. Questa finestra si nasconde mentre viene scattato, così ottieni la pagina dietro.",
    recentClientErrors: "Errori recenti del client",
    sendMyDescriptionOnly: "Invia solo la mia descrizione",
    dropsDetailsAboveAnyScreenshotWe: "Scarta i dettagli qui sopra e ogni screenshot. Lo leggeremo comunque, ma il bug sarà molto più difficile da riprodurre.",
    cancel: "Annulla",
    build: "Versione",
    page: "Pagina",
    room: "Stanza",
    screen: "Schermo",
    browser: "Browser",
    connection: "Connessione",
    waitingForThePicker: "In attesa del selettore…",
    attachAScreenshot: "Allega uno screenshot",
    whatWeAreLeavingOut: "Cosa lasciamo fuori",
    whatWeSendWithThis: "Cosa inviamo insieme",
    noneOfThisIsBeing: "Niente di tutto questo viene inviato: solo la tua descrizione qui sopra.",
    theLast20ErrorsYour: "Gli ultimi 20 errori registrati dal tuo browser. Nessun indirizzo di pagina oltre il percorso, niente di ciò che hai scritto in chat e mai la parola in gioco.",
    sending: "Invio…",
    sendReport: "Invia segnalazione",
    kilobytes: (p: { size: number }) =>
      `${number(p.size)} KB`,
    megabytes: (p: { size: number }) =>
      `${number(p.size)} MB`,
  },

  changePasswordDialog: {
    forgottenTheCurrentOne: "Dimenticata quella attuale?",
    twoNewPasswordsDoNotMatch: "Le due nuove password non coincidono.",
    passwordChangedEveryOtherDeviceHas: "Password cambiata. Tutti gli altri dispositivi sono stati disconnessi.",
    couldNotChangePasswordPleaseTry: "Non è stato possibile cambiare la password. Riprova.",
    ifThatAccountHasVerifiedEmail: "Se quell’account ha un indirizzo email verificato, un link per impostare\n              una nuova password è già in viaggio. Funziona una volta e scade.",
    done: "Fatto",
    everyDeviceSignsOutWhenPassword: "Ogni dispositivo viene disconnesso quando cambia la password, compresi\n              quelli che non volevi lasciare connessi. Questo resta.",
    currentPassword: "Password attuale",
    newPassword: "Nuova password",
    newPasswordAgain: "Ripeti la nuova password",
    emailMeLinkInstead: "Mandami invece un link",
    checkYourInbox: "Controlla la tua casella di posta",
    changeYourPassword: "Cambia la tua password",
    pleaseWait: "Attendi…",
    changePassword: "Cambia password",
    close: "Chiudi",
    cancel: "Annulla",
  },

  choosingPromptOverlay: {
    isChoosingPrompt: "{drawer} sta scegliendo una parola…",
    nextTurn: "Turno successivo",
    drawingWillBeginAsSoonAs: "Il disegno inizierà appena avrà scelto.",
  },

  colorblindSafeSuggestionBanner: {
    colorblindSafeColorSuggestion: "Suggerimento sui colori adatti al daltonismo",
    playerThisRoomPlaysWithColorblind: "Un giocatore in questa stanza gioca con colori adatti al daltonismo.",
    switchRoomPaletteFutureDrawings: "Cambiare la tavolozza della stanza per i prossimi disegni?",
    switchColors: "Cambia colori",
    notNow: "Non ora",
  },

  confirmationDialog: {
    cancel: "Annulla",
  },

  crashPage: {
    couldNotSendReport: "Non è stato possibile inviare la segnalazione.",
    bugCrawledOntoPage: "Un bug si è arrampicato sulla pagina",
    helpUsSquash: "Aiutaci a schiacciarlo",
    reportReadySendErrorWhatThis: "C’è una segnalazione pronta da inviare: l’errore e quello che questa scheda\n            sa di sé. Arriva a chi gestisce Sketchy — mai agli altri giocatori.",
    whatWereYouDoing: "Cosa stavi facendo?",
    optional: "Facoltativo",
    lastThingYouClickedTypedIf: "L’ultima cosa che hai cliccato o scritto, se te la ricordi.",
    recentClientErrorsNewestFirst: "Errori recenti del client, dal più nuovo",
    sendMyDescriptionOnly: "Invia solo la mia descrizione",
    dropsDetailsAboveWeWillStill: "Scarta i dettagli qui sopra. Lo leggeremo comunque, ma il crash sarà molto più difficile da trovare.",
    thanksYourReportWithPeopleWho: "Grazie — la tua segnalazione è arrivata a chi gestisce Sketchy.",
    reload: "Ricarica",
    backLobby: "Torna alla lobby",
    summary: "Riepilogo",
    build: "Versione",
    page: "Pagina",
    room: "Stanza",
    screen: "Schermo",
    browser: "Browser",
    connection: "Connessione",
    thisRoomSScreenHit: "La schermata di questa stanza ha avuto un errore e si è dovuta fermare. Il tuo posto resta riservato per un momento: invia la segnalazione qui sotto, poi ricarica per riprenderlo o torna alla lobby.",
    thisScreenHitAnError: "Questa schermata ha avuto un errore e si è dovuta fermare. Il tuo account e le impostazioni sono al sicuro. Invia la segnalazione qui sotto e potrai proseguire.",
    whatWeAreLeavingOut: "Cosa lasciamo fuori",
    whatWeSendWithThis: "Cosa inviamo insieme",
    noneOfThisIsBeing: "Niente di tutto questo viene inviato: solo la tua descrizione qui sopra.",
    theCrashTheLast20: "Il crash, gli ultimi 20 errori registrati dal tuo browser e il punto della pagina in cui è successo. Nessun indirizzo di pagina oltre il percorso, niente di ciò che hai scritto in chat e mai la parola in gioco.",
    sendingAgain: "Nuovo invio…",
    sending: "Invio…",
    trySendingAgain: "Riprova a inviare",
    sendReport: "Invia segnalazione",
  },

  createRoomPage: {
    setupTiming: "Questa configurazione dura {full} con una stanza piena da {capacity}",
    setupTimingFull: (p: { minutes: number }) =>
      `circa ${counted(p.minutes, { one: "minuto", other: "minuti" })}`,
    setupTimingHalf: (p: { players: number }) => ` — più vicino a {half} se entrano in ${p.players}`,
    couldNotLoadYourRoomPresets: "Non è stato possibile caricare le tue preimpostazioni.",
    couldNotApplyThatPreset: "Non è stato possibile applicare questa preimpostazione.",
    enterNameRoomPreset: "Dai un nome alla preimpostazione della stanza.",
    couldNotSaveThatPreset: "Non è stato possibile salvare questa preimpostazione.",
    couldNotUpdateThatPreset: "Non è stato possibile aggiornare questa preimpostazione.",
    couldNotDeleteThatPreset: "Non è stato possibile eliminare questa preimpostazione.",
    fixCustomPromptEntriesMarkedAbove: "Correggi le parole personalizzate segnate qui sopra prima di creare la stanza.",
    failedCreateRoom: "Creazione della stanza non riuscita",
    roomSetup: "Configurazione della stanza",
    createRoom: "Crea una stanza",
    startFromSavedPreset: "Parti da una preimpostazione salvata",
    startFromPreset: "Parti da una preimpostazione…",
    nameThisPreset: "Dai un nome a questa preimpostazione",
    save: "Salva",
    cancel: "Annulla",
    saveAsPreset: "Salva come preimpostazione",
    update: "Aggiorna",
    delete: "Elimina",
    undo: "Annulla",
    saveAsReusableList: "Salva come lista riutilizzabile",
    saveQuickPromptsAsA: "Salva le parole rapide come lista e rimuovi i codici condivisi prima di salvare un’impostazione predefinita.",
    appliedName: (p: { name: string }) =>
      `«${p.name}» applicato.`,
    savedName: (p: { name: string }) =>
      `«${p.name}» salvato.`,
    updatedName: (p: { name: string }) =>
      `«${p.name}» aggiornato.`,
    deleteThisRoomSettingPreset: "Eliminare questa impostazione predefinita della stanza?",
    createTheRoom: "creare la stanza",
    noScoring: "Senza punteggio",
    public: "Pubblica",
    private: "Privata",
    backToLobby: "Torna alla lobby",
    leaveBlankForARandom: "Lascia vuoto per un nome a caso!",
    creating: "Creazione…",
    createRoom2: "Crea stanza",
    playerCount: (p: { count: number }) =>
      counted(p.count, { one: "giocatore", other: "giocatori" }),
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "round", other: "round" }),
  },

  customPromptsEditor: {
    usableCount: (p: { count: number }) =>
      counted(p.count, { one: "parola personalizzata utilizzabile", other: "parole personalizzate utilizzabili" }),
    duplicatesIgnored: (p: { count: number }) =>
      `${counted(p.count, { one: "doppione ignorato", other: "doppioni ignorati" })}`,
    entriesTooLong: (p: { count: number; limit: number }) =>
      `${counted(p.count, { one: "voce supera", other: "voci superano" })} i ${number(p.limit)} caratteri`,
    entryLimit: (p: { limit: number }) => `Sono ammesse solo ${number(p.limit)} voci`,
    customPromptsOptional: "Parole personalizzate (facoltativo)",
    onePromptPerLineSeparateEntries: "Una parola per riga\noppure separa le voci con virgole",
    shortenRemoveOverlongEntriesBeforeCreating: "Accorcia o togli le voci troppo lunghe prima di creare la stanza.",
  },

  customPromptsPreview: {
    resultsMatching: (p: { shown: number; total: number }) =>
      `${number(p.shown)} parole su ${number(p.total)} corrispondono`,
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "parola", other: "parole" }),
    customPromptCount: (p: { count: number }) =>
      counted(p.count, { one: "parola personalizzata", other: "parole personalizzate" }),
    inspectPrompts: (p: { count: number }) =>
      `Esamina ${counted(p.count, { one: "parola personalizzata", other: "parole personalizzate" })}`,
    couldNotLoadCustomPrompts: "Non è stato possibile caricare le parole personalizzate",
    loadingCustomPrompts: "Caricamento delle parole personalizzate…",
    roomPromptCollection: "Raccolta di parole della stanza",
    readOnlyListSuppliedByRoom: "Lista in sola lettura fornita dall’host.",
    findPrompt: "Trova una parola",
    searchCustomPrompts: "Cerca fra le parole personalizzate…",
    filterPromptsByLength: "Filtra le parole per lunghezza",
    noCustomPromptsMatchTheseFilters: "Nessuna parola personalizzata corrisponde a questi filtri.",
    all: "Tutte",
    allPromptLengths: "Tutte le lunghezze",
    short: "Corte",
    n5CharactersOrFewer: "5 caratteri o meno",
    medium: "Medie",
    n6To10Characters: "Da 6 a 10 caratteri",
    long: "Lunghe",
    n11CharactersOrMore: "11 caratteri o più",
    loadTheCustomPrompts: "caricare le parole personalizzate",
  },

  deleteAccountDialog: {
    whatIsRemoved: (p: { isGuest: boolean }) =>
      `${
        p.isGuest
          ? "Il nome, i punti e la cronologia tenuti su questo browser vengono rimossi."
          : "Il tuo nome viene rimosso dalle partite che hai giocato."
      } I punteggi e i disegni restano, sotto «Giocatore eliminato», perché sono anche le partite di altre persone. Non si può annullare.`,
    typeToConfirm: (p: { word: string }) => `Scrivi ${p.word} per confermare`,
    couldNotDeleteAccount: "Non è stato possibile eliminare l’account.",
    password: "Password",
    deleteThisGuest: "Elimina questo ospite",
    deleteYourAccount: "Elimina il tuo account",
    deleting: "Eliminazione…",
    deleteForGood: "Elimina per sempre",
    keepPlaying: "Continua a giocare",
    keepMyAccount: "Tieni il mio account",
  },

  drawingReactionControl: {
    reactionSummary: (p: { total: number; chips: string }) =>
      `${counted(p.total, { one: "reazione", other: "reazioni" })}: ${p.chips}`,
    thatReactionCouldNotBeSent: "Non è stato possibile inviare questa reazione.",
    reactThisDrawing: "Reagisci a questo disegno",
    reactions: "Reazioni",
    createAccountReact: "Crea un account per reagire.",
    createAccount: "Crea account",
    noReactionsYet: "Ancora nessuna reazione",
    reactToThisDrawingSummary: (p: { summary: string }) =>
      `Reagisci a questo disegno. ${p.summary}`,
    labelYourReactionPressTo: (p: { label: string }) =>
      `${p.label}, la tua reazione. Premi per toglierla`,
  },

  drawingRecapGallery: {
    drawingLabel: (p: { prompt: string; drawer: string }) =>
      `Disegno di ${p.prompt} fatto da ${p.drawer}`,
    drawnBy: "Disegnato da {drawer} · Round {round} · Turno {turn}",
    position: (p: { position: number; total: number }) => `${p.position} di ${p.total}`,
    thisDrawingCouldNotBeDecoded: "Non è stato possibile decodificare questo disegno.",
    drawingRecap: "Riepilogo dei disegni",
    saveImage: "Salva immagine",
    close: "Chiudi",
    thisDrawingWasNotKept: "Questo disegno non è stato conservato.",
    roomRanOutRoomLaterTurns: "Nella stanza non c’era più spazio. Sono stati tenuti i turni successivi.",
    tryAgain: "Riprova",
    loadingDrawing: "Caricamento del disegno…",
    noDrawingWasCapturedThisTurn: "Per questo turno non è stato salvato nessun disegno.",
    drawingRecapNavigation: "Navigazione del riepilogo dei disegni",
    previous: "Precedente",
    next: "Successivo",
    loadThisDrawing: "caricare questo disegno",
  },

  emailRecoveryReminder: {
    addEmail: "Aggiungi un’email",
    dismiss: "Chiudi",
    confirmPendingAddressToFinishSetting: (p: { pendingAddress: string }) =>
      `Conferma ${p.pendingAddress} per completare il recupero dell’account.`,
    thisAccountHasNoEmail: "Questo account non ha un indirizzo email, quindi una password dimenticata non si può reimpostare.",
  },

  firstRunIdentity: {
    couldNotSaveThatNamePlease: "Non è stato possibile salvare questo nome. Riprova.",
    keepYourUsernameYourStatsEvery: "Tieni il tuo nome utente e le tue statistiche su ogni dispositivo.",
    createAccount: "Crea un account",
    logIn: "Accedi",
    or: "oppure",
    displayName: "Nome visualizzato",
    beenHereBefore: "Sei già stato qui?",
    playAsYourself: "Gioca come te stesso",
    whatShouldWeCallYou: "Come ti chiamiamo?",
    justPlayingOncePickA: "Solo una partita? Scegli un nome visualizzato",
    play: "Gioca",
    playAsGuest: "Gioca come ospite",
  },

  friendButton: {
    requestSentTo: (p: { name: string }) => `Richiesta di amicizia inviata a ${p.name}`,
    addFriend: "Aggiungi amico",
    acceptRequest: "Accetta richiesta",
    requestSent: "Richiesta inviata",
  },

  friendInviteNotice: {
    couldNotJoinThatGame: "Non è stato possibile entrare in questa partita.",
    thatGameCouldNotBeJoined: "Non è stato possibile entrare in questa partita.",
    invitedYouTheirGame: "ti ha invitato nella sua partita.",
    join: "Entra",
    dismissInvitation: "Chiudi l’invito",
  },

  friendsOverlay: {
    declineWarning: (p: { name: string }) =>
      `${p.name} non potrà richiederlo. Tu potrai comunque mandargli una richiesta più avanti.`,
    decline2: "Rifiuta",
    youWillBothStopBeingAble: "Non potrete più entrare nelle partite l’uno dell’altro senza invito. Potete richiederlo quando volete.",
    remove2: "Rimuovi",
    removeConfirm: (p: { name: string }) => `Rimuovere ${p.name}?`,
    friends: "Amici",
    close: "Chiudi",
    closeFriends: "Chiudi gli amici",
    friendsNeedAccountGuestNameBelongs: "Per gli amici serve un account. Un nome da ospite appartiene a questo\n              browser e non a te, quindi fra un mese non resterebbe nessuno con\n              cui essere amici.",
    loading: "Caricamento…",
    noFriendsYetAddSomebodyFrom: "Ancora nessun amico. Aggiungi qualcuno dalla lobby, o da una partita\n              in cui siete entrambi.",
    requests: "Richieste",
    accept: "Accetta",
    decline: "Rifiuta",
    sent: "Inviata",
    cancel: "Annulla",
    remove: "Rimuovi",
    declineThisRequest: "Rifiutare questa richiesta?",
    recentlyPlayedWith: "Giocato di recente con",
  },

  gameEndOverlay: {
    continueLabel: "Continua",
    youFinished: (p: { points: number }) =>
      `Sei arrivato {place} con ${counted(p.points, { one: "punto", other: "punti" })}.`,
    continueToWaitingRoom: "Vai alla sala d’attesa",
    continueWithCountdown: (p: { seconds: number }) =>
      `Vai alla sala d’attesa, ${counted(p.seconds, { one: "secondo", other: "secondi" })} rimasti`,
    gameOver: "Partita finita",
    you: "tu",
    friend: "Amico",
    noScoresThisTimeJustRoom: "Niente punti stavolta: solo una stanza piena di schizzi e tentativi.",
    keep: "Tieni",
    asYourUsername: "come nome utente",
    createAccount: "Crea account",
    highlights: "Momenti migliori",
    drawings: "Disegni",
    stayHere: "Resto qui",
    aGreatGameOfDrawing: "Una bella partita di disegno",
    theRoomTakesTheCrown: "L’intera stanza si prende la corona!",
    winnersCountPlayersShareTheCrown: (p: { winnersCount: number }) =>
      `${p.winnersCount} giocatori si dividono la corona!`,
    takesTheCrown: " si prende la corona!",
    shareTheCrown: " si dividono la corona!",
  },

  gameHighlightsPanel: {
    lastGame: "Ultima partita",
    highlights: "Momenti migliori",
    closeHighlights: "Chiudi i momenti migliori",
    thatGameWasTooShortSay: "Questa partita è stata troppo corta per dire granché. Giocane una più\n            lunga e qui compariranno i momenti migliori.",
    seeIt: "Guarda",
    back: "Indietro",
  },

  inviteEntryPage: {
    roomCode: (p: { code: string }) => `Stanza ${p.code}`,
    hereCount: (p: { here: number; capacity: number; full: boolean }) =>
      `${p.here}/${p.capacity} qui${p.full ? " · piena" : ""}`,
    roomSummary: (p: { rounds: number; seconds: number; hintMode: string }) =>
      `${counted(p.rounds, { one: "round", other: "round" })} · ${p.seconds}s · ${p.hintMode}`,
    checkingYourInvite: "Controllo del tuo invito…",
    loadingRoomDetails: "Caricamento dei dettagli della stanza.",
    roomUnavailable: "Stanza non disponibile",
    backLobby: "Torna alla lobby",
    players: "Giocatori",
    rounds: "Round",
    drawTime: "Tempo di disegno",
    scoring: "Punteggio",
    roomRules: "Regole della stanza",
    thisGameAlreadyProgressJoiningAs: "Questa partita è già in corso. Entrando come giocatore ti tocca un turno successivo.",
    playerSlotsAreFullSpectatingStill: "I posti da giocatore sono pieni. Puoi ancora guardare.",
    promptDetailsHidden: "Dettagli della parola nascosti",
    timedHints: "Indizi a tempo",
    buyableLetterHints: "Indizi di lettere acquistabili",
    wheelOfFortune: "Ruota della fortuna",
    noLetterHints: "Nessun indizio di lettere",
    publicRoom: "Stanza pubblica",
    privateInvite: "Invito privato",
    inProgress: "In corso",
    waiting: "In attesa",
    full: " · Piena",
    noScoring: "Senza punteggio",
    pressure: "Pressione",
    default: "Standard",
    everyToolAndColor: "Tutti gli strumenti e i colori",
    spectatorsCanSeeThePrompt: "Gli spettatori vedono la parola",
    spectatorsGuessAlong: "Anche gli spettatori indovinano",
    defaultPromptList: "Lista di parole standard",
    roomFull: "Stanza piena",
    joining: "Ingresso…",
    joinGameInProgress: "Entra nella partita in corso",
    joinGame: "Entra nella partita",
    spectate: "Guarda",
    customPromptsOnly: (p: { count: number }) =>
      `solo ${counted(p.count, { one: "parola personalizzata", other: "parole personalizzate" })}`,
    customPromptsPlusDefaults: (p: { count: number }) =>
      `${counted(p.count, { one: "parola personalizzata", other: "parole personalizzate" })} più quelle standard`,
  },

  inviteFriendsList: {
    invitationCouldNotBeSent: "Non è stato possibile inviare questo invito.",
    invitationSent: (p: { name: string }) => `Invito inviato a ${p.name}.`,
    thatInvitationCouldNotBeSent: "Non è stato possibile inviare questo invito.",
    friendsLobby: "Amici nella lobby",
    invited: "Invitato",
    invite: "Invita",
  },

  languagePicker: {
    currentChoice: (p: { label: string; value: string }) => `${p.label}: ${p.value}`,
    everyLanguage: "Tutte le lingue",
  },

  lobbyBrowserPage: {
    filterByLanguage: "Filtra per lingua",
    filtersWithCount: (p: { count: number }) =>
      p.count > 0 ? `Filtri · ${p.count}` : "Filtri",
    showRooms: (p: { count: number }) =>
      `Mostra ${counted(p.count, { one: "stanza", other: "stanze" })}`,
    removedFromRoom: "Rimosso dalla stanza",
    ok: "OK",
    roomCode: "Codice stanza",
    abc123: "ABC123",
    thereNoRoomCodeClipboard: "Negli appunti non c’è nessun codice stanza.",
    sketchyCouldNotReadClipboardPaste: "Sketchy non è riuscito a leggere gli appunti. Incolla invece nelle caselle.",
    pleaseEnterRoomCode: "Inserisci un codice stanza",
    failedJoinRoom: "Impossibile entrare nella stanza",
    joinByCode: "Entra con un codice",
    createRoom: "Crea stanza",
    publicRooms: "Stanze pubbliche",
    searchRoomsByNameCode: "Cerca stanze per nome o codice",
    hideFull: "Nascondi piene",
    hideProgress: "Nascondi in corso",
    filters: "Filtri",
    clearFilters: "Azzera i filtri",
    language: "Lingua",
    hideFullRooms: "Nascondi le stanze piene",
    hideGamesProgress: "Nascondi le partite in corso",
    loadingPublicRooms: "Caricamento delle stanze pubbliche…",
    noPublicRoomsYetCreateOne: "Ancora nessuna stanza pubblica. Creane una!",
    noPublicRoomsMatchYourSearch: "Nessuna stanza pubblica corrisponde alla tua ricerca.",
    createRoom2: "Crea una stanza",
    joinWithCode: "Entra con un codice",
    paste: "Incolla",
    couldNotSaveThatName: "Impossibile salvare quel nome. Riprova.",
    joinAsASpectator: "entrare come spettatore",
    joinTheRoom: "entrare nella stanza",
    loading: "Caricamento…",
    showingFilteredRoomsCountOfRoomsCount: (p: { filteredRoomsCount: number; roomsCount: number }) =>
      `${p.filteredRoomsCount} su ${p.roomsCount} mostrate`,
    n0Rooms: "0 stanze",
    close: "Chiudi",
    joining: "Ingresso…",
    joinTheRoom2: "Entra nella stanza",
    joiningAsSpectator: "Ingresso come spettatore…",
    watchWithoutPlaying: "Guarda senza giocare",
  },

  lobbyChatPanel: {
    reportThisLine: (p: { name: string }) => `Segnala questa riga di ${p.name}`,
    couldNotSendThat: "Non è stato possibile inviarlo.",
    chat: "Chat",
    lobbyChat: "Chat della lobby",
    nobodyHasSaidAnythingYet: "Non ha ancora detto niente nessuno.",
    chooseNameChat: "Scegli un nome per chattare",
    saySomethingLobby: "Di’ qualcosa alla lobby…",
    lobbyChatMessage: "Messaggio della chat della lobby",
    send: "Invia",
    couldNotSaveThatName: "Impossibile salvare quel nome. Riprova.",
    sendTheMessage: "inviare il messaggio",
  },

  lobbyPlayerMenu: {
    whatToDoAbout: (p: { name: string }) => `Cosa fare con ${p.name}`,
    openPlayerProfile: "Apri il profilo del giocatore",
    addAsFriend: "Aggiungi agli amici",
    report: "Segnala",
  },

  promptTags: {
    "animals": "Animali",
    "food-and-drink": "Cibo e bevande",
    "objects": "Oggetti",
    "nature": "Natura",
    "places": "Luoghi",
    "people": "Persone",
    "actions": "Azioni",
    "sports-and-games": "Sport e giochi",
    "transport": "Trasporti",
    "entertainment": "Intrattenimento",
    "science-and-technology": "Scienza e tecnologia",
    "history-and-culture": "Storia e cultura",
    "holidays": "Feste",
    "fantasy": "Fantasy",
    "abstract": "Astratto",
  },
  myPromptListsPage: {
    tags: "Etichette",
    tagsChosen: (p: { chosen: number; max: number }) => `${p.chosen} di ${p.max} scelte`,
    tagsAreHowListsAreFound: "Le etichette sono il modo in cui questa lista si trova nel catalogo della community.",
    listSummary: (p: { prompts: number; visibility: string; moderationState: string | null }) =>
      `${counted(p.prompts, { one: "parola", other: "parole" })} · ${p.visibility}${
        p.moderationState ? ` · ${p.moderationState}` : ""
      }`,
    listUnderReview: (p: { state: string }) =>
      `Questa lista è ${p.state} e non si può usare in nuove partite. Modificarla non la ripristina in automatico; deve esaminarla un moderatore.`,
    needsReview: (p: { count: number }) => `Da esaminare (${p.count})`,
    removePrompt: (p: { prompt: string }) => `Rimuovi ${p.prompt}`,
    couldNotLoadYourPromptLists: "Non è stato possibile caricare le tue liste di parole.",
    couldNotOpenThatPromptList: "Non è stato possibile aprire questa lista.",
    addAtLeastOnePromptBefore: "Aggiungi almeno una parola prima di salvare.",
    couldNotSaveThisPromptList: "Non è stato possibile salvare questa lista di parole.",
    couldNotDeleteThisPromptList: "Non è stato possibile eliminare questa lista.",
    yourLibrary: "La tua raccolta",
    reusablePromptLists: "Liste di parole riutilizzabili",
    newList: "Nuova lista",
    createAccountSaveReviseSharePrompt: "Crea un account per salvare, rivedere e condividere liste di parole. Le parole veloci di una stanza restano locali ed effimere.",
    yourPromptLists: "Le tue liste di parole",
    loading: "Caricamento…",
    noSavedListsYet: "Ancora nessuna lista salvata.",
    name: "Nome",
    description: "Descrizione",
    language: "Lingua",
    visibility: "Visibilità",
    private: "Privata",
    anyoneWithCode: "Chiunque abbia il codice",
    shareCode: "Codice di condivisione",
    couldNotCopyShareCode: "Non è stato possibile copiare il codice.",
    copy: "Copia",
    addPrompts: "Aggiungi parole",
    onePromptPerLineSeparateEntries: "Una parola per riga\noppure separa le voci con virgole",
    addList: "Aggiungi alla lista",
    noPromptsYetPasteSomeAbove: "Ancora nessuna parola. Incollane qualcuna qui sopra per iniziare.",
    thisList: "In questa lista",
    searchPrompts: "Cerca parole",
    nothingMatchesThatSearch: "Niente corrisponde a questa ricerca.",
    deleteList: "Elimina lista…",
    promptListSaved: "Lista di parole salvata.",
    deleteThisPromptListAnd: "Eliminare questa lista di parole e tutte le sue revisioni?",
    promptListDeleted: "Lista di parole eliminata.",
    backToLobby: "Torna alla lobby",
    promptsCountOfMaxListPrompts: (p: { promptsCount: number; MAX_LIST_PROMPTS: number }) =>
      `${p.promptsCount} parole su ${p.MAX_LIST_PROMPTS} in questa lista`,
    saving: "Salvataggio…",
    saveList: "Salva lista",
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "parola", other: "parole" }),
    visibleOfTotal: (p: { visible: number; total: number }) =>
      `${p.visible} su ${p.total}`,
  },

  notFoundPage: {
    nobodyDrewThisPage: "Questa pagina non l’ha disegnata nessuno",
    thatLinkDoesnTLeadAnywhere: "Questo link non porta da nessuna parte su Sketchy.",
    backLobby: "Torna alla lobby",
  },

  onlinePlayersPanel: {
    couldNotJoinThatGame: "Non è stato possibile entrare in questa partita.",
    whoOnline: "Chi è online",
    nobodyElseHereRightNow: "Al momento non c’è nessun altro qui.",
    friend: "Amico",
    join: "Entra",
    inAGame: "In partita",
    inTheLobby: "Nella lobby",
  },

  pictureCropDialog: {
    fileNotAPicture: "Non è stato possibile leggere questo file come immagine.",
    couldNotSetThatPicturePlease: "Non è stato possibile impostare questa immagine. Riprova.",
    frameYourPicture: "Inquadra la tua immagine",
    dragMoveZoomGetCloserCircle: "Trascina per spostarla e usa lo zoom per avvicinarti. Il cerchio è ciò che vedono tutti.",
    pictureFramedArrowKeysMovePlus: "L’immagine, inquadrata. Le frecce la spostano; più e meno fanno zoom.",
    zoom: "Zoom",
    cancel: "Annulla",
    uploading: "Caricamento…",
    usePicture: "Usa immagine",
  },

  playerList: {
    requestCouldNotBeSent: "Non è stato possibile inviare questa richiesta.",
    nowFriends: (p: { name: string }) => `Tu e ${p.name} ora siete amici.`,
    friendRequestSent: (p: { name: string }) => `Richiesta di amicizia inviata a ${p.name}.`,
    nothingToDoAbout: (p: { name: string }) => `Con ${p.name} non c’è niente da fare adesso.`,
    rank: (p: { rank: number }) => `Posizione ${p.rank}`,
    moderationFor: (p: { name: string }) => `Moderazione per ${p.name}`,
    moderationActionsFor: (p: { name: string }) => `Azioni di moderazione per ${p.name}`,
    thatRequestCouldNotBeSent: "Non è stato possibile inviare questa richiesta.",
    drawing: "Disegna",
    gotIt: "Indovinato ·",
    afk: "Assente",
    you: "(tu)",
    host: "Host",
    friend: "Amico",
    disconnected: "Disconnesso",
    kick: "Espelli",
    addFriend: "Aggiungi amico",
    sendRequest: "Invia una richiesta",
    report: "Segnala",
    toAModerator: "A un moderatore",
    voteAfkOrKickOr: "Vota assente o espulsione, oppure segnala",
    reportThisPlayer: "Segnala questo giocatore",
    undoVote: "Annulla voto",
    vote: "Vota",
    voteKindAfk: "Assente",
    voteKindKick: "Espulsione",
    undoVoteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Annulla il voto ${p.kind} per ${p.nickname}, ${p.count} su ${p.required}`,
    voteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Vota ${p.kind} per ${p.nickname}, ${p.count} su ${p.required}`,
    votesFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Voti ${p.kind} per ${p.nickname}, ${p.count} su ${p.required}`,
    votesForIncludingYours: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Voti ${p.kind} per ${p.nickname}, ${p.count} su ${p.required}, compreso il tuo`,
    guestName: (p: { nickname: string }) =>
      `${p.nickname} (ospite)`,
  },

  profilePage: {
    gamesPlayed: "Partite giocate",
    gamesWon: "Partite vinte",
    winRate: "Percentuale di vittorie",
    averageScore: "Punteggio medio",
    turnsPlayed: "Turni giocati",
    promptsGuessed: "Parole indovinate",
    drawingsMade: "Disegni fatti",
    reactionsReceived: "Reazioni ricevute",
    totalScore: "Punteggio totale",
    noSuchProfile: "Non c’è nessun giocatore con questo profilo.",
    couldNotLoadProfile: "Non è stato possibile caricare questo profilo. Riprova.",
    gameMeta: (p: { finishedAt: string; rounds: number; players: number }) =>
      `${p.finishedAt} · ${counted(p.rounds, { one: "round", other: "round" })} · ${counted(p.players, { one: "giocatore", other: "giocatori" })}`,
    seatScore: (p: { points: number }) => `${number(p.points)} pt`,
    gameRules: (p: {
      scoringMode: string;
      scoringVersion: number;
      hintMode: string;
      seconds: number;
      promptSource: string;
    }) =>
      `Regole: punteggio ${p.scoringMode}${
        p.scoringVersion > 0 ? ` v${p.scoringVersion}` : " (versione vecchia ignota)"
      } · indizi ${p.hintMode} · ${p.seconds} secondi · parole ${p.promptSource}`,
    reportPlayer: (p: { name: string }) => `Segnala ${p.name}`,
    privateRoom: "stanza privata",
    thisGameDidNotFinishSo: "Questa partita non è finita, quindi questi sono i punteggi com’erano\n              quando si è fermata e non una classifica finale.",
    loadingTurns: "Caricamento dei turni…",
    turnByTurn: "Turno per turno",
    round: "Round",
    prompt: "Parola",
    drawnBy: "Disegnato da",
    time: "Tempo",
    drawing: "Disegna",
    reactions: "Reazioni",
    guesserOutcomes: "Esiti di chi indovinava",
    view: "Guarda",
    couldNotLoadMoreGames: "Non è stato possibile caricare altre partite.",
    loading: "Caricamento…",
    friend: "Amico.",
    claimYourAccount: "Reclama il tuo account",
    yourGamesAreAlreadyBeingRecorded: "Le tue partite sono già registrate con questo nome visualizzato.\n                Crea un account per tenerle e usarlo come nome utente su ogni dispositivo.",
    createAccount: "Crea account",
    statistics: "Statistiche",
    gameHistory: "Cronologia delle partite",
    includeGamesThatFellApart: "Includi le partite andate a monte",
    notKept: "non conservato",
    nothingDrawn: "niente disegnato",
    onlyThePlayersInThis: "Solo i giocatori di questa partita possono vederne i turni.",
    couldNotLoadTheTurns: "Impossibile caricare i turni di questa partita.",
    cutShort: "interrotta",
    noAttempt: "nessun tentativo",
    joinedLate: "entrato tardi",
    notEligibleEligibilityReason: (p: { eligibilityReason: string }) =>
      `non conteggiato (${p.eligibilityReason})`,
    unknownPlayer: "Giocatore sconosciuto",
    backToLobby: "Torna alla lobby",
    guestDisplayNameNotSaved: "Ospite — nome visualizzato non salvato",
    registeredPlayer: "Giocatore registrato",
    noFinishedGamesYetPlay: "Ancora nessuna partita conclusa. Giocane una e comparirà qui.",
    noGamesToShowGames: "Nessuna partita da mostrare. Le partite delle stanze private sono visibili solo a chi c’era.",
    loadHistoryPageSizeMore: (p: { HISTORY_PAGE_SIZE: number }) =>
      `Carica altre ${p.HISTORY_PAGE_SIZE}`,
    correctWithPoints: (p: { points: number }) =>
      `indovinato, ${p.points}`,
    wrongCount: (p: { count: number }) =>
      counted(p.count, { one: "errore", other: "errori" }),
    joinedOn: (p: { date: string }) =>
      `iscritto il ${p.date}`,
  },

  promptContentReportDialog: {
    reportList: (p: { name: string }) => `Segnala ${p.name}`,
    couldNotSendReport: "Non è stato possibile inviare la segnalazione.",
    reportsAreReviewedAfterSubmissionList: "Le segnalazioni vengono esaminate dopo l’invio. La lista resta disponibile a meno che un moderatore non la nasconda.",
    content: "Contenuto",
    entireList: "Tutta la lista",
    reason: "Motivo",
    whatShouldModeratorKnow: "Cosa dovrebbe sapere il moderatore?",
    cancel: "Annulla",
    inappropriateContent: "Contenuto inappropriato",
    hatefulOrAbusiveContent: "Contenuto d’odio o offensivo",
    sexualContent: "Contenuto sessuale",
    violence: "Violenza",
    spam: "Spam",
    other: "Altro",
    sending: "Invio…",
    sendReport: "Invia segnalazione",
  },

  promptDisplay: {
    couldNotDoAction: (p: { action: string }) => `Non è stato possibile ${p.action}.`,
    nextHintCost: (p: { cost: number }) => `Prossimo indizio: ${p.cost}`,
    hintSpendTotal: (p: { spent: number }) => `Totale: ${p.spent}`,
    buyLetter: (p: { letter: string; price: number }) =>
      `Compra «${p.letter}» per ${counted(p.price, { one: "punto", other: "punti" })}`,
    maskedPrompt: (p: { shape: string }) => `Parola nascosta, ${p.shape} lettere`,
    buyThisLetter: (p: { cost: number }) =>
      `Compra questa lettera per ${counted(p.cost, { one: "punto", other: "punti" })}`,
    letterCount: (p: { count: number }) =>
      counted(p.count, { one: "lettera", other: "lettere" }),
    yourTurn: "Tocca a te",
    pickSomethingDraw: "Scegli qualcosa da disegnare",
    autoPicksWhenTimeRunsOut: "Sceglie da sola allo scadere del tempo.",
    hintSpendLimitReached: "Limite di spesa in indizi raggiunto",
    deductedFromYourScoreIfYou: "Viene tolto dal tuo punteggio se indovini la parola",
    buyLetterRevealsEveryMatch: "Compra una lettera: rivela tutte le sue occorrenze",
    selectThePrompt: "scegliere la parola",
    choosing: "Scelta…",
    buyTheHint: "comprare l’indizio",
    buyTheLetterHint: "comprare l’indizio di lettera",
  },

  promptListPicker: {
    languageMismatch: (p: { listLanguage: string; roomLanguage: string }) =>
      `Questa lista è in ${p.listLanguage}; questa stanza è in ${p.roomLanguage}.`,
    choicesUnavailable: (p: { reason: string }) =>
      `La scelta delle liste di parole non è disponibile (${p.reason}). La tua selezione resta invariata.`,
    noListsInLanguage: (p: { language: string }) =>
      `Ancora nessuna lista in ${p.language} — questa stanza usa le sue parole personalizzate.`,
    howListPlays: (p: { name: string }) => `Come si giocano le parole di ${p.name}`,
    reportList: (p: { name: string }) => `Segnala ${p.name}`,
    failedLoadPromptLists: "Impossibile caricare le liste di parole",
    couldNotAddThatSharedList: "Non è stato possibile aggiungere questa lista condivisa.",
    loadingCuratedPromptLists: "Caricamento delle liste di parole…",
    promptLists: "Liste di parole",
    addUnlistedListByCode: "Aggiungi una lista non elencata con un codice",
    namePromptCountPrompts: (p: { name: string; promptCount: number }) =>
      `${p.name} (${p.promptCount} parole)`,
    adding: "Aggiunta…",
    add: "Aggiungi",
    reportSentForModeratorReview: "Segnalazione inviata ai moderatori.",
  },

  promptStatsPage: {
    noSuchList: "Non c’è nessuna lista di parole con questo nome.",
    couldNotLoadStats: "Non è stato possibile caricare queste statistiche. Riprova.",
    showMore: (p: { count: number }) => `Mostra altri ${p.count}`,
    showingOf: (p: { shown: number; total: number }) => `Mostrati ${p.shown} su ${p.total}`,
    couldNotLoadPromptListsPlease: "Non è stato possibile caricare le liste di parole. Riprova.",
    serverWide: "Su tutto il server",
    promptStats: "Statistiche parole",
    everyPromptListHowHasActually: "Ogni parola della lista, e come è andata davvero nelle partite concluse\n          su questo server.",
    promptList: "Lista di parole",
    sort: "Ordine",
    period: "Periodo",
    scoring: "Punteggio",
    hints: "Indizi",
    findPrompt: "Trova una parola",
    rollerCoaster: "montagne russe",
    loading: "Caricamento…",
    prompt: "Parola",
    howGoes: "Come va",
    guessed: "Indovinata",
    picked: "Scelta",
    drawn: "Disegnata",
    allTime: "Da sempre",
    last30Days: "Ultimi 30 giorni",
    last90Days: "Ultimi 90 giorni",
    allScoringModes: "Tutte le modalità di punteggio",
    noScoring: "Senza punteggio",
    defaultScoring: "Punteggio standard",
    pressureScoring: "Punteggio a pressione",
    allHintModes: "Tutte le modalità di indizi",
    noHints: "Senza indizi",
    checkpointHints: "Indizi a tempo",
    purchasedHints: "Indizi acquistati",
    letterWheel: "Ruota delle lettere",
    backToLobby: "Torna alla lobby",
  },

  publicRoomCard: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "round", other: "round" }),
    promptLanguage: (p: { language: string }) => `Lingua delle parole: ${p.language}`,
    seeWhoThisRoom: "Guarda chi è in questa stanza",
    rounds: "Round",
    drawingTime: "Tempo di disegno",
    full: "Piena",
    inProgress: "In corso",
    looking: "Ricerca…",
    nobodySeatedYet: "Non si è ancora seduto nessuno.",
    host: "Host",
    couldNotReadWhoIs: "Impossibile sapere chi c’è in questa stanza.",
    joining: "Ingresso…",
    join: "Entra",
    spectate: "Guarda",
  },

  reactionRequests: {
    thatReactionCouldNotBeSent: "Non è stato possibile inviare questa reazione.",
  },

  recapDrawings: {
    thisDrawingCouldNotBeLoaded: "Non è stato possibile caricare questo disegno.",
  },

  reportAccountDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Un moderatore lo vedrà. A ${p.name} non succede niente adesso, e non gli viene detto chi l’ha segnalato.`,
    theirPicture: (p: { name: string }) => `immagine di ${p.name}`,
    thatReportCouldNotBeSent: "Non è stato possibile inviare questa segnalazione. Riprova.",
    whatWrongWith: "Cosa c’è che non va",
    reportedTheirNameTheyHaveNo: "Segnalato per il nome. Non ha un’immagine da segnalare.",
    anythingElseOptional: "Altro (facoltativo)",
    anythingModeratorShouldKnow: "Tutto ciò che un moderatore dovrebbe sapere",
    sentWithWhatAboutAttached: "Inviata, con allegato ciò a cui si riferisce.",
    done: "Fatto",
    inappropriateName: "Nome inappropriato",
    inappropriatePicture: "Immagine inappropriata",
    reportSent: "Segnalazione inviata",
    reportDisplayName: (p: { displayName: string }) =>
      `Segnala ${p.displayName}`,
    thePictureOnTheAccount: "L’immagine dell’account viene allegata così com’è ora.",
    theNameOnTheAccount: "Il nome dell’account viene allegato così com’è ora.",
    sending: "Invio…",
    sendReport: "Invia segnalazione",
    close: "Chiudi",
    cancel: "Annulla",
  },

  reportedDrawing: {
    thisDrawingCouldNotBeDecoded: "Non è stato possibile decodificare questo disegno.",
    drawingCouldNotBeLoaded: "Non è stato possibile caricare il disegno.",
    loadingTheDrawing: "Caricamento del disegno…",
  },

  reportLobbyLineDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Un moderatore vedrà questa riga. A ${p.name} non succede niente adesso, e non gli viene detto chi l’ha segnalato.`,
    thatReportCouldNotBeSent: "Non è stato possibile inviare questa segnalazione. Riprova.",
    whatWrongWith: "Cosa c’è che non va",
    anythingElseOptional: "Altro (facoltativo)",
    anythingModeratorShouldKnow: "Tutto ciò che un moderatore dovrebbe sapere",
    thisLineAttachedWithWhatLobby: "Questa riga è allegata, insieme a ciò che la lobby ha detto intorno.",
    sentWithLineWhatWasSaid: "Inviata, con allegata la riga e ciò che si è detto intorno.",
    done: "Fatto",
    harassmentOrAbuse: "Molestie o insulti",
    spam: "Spam",
    inappropriateName: "Nome inappropriato",
    reportSent: "Segnalazione inviata",
    reportDisplayName: (p: { displayName: string }) =>
      `Segnala ${p.displayName}`,
    sending: "Invio…",
    sendReport: "Invia segnalazione",
    close: "Chiudi",
    cancel: "Annulla",
  },

  reportPlayerDialog: {
    reportCouldNotBeSent: "Non è stato possibile inviare questa segnalazione.",
    recentMessages: (p: { count: number }) =>
      `${p.count} dei suoi ${plural(p.count, { one: "messaggio recente", other: "messaggi recenti" })}`,
    nothingHappensYet: (p: { name: string }) =>
      `Un moderatore lo vedrà. A ${p.name} non succede niente adesso, e non gli viene detto chi l’ha segnalato.`,
    whatHappened: "Cosa è successo",
    anythingElseOptional: "Altro (facoltativo)",
    whatTheySaidDrewWhen: "Cosa ha detto o disegnato, e quando",
    theirRecentMessagesThisRoomAre: "I suoi messaggi recenti in questa stanza vengono allegati in automatico,\n                insieme a ciò che si è detto intorno, quindi questo può restare vuoto.",
    includeTheirDrawing: "Includi il suo disegno",
    canvasAsRightNowSoModerator: "La tela com’è adesso, così un moderatore vede quello che\n                      hai visto tu.",
    done: "Fatto",
    sentWithTheirDrawingAnd: (p: { messages: string }) =>
      `Inviata, con il suo disegno e ${p.messages} allegati.`,
    sentWithTheirDrawingAttached: "Inviata, con il suo disegno allegato.",
    sentWithMessagesAttached: (p: { messages: string }) =>
      `Inviata, con ${p.messages} allegati.`,
    sentTheyHadSaidNothing: "Inviata. Non aveva scritto nulla in questa stanza, quindi non ci sono messaggi allegati.",
    baseTheTurnHadEnded: (p: { base: string }) =>
      `${p.base} Il turno era finito, quindi non è stato possibile allegare il disegno.`,
    harassmentOrAbuse: "Molestie o insulti",
    offensiveDrawing: "Disegno offensivo",
    inappropriateName: "Nome inappropriato",
    cheating: "Imbrogli",
    spam: "Spam",
    inappropriatePicture: "Immagine inappropriata",
    sendThatReport: "inviare la segnalazione",
    reportNickname: (p: { nickname: string }) =>
      `Segnala ${p.nickname}`,
    reportSent: "Segnalazione inviata",
    sending: "Invio…",
    sendReport: "Invia segnalazione",
    cancel: "Annulla",
    close: "Chiudi",
  },

  reportsReviewedNotice: {
    reportsReviewed: (p: { count: number }) =>
      `${counted(p.count, { one: "segnalazione che hai inviato è stata esaminata", other: "segnalazioni che hai inviato sono state esaminate" })}. Grazie.`,
  },

  restartVoteBanner: {
    voteTally: (p: { yes: number; no: number; pending: number }) =>
      `${p.yes} a favore, ${p.no} contrari, ${p.pending} in attesa`,
    restartingIn: (p: { seconds: number }) =>
      `Riavvio tra ${counted(p.seconds, { one: "secondo", other: "secondi" })}`,
    restartApproved: "Riavvio approvato!",
    seconds: "secondi",
    voteRestartGame: "Vota per riavviare la partita",
    restart: "Riavvia",
    keepPlaying: "Continua a giocare",
    onlyEligiblePlayersPresentWhenVote: "Possono votare solo i giocatori idonei presenti quando è iniziata la votazione.",
    proposerNicknameProposedRestartingRemainingS: (p: { proposerNickname: string; remaining: number }) =>
      `${p.proposerNickname} propone di ricominciare · ${p.remaining} s`,
    theCurrentGameIsRestarting: "La partita sta ricominciando ora.",
    yesYesNoNoPending: (p: { yes: number; no: number; pending: number; requiredVotes: number }) =>
      `${p.yes} sì · ${p.no} no · ${p.pending} in attesa · ${p.requiredVotes} necessari`,
  },

  roleChangeNotice: {
    youHaveBeenSignedOutEvery: "Sei stato disconnesso da ogni dispositivo perché la modifica abbia\n            effetto. Accedi di nuovo per continuare.",
    setUpNow: "Attivalo adesso",
    later: "Più tardi",
    oneMoment: "Un momento…",
    signInAgain: "Accedi di nuovo",
    understood: "Capito",
  },

  roomChatPanel: {
    unreadMessages: (p: { count: number }) =>
      `${counted(p.count, { one: "nuovo messaggio", other: "nuovi messaggi" })}`,
    correctWithPlace: (p: { place: string | null }) =>
      p.place ? `Giusto · ${p.place}` : "Giusto",
    couldNotSendMessage: "Non è stato possibile inviare il messaggio",
    sent: "Inviato:",
    send: "Invia",
    youReDrawingWatchGuessesCome: "Stai disegnando: guarda arrivare i tentativi.",
    yourGuessTrimmedDidNot: (p: { trimmed: string }) =>
      `La tua risposta «${p.trimmed}» non è arrivata al server. Inviala di nuovo.`,
    sendTheMessage: "inviare il messaggio",
    chatWhileYouWait: "Chatta mentre aspetti",
    gameChat: "Chat della partita",
    guessAndChat: "Indovina e chatta",
    guessesAndChat: "Risposte e chat",
    roomChat: "Chat della stanza",
    sayHelloBeforeTheGame: "Saluta prima che inizi la partita.",
    noMessagesYet: "Ancora nessun messaggio.",
    typeYourGuess: "Scrivi la tua risposta...",
    typeAMessage: "Scrivi un messaggio...",
  },

  roomEntryState: {
    thisRoomNoLongerAvailable: "Questa stanza non è più disponibile",
    couldNotJoinThisRoom: "Non è stato possibile entrare in questa stanza",
    thatNameIsReservedPlease: "Quel nome è riservato. Scegline un altro.",
    thisRoomHasEndedAsk: "Questa stanza è chiusa. Chiedi all’host un nuovo invito.",
    loadThisRoom: "caricare questa stanza",
    enterANicknameToContinue: "Inserisci un soprannome per continuare.",
    thePlayerSlotsJustFilled: "I posti da giocatore si sono appena riempiti, ma puoi ancora guardare.",
    joinAsASpectator: "entrare come spettatore",
    joinThisRoom: "entrare in questa stanza",
    nicknameRule: "Usa da 3 a 16 caratteri: lettere, numeri, trattini o trattini bassi. Niente spazi.",
  },

  roomMenuSheet: {
    startTheGameOver: "Ricomincia la partita",
    startOverCooldown: (p: { seconds: number }) => ` · tra ${p.seconds}s`,
    room: "Stanza",
    playersScores: "Giocatori e punteggi",
    copyInviteLink: "Copia il link d’invito",
    saveThisDrawing: "Salva questo disegno",
    settings: "Impostazioni",
    leaveRoom: "Esci dalla stanza",
    iMBack: "Sono tornato",
    goAwayForABit: "Assentati un attimo",
  },

  roomPlayersPanel: {
    spectatorCount: (p: { count: number }) =>
      counted(p.count, { one: "spettatore", other: "spettatori" }),
    spectatorsHeading: (p: { count: number }) => `Spettatori (${p.count})`,
    playersOfCapacity: (p: { here: number; capacity: number }) =>
      `${p.here} giocatori su ${p.capacity}`,
    readyCount: (p: { count: number }) => `${p.count} pronti`,
    couldNotJoinAsPlayer: "Non è stato possibile entrare come giocatore",
    finalStandings: "Classifica finale",
    players: "Giocatori",
    joinAsAPlayer: "entrare come giocatore",
    aPlayerSlotIsAvailable: "C’è un posto da giocatore libero.",
    playerSlotsAreCurrentlyFull: "I posti da giocatore sono tutti occupati.",
    joining: "Ingresso…",
    joinAsPlayer: "Entra come giocatore",
  },

  roomSettingsEditor: {
    couldNotLoadRoomRules: "Non è stato possibile caricare le regole della stanza",
    roomRefusedThoseSettings: "La stanza ha rifiutato queste impostazioni.",
    hostSettings: "Impostazioni dell’host",
    editRoomRules: "Modifica le regole della stanza",
    loadingSettings: "Caricamento delle impostazioni…",
    cancel: "Annulla",
    loadRoomRules: "caricare le regole della stanza",
    saveRoomRules: "salvare le regole della stanza",
    saving: "Salvataggio…",
    saveSettings: "Salva impostazioni",
    saved: "Salvato",
  },

  roomSetupForm: {
    language: "Lingua",
    visibility: "Visibilità",
    maxPlayers: "Numero massimo di giocatori",
    rounds: "Round",
    drawingTime: "Tempo di disegno",
    onlyUseCustomPrompts: "Usa solo parole personalizzate",
    addUsableCustomPromptEnableThis: "Aggiungi una parola personalizzata utilizzabile per attivare questa opzione.",
    allowedTools: "Strumenti consentiti",
    colors: "Colori",
    scoring: "Punteggio",
    hints: "Indizi",
    spectatorsCanSeePrompt: "Gli spettatori vedono la parola",
    hideBlanks: "Nascondi gli spazi",
    alsoTurnsHintsOffWithNo: "Spegne anche gli indizi: senza spazi non c’è niente da rivelare.",
    promptTotal: (p: { count: number }) =>
      counted(p.count, { one: "parola", other: "parole" }),
    basics: "Base",
    roomName: "Nome della stanza",
    public: "Pubblica",
    private: "Privata",
    prompts: "Parole",
    drawing: "Disegna",
    scoringHints: "Punteggio e indizi",
    hintsAreOffBecauseBlanksAre: "Gli indizi sono spenti perché gli spazi sono nascosti.",
    pointPurchaseHintModesRequireScoring: "Le modalità di indizio a pagamento richiedono il punteggio.",
    allColors: "Tutti i colori",
    noScoring: "Senza punteggio",
    listedInTheLobbyAnyone: "Elencata nella lobby: chiunque può entrare.",
    joinableOnlyWithTheCode: "Accessibile solo con il codice o il link d’invito.",
    customCount: (p: { count: number }) =>
      counted(p.count, { one: "personalizzata", other: "personalizzate" }),
  },

  rulesPage: {
    sketchy: "Sketchy",
    theRules: "Le regole",
    thisPage: "In questa pagina",
    forExample: "Per esempio",
    backToLobby: "Torna alla lobby",
  },

  sessionManagerDialog: {
    lastUsed: (p: { when: string }) => `Usato l’ultima volta ${p.when}`,
    signsOutOn: (p: { when: string }) => `Si disconnette da solo ${p.when}`,
    usedElsewhere: (p: { when: string }) =>
      `Usato da un altro browser il ${p.when}. Revoca questo dispositivo se non eri tu.`,
    couldNotLoadSignedDevices: "Non è stato possibile caricare i dispositivi connessi.",
    couldNotRevokeDevice: "Non è stato possibile revocare il dispositivo.",
    couldNotLogOutEverywhere: "Non è stato possibile disconnettersi ovunque.",
    signedDevices: "Dispositivi connessi",
    revokeAnyDeviceYouNoLonger: "Revoca ogni dispositivo che non riconosci più. I nomi dei dispositivi sono approssimativi e non conservano le versioni del browser.\n          Un dispositivo che smetti di usare si disconnette da solo dopo novanta giorni.",
    loadingDevices: "Caricamento dei dispositivi…",
    currentDevice: "Dispositivo attuale",
    close: "Chiudi",
    revoking: "Revoca…",
    revoke: "Revoca",
    loggingOut: "Uscita…",
    logOutEverywhere: "Esci ovunque",
  },

  settingsOverlay: {
    email: "Email",
    password: "Password",
    twoFactorAuthentication: "Autenticazione a due fattori",
    signedDevices: "Dispositivi connessi",
    downloadEverything: "Scarica tutto",
    colorScheme: "Schema di colori",
    appliesMomentYouPick: "Vale dal momento in cui lo scegli.",
    languageYouPlay: "Lingua in cui giochi",
    roomsThisLanguageComeFirstLobby: "Le stanze in questa lingua vengono prima nella lobby, e una stanza che crei parte in questa lingua. È separata dalla lingua in cui leggi Sketchy.",
    interfaceLanguage: "Lingua in cui leggi",
    interfaceLanguageHint: "Ogni parola di Sketchy stesso. Separata dalla lingua in cui giochi: leggere in una e giocare in un’altra è del tutto normale.",
    timeFormat: "Formato dell’ora",
    howEveryClockReadsChatTimestamps: "Come si legge ogni orologio: orari della chat, date di accesso, avvisi. «Sistema» segue il tuo dispositivo.",
    iHaveTroubleTellingColorsApart: "Faccio fatica a distinguere i colori",
    nudgesHostsTowardRoomColorsThat: "Spinge gli host verso colori della stanza che restano distinguibili con deuteranopia e protanopia, senza dire chi l’ha chiesto. Da solo non cambia niente.",
    brushCursor: "Cursore del pennello",
    crosshairPreciseAtPointOutlineShows: "Un mirino è preciso sul punto; un contorno mostra quanto sarà largo il tratto.",
    brushCursorStyle: "Stile del cursore del pennello",
    soundEffects: "Effetti sonori",
    chimesCorrectGuessStartRoundLast: "Suoni per una risposta giusta, l’inizio di un round, gli ultimi dieci secondi e i giocatori che entrano ed escono.",
    volume2: "Volume",
    confetti: "Coriandoli",
    burstWhenYouGuessRightAgain: "Un getto quando indovini, e un altro per chi vince alla fine della partita.",
    clickKeyRebindEachActionCan: "Clicca un tasto per riassegnarlo. Ogni azione ne può tenere due. Premi Esc per annullare.",
    theseAreTheirSettings: (p: { name: string }) => `Ora queste sono le impostazioni di ${p.name}.`,
    guestLivesInThisBrowser: (p: { name: string }) =>
      `${p.name} vive solo in questo browser. Un account conserva il nome, i tuoi punti e la tua cronologia su ogni dispositivo, e ti lascia scegliere un colore.`,
    systemThemeNow: (p: { theme: "dark" | "light" }) => `Adesso: ${p.theme}`,
    needsAccount: "Serve un account",
    choosePicture: "Scegli un’immagine",
    editPicture: "Modifica l’immagine",
    picture: "Immagine",
    changePicture: "Cambia immagine",
    removePicture: "Rimuovi immagine",
    couldNotRemovePicture: "Non è stato possibile rimuovere l’immagine.",
    couldNotChangeYourDisplayName: "Non è stato possibile cambiare il tuo nome visualizzato.",
    couldNotChangeYourDisplayName2: "Non è stato possibile cambiare il tuo nome visualizzato. Riprova.",
    themeSoundShortcutsCameFromAccount: "Il tema, l’audio e le\n            scorciatoie arrivano dall’account. Quello che aveva questo browser resta\n            intatto e torna se esci.",
    dismiss: "Chiudi",
    playingAsGuest: "Stai giocando come ospite",
    createAccount: "Crea un account",
    logIn: "Accedi",
    you: "Tu",
    displayName: "Nome visualizzato",
    cancel: "Annulla",
    change: "Cambia",
    nameColor: "Colore del nome",
    signingIn: "Accesso",
    changePassword: "Cambia password",
    manage: "Gestisci",
    yourData: "I tuoi dati",
    requestExport: "Richiedi esportazione",
    delete: "Elimina…",
    display: "Schermo",
    theme: "Tema",
    accessibility: "Accessibilità",
    theCanvas: "La tela",
    sound: "Audio",
    volume: "Volume",
    effects: "Effetti",
    noKeyboardThisDevice: "Nessuna tastiera su questo dispositivo",
    yourBindingsAreStillSavedStill: "Le tue scorciatoie restano salvate e funzionano. Apri Sketchy con una tastiera\n            collegata per cambiarle.",
    drawingTools: "Strumenti di disegno",
    resetDefaults: "Ripristina i valori predefiniti",
    settings: "Impostazioni",
    close: "Chiudi",
    closeSettings: "Chiudi le impostazioni",
    settingsSections: "Sezioni delle impostazioni",
    account: "Account",
    appearance: "Aspetto",
    soundEffects2: "Suoni ed effetti",
    shortcuts: "Scorciatoie",
    red: "Rosso",
    orange: "Arancione",
    yellow: "Giallo",
    lime: "Lime",
    green: "Verde",
    teal: "Verde acqua",
    sky: "Celeste",
    blue: "Blu",
    indigo: "Indaco",
    purple: "Viola",
    magenta: "Magenta",
    pink: "Rosa",
    brown: "Marrone",
    light: "Chiaro",
    dark: "Scuro",
    system: "Sistema",
    crosshair: "Mirino",
    outline: "Contorno",
    space: "Spazio",
    hideTheFullAddress: "Nascondi l’indirizzo completo",
    showTheFullAddress: "Mostra l’indirizzo completo",
    hide: "Nascondi",
    showInFull: "Mostra per intero",
    verified: "Verificato",
    notVerified: "Non verificato",
    saving: "Salvataggio…",
    save: "Salva",
    aGuestHasNothingTo: "Un ospite non ha nulla da recuperare: non c’è una password da dimenticare.",
    withoutOneThereIsNo: "Senza, non c’è modo di rientrare in questo account se dimentichi la password.",
    addAnEmail: "Aggiungi un’email",
    guestsHaveNoPassword: "Gli ospiti non hanno password.",
    changingItSignsEveryOther: "Cambiarla disconnette tutti gli altri dispositivi.",
    setThisUpAndThe: (p: { pendingRole: string }) =>
      `Configurala e il ruolo di ${p.pendingRole} che ti è stato offerto diventerà effettivo.`,
    anAuthenticatorAppSCode: "Il codice di un’app di autenticazione, oltre alla password. Moderatori e amministratori devono averla.",
    setUp: "Configura",
    thisBrowserIsTheOnly: "Questo browser è l’unico posto in cui esisti.",
    everyBrowserStillHoldingA: "Ogni browser che ha ancora una sessione, e un modo per chiuderne una qualsiasi.",
    worksForAGuestToo: "Funziona anche per gli ospiti: le partite che hai giocato sono tue.",
    everyGameListAndSetting: "Ogni partita, lista e impostazione che Sketchy conserva su di te, in un unico file JSON.",
    deleteThisGuest: "Elimina questo ospite",
    deleteYourAccount: "Elimina il tuo account",
    removesTheNameThePoints: "Rimuove il nome, i punti e la cronologia legati a questo browser.",
    gamesYouPlayedStayIn: "Le partite che hai giocato restano nella cronologia degli altri, senza il tuo nome.",
    clickToRebindTheSecond: "Fai clic per riassegnare il secondo tasto",
    clickToRebind: "Fai clic per riassegnare",
    pressKey: "Premi un tasto…",
    key: "+ tasto",
    none: "Nessuno",
  },

  stepUpDialog: {
    codeFromYourAuthenticatorApp2: "Codice dalla tua app di autenticazione",
    passkeyNotUsed: "Questa passkey non è stata usata. Puoi riprovare.",
    thatCodeWasNotAccepted: "Questo codice non è stato accettato.",
    thatPasskeyWasNotAccepted: "Questa passkey non è stata accettata.",
    confirmYou: "Conferma che sei tu",
    recoveryCode: "Codice di recupero",
    codeFromYourAuthenticatorApp: "Codice dalla tua app di autenticazione",
    cancel: "Annulla",
    waitingForYourDevice: "In attesa del tuo dispositivo…",
    useYourPasskey: "Usa la tua passkey",
    useYourAuthenticatorApp: "Usa la tua app di autenticazione",
    useARecoveryCode: "Usa un codice di recupero",
    checking: "Verifica…",
    confirm: "Conferma",
  },

  suspensionNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Il tuo disegno di ${p.prompt}, com’è stato segnalato`,
    recordedAs: "Registrato come {category}",
    yourAccountSuspended: "Il tuo account è sospeso",
    youWereAskedDraw: "Toccava a te disegnare",
    theMessageThisWasAbout: "Il messaggio in questione:",
    theMessagesThisWasAbout: "I messaggi in questione:",
    theDrawingThisWasAbout: "Il disegno in questione:",
    theDrawingsThisWasAbout: "I disegni in questione:",
    signingOut: "Uscita…",
    signOut: "Esci",
  },

  toastProvider: {
    notifications: "Notifiche",
    dismissNotification: "Chiudi la notifica",
  },

  toolbar: {
    colorOption: (p: { color: string }) => `colore ${p.color}`,
    adjustSize: (p: { tool: string }) => `Regola la dimensione di ${p.tool}`,
    sizeSnappingSlider: (p: { tool: string }) => `Cursore di dimensione a scatti per ${p.tool}`,
    chooseToolCurrent: (p: { tool: string }) => `Scegli lo strumento, attuale: ${p.tool}`,
    chooseColorCurrent: (p: { color: string }) => `Scegli il colore, attuale ${p.color}`,
    sizeWithWidth: (p: { tool: string; width: number }) => `${p.tool}, dimensione ${p.width}px`,
    sizeShortcutHint: (p: { tool: string; width: number }) =>
      `${p.tool}, dimensione: ${p.width}px ([ / ])`,
    widthReadout: (p: { width: number }) => `${p.width}px`,
    colorSwatch: (p: { color: string }) => `Colore ${p.color}`,
    drawingTools: "Strumenti di disegno",
    chooseTool: "Scegli lo strumento",
    chooseColor: "Scegli il colore",
    undoLastStroke: "Annulla l’ultimo tratto",
    undo: "Annulla",
    clearCanvas: "Svuota la tela",
    chooseCustomColor: "Scegli un colore personalizzato",
    colorPalette: "Tavolozza dei colori",
    canvasActions: "Azioni sulla tela",
    undoLastStrokeCtrlZ: "Annulla l’ultimo tratto (Ctrl+Z)",
    clear: "Svuota",
    brush: "Pennello",
    fill: "Riempimento",
    eraser: "Gomma",
    rectangle: "Rettangolo",
    triangle: "Triangolo",
    ellipse: "Ellisse",
    fillIsUnavailableForThe: "Il riempimento non è disponibile per il resto del turno",
    drawingByHandIsUnavailable: "Il disegno a mano libera non è disponibile per il resto del turno",
  },

  turnResultsOverlay: {
    yourTurnWithHints: (p: { base: number; hintSpend: number; points: number; rank: number }) =>
      `Il tuo turno: +${p.base} -${p.hintSpend} indizi = ${counted(p.points, { one: "punto", other: "punti" })} · ora #${p.rank}`,
    yourTurn: (p: { delta: number; rank: number }) =>
      `Il tuo turno: ${p.delta >= 0 ? "+" : ""}${p.delta} ${
        Math.abs(p.delta) === 1 ? "punto" : "punti"
      } · ora #${p.rank}`,
    promptWas: "La parola era",
    noOneGuessedCorrectly: "Non ha indovinato nessuno.",
    you: "(tu)",
    drewThisTurn: "Ha disegnato in questo turno",
    nextTurn: "Turno successivo",
    turnResults: "Risultati del turno",
    turnComplete: "Turno concluso",
  },

  twoFactorDialog: {
    scanThisWithYourAuthenticatorApp: "Scansiona questo con la tua app di autenticazione per aggiungere questo account",
    codeFromYourAuthenticatorApp: "Codice dalla tua app di autenticazione",
    secondFactorState: (p: {
      recoveryCodesRemaining: number | null;
      confirmAuthenticator: boolean;
    }) =>
      [
        "L’autenticazione a due fattori è attiva.",
        p.recoveryCodesRemaining === null
          ? null
          : `Ti restano ${counted(p.recoveryCodesRemaining, {
              one: "codice di recupero",
              other: "codici di recupero",
            })}.`,
        p.confirmAuthenticator
          ? "Prima che questo account possa ricevere un ruolo di moderatore o amministratore, conferma con la tua password e un codice che l’autenticatore è tuo."
          : null,
        "Ognuna delle modifiche qui sotto sostituisce una credenziale, quindi ognuna chiede la tua password.",
      ]
        .filter(Boolean)
        .join(" "),
    confirmAuthenticatorFirst:
      "Prima che questo account possa ricevere un ruolo di moderatore o amministratore, conferma con la tua password e un codice che l’autenticatore è tuo.",
    copied: (p: { what: string }) => `${p.what} copiato.`,
    couldNotCopy: (p: { what: string }) =>
      `Non è stato possibile copiare ${p.what}. Selezionalo e copialo a mano.`,
    roleTaken: (p: { role: "admin" | "moderator" }) =>
      `Ora sei ${p.role === "admin" ? "amministratore" : "moderatore"}. L’autenticazione a due fattori è attiva, e il ruolo che la aspettava è entrato in vigore. Gli altri tuoi dispositivi sono stati disconnessi; questo prosegue, e ogni accesso da qui chiederà un codice.`,
    recoveryCodesLeft: (p: { count: number }) =>
      `Ti restano ${counted(p.count, { one: "codice di recupero", other: "codici di recupero" })}.`,
    couldNotReadYourSecuritySettings: "Non è stato possibile leggere le tue impostazioni di sicurezza.",
    yourPasswordConfirmsAuthenticatorYours: "La tua password conferma che l’autenticatore è tuo.",
    yourPasswordConfirmsThisPasskeyYours: "La tua password conferma che questa passkey è tua.",
    passkeyAdded: "Passkey aggiunta.",
    thatPasskeyWasNotCreatedYou: "Questa passkey non è stata creata. Puoi riprovare.",
    yourPasswordNeededRemovePasskey: "Per rimuovere una passkey serve la tua password.",
    confirmedThisAccountCanNowBe: "Confermato. Questo account ora può ricevere un ruolo dello staff.",
    twoFactorAuthentication: "Autenticazione a due fattori",
    saveTheseRecoveryCodesNow: "Salva subito questi codici di recupero.",
    eachOneSignsYouOnceIf: "Ognuno ti fa accedere una\n              volta se perdi la tua app di autenticazione. Non vengono mostrati\n              di nuovo — se ne conservano solo gli hash.",
    recoveryCodes: "Codici di recupero",
    downloadAsFile: "Scarica come file",
    copyAll: "Copia tutti",
    iHaveSavedTheseSomewhereSafe: "Li ho salvati in un posto sicuro",
    done: "Fatto",
    moderatorsAdministratorsSignWithPasskeyYour: "Moderatori e amministratori accedono con una passkey: il tuo\n              dispositivo conferma che sei tu — impronta, volto o PIN — e non\n              si digita niente che si possa consegnare a qualcuno.",
    yourPassword: "La tua password",
    confirmsPasskeyBeingAddedByYou: "Conferma che la passkey la stai aggiungendo tu.",
    useAuthenticatorAppInstead: "Usa invece un’app di autenticazione",
    scanCodeWithAuthenticatorAppThen: "Scansiona il codice con un’app di autenticazione, poi digita le sei\n              cifre che mostra.",
    drawingCode: "Disegno del codice…",
    pointYourAppAtThis: "Punta qui la tua app.",
    setupKey: "Chiave di configurazione",
    copySetupKey: "Copia la chiave di configurazione",
    useThisIfYouCanT: "Usa questa se non puoi scansionare.",
    confirmsAuthenticatorYours: "Conferma che l’autenticatore è tuo.",
    codeFromYourApp: "Codice dalla tua app",
    cancel: "Annulla",
    passkeys: "Passkey",
    thisDeviceOnly: "· solo su questo dispositivo",
    remove: "Rimuovi",
    confirmSYours: "Conferma che è tua",
    addPasskey: "Aggiungi una passkey",
    newRecoveryCodes: "Nuovi codici di recupero",
    turnOff: "Disattiva",
    addAuthenticatorApp: "Aggiungi un’app di autenticazione",
    close: "Chiudi",
    couldNotStartSettingThis: "Impossibile avviare la configurazione.",
    thatCodeWasNotAccepted: "Quel codice non è stato accettato.",
    couldNotAddThatPasskey: "Impossibile aggiungere quella passkey.",
    couldNotRemoveThatPasskey: "Impossibile rimuovere quella passkey.",
    couldNotConfirmIt: "Impossibile confermare.",
    couldNotReplaceYourRecovery: "Impossibile sostituire i tuoi codici di recupero.",
    couldNotTurnThisOff: "Impossibile disattivarla.",
    waitingForYourDevice: "In attesa del tuo dispositivo…",
    setUpAPasskey: "Configura una passkey",
    noPasskeyOnThisDevice: "Nessuna passkey su questo dispositivo? ",
    thisBrowserCannotMakeA: "Questo browser non può creare una passkey. ",
    checking: "Verifica…",
    confirm: "Conferma",
  },

  useFriendArrivalNotices: {
    wantsToBeFriends: (p: { name: string }) => `${p.name} vuole essere tuo amico.`,
    acceptedYourRequest: (p: { name: string }) => `${p.name} ha accettato la tua richiesta di amicizia.`,
    severalAccepted: (p: { count: number }) =>
      `${counted(p.count, { one: "persona ha accettato", other: "persone hanno accettato" })} le tue richieste di amicizia.`,
    accept: "Accetta",
    open: "Apri",
    manyArrived: (p: { name: string; others: number }) =>
      `${p.name} e ${counted(p.others, { one: "un’altra persona", other: "altre persone" })} vogliono diventare tuoi amici.`,
  },

  useRoomSessionReconnect: {
    joinRoomFailed: "join_room failed",
  },

  waitingRoomPanel: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "round", other: "round" }),
    needMorePlayers: (p: { count: number }) =>
      `${counted(p.count, { one: "Manca 1 giocatore", other: "Mancano altri giocatori" })}`,
    hostWillStart: (p: { rematch: boolean }): string =>
      p.rematch ? "{host} inizierà la rivincita" : "{host} inizierà la partita",
    copied: (p: { what: string }) => `${p.what} copiato.`,
    couldNotCopy: (p: { what: string }) =>
      `Non è stato possibile copiare ${p.what}. Copialo dalla barra degli indirizzi.`,
    roomCodeLabel: (p: { code: string }) => `Codice stanza ${p.code}`,
    rosterCount: (p: { here: number; capacity: number }) => `${p.here} su ${p.capacity}`,
    inviteYourFriends: "Invita i tuoi amici",
    shareLink: "Condividi il link",
    copyCode: "Copia il codice",
    inTheRoom: "Nella stanza",
    you: "(tu)",
    host: "Host",
    friend: "Amico",
    invite: "Invita",
    edit: "Modifica",
    viewHighlights: "Guarda i momenti migliori",
    viewDrawings: "Guarda i disegni",
    spectatorsAfkAndDisconnectedPlayers: "Spettatori, assenti e giocatori disconnessi non contano per i due giocatori attivi che servono a una partita.",
    joinMySketchyRoomCode: (p: { code: string }) =>
      `Entra nella mia stanza di Sketchy: ${p.code}`,
    inviteLink: "Link d’invito",
    customPromptsOnlyCustomPromptCount: (p: { customPromptCount: number }) =>
      `Solo parole personalizzate (${p.customPromptCount})`,
    customPromptCountCustomPromptsCuratedLists: (p: { customPromptCount: number }) =>
      `${p.customPromptCount} parole personalizzate + liste selezionate`,
    promptListSlugsCountCuratedPromptLists: (p: { promptListSlugsCount: number }) =>
      `${p.promptListSlugsCount} liste di parole selezionate`,
    noScoring: "Senza punteggio",
    spectatorsSeeThePrompt: "Gli spettatori vedono la parola",
    publicRoom: "Stanza pubblica",
    privateRoom: "Stanza privata",
    betweenGames: "tra una partita e l’altra",
    waitingForPlayers: "in attesa di giocatori",
    roomCode: "Codice stanza",
    starting: "Avvio…",
    rematch: "Rivincita",
    startGame: "Avvia partita",
    waitingForAHost: "In attesa di un host",
  },

  warningNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Il tuo disegno di ${p.prompt}, com’è stato segnalato`,
    recordedAs: "Registrato come {category}",
    whatAWarningMeans:
      "Una segnalazione sul tuo comportamento è stata esaminata, e questo è l’esito. Non c’è nessuna restrizione, ma un’altra segnalazione potrebbe portare alla sospensione del tuo account.",
    youWereAskedDraw: "Toccava a te disegnare",
    yourPictureWasRemoved: "La tua immagine è stata rimossa",
    aModeratorWarning: "Un avvertimento della moderazione",
    aReportAboutYourPicture: "Una segnalazione sulla tua immagine è stata esaminata, e questo è l’esito. Nient’altro nel tuo account è interessato.",
    theMessageThisWasAbout: "Il messaggio in questione:",
    theMessagesThisWasAbout: "I messaggi in questione:",
    theDrawingThisWasAbout: "Il disegno in questione:",
    theDrawingsThisWasAbout: "I disegni in questione:",
    oneMoment: "Un momento…",
    understood: "Capito",
  },
  connectionStatusBanner: {
    youReDisconnectedCheckYour: "Sei disconnesso. Controlla la connessione; Sketchy si riconnetterà da solo.",
    couldnTReconnectToYour: "Impossibile riconnettersi alla tua stanza. Ricarica la pagina per riprovare.",
    connectionLostReconnecting: "Connessione persa — riconnessione…",
  },
  accountData: {
    queued: "In coda",
    preparing: "Preparazione…",
    ready: "Pronto",
    tooLargeToPrepareHere: "Troppo grande per prepararlo qui",
    couldNotPrepare: "Impossibile preparare",
    yourDataIsLargerThan: "I tuoi dati superano ciò che questo server prepara in un unico documento. Chiedi al gestore di alzare il limite.",
    somethingWentWrongWhilePreparing: "Qualcosa è andato storto durante la preparazione. Puoi richiedere un’altra esportazione.",
  },
  recoveryCodeFile: {
    sketchyRecoveryCodes: "Codici di recupero di Sketchy",
    accountUsername: (p: { username: string }) =>
      `Account: ${p.username}`,
    createdValue: (p: { value: string }) =>
      `Creato: ${p.value}`,
    eachCodeSignsYouIn: "Ogni codice ti fa accedere una volta se perdi la tua app di autenticazione.",
    keepThisFile: "Conserva questo file dove solo tu puoi arrivare. Chiunque abbia questi codici\ne la tua password può accedere al posto tuo.",
  },
  avatars: {
    chooseAPngJpegWebP: "Scegli un’immagine PNG, JPEG, WebP o GIF.",
    thatPictureIsTooLarge: "Quell’immagine è troppo grande da leggere: al massimo 10 MB.",
    thatFileCouldNotBe: "Quel file non si è potuto leggere come immagine.",
    thatPictureIsTooSmall: "Quell’immagine è troppo piccola per ricavarne qualcosa.",
    thisBrowserCannotResizePictures: "Questo browser non può ridimensionare le immagini.",
    thatPictureIsTooDetailed: "Quell’immagine è troppo dettagliata. Provane una più semplice, o ingrandisci una sua parte.",
  },
  settingsSync: {
    thatChangeAppliesHereBut: "La modifica vale qui, ma non è stato possibile salvarla nel tuo account. Gli altri tuoi dispositivi non la vedranno.",
  },
  promptStats: {
    hardestFirst: "Prima le più difficili",
    easiestFirst: "Prima le più facili",
    mostPicked: "Le più scelte",
    getsGuessed: "Viene indovinata",
    usuallyGuessed: "Di solito indovinata",
    evenOdds: "Metà e metà",
    oftenMissed: "Spesso mancata",
    rarelyGuessed: "Indovinata di rado",
    notPlayedEnough: "Giocata troppo poco",
    allRanked: (p: { count: number }) =>
      `Tutte le ${p.count} parole sono state giocate abbastanza da essere classificate.`,
    noneRanked: (p: { unrated: number; guessers: number }) =>
      `Nessuna di queste ${p.unrated} parole ha ancora avuto ${p.guessers} giocatori a indovinarla, quindi nessuna è classificata. Fate qualche partita e qui comparirà la loro difficoltà.`,
    someRanked: (p: { rated: number; unrated: number; guessers: number }) =>
      `${p.rated} classificate. ${plural(p.unrated, { one: `Un’altra parola non è ancora classificata`, other: `Altre ${p.unrated} parole non sono ancora classificate` })}: meno di ${p.guessers} giocatori le hanno viste.`,
    noMatch: (p: { query: string }) =>
      `Nessuna parola corrisponde a «${p.query}».`,
    matching: (p: { count: number; query: string }) =>
      `${counted(p.count, { one: "parola corrisponde", other: "parole corrispondono" })} a «${p.query}».`,
  },
  gameHeaderStatus: {
    roundRoundNumberOfTotalRounds: (p: { roundNumber: number; totalRounds: number }) =>
      `Round ${p.roundNumber} di ${p.totalRounds}`,
  },
  gameRoomRegions: {
    theNextPlayer: "Il prossimo giocatore",
    drawingCanvasYouAreDrawing: "Area di disegno. Stai disegnando tu.",
    yourTurnToDraw: "Tocca a te disegnare.",
    canvasSpectating: (p: { drawer: string }) =>
      `Area di disegno. Stai guardando ${p.drawer}.`,
    canvasSomeoneDrawing: (p: { drawer: string }) =>
      `Area di disegno. ${p.drawer} sta disegnando.`,
    someoneIsDrawing: (p: { drawer: string }) =>
      `${p.drawer} sta disegnando.`,
    theDrawer: "chi disegna",
    aPlayer: "Qualcuno",
  },
  useToolbarState: {
    fillIsUnavailableForThe: "Il riempimento non è disponibile per il resto del turno.",
    drawingByHandIsUnavailable: "Il disegno a mano libera non è disponibile per il resto del turno. Le forme funzionano ancora.",
  },
  timer: {
    n10SecondsRemaining: "Mancano 10 secondi",
    timeIsUp: "Tempo scaduto",
  },
  chatAnnouncements: {
    nicknameGuessedThePrompt: (p: { nickname: string }) =>
      `${p.nickname} ha indovinato la parola.`,
  },
  canvasSnapshot: {
    drawingOfDownloadPrompt: (p: { downloadPrompt: string }) =>
      `Disegno di ${p.downloadPrompt}`,
    savedDrawing: "Disegno salvato",
  },
  roomSetup: {
    default: "Standard",
    fasterGuessesEarnMore100: "Chi indovina prima guadagna di più, da 100 a 300 punti.",
    pressure: "Pressione",
    pointsDecayEverySecondTwice: "I punti calano ogni secondo, il doppio più in fretta appena qualcuno indovina.",
    noScoring: "Senza punteggio",
    justDrawAndGuessNo: "Solo disegnare e indovinare. Nessuna classifica.",
    timedHints: "Indizi a tempo",
    lettersRevealToEveryoneAt: "Le lettere si rivelano a tutti a tempi fissi.",
    noHints: "Senza indizi",
    blanksOnlyAllTurnLong: "Solo spazi vuoti, per tutto il turno.",
    buyLetters: "Compra lettere",
    revealALetterSlotJust: "Rivela una lettera solo per te, pagata con i punti di quel turno.",
    wheelOfFortune: "Ruota della fortuna",
    pickALetterPayIts: "Scegli una lettera e pagane il prezzo: le vocali costano di più.",
    hiddenPrompt: "Parola nascosta",
    defaultScoring: "Punteggio standard",
    pressureScoring: "Punteggio a pressione",
  },
  screenCapture: {
    thisBrowserCouldNotEncode: "Questo browser non è riuscito a codificare lo screenshot.",
    theCaptureWasEmpty: "La cattura era vuota.",
    thisBrowserCouldNotRead: "Questo browser non è riuscito a leggere lo screenshot.",
    thatScreenshotIsTooLarge: "Quello screenshot è troppo grande da inviare.",
  },
  accountRecovery: {
    youCanRecoverThisAccount: (p: { address: string }) =>
      `Puoi recuperare questo account tramite ${p.address}.`,
    checkPendingAddressForAConfirmation: (p: { pendingAddress: string }) =>
      `Cerca in ${p.pendingAddress} un link di conferma. Finché non lo segui, questo account non ha modo di essere recuperato.`,
    thisServerCannotSendEmail: "Questo server non può inviare email, quindi una password persa deve essere reimpostata da chi lo gestisce.",
    addAnEmailAddressSo: "Aggiungi un indirizzo email per poter rientrare se dimentichi la password.",
  },
  friends: {
    aFriend: "Un amico",
  },
  lobbyPresence: {
    showingShownOfOnlineCount: (p: { shown: number; onlineCount: number }) =>
      `${p.shown} su ${p.onlineCount} mostrati`,
    onlineCount: (p: { count: number }) =>
      `${number(p.count)} online`,
  },
  authStore: {
    chooseANameToPlay: "Scegli un nome con cui giocare.",
  },
  passkeys: {
    noPasskeyWasCreated: "Non è stata creata nessuna passkey.",
    noPasskeyWasUsed: "Non è stata usata nessuna passkey.",
  },
  useGameSocketListeners: {
    nicknameJoinedTheRoom: (p: { nickname: string }) =>
      `${p.nickname} è entrato nella stanza`,
    gameStarted: "La partita è iniziata!",
    drawerNicknameIsChoosingAPrompt: (p: { drawerNickname: string }) =>
      `${p.drawerNickname} sta scegliendo una parola...`,
    thePromptWasPrompt: (p: { prompt: string }) =>
      `La parola era «${p.prompt}»`,
    gotIt: (p: { nickname: string; time: string | null; points: number | null }) =>
      `${p.nickname} ha indovinato${p.time === null ? "" : ` · ${p.time}`}${p.points === null ? "" : ` (+${p.points})`}`,
    playerReconnected: (p: { nickname: string }) =>
      `${p.nickname} si è riconnesso`,
    playerDisconnected: (p: { nickname: string }) =>
      `${p.nickname} si è disconnesso`,
  },
  settingsStore: {
    brushTool: "Pennello",
    fillTool: "Riempimento",
    eraserTool: "Gomma",
    rectangleTool: "Rettangolo",
    triangleTool: "Triangolo",
    ellipseTool: "Ellisse",
    decreaseBrushSize: "Pennello più piccolo",
    increaseBrushSize: "Pennello più grande",
    undoStroke: "Annulla tratto",
  },
  reactions: {
    loveIt: "Adoro",
    funny: "Divertente",
    wow: "Wow",
    fire: "Fuoco",
    reaction: "Reazione",
  },
  drawingRules: {
    brush: "Pennello",
    theBrushAndTheEraser: "Il pennello e la gomma.",
    fill: "Riempimento",
    theFillTool: "Lo strumento di riempimento.",
    shapes: "Forme",
    rectangleEllipseAndTriangle: "Rettangolo, ellisse e triangolo.",
    allColors: "Tutti i colori",
    thePaletteAndTheCustom: "La tavolozza e il selettore di colore libero.",
    paletteOnly: "Solo tavolozza",
    theBuiltInSwatchesNo: "I campioni predefiniti; niente colori liberi.",
    colorblindSafe: "Adatti al daltonismo",
    colorsThatStayApartFor: "Colori che restano distinguibili per chi è daltonico.",
    blackAndWhite: "Bianco e nero",
    blackAndWhiteOnly: "Solo bianco e nero.",
    allTools: "Tutti gli strumenti",
    onlyTool: (p: { tool: string }) =>
      `solo ${p.tool}`,
    toolList: (p: { rest: string; last: string }) =>
      `${p.rest} e ${p.last}`,
  },
  socket: {
    sketchyIsFullRightNow: "Sketchy è pieno in questo momento. Riprova tra qualche minuto.",
    connectionLostWhileTryingTo: (p: { action: string }) =>
      `Connessione persa mentre si tentava di ${p.action}. Riprova.`,
    theRequestToActionTimed: (p: { action: string }) =>
      `La richiesta di ${p.action} è scaduta. Riprova.`,
    couldNotActionPleaseTry: (p: { action: string }) =>
      `Impossibile ${p.action}. Riprova.`,
  },
  bugReports: {
    drawingAndCanvas: "Disegno e area di disegno",
    guessingAndChat: "Risposte e chat",
    roundsScoringAndResults: "Round, punteggio e risultati",
    roomsAndLobby: "Stanze e lobby",
    promptLists: "Liste di parole",
    accountAndSettings: "Account e impostazioni",
    connectionAndSync: "Connessione e sincronizzazione",
    performance: "Prestazioni",
    accessibility: "Accessibilità",
    somethingElse: "Altro",
    blocksPlayICouldNot: "Blocca il gioco — non potevo continuare",
    majorHardToPlayAround: "Grave — difficile da aggirare",
    minorWorthFixingOneDay: "Lieve — da sistemare prima o poi",
    notInARoom: "Non in una stanza",
    codeNotInARound: (p: { code: string }) =>
      `${p.code} · fuori dal round`,
    codeRoundRoundOfTotal: (p: { code: string; round: number; total: number }) =>
      `${p.code} · round ${p.round} di ${p.total}`,
  },
  suspension: {
    thisSuspensionHasNoEnd: "Questa sospensione non ha una data di fine.",
    thisSuspensionHasEndedTry: "Questa sospensione è terminata; prova ad accedere di nuovo.",
    thisSuspensionLastsUntilEnds: (p: { ends: string }) =>
      `Questa sospensione dura fino al ${p.ends}.`,
  },
  clock: {
    unknown: "Sconosciuto",
  },
  protocol: {
    theServerWasUpdated: "Il server è stato aggiornato.",
  },
  passwordPolicy: {
    tooShort: (p: { count: number }) =>
      `Una password deve avere almeno ${p.count} caratteri.`,
  },
  operatorAccess: {
    administrator: "amministratore",
    moderator: "moderatore",
    pendingTitle: "Il ruolo di moderatore ti aspetta",
    pendingBody: "Un amministratore ti ha offerto il ruolo di moderatore. Diventa effettivo quando configuri l’autenticazione a due fattori: i moderatori accedono con il codice di un’app di autenticazione, e il ruolo parte non appena è attiva. Gli altri tuoi dispositivi verranno disconnessi in quel momento. Non cambia nulla finché non la configuri, e l’offerta ti aspetta nelle Impostazioni se ora non è il momento.",
    grantedTitle: "Ora sei moderatore",
    grantedBody: "Un amministratore ti ha dato il ruolo di moderatore. Nel menu del tuo account è comparsa la voce Moderazione: lì si esaminano le segnalazioni su giocatori e parole. Il tuo modo di giocare non cambia.",
    removedTitle: "Non sei più moderatore",
    removedBody: "Un amministratore ha rimosso il ruolo di moderatore dal tuo account. La voce Moderazione è sparita dal tuo menu. Nient’altro del tuo account o delle tue partite è interessato.",
  },
  moderationCategories: {
    harassment: "molestie",
    offensive_drawing: "un disegno offensivo",
    inappropriate_name: "un nome inappropriato",
    cheating: "imbrogli",
    spam: "spam",
    inappropriate_avatar: "un’immagine inappropriata",
  },
  roomNotices: {
    kickedByVote: "Sei stato espulso dalla stanza con una votazione.",
    roomClosed: "Un amministratore ha chiuso questa stanza.",
    removedByAdmin: "Un amministratore ti ha rimosso.",
    accountDeleted: "Il tuo account è stato eliminato.",
    accountSuspended: "Il tuo account è stato sospeso.",
  },
};
