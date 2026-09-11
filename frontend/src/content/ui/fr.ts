/** Every word the interface says, in French.

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

const { counted, number, ordinal, plural } = formattersFor("fr", {"one":"er","other":"e"});


/** Values a refusal or an announcement carries. Plain data, never words. */
export type MessageParams = Record<string, unknown>;

function count(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function megabytes(bytes: unknown, fallback: string): string {
  const value = typeof bytes === "number" && bytes > 0 ? bytes / 1_000_000 : null;
  if (value === null) return fallback;
  return value >= 1 ? `${Math.round(value)} Mo` : `${Math.round(value / 1000)} Ko`;
}

/** Why a password was refused. The server screens; the wording is ours.

Each reason is actionable on its own, which is the reason the screening sends
one at all: somebody told only "no" comes back with the same password and one
more digit (R-AUTH-19). */
function weakPassword(params: MessageParams): string {
  const detail = params.detail;
  switch (params.reason) {
    case "too_short":
      return `Le mot de passe doit comporter au moins ${count(detail, 12)} caractères.`;
    case "too_long":
      return `Le mot de passe doit comporter au plus ${count(detail, 128)} caractères.`;
    case "common":
      return "Ce mot de passe fait partie des plus courants. Choisis-en un autre.";
    case "common_repeated":
      return "C’est un mot de passe courant, simplement répété. Choisis-en un autre.";
    case "short_repeated":
      return "Ce mot de passe est un mot court répété. Choisis-en un autre.";
    case "too_few_characters":
      return `Ce mot de passe n’utilise que ${count(detail, 4)} caractères différents. Choisis-en un autre.`;
    case "keyboard_walk":
      return "Ce mot de passe est surtout une suite de touches à la file. Choisis-en un autre.";
    case "contains_identity":
      return "Un mot de passe ne doit pas contenir ton nom, ton adresse e-mail ni le nom de ce site.";
    case "common_with_digits":
      return "C’est un mot de passe courant avec des chiffres ajoutés. Choisis-en un autre.";
    default:
      return "Choisis un autre mot de passe.";
  }
}

/** *Create an account to …* - one refusal, said about the thing it refused. */
function accountRequired(params: MessageParams): string {
  switch (params.action) {
    case "avatar":
      return "Crée un compte pour choisir une image.";
    case "prompt_lists":
      return "Crée un compte pour enregistrer des listes de mots réutilisables.";
    case "name_color":
      return "Crée un compte pour choisir une couleur de nom.";
    case "password":
      return "Crée un compte pour définir un mot de passe.";
    case "second_factor":
      return "Crée un compte avant de configurer la double authentification.";
    case "friends":
      return "Crée un compte pour ajouter des amis.";
    default:
      return "Crée un compte pour faire cela.";
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
      return "une mise à jour du serveur est en cours";
    case "too_few_players":
      return "il reste moins de deux joueurs actifs";
    case "prompt_lists_unavailable":
      return "les listes de mots n’ont pas pu être chargées";
    case "everybody_left":
      return "tout le monde est parti avant le départ";
    default:
      return "cela ne pouvait plus continuer";
  }
}

type Sentence = string | ((params: MessageParams) => string);

/** Why the server refused, said to the player.

One entry per `ErrorCode`; `Record` makes it exhaustive, so a code the server
adds without a sentence here fails the build rather than the player
(R-I18N-04). */
const REFUSALS: Record<ErrorCode, Sentence> = {
  // Payloads and arguments
  invalid_payload: "Sketchy n’a pas pu lire cette requête.",
  invalid_nickname: "Ce nom ne peut pas être utilisé ici.",
  invalid_name_color: "Choisis une couleur lisible dans la liste des joueurs claire comme sombre.",
  invalid_hint: "Cet indice n’est pas valide.",
  invalid_letter: "Cette lettre n’est pas valide.",
  invalid_prompt_lists: "Ces listes de mots ne peuvent pas être utilisées ensemble.",
  invalid_custom_prompts: "Ces mots personnalisés n’ont pas pu être lus.",
  max_players_below_seated: (params) =>
  `Le maximum de joueurs ne peut pas être inférieur aux ${count(params.seated, 2)} joueurs déjà présents.`,
  empty_message: "Écris quelque chose d’abord.",

  // Rate and capacity
  too_fast: "Tu vas trop vite. Ralentis un instant.",
  seat_changing_too_fast: "Cette place change de mains trop vite. Réessaie dans une minute.",
  joining_too_fast: "Tu rejoins des salons trop vite. Réessaie dans une minute.",
  room_quota: "Tu as déjà autant de salons ouverts que possible.",
  room_full: "Ce salon est complet.",
  spectators_full: "Ce salon n’accepte plus de spectateurs.",
  player_slots_full: "Toutes les places de joueur sont prises.",

  // Server and account state
  server_draining: "Sketchy redémarre. Réessaie dans un instant.",
  server_paused: "Sketchy n’accepte pas de nouveaux salons pour le moment.",
  database_busy: "Sketchy n’arrive pas à joindre sa base de données. Réessaie.",
  account_ended: "Ce compte n’est plus actif.",
  account_required: accountRequired,
  identity_unavailable: "Sketchy n’a pas pu confirmer qui tu es. Recharge et réessaie.",

  // Rooms
  not_in_room: "Tu n’es pas dans ce salon.",
  room_not_found: "Salon introuvable.",
  room_ended: "Ce salon est terminé.",
  could_not_create_room: "Le salon n’a pas pu être créé.",
  no_session_to_resume: "Il n’y a aucune session à toi à reprendre dans ce salon.",
  host_only: "Seul l’hôte peut faire cela.",
  players_only: "Seuls les joueurs peuvent faire cela.",
  waiting_room_only: "Ce n’est disponible que dans la salle d’attente.",
  already_a_player: "Tu es déjà joueur.",
  registered_name_fixed: "Les joueurs inscrits jouent sous leur nom d’utilisateur.",
  name_taken_by_account: "Ce nom appartient à un joueur inscrit.",
  guests_cannot_choose_color: "Crée un compte pour choisir une couleur de nom.",
  suggestion_inactive: "Cette suggestion n’est plus active.",
  drawing_not_found: "Dessin introuvable.",
  drawing_not_kept: "Ce dessin n’a pas été conservé.",

  // Games and turns
  not_in_game: "Tu n’es dans aucune partie en cours.",
  game_in_progress: "La partie est déjà en cours.",
  game_starting: "La partie démarre encore.",
  need_two_players: "Il faut deux joueurs actifs pour commencer.",
  room_not_startable: "Ce salon ne peut pas lancer de partie pour le moment.",
  prompt_not_ready: "La partie n’est pas encore prête pour un mot.",
  prompt_unavailable: "Ce mot n’est plus disponible.",
  hints_disabled: "Les indices sont désactivés dans ce salon.",
  hint_spend_limit: "Tu as atteint la limite de dépense en indices de ce tour.",
  hint_unavailable: "Cet indice n’est pas disponible.",

  // Canvas
  drawer_only: "Seul celui qui dessine peut faire cela.",
  canvas_stale_generation: "Le tableau a avancé. Rattrapage en cours.",
  canvas_sequence_committed: "Cela a déjà été dessiné.",
  canvas_out_of_sequence: "Les actions de dessin sont arrivées dans le désordre. Rattrapage en cours.",
  canvas_out_of_sync: "Le tableau est désynchronisé. Rattrapage en cours.",
  nothing_to_undo: "Il n’y a rien à annuler.",

  // Votes and restarts
  spectators_cannot_vote: "Les spectateurs ne peuvent pas voter.",
  spectators_cannot_be_targets: "Un spectateur ne peut pas faire l’objet d’un vote.",
  invalid_vote_target: "Tu ne peux pas voter sur ce joueur.",
  not_eligible: "Seuls les joueurs actifs peuvent proposer un redémarrage.",
  restart_vote_active: "Un vote de redémarrage est déjà en cours.",
  restart_vote_cooldown: "Un redémarrage vient d’être voté. Attends un peu avant d’en proposer un autre.",
  no_restart_vote: "Il n’y a aucun vote de redémarrage auquel répondre.",
  restart_vote_closed: "Ce vote de redémarrage est déjà clos.",

  // Reactions
  spectators_cannot_react: "Les spectateurs ne peuvent pas réagir à un dessin.",
  guests_cannot_react: "Crée un compte pour réagir à un dessin.",
  reaction_not_visible: "Tu ne peux pas réagir à un dessin que tu ne vois pas.",
  own_drawing: "Tu ne peux pas réagir à ton propre dessin.",
  game_still_saving: "Cette partie est encore en cours d’enregistrement. Réessaie dans un instant.",
  game_not_recorded: "Cette partie n’a pas été enregistrée.",
  reaction_not_accepted: "Cette réaction n’a pas pu être envoyée.",

  // Friends
  friends_unavailable: "Les amis ne sont pas disponibles pour le moment.",
  friend_refused: "Cette demande d’ami n’a pas pu aboutir.",
  friend_not_in_game: "Ton ami n’est dans aucune partie pour le moment.",
  friend_in_several_games: "Cet ami est dans plusieurs parties. Demande-lui une invitation.",
  not_friends: "Tu ne peux rejoindre que la partie d’un ami.",
  friends_only_uninvited: "Seuls les amis de l’hôte peuvent rejoindre sans invitation. Demande-lui-en une.",
  invite_expired: "Cette invitation a expiré.",

  // Moderation, from the reporter's side
  reporting_unavailable: "Les signalements ne sont pas disponibles sur ce serveur.",
  no_such_player: "Ce joueur n’existe pas.",
  cannot_report: "Ce joueur ne peut pas être signalé.",
  already_reported: "Tu as déjà signalé cela, et un modérateur ne l’a pas encore examiné.",

  // Lobby chat
  name_required: "Choisis un nom avant de parler dans le hall.",
  not_watching_lobby: "Tu ne regardes plus le hall.",

  // Versioning
  protocol_mismatch: "Cet onglet utilise une ancienne version de Sketchy. Recharge la page pour continuer.",

  // Sessions and accounts
  sign_in_required: "Connecte-toi d’abord.",
  credentials_incorrect: "Nom d’utilisateur ou mot de passe incorrect.",
  password_incorrect: "Le mot de passe est incorrect.",
  account_suspended: "Ce compte est suspendu.",
  already_signed_in: "Tu es déjà connecté à un compte.",
  username_taken: "Ce nom d’utilisateur est pris.",
  invalid_username: "Ce nom d’utilisateur ne peut pas être utilisé.",
  weak_password: weakPassword,
  password_change_failed: "Le mot de passe n’a pas pu être changé.",
  session_not_found: "Cet appareil n’est plus connecté.",
  session_replaced: "Cette session a été remplacée. Recharge et réessaie.",
  guest_progress_unlinked: "La progression d’invité n’a pas pu être liée à ce compte.",
  not_taking_visitors: "Sketchy n’accepte pas de nouveaux visiteurs pour le moment. Réessaie plus tard.",
  account_delete_refused: "Le compte n’a pas pu être supprimé maintenant. Réessaie.",
  password_required_to_delete: "Saisis ton mot de passe pour supprimer le compte.",

  // Second factor and passkeys
  second_factor_required: "Saisis le code de ton application d’authentification.",
  second_factor_passkey_only: "Connecte-toi avec ta clé d’accès.",
  second_factor_not_enrolled:
  "Ce compte a besoin de la double authentification avant de pouvoir se connecter. Demande de l’aide à un administrateur pour la configurer.",
  second_factor_not_set_up: "La double authentification n’est pas configurée.",
  second_factor_code_wrong: "Ce code n’est pas le bon.",
  second_factor_throttled: "Trop de codes erronés. Patiente un peu et réessaie.",
  step_up_required: "Confirme que c’est bien toi avant de faire cela.",
  passkey_sign_in_required: "Connecte-toi avec ta clé d’accès.",
  passkey_not_registered: "Cette clé d’accès n’est pas enregistrée ici.",
  passkey_not_found: "Cette clé d’accès n’existe pas.",
  passkey_refused:
  "Les clés d’accès sont réservées aux comptes de modérateur et d’administrateur. On te demandera d’en créer une si un rôle t’est un jour proposé.",
  last_factor: "C’est le seul moyen dont tu disposes pour prouver que c’est toi. Ajoutes-en un autre avant de retirer celui-ci.",
  second_factor_required_for_role: "Le rôle de ce compte exige la double authentification.",
  second_factor_not_proved:
  "Cet authentificateur n’a pas encore été confirmé comme le tien. Utilise une clé d’accès, ou confirme-le avec ton mot de passe dans les paramètres.",

  // Email, verification and recovery
  invalid_email: "Cela ne ressemble pas à une adresse e-mail.",
  email_in_use: "Cette adresse est déjà utilisée.",
  email_change_refused: "Cette adresse ne peut pas être ajoutée à ce compte.",
  verification_link_invalid: "Ce lien de confirmation a expiré ou a déjà été utilisé.",
  reset_link_invalid: "Ce lien de réinitialisation a expiré ou a déjà été utilisé.",

  // Account data export
  export_not_found: "Export introuvable.",
  export_expired: "L’export a expiré.",
  export_not_ready: "L’export n’est pas prêt.",
  export_unreadable: "Le document d’export n’a pas pu être lu. Demande un nouvel export.",
  export_not_yet_allowed: "Tu as demandé un export récemment. Réessaie plus tard.",
  export_refused: "Cet export n’a pas pu être lancé. Réessaie.",

  // Rate limits reached over HTTP
  too_many_attempts: "Trop de tentatives. Patiente un peu et réessaie.",
  too_many_requests: "Trop de requêtes. Patiente un peu et réessaie.",
  too_many_reports: "Trop de signalements. Attends avant d’en envoyer un autre.",
  too_many_bug_reports: "Trop de rapports de bug. Attends avant d’en envoyer un autre.",
  too_many_pictures: "Trop d’images. Patiente un peu et réessaie.",

  // Pictures
  unsupported_picture_type: "Ce n’est pas une image WebP ou PNG.",
  picture_not_found: "Cette image n’existe pas.",
  picture_refused: "Cette image ne peut pas être utilisée ici.",

  // Bug reports
  screenshot_unreadable: "La capture n’a pas pu être lue.",
  screenshot_too_large: (params) =>
  `Cette capture est trop lourde. La limite est de ${megabytes(params.limitBytes, "2 MB")}.`,
  screenshot_unsupported_type: "Une capture doit être une image PNG ou WebP.",
  bug_report_context_too_large: "Ce rapport transporte trop de contexte.",

  // Friends, over HTTP
  friends_throttled: "Tu as envoyé beaucoup de demandes d’ami. Réessaie plus tard.",
  that_is_you: "C’est toi.",

  // Profiles and history
  no_such_game: "Cette partie n’existe pas.",
  no_such_drawing: "Ce dessin n’existe pas.",
  drawing_unreadable: "Ce dessin n’a pas pu être lu.",

  // Prompt lists
  prompt_list_not_found: "Liste de mots introuvable.",
  shared_prompt_list_not_found: "Aucune liste de mots partagée trouvée.",
  prompt_list_conflict: "Quelqu’un d’autre a modifié cette liste. Recharge-la et réessaie.",
  prompt_list_invalid: "Cette liste de mots n’a pas pu être enregistrée.",
  prompt_list_forbidden: "Cette liste de mots n’est pas à toi.",
  unknown_sort: "Sketchy ne peut pas trier par cela.",
  timezone_required: "Indique un fuseau horaire avec cette date.",
  range_reversed: "Le début de la période doit précéder sa fin.",

  // Room presets
  room_preset_not_found: "Préréglage de salon introuvable.",
  room_preset_conflict: "Tu as déjà un préréglage portant ce nom.",
  room_preset_unavailable: "Ce préréglage ne peut pas être utilisé pour le moment.",
  room_preset_forbidden: "Ce préréglage n’est pas le tien.",

  // Blocks
  cannot_block_yourself: "Tu ne peux pas te bloquer toi-même.",
  block_list_full: (params) =>
  `Ta liste de blocages est pleine${
    typeof params.limit === "number" ? ` à ${params.limit}` : ""
  }. Débloque d’abord quelqu’un.`,

  // Settings
  setting_refused: "Ce réglage n’a pas pu être enregistré.",

  // Role notices
  no_such_notice: "Cet avis n’existe pas.",

  // Reporting, from the reporter's side
  cannot_report_yourself: "Tu ne peux pas te signaler toi-même.",
  cannot_report_own_prompt_list: "Tu ne peux pas signaler ta propre liste de mots.",
  no_reportable_prompt_list: "Aucune liste de mots signalable trouvée.",
  prompt_not_in_list: "Ce mot n’appartient pas à cette liste.",
  no_picture_to_report: "Ce joueur n’a pas d’image à signaler.",
  no_such_game_context: "Ce contexte de partie n’existe pas.",
  no_such_turn_context: "Ce contexte de tour n’existe pas.",
  turn_not_in_game: "Le tour n’appartient pas à cette partie.",
  evidence_unavailable: "Un ou plusieurs messages sélectionnés ne sont pas disponibles.",
  evidence_mixed_scopes: "Les messages du hall et du salon ne peuvent pas être mélangés dans un signalement.",
  evidence_several_rooms: "Les messages sélectionnés doivent venir du même salon.",
  evidence_not_theirs: "Les preuves doivent être du joueur signalé.",
  evidence_not_received: "Tu ne peux pas sélectionner un message que tu n’as pas reçu.",
  evidence_not_in_game: "Le message sélectionné n’appartient pas à cette partie.",
  evidence_not_in_turn: "Le message sélectionné n’appartient pas à ce tour.",
  no_such_warning: "Cet avertissement n’existe pas.",
  no_drawing: "Aucun dessin.",};

/** What the room says about itself. One entry per `AnnouncementCode`. */
const ANNOUNCEMENTS: Record<AnnouncementCode, (params: MessageParams) => string> = {
  nickname_changed: (p) =>
  `${text(p.previous)} s’appelle désormais ${text(p.nickname)}.`,
  joined_as_player: (p) => `${text(p.nickname)} a rejoint la partie comme joueur.`,
  kicked_by_vote: (p) => `${text(p.nickname)} a été exclu par vote.`,
  marked_afk_by_vote: (p) => `${text(p.nickname)} a été marqué absent par vote.`,

  restart_vote_started: (p) =>
  `${text(p.nickname)} a lancé un vote pour redémarrer la partie.`,
  restart_vote_passed: (p) =>
  `Le vote de redémarrage est passé. Redémarrage dans ${count(p.seconds, 5)} secondes.`,
  restart_vote_rejected: () => "Le vote de redémarrage a été rejeté.",
  restart_vote_expired: () => "Le vote de redémarrage a expiré sans passer.",
  restart_vote_abandoned: () =>
  "Le vote de redémarrage a été annulé car il reste moins de deux joueurs actifs.",
  restart_cancelled: (p) => `Le redémarrage a été annulé car ${cancelReason(p.reason)}.`,
  game_restarted_by_vote: () => "La partie a été redémarrée par vote des joueurs.",

  hint_letter_found: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pts - trouvée ${counted(count(p.count, 1), {
    one: "fois",
    other: "fois",
  })} !`,
  hint_letter_missing: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pts - absente du mot.`,
  guess_very_close: (p) => `« ${text(p.text)} » est tout proche !`,
  guess_some_words_correct: () => "Certains mots sont corrects",};

export const FR: Catalogue = {
  refusals: REFUSALS,
  announcements: ANNOUNCEMENTS,

  /** What the document itself says: the tab, and what a link preview shows.

      Rendered into `index.html` for a crawler, which arrives before any
      script, and rewritten here for the reader once their locale is known. */
  document: {
    description: "Dessine, devine et ris avec tes amis !",
  },

  /** Shapes that belong to the language rather than to any one screen. */
  format: {
    /** `1st`, `2nd`, `3rd`; a language with no ordinal form gets the number. */
    ordinal: (p: { value: number }) => ordinal(p.value),
  },

  promptListDrafts: {
    promptsAdded: (p: { count: number }) =>
      `${counted(p.count, { one: "mot ajouté", other: "mots ajoutés" })}`,
  },

  lastSeen: {
    online: "en ligne",
    justNow: "vu à l’instant",
    lastSeenAgo: (p: { count: number; unit: "minute" | "hour" | "day" }) => {
      const words = {
        minute: { one: "minute", other: "minutes" },
        hour: { one: "heure", other: "heures" },
        day: { one: "jour", other: "jours" },
      }[p.unit];
      return `vu il y a ${counted(p.count, words)}`;
    },
  },

  gameHighlights: {
    reactionCount: (p: { count: number }) =>
      counted(p.count, { one: "réaction", other: "réactions" }),
  },

  versionBadge: {
    buildDetails: (p: { commitDate: string; builtAt: string }) =>
      `Date du commit : ${p.commitDate} | Compilé : ${p.builtAt}`,
  },

  segmentedCodeInput: {
    digitPosition: (p: { label: string; index: number; length: number }) =>
      `${p.label}, chiffre ${p.index} sur ${p.length}`,
  },

  roomSetupControls: {
    decrease: (p: { label: string }) => `Diminuer ${p.label}`,
    increase: (p: { label: string }) => `Augmenter ${p.label}`,
  },

  guessPips: {
    playerGuessState: (p: { nickname: string; isFriend: boolean; guessed: boolean }) =>
      `${p.nickname}${p.isFriend ? " (ami)" : ""} ${p.guessed ? "a trouvé" : "cherche encore"}`,
  },

  accountDataDialog: {
    requestedOn: (p: { when: string; schemaVersion: number }) =>
      `Demandé ${p.when} · format v${p.schemaVersion}`,
    exportAllowance: (p: { nextAllowed: string | null }) =>
      p.nextAllowed
        ? `Un export par semaine ; les exports prêts expirent au bout de sept jours. Tu pourras en redemander un le ${p.nextAllowed}.`
        : "Un export par semaine ; les exports prêts expirent au bout de sept jours.",
    couldNotLoadYourDataExports: "Tes exports de données n’ont pas pu être chargés.",
    couldNotRequestYourDataExport: "Ton export de données n’a pas pu être demandé.",
    yourData: "Tes données",
    downloadPrivateJsonCopyYourAccount: "Télécharge une copie privée en JSON de ton compte et de tes données de jeu. Les profils et messages des autres joueurs n’y sont pas.",
    dataExports: "Exports de données",
    loadingExports: "Chargement des exports…",
    youHaveNotRequestedExportYet: "Tu n’as pas encore demandé d’export.",
    download: "Télécharger",
    close: "Fermer",
  },

  accountMenu: {
    noPasskeyWasUsed: "Aucune clé d’accès n’a été utilisée. Tu peux te connecter avec ton mot de passe.",
    signedInWithRequests: (p: { name: string; waiting: number }) =>
      `Connecté en tant que ${p.name}. ${counted(p.waiting, {
        one: "demande d’ami",
        other: "demandes d’ami",
      })} en attente.`,
    friends: "Amis",
    finishYourRole: (p: { role: "admin" | "moderator" }) =>
      `Termine ton rôle d’${p.role === "admin" ? "administrateur" : "modérateur"}`,
    agreeToRules: "En créant un compte, tu acceptes de suivre les {rules}.",
    reportBug: "Signaler un bug",
    account: "Compte",
    settings: "Paramètres",
    myProfile: "Mon profil",
    promptStats: "Statistiques des mots",
    createAccount: "Créer un compte",
    logIn: "Se connecter",
    myPromptLists: "Mes listes de mots",
    rules: "Règles",
    logOut: "Se déconnecter",
    thatDoesNotLookLikeEmail: "Cela ne ressemble pas à une adresse e-mail.",
    somethingWentWrongPleaseTryAgain: "Quelque chose s’est mal passé. Réessaie.",
    thatPasskeyWasNotAccepted: "Cette clé d’accès n’a pas été acceptée.",
    thisAccountSignsWithPasskey: "Ce compte se connecte avec une clé d’accès.",
    or: "ou",
    username: "Nom d’utilisateur",
    password: "Mot de passe",
    codeFromYourAuthenticatorApp: "Code de ton application d’authentification",
    recoveryCodeWorksHereTooCan: "Un code de récupération marche ici aussi, et sert une fois.",
    email: "E-mail",
    optional: "facultatif",
    letsYouResetYourPasswordLater: "Te permet de réinitialiser ton mot de passe plus tard. Sert uniquement à cela.",
    rules2: "règles",
    forgotYourPassword: "Mot de passe oublié ?",
    notNow: "Pas maintenant",
  },

  accountRecoveryPage: {
    thatConfirmationLinkCouldNotBe: "Ce lien de confirmation n’a pas pu être utilisé.",
    somethingWentWrongPleaseTryAgain: "Quelque chose s’est mal passé. Réessaie.",
    evenBestGuessersForgetSometimes: "Même les meilleurs devineurs oublient parfois.",
    weRsquoLlSendSecureTime: "Nous enverrons un lien sécurisé et limité dans le temps à l’adresse\n            confirmée de ton compte.",
    accountHelp: "Aide sur le compte",
    backLobby: "Retour au hall",
    enterYourUsernameYourConfirmedEmail: "Saisis ton nom d’utilisateur ou ton adresse confirmée. Si le compte\n              peut être récupéré, un lien est en route.",
    usernameEmail: "Nom d’utilisateur ou e-mail",
    thatResetLinkHasExpiredHas: "Ce lien de réinitialisation a expiré ou a déjà été utilisé. Ces liens\n              servent une fois et durent une heure.",
    sendNewOne: "En envoyer un nouveau",
    checkingThatLink: "Vérification du lien…",
    everySignedDeviceWillBeSigned: "Tous les appareils connectés seront déconnectés, y compris ceux que\n              tu n’as pas reconnus.",
    newPassword: "Nouveau mot de passe",
  },

  activeGameRoom: {
    leaveGame: "Quitter la partie",
    markedAfkByRoomVote: "Le salon t’a marqué absent par vote.",
    couldNotChangeSuggestion: (p: { action: string }) =>
      `Impossible de ${p.action} la suggestion de couleurs.`,
    inviteLinkCopied: "Lien d’invitation copié.",
    couldnTCopyLinkCopyFrom: "Le lien n’a pas pu être copié. Copie-le depuis la barre d’adresse.",
    couldNotStartGamePleaseTry: "La partie n’a pas pu démarrer. Réessaie.",
    couldNotStartRestartVote: "Le vote de redémarrage n’a pas pu être lancé.",
    couldNotRecordYourRestartVote: "Ton vote de redémarrage n’a pas pu être enregistré.",
    copyRoomInviteLink: "Copier le lien d’invitation du salon",
    clickCopyRoomInviteLink: "Clique pour copier le lien d’invitation",
    roomMenu: "Menu du salon",
    afk: "Absent",
    saveImage: "Enregistrer l’image",
    saveDrawnImageFile: "Enregistrer le dessin dans un fichier",
    playerSettings: "Paramètres du joueur",
    leaveRoom: "Quitter le salon",
    leave: "Quitter",
    players: "Joueurs",
  },

  addEmailDialog: {
    followTheLink: (p: { address: string; replacing: boolean }) =>
      `Suis le lien envoyé à ${p.address}. D’ici là, l’adresse n’est pas rattachée à ton compte et ne permet pas de le récupérer${
        p.replacing ? ", et celle que tu avais reste en place." : "."
      }`,
    thatDoesNotLookLikeEmail: "Cela ne ressemble pas à une adresse e-mail.",
    somethingWentWrongPleaseTryAgain: "Quelque chose s’est mal passé. Réessaie.",
    done: "Terminé",
    usedOnlyResetYourPasswordTell: "Sert uniquement à réinitialiser ton mot de passe et à te prévenir si\n              ton compte ou quelque chose que tu as partagé fait l’objet d’une\n              décision. Rien d’autre n’est jamais envoyé ici.",
  },

  afkCheckDialog: {
    secondsUnit: (p: { count: number }) =>
      plural(p.count, { one: "seconde", other: "secondes" }),
    stillThere: "Toujours là ?",
    youHaveBeenQuietWhileAnswer: "Tu es silencieux depuis un moment. Réponds et tu continues à jouer ;\n          sinon le salon te marquera absent et poursuivra sans toi.",
    stillTherePressButtonMoveMouse: "Toujours là ? Appuie sur le bouton, ou bouge la souris, pour continuer à jouer.",
    iMHere: "Je suis là",
  },

  app: {
    serverUpdateInProgress: (p: { seconds: number }) =>
      p.seconds > 0
        ? `Mise à jour du serveur en cours. Aucun salon ni aucune partie ne peut démarrer ; une partie en cours a encore ${counted(p.seconds, { one: "seconde", other: "secondes" })}.`
        : "Mise à jour du serveur en cours. Aucun salon ni aucune partie ne peut démarrer ; les parties en cours se terminent maintenant.",
    thisTabOutDateCannotPlay: "Cet onglet est obsolète et ne peut pas jouer tant qu’il n’est pas rechargé.",
    reload: "Recharger",
    newRoomsArePausedMaintenanceGames: "Les nouveaux salons sont en pause pour maintenance. Les parties déjà lancées\n          continuent normalement.",
    serverWasUpdatedBackAnyGame: "Le serveur a été mis à jour et est de retour. Les parties en cours sont terminées.",
    dismiss: "Masquer",
  },

  appHeader: {
    playerSettings: "Paramètres du joueur",
  },

  bugReportDialog: {
    connectionSummary: (p: { connected: boolean; reconnects: number }) =>
      `${p.connected ? "connecté" : "hors ligne"} · ${counted(p.reconnects, {
        one: "reconnexion",
        other: "reconnexions",
      })} pendant cette visite`,
    couldNotTakeScreenshot: "La capture n’a pas pu être prise.",
    thanksYourReportWithPeopleWho: "Merci — ton rapport est arrivé chez les personnes qui font tourner Sketchy.",
    couldNotSendReport: "Le rapport n’a pas pu être envoyé.",
    reportBug: "Signaler un bug",
    somethingBrokenNotSomethingSomeoneSaid: "Quelque chose de cassé, pas quelque chose que quelqu’un a dit. Cela va aux personnes qui font tourner Sketchy — jamais aux autres joueurs.",
    where: "Où",
    howBad: "Gravité",
    oneLineSummary: "Résumé en une ligne",
    whatWentWrongOneLine: "Ce qui n’a pas marché, en une ligne",
    whatHappened: "Ce qui s’est passé",
    whatYouDidWhatYouExpected: "Ce que tu as fait, ce que tu attendais, ce qui s’est passé à la place.",
    screenshot: "Capture",
    optional: "Facultatif",
    screenshotThatWillBeSentWith: "La capture qui sera envoyée avec ce rapport",
    thisDialogHidesItselfWhileShot: "Cette fenêtre se cache pendant la capture, tu obtiens donc la page derrière. Regarde-la avant d’envoyer — c’est toi qui choisis ce que tu partages.",
    replace: "Remplacer",
    remove: "Retirer",
    opensYourBrowserSOwnPicker: "Ouvre le sélecteur de ton navigateur — choisis cet onglet. Cette fenêtre se cache pendant la capture, tu obtiens donc la page derrière.",
    recentClientErrors: "Erreurs client récentes",
    sendMyDescriptionOnly: "Envoyer seulement ma description",
    dropsDetailsAboveAnyScreenshotWe: "Abandonne les détails ci-dessus et toute capture. Nous le lirons quand même, mais le bug sera bien plus difficile à reproduire.",
    cancel: "Annuler",
  },

  changePasswordDialog: {
    forgottenTheCurrentOne: "Tu as oublié l’actuel ?",
    twoNewPasswordsDoNotMatch: "Les deux nouveaux mots de passe ne correspondent pas.",
    passwordChangedEveryOtherDeviceHas: "Mot de passe changé. Tous les autres appareils ont été déconnectés.",
    couldNotChangePasswordPleaseTry: "Le mot de passe n’a pas pu être changé. Réessaie.",
    ifThatAccountHasVerifiedEmail: "Si ce compte a une adresse vérifiée, un lien pour définir un nouveau\n              mot de passe est en route. Il sert une fois, et il expire.",
    done: "Terminé",
    everyDeviceSignsOutWhenPassword: "Chaque appareil est déconnecté lors d’un changement de mot de passe, y\n              compris ceux que tu n’avais pas voulu laisser connectés. Celui-ci reste.",
    currentPassword: "Mot de passe actuel",
    newPassword: "Nouveau mot de passe",
    newPasswordAgain: "Nouveau mot de passe (confirmation)",
    emailMeLinkInstead: "Envoie-moi plutôt un lien",
  },

  choosingPromptOverlay: {
    isChoosingPrompt: "{drawer} choisit un mot…",
    nextTurn: "Tour suivant",
    drawingWillBeginAsSoonAs: "Le dessin commencera dès que le choix sera fait.",
  },

  colorblindSafeSuggestionBanner: {
    colorblindSafeColorSuggestion: "Suggestion de couleurs adaptées au daltonisme",
    playerThisRoomPlaysWithColorblind: "Un joueur de ce salon joue avec des couleurs adaptées au daltonisme.",
    switchRoomPaletteFutureDrawings: "Changer la palette du salon pour les prochains dessins ?",
    switchColors: "Changer les couleurs",
    notNow: "Pas maintenant",
  },

  confirmationDialog: {
    cancel: "Annuler",
  },

  crashPage: {
    couldNotSendReport: "Le rapport n’a pas pu être envoyé.",
    bugCrawledOntoPage: "Un bug a rampé sur la page",
    helpUsSquash: "Aide-nous à l’écraser",
    reportReadySendErrorWhatThis: "Un rapport est prêt : l’erreur, et ce que cet onglet sait de lui-même.\n            Il va aux personnes qui font tourner Sketchy — jamais aux autres joueurs.",
    whatWereYouDoing: "Que faisais-tu ?",
    optional: "Facultatif",
    lastThingYouClickedTypedIf: "La dernière chose que tu as cliquée ou tapée, si tu t’en souviens.",
    recentClientErrorsNewestFirst: "Erreurs client récentes, les plus récentes en premier",
    sendMyDescriptionOnly: "Envoyer seulement ma description",
    dropsDetailsAboveWeWillStill: "Abandonne les détails ci-dessus. Nous le lirons quand même, mais le plantage sera bien plus difficile à trouver.",
    thanksYourReportWithPeopleWho: "Merci — ton rapport est arrivé chez les personnes qui font tourner Sketchy.",
    reload: "Recharger",
    backLobby: "Retour au hall",
  },

  createRoomPage: {
    setupTiming: "Cette configuration dure {full} avec un salon complet de {capacity}",
    setupTimingFull: (p: { minutes: number }) =>
      `environ ${counted(p.minutes, { one: "minute", other: "minutes" })}`,
    setupTimingHalf: (p: { players: number }) => ` — plutôt {half} si ${p.players} rejoignent`,
    couldNotLoadYourRoomPresets: "Tes préréglages de salon n’ont pas pu être chargés.",
    couldNotApplyThatPreset: "Ce préréglage n’a pas pu être appliqué.",
    enterNameRoomPreset: "Donne un nom au préréglage de salon.",
    couldNotSaveThatPreset: "Ce préréglage n’a pas pu être enregistré.",
    couldNotUpdateThatPreset: "Ce préréglage n’a pas pu être mis à jour.",
    couldNotDeleteThatPreset: "Ce préréglage n’a pas pu être supprimé.",
    fixCustomPromptEntriesMarkedAbove: "Corrige les mots personnalisés signalés ci-dessus avant de créer le salon.",
    failedCreateRoom: "Échec de la création du salon",
    roomSetup: "Configuration du salon",
    createRoom: "Créer un salon",
    startFromSavedPreset: "Partir d’un préréglage enregistré",
    startFromPreset: "Partir d’un préréglage…",
    nameThisPreset: "Nommer ce préréglage",
    save: "Enregistrer",
    cancel: "Annuler",
    saveAsPreset: "Enregistrer comme préréglage",
    update: "Mettre à jour",
    delete: "Supprimer",
    undo: "Annuler",
    saveAsReusableList: "Enregistrer comme liste réutilisable",
  },

  customPromptsEditor: {
    usableCount: (p: { count: number }) =>
      counted(p.count, { one: "mot personnalisé utilisable", other: "mots personnalisés utilisables" }),
    duplicatesIgnored: (p: { count: number }) =>
      `${counted(p.count, { one: "doublon ignoré", other: "doublons ignorés" })}`,
    entriesTooLong: (p: { count: number; limit: number }) =>
      `${counted(p.count, { one: "entrée dépasse", other: "entrées dépassent" })} ${number(p.limit)} caractères`,
    entryLimit: (p: { limit: number }) => `Seules ${number(p.limit)} entrées sont autorisées`,
    customPromptsOptional: "Mots personnalisés (facultatif)",
    onePromptPerLineSeparateEntries: "Un mot par ligne\nou sépare les entrées par des virgules",
    shortenRemoveOverlongEntriesBeforeCreating: "Raccourcis ou supprime les entrées trop longues avant de créer le salon.",
  },

  customPromptsPreview: {
    resultsMatching: (p: { shown: number; total: number }) =>
      `${number(p.shown)} mots sur ${number(p.total)} correspondent`,
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "mot", other: "mots" }),
    customPromptCount: (p: { count: number }) =>
      counted(p.count, { one: "mot personnalisé", other: "mots personnalisés" }),
    inspectPrompts: (p: { count: number }) =>
      `Examiner ${counted(p.count, { one: "mot personnalisé", other: "mots personnalisés" })}`,
    couldNotLoadCustomPrompts: "Les mots personnalisés n’ont pas pu être chargés",
    loadingCustomPrompts: "Chargement des mots personnalisés…",
    roomPromptCollection: "Collection de mots du salon",
    readOnlyListSuppliedByRoom: "Liste en lecture seule fournie par l’hôte du salon.",
    findPrompt: "Trouver un mot",
    searchCustomPrompts: "Rechercher dans les mots personnalisés…",
    filterPromptsByLength: "Filtrer les mots par longueur",
    noCustomPromptsMatchTheseFilters: "Aucun mot personnalisé ne correspond à ces filtres.",
  },

  deleteAccountDialog: {
    whatIsRemoved: (p: { isGuest: boolean }) =>
      `${
        p.isGuest
          ? "Le nom, les points et l’historique conservés dans ce navigateur sont supprimés."
          : "Ton nom est retiré des parties que tu as jouées."
      } Les scores et les dessins restent, sous « Joueur supprimé », car ce sont aussi les parties d’autres personnes. C’est irréversible.`,
    typeToConfirm: (p: { word: string }) => `Tape ${p.word} pour confirmer`,
    couldNotDeleteAccount: "Le compte n’a pas pu être supprimé.",
    password: "Mot de passe",
  },

  drawingReactionControl: {
    reactionSummary: (p: { total: number; chips: string }) =>
      `${counted(p.total, { one: "réaction", other: "réactions" })} : ${p.chips}`,
    thatReactionCouldNotBeSent: "Cette réaction n’a pas pu être envoyée.",
    reactThisDrawing: "Réagir à ce dessin",
    reactions: "Réactions",
    createAccountReact: "Crée un compte pour réagir.",
    createAccount: "Créer un compte",
  },

  drawingRecapGallery: {
    drawingLabel: (p: { prompt: string; drawer: string }) =>
      `Dessin de ${p.prompt} par ${p.drawer}`,
    drawnBy: "Dessiné par {drawer} · Manche {round} · Tour {turn}",
    position: (p: { position: number; total: number }) => `${p.position} sur ${p.total}`,
    thisDrawingCouldNotBeDecoded: "Ce dessin n’a pas pu être décodé.",
    drawingRecap: "Récapitulatif des dessins",
    saveImage: "Enregistrer l’image",
    close: "Fermer",
    thisDrawingWasNotKept: "Ce dessin n’a pas été conservé.",
    roomRanOutRoomLaterTurns: "Le salon n’avait plus de place. Des tours plus tardifs ont été conservés à la place.",
    tryAgain: "Réessayer",
    loadingDrawing: "Chargement du dessin…",
    noDrawingWasCapturedThisTurn: "Aucun dessin n’a été capturé pour ce tour.",
    drawingRecapNavigation: "Navigation du récapitulatif des dessins",
    previous: "Précédent",
    next: "Suivant",
  },

  emailRecoveryReminder: {
    addEmail: "Ajouter une adresse e-mail",
    dismiss: "Masquer",
  },

  firstRunIdentity: {
    couldNotSaveThatNamePlease: "Ce nom n’a pas pu être enregistré. Réessaie.",
    keepYourUsernameYourStatsEvery: "Garde ton nom d’utilisateur et tes statistiques sur tous tes appareils.",
    createAccount: "Créer un compte",
    logIn: "Se connecter",
    or: "ou",
    displayName: "Nom affiché",
  },

  friendButton: {
    requestSentTo: (p: { name: string }) => `Demande d’ami envoyée à ${p.name}`,
    addFriend: "Ajouter en ami",
    acceptRequest: "Accepter la demande",
    requestSent: "Demande envoyée",
  },

  friendInviteNotice: {
    couldNotJoinThatGame: "Cette partie n’a pas pu être rejointe.",
    thatGameCouldNotBeJoined: "Cette partie n’a pas pu être rejointe.",
    invitedYouTheirGame: "t’a invité dans sa partie.",
    join: "Rejoindre",
    dismissInvitation: "Masquer l’invitation",
  },

  friendsOverlay: {
    declineWarning: (p: { name: string }) =>
      `${p.name} ne pourra pas redemander. Tu pourras toujours lui envoyer une demande plus tard.`,
    decline2: "Refuser",
    youWillBothStopBeingAble: "Vous ne pourrez plus rejoindre les parties l’un de l’autre sans invitation. Chacun peut redemander.",
    remove2: "Retirer",
    removeConfirm: (p: { name: string }) => `Retirer ${p.name} ?`,
    friends: "Amis",
    close: "Fermer",
    closeFriends: "Fermer les amis",
    friendsNeedAccountGuestNameBelongs: "Les amis demandent un compte. Un nom d’invité appartient à ce navigateur\n              plutôt qu’à toi, donc dans un mois il ne resterait plus personne\n              avec qui être ami.",
    loading: "Chargement…",
    noFriendsYetAddSomebodyFrom: "Pas encore d’amis. Ajoute quelqu’un depuis le hall, ou depuis une partie\n              où vous êtes tous les deux.",
    requests: "Demandes",
    accept: "Accepter",
    decline: "Refuser",
    sent: "Envoyée",
    cancel: "Annuler",
    remove: "Retirer",
    declineThisRequest: "Refuser cette demande ?",
    recentlyPlayedWith: "Joué récemment avec",
  },

  gameEndOverlay: {
    continueLabel: "Continuer",
    youFinished: (p: { points: number }) =>
      `Tu finis {place} avec ${counted(p.points, { one: "point", other: "points" })}.`,
    continueToWaitingRoom: "Aller à la salle d’attente",
    continueWithCountdown: (p: { seconds: number }) =>
      `Aller à la salle d’attente, ${counted(p.seconds, { one: "seconde", other: "secondes" })} restantes`,
    gameOver: "Partie terminée",
    you: "toi",
    friend: "Ami",
    noScoresThisTimeJustRoom: "Pas de score cette fois — juste un salon plein de croquis et de suppositions.",
    keep: "Garder",
    asYourUsername: "comme nom d’utilisateur",
    createAccount: "Créer un compte",
    highlights: "Moments forts",
    drawings: "Dessins",
    stayHere: "Rester ici",
  },

  gameHighlightsPanel: {
    lastGame: "Dernière partie",
    highlights: "Moments forts",
    closeHighlights: "Fermer les moments forts",
    thatGameWasTooShortSay: "Cette partie était trop courte pour en dire grand-chose. Joues-en une plus\n            longue et les moments forts apparaîtront ici.",
    seeIt: "Voir",
    back: "Retour",
  },

  inviteEntryPage: {
    roomCode: (p: { code: string }) => `Salon ${p.code}`,
    hereCount: (p: { here: number; capacity: number; full: boolean }) =>
      `${p.here}/${p.capacity} ici${p.full ? " · complet" : ""}`,
    roomSummary: (p: { rounds: number; seconds: number; hintMode: string }) =>
      `${counted(p.rounds, { one: "manche", other: "manches" })} · ${p.seconds}s · ${p.hintMode}`,
    checkingYourInvite: "Vérification de ton invitation…",
    loadingRoomDetails: "Chargement des détails du salon.",
    roomUnavailable: "Salon indisponible",
    backLobby: "Retour au hall",
    players: "Joueurs",
    rounds: "Manches",
    drawTime: "Temps de dessin",
    scoring: "Score",
    roomRules: "Règles du salon",
    thisGameAlreadyProgressJoiningAs: "Cette partie est déjà en cours. En rejoignant comme joueur, tu entres à un tour suivant.",
    playerSlotsAreFullSpectatingStill: "Les places de joueur sont prises. Tu peux encore regarder.",
  },

  inviteFriendsList: {
    invitationCouldNotBeSent: "Cette invitation n’a pas pu être envoyée.",
    invitationSent: (p: { name: string }) => `Invitation envoyée à ${p.name}.`,
    thatInvitationCouldNotBeSent: "Cette invitation n’a pas pu être envoyée.",
    friendsLobby: "Amis dans le hall",
    invited: "Invité",
    invite: "Inviter",
  },

  languagePicker: {
    currentChoice: (p: { label: string; value: string }) => `${p.label} : ${p.value}`,
    everyLanguage: "Toutes les langues",
  },

  lobbyBrowserPage: {
    filterByLanguage: "Filtrer par langue",
    filtersWithCount: (p: { count: number }) =>
      p.count > 0 ? `Filtres · ${p.count}` : "Filtres",
    showRooms: (p: { count: number }) =>
      `Voir ${counted(p.count, { one: "salon", other: "salons" })}`,
    removedFromRoom: "Retiré du salon",
    ok: "OK",
    roomCode: "Code du salon",
    abc123: "ABC123",
    thereNoRoomCodeClipboard: "Il n’y a aucun code de salon dans le presse-papiers.",
    sketchyCouldNotReadClipboardPaste: "Sketchy n’a pas pu lire le presse-papiers. Colle plutôt dans les cases.",
    pleaseEnterRoomCode: "Saisis un code de salon",
    failedJoinRoom: "Impossible de rejoindre le salon",
    joinByCode: "Rejoindre avec un code",
    createRoom: "Créer un salon",
    publicRooms: "Salons publics",
    searchRoomsByNameCode: "Chercher des salons par nom ou code",
    hideFull: "Masquer les complets",
    hideProgress: "Masquer les parties en cours",
    filters: "Filtres",
    clearFilters: "Effacer les filtres",
    language: "Langue",
    hideFullRooms: "Masquer les salons complets",
    hideGamesProgress: "Masquer les parties en cours",
    loadingPublicRooms: "Chargement des salons publics…",
    noPublicRoomsYetCreateOne: "Aucun salon public pour l’instant. Crées-en un !",
    noPublicRoomsMatchYourSearch: "Aucun salon public ne correspond à ta recherche.",
    createRoom2: "Créer un salon",
    joinWithCode: "Rejoindre avec un code",
    paste: "Coller",
  },

  lobbyChatPanel: {
    reportThisLine: (p: { name: string }) => `Signaler cette ligne de ${p.name}`,
    couldNotSendThat: "Impossible d’envoyer cela.",
    chat: "Discussion",
    lobbyChat: "Discussion du hall",
    nobodyHasSaidAnythingYet: "Personne n’a encore rien dit.",
    chooseNameChat: "Choisis un nom pour discuter",
    saySomethingLobby: "Dis quelque chose au hall…",
    lobbyChatMessage: "Message de la discussion du hall",
    send: "Envoyer",
  },

  lobbyPlayerMenu: {
    whatToDoAbout: (p: { name: string }) => `Que faire au sujet de ${p.name}`,
    openPlayerProfile: "Ouvrir le profil du joueur",
    addAsFriend: "Ajouter en ami",
    report: "Signaler",
  },

  myPromptListsPage: {
    listSummary: (p: { prompts: number; visibility: string; moderationState: string | null }) =>
      `${counted(p.prompts, { one: "mot", other: "mots" })} · ${p.visibility}${
        p.moderationState ? ` · ${p.moderationState}` : ""
      }`,
    listUnderReview: (p: { state: string }) =>
      `Cette liste est ${p.state} et ne peut pas servir dans de nouvelles parties. La modifier ne la rétablit pas automatiquement ; un modérateur doit l’examiner.`,
    needsReview: (p: { count: number }) => `À examiner (${p.count})`,
    removePrompt: (p: { prompt: string }) => `Retirer ${p.prompt}`,
    couldNotLoadYourPromptLists: "Tes listes de mots n’ont pas pu être chargées.",
    couldNotOpenThatPromptList: "Cette liste de mots n’a pas pu être ouverte.",
    addAtLeastOnePromptBefore: "Ajoute au moins un mot avant d’enregistrer.",
    couldNotSaveThisPromptList: "Cette liste de mots n’a pas pu être enregistrée.",
    couldNotDeleteThisPromptList: "Cette liste de mots n’a pas pu être supprimée.",
    yourLibrary: "Ta bibliothèque",
    reusablePromptLists: "Listes de mots réutilisables",
    newList: "Nouvelle liste",
    createAccountSaveReviseSharePrompt: "Crée un compte pour enregistrer, réviser et partager des listes de mots. Les mots rapides d’un salon restent locaux et éphémères.",
    yourPromptLists: "Tes listes de mots",
    loading: "Chargement…",
    noSavedListsYet: "Aucune liste enregistrée pour l’instant.",
    name: "Nom",
    description: "Description",
    language: "Langue",
    visibility: "Visibilité",
    private: "Privée",
    anyoneWithCode: "Toute personne avec le code",
    shareCode: "Code de partage",
    couldNotCopyShareCode: "Le code de partage n’a pas pu être copié.",
    copy: "Copier",
    addPrompts: "Ajouter des mots",
    onePromptPerLineSeparateEntries: "Un mot par ligne\nou sépare les entrées par des virgules",
    addList: "Ajouter à la liste",
    noPromptsYetPasteSomeAbove: "Pas encore de mots. Colles-en quelques-uns ci-dessus pour commencer.",
    thisList: "Dans cette liste",
    searchPrompts: "Rechercher des mots",
    nothingMatchesThatSearch: "Rien ne correspond à cette recherche.",
    deleteList: "Supprimer la liste…",
  },

  notFoundPage: {
    nobodyDrewThisPage: "Personne n’a dessiné cette page",
    thatLinkDoesnTLeadAnywhere: "Ce lien ne mène nulle part sur Sketchy.",
    backLobby: "Retour au hall",
  },

  onlinePlayersPanel: {
    couldNotJoinThatGame: "Cette partie n’a pas pu être rejointe.",
    whoOnline: "Qui est en ligne",
    nobodyElseHereRightNow: "Il n’y a personne d’autre ici pour le moment.",
    friend: "Ami",
    join: "Rejoindre",
  },

  pictureCropDialog: {
    fileNotAPicture: "Ce fichier n’a pas pu être lu comme image.",
    couldNotSetThatPicturePlease: "Cette image n’a pas pu être définie. Réessaie.",
    frameYourPicture: "Cadre ton image",
    dragMoveZoomGetCloserCircle: "Fais glisser pour la déplacer et zoome pour t’approcher. Le cercle est ce que tout le monde voit.",
    pictureFramedArrowKeysMovePlus: "L’image, cadrée. Les flèches la déplacent ; plus et moins zooment.",
    zoom: "Zoom",
    cancel: "Annuler",
  },

  playerList: {
    requestCouldNotBeSent: "Cette demande n’a pas pu être envoyée.",
    nowFriends: (p: { name: string }) => `${p.name} et toi êtes maintenant amis.`,
    friendRequestSent: (p: { name: string }) => `Demande d’ami envoyée à ${p.name}.`,
    nothingToDoAbout: (p: { name: string }) => `Rien à faire au sujet de ${p.name} pour le moment.`,
    rank: (p: { rank: number }) => `Rang ${p.rank}`,
    moderationFor: (p: { name: string }) => `Modération pour ${p.name}`,
    moderationActionsFor: (p: { name: string }) => `Actions de modération pour ${p.name}`,
    thatRequestCouldNotBeSent: "Cette demande n’a pas pu être envoyée.",
    drawing: "Dessine",
    gotIt: "Trouvé ·",
    afk: "Absent",
    you: "(toi)",
    host: "Hôte",
    friend: "Ami",
    disconnected: "Déconnecté",
    kick: "Exclure",
    addFriend: "Ajouter en ami",
    sendRequest: "Envoyer une demande",
    report: "Signaler",
    toAModerator: "À un modérateur",
  },

  profilePage: {
    gamesPlayed: "Parties jouées",
    gamesWon: "Parties gagnées",
    winRate: "Taux de victoire",
    averageScore: "Score moyen",
    turnsPlayed: "Tours joués",
    promptsGuessed: "Mots trouvés",
    drawingsMade: "Dessins réalisés",
    reactionsReceived: "Réactions reçues",
    totalScore: "Score total",
    noSuchProfile: "Il n’y a aucun joueur avec ce profil.",
    couldNotLoadProfile: "Ce profil n’a pas pu être chargé. Réessaie.",
    gameMeta: (p: { finishedAt: string; rounds: number; players: number }) =>
      `${p.finishedAt} · ${counted(p.rounds, { one: "manche", other: "manches" })} · ${counted(p.players, { one: "joueur", other: "joueurs" })}`,
    seatScore: (p: { points: number }) => `${number(p.points)} pts`,
    gameRules: (p: {
      scoringMode: string;
      scoringVersion: number;
      hintMode: string;
      seconds: number;
      promptSource: string;
    }) =>
      `Règles : score ${p.scoringMode}${
        p.scoringVersion > 0 ? ` v${p.scoringVersion}` : " (version ancienne inconnue)"
      } · indices ${p.hintMode} · ${p.seconds} secondes · mots ${p.promptSource}`,
    reportPlayer: (p: { name: string }) => `Signaler ${p.name}`,
    privateRoom: "salon privé",
    thisGameDidNotFinishSo: "Cette partie n’est pas allée à son terme : voici donc les scores tels\n              qu’ils étaient à l’arrêt, et non un classement final.",
    loadingTurns: "Chargement des tours…",
    turnByTurn: "Tour par tour",
    round: "Manche",
    prompt: "Mot",
    drawnBy: "Dessiné par",
    time: "Temps",
    drawing: "Dessine",
    reactions: "Réactions",
    guesserOutcomes: "Résultats des devineurs",
    view: "Voir",
    couldNotLoadMoreGames: "Impossible de charger plus de parties.",
    loading: "Chargement…",
    friend: "Ami.",
    claimYourAccount: "Récupère ton compte",
    yourGamesAreAlreadyBeingRecorded: "Tes parties sont déjà enregistrées sous ce nom affiché.\n                Crée un compte pour les garder et l’utiliser comme nom d’utilisateur partout.",
    createAccount: "Créer un compte",
    statistics: "Statistiques",
    gameHistory: "Historique des parties",
    includeGamesThatFellApart: "Inclure les parties qui se sont effondrées",
  },

  promptContentReportDialog: {
    reportList: (p: { name: string }) => `Signaler ${p.name}`,
    couldNotSendReport: "Le rapport n’a pas pu être envoyé.",
    reportsAreReviewedAfterSubmissionList: "Les signalements sont examinés après envoi. La liste reste disponible sauf si un modérateur la masque.",
    content: "Contenu",
    entireList: "Liste entière",
    reason: "Motif",
    whatShouldModeratorKnow: "Que doit savoir le modérateur ?",
    cancel: "Annuler",
  },

  promptDisplay: {
    couldNotDoAction: (p: { action: string }) => `Impossible de ${p.action}.`,
    nextHintCost: (p: { cost: number }) => `Indice suivant : ${p.cost}`,
    hintSpendTotal: (p: { spent: number }) => `Total : ${p.spent}`,
    buyLetter: (p: { letter: string; price: number }) =>
      `Acheter « ${p.letter} » pour ${counted(p.price, { one: "point", other: "points" })}`,
    maskedPrompt: (p: { shape: string }) => `Mot masqué, ${p.shape} lettres`,
    buyThisLetter: (p: { cost: number }) =>
      `Acheter cette lettre pour ${counted(p.cost, { one: "point", other: "points" })}`,
    letterCount: (p: { count: number }) =>
      counted(p.count, { one: "lettre", other: "lettres" }),
    yourTurn: "À toi de jouer",
    pickSomethingDraw: "Choisis quelque chose à dessiner",
    autoPicksWhenTimeRunsOut: "Choix automatique à la fin du temps.",
    hintSpendLimitReached: "Limite de dépense en indices atteinte",
    deductedFromYourScoreIfYou: "Déduit de ton score si tu trouves le mot",
    buyLetterRevealsEveryMatch: "Achète une lettre — révèle toutes ses occurrences",
  },

  promptListPicker: {
    languageMismatch: (p: { listLanguage: string; roomLanguage: string }) =>
      `Cette liste est en ${p.listLanguage} ; ce salon est en ${p.roomLanguage}.`,
    choicesUnavailable: (p: { reason: string }) =>
      `Le choix des listes de mots est indisponible (${p.reason}). Ta sélection actuelle est inchangée.`,
    noListsInLanguage: (p: { language: string }) =>
      `Pas encore de listes en ${p.language} — ce salon puise dans ses propres mots.`,
    howListPlays: (p: { name: string }) => `Comment se jouent les mots de ${p.name}`,
    reportList: (p: { name: string }) => `Signaler ${p.name}`,
    failedLoadPromptLists: "Impossible de charger les listes de mots",
    couldNotAddThatSharedList: "Cette liste partagée n’a pas pu être ajoutée.",
    loadingCuratedPromptLists: "Chargement des listes de mots…",
    promptLists: "Listes de mots",
    addUnlistedListByCode: "Ajouter une liste non répertoriée par code",
  },

  promptStatsPage: {
    noSuchList: "Il n’y a aucune liste de mots portant ce nom.",
    couldNotLoadStats: "Ces statistiques n’ont pas pu être chargées. Réessaie.",
    showMore: (p: { count: number }) => `Voir ${p.count} de plus`,
    showingOf: (p: { shown: number; total: number }) => `Affichage de ${p.shown} sur ${p.total}`,
    couldNotLoadPromptListsPlease: "Les listes de mots n’ont pas pu être chargées. Réessaie.",
    serverWide: "Sur tout le serveur",
    promptStats: "Statistiques des mots",
    everyPromptListHowHasActually: "Chaque mot de la liste, et comment il s’est vraiment joué dans les parties\n          terminées de ce serveur.",
    promptList: "Liste de mots",
    sort: "Tri",
    period: "Période",
    scoring: "Score",
    hints: "Indices",
    findPrompt: "Trouver un mot",
    rollerCoaster: "montagnes russes",
    loading: "Chargement…",
    prompt: "Mot",
    howGoes: "Comment ça se passe",
    guessed: "Trouvé",
    picked: "Choisi",
    drawn: "Dessiné",
  },

  publicRoomCard: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "manche", other: "manches" }),
    promptLanguage: (p: { language: string }) => `Langue des mots : ${p.language}`,
    seeWhoThisRoom: "Voir qui est dans ce salon",
    rounds: "Manches",
    drawingTime: "Temps de dessin",
    full: "Complet",
    inProgress: "En cours",
    looking: "Recherche…",
    nobodySeatedYet: "Personne n’est encore assis.",
    host: "Hôte",
  },

  reactionRequests: {
    thatReactionCouldNotBeSent: "Cette réaction n’a pas pu être envoyée.",
  },

  recapDrawings: {
    thisDrawingCouldNotBeLoaded: "Ce dessin n’a pas pu être chargé.",
  },

  reportAccountDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Un modérateur le verra. Rien n’arrive à ${p.name} pour l’instant, et on ne lui dit pas qui l’a signalé.`,
    theirPicture: (p: { name: string }) => `image de ${p.name}`,
    thatReportCouldNotBeSent: "Ce signalement n’a pas pu être envoyé. Réessaie.",
    whatWrongWith: "Ce qui ne va pas",
    reportedTheirNameTheyHaveNo: "Signalé pour son nom. Il n’a pas d’image à signaler.",
    anythingElseOptional: "Autre chose (facultatif)",
    anythingModeratorShouldKnow: "Tout ce qu’un modérateur devrait savoir",
    sentWithWhatAboutAttached: "Envoyé, avec l’objet du signalement joint.",
    done: "Terminé",
  },

  reportedDrawing: {
    thisDrawingCouldNotBeDecoded: "Ce dessin n’a pas pu être décodé.",
    drawingCouldNotBeLoaded: "Le dessin n’a pas pu être chargé.",
  },

  reportLobbyLineDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Un modérateur verra cette ligne. Rien n’arrive à ${p.name} pour l’instant, et on ne lui dit pas qui l’a signalé.`,
    thatReportCouldNotBeSent: "Ce signalement n’a pas pu être envoyé. Réessaie.",
    whatWrongWith: "Ce qui ne va pas",
    anythingElseOptional: "Autre chose (facultatif)",
    anythingModeratorShouldKnow: "Tout ce qu’un modérateur devrait savoir",
    thisLineAttachedWithWhatLobby: "Cette ligne est jointe, avec ce que le hall disait autour.",
    sentWithLineWhatWasSaid: "Envoyé, avec la ligne et ce qui se disait autour.",
    done: "Terminé",
  },

  reportPlayerDialog: {
    reportCouldNotBeSent: "Ce signalement n’a pas pu être envoyé.",
    recentMessages: (p: { count: number }) =>
      `${p.count} de ses ${plural(p.count, { one: "message récent", other: "messages récents" })}`,
    nothingHappensYet: (p: { name: string }) =>
      `Un modérateur le verra. Rien n’arrive à ${p.name} pour l’instant, et on ne lui dit pas qui l’a signalé.`,
    whatHappened: "Ce qui s’est passé",
    anythingElseOptional: "Autre chose (facultatif)",
    whatTheySaidDrewWhen: "Ce qu’il a dit ou dessiné, et quand",
    theirRecentMessagesThisRoomAre: "Ses messages récents dans ce salon sont joints automatiquement,\n                avec ce qui se disait autour ; tu peux donc laisser ceci vide.",
    includeTheirDrawing: "Inclure son dessin",
    canvasAsRightNowSoModerator: "Le tableau tel qu’il est maintenant, pour qu’un modérateur voie\n                      ce que tu as vu.",
    done: "Terminé",
  },

  reportsReviewedNotice: {
    reportsReviewed: (p: { count: number }) =>
      `${counted(p.count, { one: "signalement que tu as envoyé a été examiné", other: "signalements que tu as envoyés ont été examinés" })}. Merci.`,
  },

  restartVoteBanner: {
    voteTally: (p: { yes: number; no: number; pending: number }) =>
      `${p.yes} pour, ${p.no} contre, ${p.pending} en attente`,
    restartingIn: (p: { seconds: number }) =>
      `Redémarrage dans ${counted(p.seconds, { one: "seconde", other: "secondes" })}`,
    restartApproved: "Redémarrage approuvé !",
    seconds: "secondes",
    voteRestartGame: "Voter pour redémarrer la partie",
    restart: "Redémarrer",
    keepPlaying: "Continuer à jouer",
    onlyEligiblePlayersPresentWhenVote: "Seuls les joueurs éligibles présents au lancement du vote peuvent voter.",
  },

  roleChangeNotice: {
    youHaveBeenSignedOutEvery: "Tu as été déconnecté de tous tes appareils pour que le changement\n            prenne effet. Reconnecte-toi pour continuer.",
    setUpNow: "Le configurer maintenant",
    later: "Plus tard",
  },

  roomChatPanel: {
    unreadMessages: (p: { count: number }) =>
      `${counted(p.count, { one: "nouveau message", other: "nouveaux messages" })}`,
    correctWithPlace: (p: { place: string | null }) =>
      p.place ? `Correct · ${p.place}` : "Correct",
    couldNotSendMessage: "Le message n’a pas pu être envoyé",
    sent: "Envoyé :",
    send: "Envoyer",
    youReDrawingWatchGuessesCome: "Tu dessines — regarde les propositions arriver.",
  },

  roomEntryState: {
    thisRoomNoLongerAvailable: "Ce salon n’est plus disponible",
    couldNotJoinThisRoom: "Impossible de rejoindre ce salon",
  },

  roomMenuSheet: {
    startTheGameOver: "Recommencer la partie",
    startOverCooldown: (p: { seconds: number }) => ` · dans ${p.seconds}s`,
    room: "Salon",
    playersScores: "Joueurs et scores",
    copyInviteLink: "Copier le lien d’invitation",
    saveThisDrawing: "Enregistrer ce dessin",
    settings: "Paramètres",
    leaveRoom: "Quitter le salon",
  },

  roomPlayersPanel: {
    spectatorCount: (p: { count: number }) =>
      counted(p.count, { one: "spectateur", other: "spectateurs" }),
    spectatorsHeading: (p: { count: number }) => `Spectateurs (${p.count})`,
    playersOfCapacity: (p: { here: number; capacity: number }) =>
      `${p.here} joueurs sur ${p.capacity}`,
    readyCount: (p: { count: number }) => `${p.count} prêts`,
    couldNotJoinAsPlayer: "Impossible de rejoindre comme joueur",
    finalStandings: "Classement final",
    players: "Joueurs",
  },

  roomSettingsEditor: {
    couldNotLoadRoomRules: "Impossible de charger les règles du salon",
    roomRefusedThoseSettings: "Le salon a refusé ces réglages.",
    hostSettings: "Réglages de l’hôte",
    editRoomRules: "Modifier les règles du salon",
    loadingSettings: "Chargement des réglages…",
    cancel: "Annuler",
  },

  roomSetupForm: {
    language: "Langue",
    visibility: "Visibilité",
    maxPlayers: "Joueurs maximum",
    rounds: "Manches",
    drawingTime: "Temps de dessin",
    onlyUseCustomPrompts: "N’utiliser que des mots personnalisés",
    addUsableCustomPromptEnableThis: "Ajoute un mot personnalisé utilisable pour activer cette option.",
    allowedTools: "Outils autorisés",
    colors: "Couleurs",
    scoring: "Score",
    hints: "Indices",
    spectatorsCanSeePrompt: "Les spectateurs voient le mot",
    hideBlanks: "Masquer les blancs",
    alsoTurnsHintsOffWithNo: "Désactive aussi les indices : sans blancs, il n’y a rien à révéler.",
    promptTotal: (p: { count: number }) =>
      counted(p.count, { one: "mot", other: "mots" }),
    basics: "Bases",
    roomName: "Nom du salon",
    public: "Public",
    private: "Privée",
    prompts: "Mots",
    drawing: "Dessine",
    scoringHints: "Score et indices",
    hintsAreOffBecauseBlanksAre: "Les indices sont désactivés car les blancs sont masqués.",
    pointPurchaseHintModesRequireScoring: "Les modes d’indice payants nécessitent un score.",
  },

  rulesPage: {
    sketchy: "Sketchy",
    theRules: "Les règles",
    thisPage: "Sur cette page",
    forExample: "Par exemple",
  },

  sessionManagerDialog: {
    lastUsed: (p: { when: string }) => `Dernière utilisation ${p.when}`,
    signsOutOn: (p: { when: string }) => `Se déconnecte tout seul ${p.when}`,
    usedElsewhere: (p: { when: string }) =>
      `Utilisé depuis un autre navigateur le ${p.when}. Révoque cet appareil si ce n’était pas toi.`,
    couldNotLoadSignedDevices: "Les appareils connectés n’ont pas pu être chargés.",
    couldNotRevokeDevice: "L’appareil n’a pas pu être révoqué.",
    couldNotLogOutEverywhere: "Impossible de se déconnecter partout.",
    signedDevices: "Appareils connectés",
    revokeAnyDeviceYouNoLonger: "Révoque tout appareil que tu ne reconnais plus. Les noms d’appareils sont approximatifs et ne stockent pas les versions de navigateur.\n          Un appareil que tu cesses d’utiliser se déconnecte seul au bout de quatre-vingt-dix jours.",
    loadingDevices: "Chargement des appareils…",
    currentDevice: "Appareil actuel",
    close: "Fermer",
  },

  settingsOverlay: {
    email: "E-mail",
    password: "Mot de passe",
    twoFactorAuthentication: "Double authentification",
    signedDevices: "Appareils connectés",
    downloadEverything: "Tout télécharger",
    colorScheme: "Thème de couleurs",
    appliesMomentYouPick: "S’applique dès que tu le choisis.",
    languageYouPlay: "Langue dans laquelle tu joues",
    roomsThisLanguageComeFirstLobby: "Les salons dans cette langue apparaissent en premier dans le hall, et un salon que tu crées démarre dedans. C’est distinct de la langue dans laquelle tu lis Sketchy.",
    interfaceLanguage: "Langue dans laquelle tu lis",
    interfaceLanguageHint: "Chaque mot de Sketchy lui-même. Distinct de la langue dans laquelle tu joues : lire dans l’une et jouer dans l’autre est tout à fait ordinaire.",
    timeFormat: "Format de l’heure",
    howEveryClockReadsChatTimestamps: "Comment se lit chaque horloge : horodatage du chat, dates de connexion, avis. « Système » suit ton appareil.",
    iHaveTroubleTellingColorsApart: "J’ai du mal à distinguer les couleurs",
    nudgesHostsTowardRoomColorsThat: "Oriente les hôtes vers des couleurs de salon qui restent distinguables avec une deutéranopie ou une protanopie, sans leur dire qui l’a demandé. Rien ne change tout seul.",
    brushCursor: "Curseur du pinceau",
    crosshairPreciseAtPointOutlineShows: "Une croix est précise au point ; un contour montre la largeur du trait.",
    brushCursorStyle: "Style du curseur du pinceau",
    soundEffects: "Effets sonores",
    chimesCorrectGuessStartRoundLast: "Des sons pour une bonne réponse, le début d’une manche, les dix dernières secondes, et les joueurs qui arrivent et partent.",
    volume2: "Volume",
    confetti: "Confettis",
    burstWhenYouGuessRightAgain: "Une salve quand tu trouves, et une autre pour le gagnant à la fin d’une partie.",
    clickKeyRebindEachActionCan: "Clique sur une touche pour la réassigner. Chaque action peut en garder deux. Échap pour annuler.",
    theseAreTheirSettings: (p: { name: string }) => `Ce sont désormais les réglages de ${p.name}.`,
    guestLivesInThisBrowser: (p: { name: string }) =>
      `${p.name} ne vit que dans ce navigateur. Un compte garde le nom, tes points et ton historique sur tous les appareils, et te laisse choisir une couleur.`,
    systemThemeNow: (p: { theme: "dark" | "light" }) => `Actuellement : ${p.theme}`,
    needsAccount: "Nécessite un compte",
    choosePicture: "Choisir une image",
    editPicture: "Modifier l’image",
    picture: "Image",
    changePicture: "Changer d’image",
    removePicture: "Retirer l’image",
    couldNotRemovePicture: "L’image n’a pas pu être retirée.",
    couldNotChangeYourDisplayName: "Ton nom affiché n’a pas pu être changé.",
    couldNotChangeYourDisplayName2: "Ton nom affiché n’a pas pu être changé. Réessaie.",
    themeSoundShortcutsCameFromAccount: "Le thème, le son et les\n            raccourcis viennent du compte. Ce que ce navigateur avait reste intact et\n            revient si tu te déconnectes.",
    dismiss: "Masquer",
    playingAsGuest: "Tu joues en invité",
    createAccount: "Créer un compte",
    logIn: "Se connecter",
    you: "Toi",
    displayName: "Nom affiché",
    cancel: "Annuler",
    change: "Changer",
    nameColor: "Couleur du nom",
    signingIn: "Connexion",
    changePassword: "Changer de mot de passe",
    manage: "Gérer",
    yourData: "Tes données",
    requestExport: "Demander un export",
    delete: "Supprimer…",
    display: "Affichage",
    theme: "Thème",
    accessibility: "Accessibilité",
    theCanvas: "Le tableau",
    sound: "Son",
    volume: "Volume",
    effects: "Effets",
    noKeyboardThisDevice: "Pas de clavier sur cet appareil",
    yourBindingsAreStillSavedStill: "Tes raccourcis restent enregistrés et fonctionnent. Ouvre Sketchy avec un clavier\n            branché pour les changer.",
    drawingTools: "Outils de dessin",
    resetDefaults: "Rétablir les valeurs par défaut",
    settings: "Paramètres",
    close: "Fermer",
    closeSettings: "Fermer les paramètres",
    settingsSections: "Sections des paramètres",
  },

  stepUpDialog: {
    codeFromYourAuthenticatorApp2: "Code de ton application d’authentification",
    passkeyNotUsed: "Cette clé d’accès n’a pas été utilisée. Tu peux réessayer.",
    thatCodeWasNotAccepted: "Ce code n’a pas été accepté.",
    thatPasskeyWasNotAccepted: "Cette clé d’accès n’a pas été acceptée.",
    confirmYou: "Confirme que c’est bien toi",
    recoveryCode: "Code de récupération",
    codeFromYourAuthenticatorApp: "Code de ton application d’authentification",
    cancel: "Annuler",
  },

  suspensionNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Ton dessin de ${p.prompt}, tel qu’il a été signalé`,
    recordedAs: "Enregistré comme {category}",
    yourAccountSuspended: "Ton compte est suspendu",
    youWereAskedDraw: "C’était à toi de dessiner",
  },

  toastProvider: {
    notifications: "Notifications",
    dismissNotification: "Masquer la notification",
  },

  toolbar: {
    colorOption: (p: { color: string }) => `couleur ${p.color}`,
    adjustSize: (p: { tool: string }) => `Ajuster la taille de ${p.tool}`,
    sizeSnappingSlider: (p: { tool: string }) => `Curseur de taille par crans pour ${p.tool}`,
    chooseToolCurrent: (p: { tool: string }) => `Choisir un outil, actuel : ${p.tool}`,
    chooseColorCurrent: (p: { color: string }) => `Choisir une couleur, actuelle ${p.color}`,
    sizeWithWidth: (p: { tool: string; width: number }) => `${p.tool}, taille ${p.width}px`,
    sizeShortcutHint: (p: { tool: string; width: number }) =>
      `${p.tool}, taille : ${p.width}px ([ / ])`,
    widthReadout: (p: { width: number }) => `${p.width}px`,
    colorSwatch: (p: { color: string }) => `Couleur ${p.color}`,
    drawingTools: "Outils de dessin",
    chooseTool: "Choisir un outil",
    chooseColor: "Choisir une couleur",
    undoLastStroke: "Annuler le dernier trait",
    undo: "Annuler",
    clearCanvas: "Effacer le tableau",
    chooseCustomColor: "Choisir une couleur personnalisée",
    colorPalette: "Palette de couleurs",
    canvasActions: "Actions du tableau",
    undoLastStrokeCtrlZ: "Annuler le dernier trait (Ctrl+Z)",
    clear: "Effacer",
  },

  turnResultsOverlay: {
    yourTurnWithHints: (p: { base: number; hintSpend: number; points: number; rank: number }) =>
      `Ton tour : +${p.base} -${p.hintSpend} indices = ${counted(p.points, { one: "point", other: "points" })} · maintenant #${p.rank}`,
    yourTurn: (p: { delta: number; rank: number }) =>
      `Ton tour : ${p.delta >= 0 ? "+" : ""}${p.delta} ${
        Math.abs(p.delta) === 1 ? "point" : "points"
      } · maintenant #${p.rank}`,
    promptWas: "Le mot était",
    noOneGuessedCorrectly: "Personne n’a trouvé.",
    you: "(toi)",
    drewThisTurn: "A dessiné ce tour",
    nextTurn: "Tour suivant",
  },

  twoFactorDialog: {
    scanThisWithYourAuthenticatorApp: "Scanne ceci avec ton application d’authentification pour ajouter ce compte",
    codeFromYourAuthenticatorApp: "Code de ton application d’authentification",
    secondFactorState: (p: {
      recoveryCodesRemaining: number | null;
      confirmAuthenticator: boolean;
    }) =>
      [
        "La double authentification est active.",
        p.recoveryCodesRemaining === null
          ? null
          : `Il te reste ${counted(p.recoveryCodesRemaining, {
              one: "code de récupération",
              other: "codes de récupération",
            })}.`,
        p.confirmAuthenticator
          ? "Avant que ce compte puisse recevoir un rôle de modérateur ou d’administrateur, confirme avec ton mot de passe et un code que l’authentificateur est le tien."
          : null,
        "Chacun des changements ci-dessous remplace un identifiant, chacun demande donc ton mot de passe.",
      ]
        .filter(Boolean)
        .join(" "),
    confirmAuthenticatorFirst:
      "Avant que ce compte puisse recevoir un rôle de modérateur ou d’administrateur, confirme avec ton mot de passe et un code que l’authentificateur est le tien.",
    copied: (p: { what: string }) => `${p.what} copié.`,
    couldNotCopy: (p: { what: string }) =>
      `Impossible de copier ${p.what}. Sélectionne-le et copie-le à la main.`,
    roleTaken: (p: { role: "admin" | "moderator" }) =>
      `Tu es maintenant ${p.role === "admin" ? "administrateur" : "modérateur"}. La double authentification est active, et le rôle qui l’attendait a pris effet. Tes autres appareils ont été déconnectés ; celui-ci continue, et chaque connexion depuis ici demandera un code.`,
    recoveryCodesLeft: (p: { count: number }) =>
      `Il te reste ${counted(p.count, { one: "code de récupération", other: "codes de récupération" })}.`,
    couldNotReadYourSecuritySettings: "Tes réglages de sécurité n’ont pas pu être lus.",
    yourPasswordConfirmsAuthenticatorYours: "Ton mot de passe confirme que l’authentificateur est le tien.",
    yourPasswordConfirmsThisPasskeyYours: "Ton mot de passe confirme que cette clé d’accès est la tienne.",
    passkeyAdded: "Clé d’accès ajoutée.",
    thatPasskeyWasNotCreatedYou: "Cette clé d’accès n’a pas été créée. Tu peux réessayer.",
    yourPasswordNeededRemovePasskey: "Ton mot de passe est nécessaire pour retirer une clé d’accès.",
    confirmedThisAccountCanNowBe: "Confirmé. Ce compte peut désormais recevoir un rôle d’équipe.",
    twoFactorAuthentication: "Double authentification",
    saveTheseRecoveryCodesNow: "Enregistre ces codes de récupération maintenant.",
    eachOneSignsYouOnceIf: "Chacun te connecte une\n              fois si tu perds ton application d’authentification. Ils ne sont\n              plus affichés ensuite — seuls leurs empreintes sont conservées.",
    recoveryCodes: "Codes de récupération",
    downloadAsFile: "Télécharger en fichier",
    copyAll: "Tout copier",
    iHaveSavedTheseSomewhereSafe: "Je les ai enregistrés en lieu sûr",
    done: "Terminé",
    moderatorsAdministratorsSignWithPasskeyYour: "Les modérateurs et administrateurs se connectent avec une clé d’accès :\n              ton appareil confirme que c’est toi — empreinte, visage ou code\n              PIN — et rien de divulgable n’est tapé.",
    yourPassword: "Ton mot de passe",
    confirmsPasskeyBeingAddedByYou: "Confirme que c’est bien toi qui ajoutes la clé d’accès.",
    useAuthenticatorAppInstead: "Utiliser plutôt une application d’authentification",
    scanCodeWithAuthenticatorAppThen: "Scanne le code avec une application d’authentification, puis tape les\n              six chiffres qu’elle affiche.",
    drawingCode: "Dessin du code…",
    pointYourAppAtThis: "Pointe ton application ici.",
    setupKey: "Clé de configuration",
    copySetupKey: "Copier la clé de configuration",
    useThisIfYouCanT: "Utilise ceci si tu ne peux pas scanner.",
    confirmsAuthenticatorYours: "Confirme que l’authentificateur est le tien.",
    codeFromYourApp: "Code de ton application",
    cancel: "Annuler",
    passkeys: "Clés d’accès",
    thisDeviceOnly: "· sur cet appareil uniquement",
    remove: "Retirer",
    confirmSYours: "Confirmer qu’elle est à toi",
    addPasskey: "Ajouter une clé d’accès",
    newRecoveryCodes: "Nouveaux codes de récupération",
    turnOff: "Désactiver",
    addAuthenticatorApp: "Ajouter une application d’authentification",
    close: "Fermer",
  },

  useFriendArrivalNotices: {
    wantsToBeFriends: (p: { name: string }) => `${p.name} veut être ton ami.`,
    acceptedYourRequest: (p: { name: string }) => `${p.name} a accepté ta demande d’ami.`,
    severalAccepted: (p: { count: number }) =>
      `${counted(p.count, { one: "personne a accepté", other: "personnes ont accepté" })} tes demandes d’ami.`,
  },

  useRoomSessionReconnect: {
    joinRoomFailed: "join_room failed",
  },

  waitingRoomPanel: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "manche", other: "manches" }),
    needMorePlayers: (p: { count: number }) =>
      `${counted(p.count, { one: "Il manque 1 joueur", other: "Il manque des joueurs" })}`,
    hostWillStart: (p: { rematch: boolean }): string =>
      p.rematch ? "{host} lancera la revanche" : "{host} lancera la partie",
    copied: (p: { what: string }) => `${p.what} copié.`,
    couldNotCopy: (p: { what: string }) =>
      `Impossible de copier ${p.what}. Copie-le depuis la barre d’adresse.`,
    roomCodeLabel: (p: { code: string }) => `Code du salon ${p.code}`,
    rosterCount: (p: { here: number; capacity: number }) => `${p.here} sur ${p.capacity}`,
    inviteYourFriends: "Invite tes amis",
    shareLink: "Partage le lien",
    copyCode: "Copier le code",
    inTheRoom: "Dans le salon",
    you: "(toi)",
    host: "Hôte",
    friend: "Ami",
    invite: "Inviter",
    edit: "Modifier",
    viewHighlights: "Voir les moments forts",
    viewDrawings: "Voir les dessins",
  },

  warningNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Ton dessin de ${p.prompt}, tel qu’il a été signalé`,
    recordedAs: "Enregistré comme {category}",
    whatAWarningMeans:
      "Un signalement concernant ton comportement a été examiné, et voici le résultat. Rien n’est restreint, mais un nouveau signalement pourrait entraîner la suspension de ton compte.",
    youWereAskedDraw: "C’était à toi de dessiner",
  },
};
