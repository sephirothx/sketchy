/** Every word the interface says, in Spanish.

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

const { counted, number, ordinal, plural } = formattersFor("es", {"other":"º"});


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
      return `La contraseña debe tener al menos ${count(detail, 12)} caracteres.`;
    case "too_long":
      return `La contraseña debe tener como máximo ${count(detail, 128)} caracteres.`;
    case "common":
      return "Esa contraseña es una de las más usadas. Elige otra.";
    case "common_repeated":
      return "Eso es una contraseña común repetida. Elige otra.";
    case "short_repeated":
      return "Esa contraseña es una corta repetida. Elige otra.";
    case "too_few_characters":
      return `Esa contraseña solo usa ${count(detail, 4)} caracteres distintos. Elige otra.`;
    case "keyboard_walk":
      return "Esa contraseña es sobre todo una fila de teclas seguidas. Elige otra.";
    case "contains_identity":
      return "Una contraseña no puede contener tu nombre, tu correo ni el nombre de este sitio.";
    case "common_with_digits":
      return "Eso es una contraseña común con dígitos añadidos. Elige otra.";
    default:
      return "Elige una contraseña distinta.";
  }
}

/** *Create an account to …* - one refusal, said about the thing it refused. */
function accountRequired(params: MessageParams): string {
  switch (params.action) {
    case "avatar":
      return "Crea una cuenta para elegir una imagen.";
    case "prompt_lists":
      return "Crea una cuenta para guardar listas de palabras reutilizables.";
    case "name_color":
      return "Crea una cuenta para elegir un color de nombre.";
    case "password":
      return "Crea una cuenta para establecer una contraseña.";
    case "second_factor":
      return "Crea una cuenta antes de configurar la verificación en dos pasos.";
    case "friends":
      return "Crea una cuenta para añadir amigos.";
    case "stars":
      return "Hace falta una cuenta para dar estrellas a las listas.";
    default:
      return "Crea una cuenta para hacer eso.";
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
      return "hay una actualización del servidor en curso";
    case "too_few_players":
      return "quedan menos de dos jugadores activos";
    case "prompt_lists_unavailable":
      return "no se pudieron cargar las listas de palabras";
    case "everybody_left":
      return "todos se fueron antes de empezar";
    default:
      return "ya no podía seguir adelante";
  }
}

type Sentence = string | ((params: MessageParams) => string);

/** Why the server refused, said to the player.

One entry per `ErrorCode`; `Record` makes it exhaustive, so a code the server
adds without a sentence here fails the build rather than the player
(R-I18N-04). */
const REFUSALS: Record<ErrorCode, Sentence> = {
  // Payloads and arguments
  invalid_payload: "Sketchy no pudo leer esa petición.",
  invalid_nickname: "Ese nombre no se puede usar aquí.",
  invalid_name_color: "Elige un color que se lea bien en la lista de jugadores clara y en la oscura.",
  invalid_hint: "Esa pista no es válida.",
  invalid_letter: "Esa letra no es válida.",
  invalid_prompt_lists: "Esas listas de palabras no se pueden usar juntas.",
  invalid_custom_prompts: "No se pudieron leer esas palabras propias.",
  max_players_below_seated: (params) =>
  `El máximo de jugadores no puede ser menor que los ${count(params.seated, 2)} que ya están en la sala.`,
  empty_message: "Escribe algo primero.",

  // Rate and capacity
  too_fast: "Vas demasiado rápido. Baja un poco el ritmo.",
  seat_changing_too_fast: "Esta plaza cambia de manos demasiado rápido. Inténtalo dentro de un minuto.",
  joining_too_fast: "Entras en salas demasiado rápido. Inténtalo dentro de un minuto.",
  room_quota: "Ya tienes tantas salas abiertas como puedes tener a la vez.",
  room_full: "Esta sala está llena.",
  spectators_full: "Esta sala no admite más espectadores.",
  player_slots_full: "Todas las plazas de jugador están ocupadas.",

  // Server and account state
  server_draining: "Sketchy se está reiniciando. Inténtalo en un momento.",
  server_paused: "Sketchy no admite salas nuevas ahora mismo.",
  database_busy: "Sketchy no consigue llegar a su base de datos. Inténtalo de nuevo.",
  account_ended: "Esta cuenta ya no está activa.",
  account_required: accountRequired,
  identity_unavailable: "Sketchy no pudo confirmar quién eres. Recarga e inténtalo de nuevo.",

  // Rooms
  not_in_room: "No estás en esta sala.",
  room_not_found: "Sala no encontrada.",
  room_ended: "Esta sala ha terminado.",
  could_not_create_room: "No se pudo crear la sala.",
  no_session_to_resume: "No hay ninguna sesión tuya que retomar en esta sala.",
  host_only: "Eso solo lo puede hacer el anfitrión.",
  players_only: "Eso solo lo pueden hacer los jugadores.",
  waiting_room_only: "Eso solo está disponible en la sala de espera.",
  already_a_player: "Ya eres jugador.",
  registered_name_fixed: "Los jugadores registrados juegan con su nombre de usuario.",
  name_taken_by_account: "Ese nombre pertenece a un jugador registrado.",
  guests_cannot_choose_color: "Crea una cuenta para elegir un color de nombre.",
  suggestion_inactive: "Esta sugerencia ya no está activa.",
  drawing_not_found: "Dibujo no encontrado.",
  drawing_not_kept: "Este dibujo no se conservó.",

  // Games and turns
  not_in_game: "No estás en una partida activa.",
  game_in_progress: "La partida ya está en curso.",
  game_starting: "La partida todavía está empezando.",
  need_two_players: "Hacen falta dos jugadores activos para empezar.",
  room_not_startable: "Esta sala no puede empezar una partida ahora mismo.",
  prompt_not_ready: "La partida aún no está lista para una palabra.",
  prompt_unavailable: "Esa palabra ya no está disponible.",
  hints_disabled: "Las pistas están desactivadas en esta sala.",
  hint_spend_limit: "Has llegado al límite de gasto en pistas de este turno.",
  hint_unavailable: "Esa pista no está disponible.",

  // Canvas
  drawer_only: "Eso solo lo puede hacer quien dibuja.",
  canvas_stale_generation: "El lienzo ha avanzado. Poniéndose al día.",
  canvas_sequence_committed: "Eso ya se ha dibujado.",
  canvas_out_of_sequence: "Las acciones de dibujo llegaron desordenadas. Poniéndose al día.",
  canvas_out_of_sync: "El lienzo está desincronizado. Poniéndose al día.",
  nothing_to_undo: "No hay nada que deshacer.",

  // Votes and restarts
  spectators_cannot_vote: "Los espectadores no pueden votar.",
  spectators_cannot_be_targets: "Un espectador no puede ser objeto de una votación.",
  invalid_vote_target: "No puedes votar sobre ese jugador.",
  not_eligible: "Solo los jugadores activos pueden proponer un reinicio.",
  restart_vote_active: "Ya hay una votación de reinicio en marcha.",
  restart_vote_cooldown: "Se acaba de votar un reinicio. Espera un poco antes de proponer otro.",
  no_restart_vote: "No hay ninguna votación de reinicio que responder.",
  restart_vote_closed: "Esa votación de reinicio ya está cerrada.",

  // Reactions
  spectators_cannot_react: "Los espectadores no pueden reaccionar a un dibujo.",
  guests_cannot_react: "Crea una cuenta para reaccionar a un dibujo.",
  reaction_not_visible: "No puedes reaccionar a un dibujo que no ves.",
  own_drawing: "No puedes reaccionar a tu propio dibujo.",
  game_still_saving: "Esa partida todavía se está guardando. Inténtalo en un momento.",
  game_not_recorded: "Esa partida no se registró.",
  reaction_not_accepted: "No se pudo enviar esa reacción.",

  // Friends
  friends_unavailable: "Los amigos no están disponibles ahora mismo.",
  friend_refused: "No se pudo completar esa solicitud de amistad.",
  friend_not_in_game: "Tu amigo no está en ninguna partida ahora mismo.",
  friend_in_several_games: "Ese amigo está en más de una partida. Pídele una invitación.",
  not_friends: "Solo puedes unirte a la partida de un amigo.",
  friends_only_uninvited: "Solo los amigos del anfitrión pueden unirse sin invitación. Pídele una.",
  invite_expired: "Esa invitación ha caducado.",

  // Moderation, from the reporter's side
  reporting_unavailable: "Los informes no están disponibles en este servidor.",
  no_such_player: "No existe ese jugador.",
  cannot_report: "Ese jugador no se puede denunciar.",
  already_reported: "Ya has denunciado esto y un moderador todavía no lo ha revisado.",

  // Lobby chat
  name_required: "Elige un nombre antes de decir nada en el vestíbulo.",
  not_watching_lobby: "Ya no estás viendo el vestíbulo.",

  // Versioning
  protocol_mismatch: "Esta pestaña usa una versión antigua de Sketchy. Recarga la página para continuar.",

  // Sessions and accounts
  sign_in_required: "Inicia sesión primero.",
  credentials_incorrect: "Nombre de usuario o contraseña incorrectos.",
  password_incorrect: "La contraseña es incorrecta.",
  account_suspended: "Esta cuenta está suspendida.",
  already_signed_in: "Ya has iniciado sesión en una cuenta.",
  username_taken: "Ese nombre de usuario está cogido.",
  invalid_username: "Ese nombre de usuario no se puede usar.",
  weak_password: weakPassword,
  password_change_failed: "No se pudo cambiar la contraseña.",
  session_not_found: "Ese dispositivo ya no tiene la sesión iniciada.",
  session_replaced: "Esta sesión ha sido sustituida. Recarga e inténtalo de nuevo.",
  guest_progress_unlinked: "No se pudo vincular el progreso de invitado a esta cuenta.",
  not_taking_visitors: "Sketchy no admite visitantes nuevos ahora mismo. Inténtalo más tarde.",
  account_delete_refused: "La cuenta no se pudo borrar ahora mismo. Inténtalo de nuevo.",
  password_required_to_delete: "Introduce tu contraseña para borrar la cuenta.",

  // Second factor and passkeys
  second_factor_required: "Introduce el código de tu aplicación de autenticación.",
  second_factor_passkey_only: "Inicia sesión con tu passkey.",
  second_factor_not_enrolled:
  "Esta cuenta necesita la verificación en dos pasos antes de poder iniciar sesión. Pide ayuda a un administrador para configurarla.",
  second_factor_not_set_up: "La verificación en dos pasos no está configurada.",
  second_factor_code_wrong: "Ese código no es correcto.",
  second_factor_throttled: "Demasiados códigos incorrectos. Espera un poco e inténtalo de nuevo.",
  step_up_required: "Confirma que eres tú antes de hacer eso.",
  passkey_sign_in_required: "Inicia sesión con tu passkey.",
  passkey_not_registered: "Esa passkey no está registrada aquí.",
  passkey_not_found: "No existe esa passkey.",
  passkey_refused:
  "Las passkeys son para cuentas de moderador y administrador. Se te pedirá configurar una si alguna vez te ofrecen un rol.",
  last_factor: "Esa es la única forma que tienes de demostrar que eres tú. Añade otra antes de quitar esta.",
  second_factor_required_for_role: "El rol de esta cuenta exige la verificación en dos pasos.",
  second_factor_not_proved:
  "Este autenticador aún no se ha confirmado como tuyo. Usa una passkey o confírmalo con tu contraseña en Ajustes.",

  // Email, verification and recovery
  invalid_email: "Eso no parece una dirección de correo.",
  email_in_use: "Esa dirección ya está en uso.",
  email_change_refused: "Esa dirección no se puede añadir a esta cuenta.",
  verification_link_invalid: "Ese enlace de confirmación ha caducado o ya se ha usado.",
  reset_link_invalid: "Ese enlace de restablecimiento ha caducado o ya se ha usado.",

  // Account data export
  export_not_found: "Exportación no encontrada.",
  export_expired: "La exportación ha caducado.",
  export_not_ready: "La exportación aún no está lista.",
  export_unreadable: "No se pudo leer el documento de exportación. Pide una nueva.",
  export_not_yet_allowed: "Has pedido una exportación hace poco. Inténtalo más tarde.",
  export_refused: "No se pudo iniciar esa exportación. Inténtalo de nuevo.",

  // Rate limits reached over HTTP
  too_many_attempts: "Demasiados intentos. Espera un poco e inténtalo de nuevo.",
  too_many_requests: "Demasiadas peticiones. Espera un poco e inténtalo de nuevo.",
  too_many_reports: "Demasiadas denuncias. Espera antes de enviar otra.",
  too_many_bug_reports: "Demasiados informes de fallos. Espera antes de enviar otro.",
  too_many_pictures: "Demasiadas imágenes. Espera un poco e inténtalo de nuevo.",

  // Pictures
  unsupported_picture_type: "Eso no es una imagen WebP ni PNG.",
  picture_not_found: "No existe esa imagen.",
  picture_refused: "Esa imagen no se puede usar aquí.",

  // Bug reports
  screenshot_unreadable: "No se pudo leer la captura.",
  screenshot_too_large: (params) =>
  `Esa captura es demasiado grande. El límite es ${megabytes(params.limitBytes, "2 MB")}.`,
  screenshot_unsupported_type: "Una captura debe ser una imagen PNG o WebP.",
  bug_report_context_too_large: "Ese informe lleva demasiado contexto.",

  // Friends, over HTTP
  friends_throttled: "Has enviado muchas solicitudes de amistad. Inténtalo más tarde.",
  that_is_you: "Ese eres tú.",

  // Profiles and history
  no_such_game: "No existe esa partida.",
  no_such_drawing: "No existe ese dibujo.",
  drawing_unreadable: "No se pudo leer ese dibujo.",

  // Prompt lists
  prompt_list_not_found: "Lista de palabras no encontrada.",
  shared_prompt_list_not_found: "No se encontró ninguna lista compartida.",
  prompt_list_conflict: "Otra persona ha cambiado esa lista. Recárgala e inténtalo de nuevo.",
  prompt_list_invalid: "No se pudo guardar esa lista de palabras.",
  prompt_list_forbidden: "Esa lista de palabras no es tuya para cambiarla.",
  prompt_list_allowance_reached: (params: Record<string, unknown>) => {
    const max = typeof params.max === "number" ? params.max : 25;
    return `Ya hay ${max} listas de palabras, el máximo por cuenta. Hay que eliminar una para hacer sitio.`;
  },
  email_verification_required: (params: Record<string, unknown>) => {
    switch (params.action) {
      case "publish":
        return "Para publicar una lista hace falta un correo electrónico confirmado.";
      case "star":
        return "Para dar una estrella a una lista hace falta un correo electrónico confirmado.";
      default:
        return "Para eso hace falta un correo electrónico confirmado.";
    }
  },
  warning_unread: (params: Record<string, unknown>) => {
    switch (params.action) {
      case "publish":
        return "Antes de publicar una lista hay que leer el aviso de moderación.";
      case "star":
        return "Antes de dar una estrella hay que leer el aviso de moderación.";
      default:
        return "Primero hay que leer el aviso de moderación.";
    }
  },
  prompt_list_hidden: "Esta lista está oculta y no se puede publicar. Primero tiene que revisarla la moderación.",
  unknown_prompt_tag: (params: Record<string, unknown>) => {
    const tag = String(params.tag ?? "");
    return `«${tag}» no es una etiqueta que pueda llevar una lista.`;
  },
  unknown_sort: "Sketchy no puede ordenar por eso.",
  timezone_required: "Incluye una zona horaria con esa fecha.",
  range_reversed: "El inicio del intervalo debe ir antes que su final.",

  // Room presets
  room_preset_not_found: "Plantilla de sala no encontrada.",
  room_preset_conflict: "Ya tienes una plantilla con ese nombre.",
  room_preset_unavailable: "Esa plantilla no se puede usar ahora mismo.",
  room_preset_forbidden: "Esa plantilla no es tuya.",

  // Blocks
  cannot_block_yourself: "No puedes bloquearte a ti mismo.",
  block_list_full: (params) =>
  `Tu lista de bloqueos está llena${
    typeof params.limit === "number" ? ` en ${params.limit}` : ""
  }. Desbloquea a alguien primero.`,

  // Settings
  setting_refused: "No se pudo guardar ese ajuste.",

  // Role notices
  no_such_notice: "No existe ese aviso.",

  // Reporting, from the reporter's side
  cannot_report_yourself: "No puedes denunciarte a ti mismo.",
  cannot_report_own_prompt_list: "No puedes denunciar tu propia lista de palabras.",
  no_reportable_prompt_list: "No se encontró ninguna lista denunciable.",
  prompt_not_in_list: "Esa palabra no pertenece a esta lista.",
  no_picture_to_report: "Ese jugador no tiene imagen que denunciar.",
  no_such_game_context: "No existe ese contexto de partida.",
  no_such_turn_context: "No existe ese contexto de turno.",
  turn_not_in_game: "El turno no pertenece a esa partida.",
  evidence_unavailable: "Uno o más mensajes seleccionados no están disponibles.",
  evidence_mixed_scopes: "Los mensajes del vestíbulo y de la sala no se pueden mezclar en una denuncia.",
  evidence_several_rooms: "Los mensajes seleccionados deben venir de la misma sala.",
  evidence_not_theirs: "Las pruebas deben ser del jugador denunciado.",
  evidence_not_received: "No puedes seleccionar un mensaje que no recibiste.",
  evidence_not_in_game: "El mensaje seleccionado no pertenece a esa partida.",
  evidence_not_in_turn: "El mensaje seleccionado no pertenece a ese turno.",
  no_such_warning: "No existe esa advertencia.",
  no_drawing: "Sin dibujo.",};

/** What the room says about itself. One entry per `AnnouncementCode`. */
const ANNOUNCEMENTS: Record<AnnouncementCode, (params: MessageParams) => string> = {
  nickname_changed: (p) =>
  `${text(p.previous)} ahora se llama ${text(p.nickname)}.`,
  joined_as_player: (p) => `${text(p.nickname)} se ha unido como jugador.`,
  kicked_by_vote: (p) => `${text(p.nickname)} fue expulsado por votación.`,
  marked_afk_by_vote: (p) => `${text(p.nickname)} fue marcado como ausente por votación.`,

  restart_vote_started: (p) =>
  `${text(p.nickname)} ha iniciado una votación para reiniciar la partida.`,
  restart_vote_passed: (p) =>
  `La votación de reinicio salió adelante. Reiniciando en ${count(p.seconds, 5)} segundos.`,
  restart_vote_rejected: () => "La votación de reinicio fue rechazada.",
  restart_vote_expired: () => "La votación de reinicio caducó sin salir adelante.",
  restart_vote_abandoned: () =>
  "La votación de reinicio se canceló porque quedan menos de dos jugadores activos.",
  restart_cancelled: (p) => `El reinicio se canceló porque ${cancelReason(p.reason)}.`,
  game_restarted_by_vote: () => "La partida se reinició por votación de los jugadores.",

  hint_letter_found: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pts - encontrada ${counted(count(p.count, 1), {
    one: "vez",
    other: "veces",
  })}!`,
  hint_letter_missing: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pts - no está en la palabra.`,
  guess_very_close: (p) => `¡«${text(p.text)}» está muy cerca!`,
  guess_some_words_correct: () => "Algunas palabras son correctas",};

export const ES: Catalogue = {
  refusals: REFUSALS,
  announcements: ANNOUNCEMENTS,

  /** What the document itself says: the tab, and what a link preview shows.

      Rendered into `index.html` for a crawler, which arrives before any
      script, and rewritten here for the reader once their locale is known. */
  document: {
    description: "¡Dibuja, adivina y ríe con tus amigos!",
  },

  /** Shapes that belong to the language rather than to any one screen. */
  format: {
    /** `1st`, `2nd`, `3rd`; a language with no ordinal form gets the number. */
    ordinal: (p: { value: number }) => ordinal(p.value),
  },

  promptListDrafts: {
    promptsAdded: (p: { count: number }) =>
      `${counted(p.count, { one: "palabra añadida", other: "palabras añadidas" })}`,
    duplicatesAlreadyInTheList: (p: { duplicates: number }) =>
      `${p.duplicates} ya en la lista`,
    tooLongCountOverMaxListPrompt: (p: { tooLongCount: number; MAX_LIST_PROMPT_LENGTH: number }) =>
      `${p.tooLongCount} de más de ${p.MAX_LIST_PROMPT_LENGTH} caracteres`,
    overLimitPastTheMaxList: (p: { overLimit: number; MAX_LIST_PROMPTS: number }) =>
      `${p.overLimit} por encima del límite de ${p.MAX_LIST_PROMPTS}`,
    keptSkippedSkipped: (p: { kept: string; skipped: string }) =>
      `${p.kept}; omitidas: ${p.skipped}.`,
  },

  lastSeen: {
    online: "en línea",
    justNow: "visto justo ahora",
    lastSeenAgo: (p: { count: number; unit: "minute" | "hour" | "day" }) => {
      const words = {
        minute: { one: "minuto", other: "minutos" },
        hour: { one: "hora", other: "horas" },
        day: { one: "día", other: "días" },
      }[p.unit];
      return `visto hace ${counted(p.count, words)}`;
    },
  },

  gameHighlights: {
    reactionCount: (p: { count: number }) =>
      counted(p.count, { one: "reacción", other: "reacciones" }),
    hardestPrompt: "Palabra más difícil",
    fastestGuess: "Acierto más rápido",
    bestDrawer: "Mejor dibujante",
    quickestOnAverage: "Más rápido de media",
    mostReactedDrawing: "Dibujo con más reacciones",
    guessedItOf: (p: { correct: number; total: number }) =>
      plural(p.correct, { one: `${p.correct} de ${p.total} la adivinó`, other: `${p.correct} de ${p.total} la adivinaron` }),
    percentGuessed: (p: { percent: string }) =>
      `${p.percent} adivinado`,
  },

  versionBadge: {
    buildDetails: (p: { commitDate: string; builtAt: string }) =>
      `Fecha del commit: ${p.commitDate} | Compilado: ${p.builtAt}`,
  },

  segmentedCodeInput: {
    digitPosition: (p: { label: string; index: number; length: number }) =>
      `${p.label}, dígito ${p.index} de ${p.length}`,
  },

  roomSetupControls: {
    decrease: (p: { label: string }) => `Reducir ${p.label}`,
    increase: (p: { label: string }) => `Aumentar ${p.label}`,
  },

  guessPips: {
    playerGuessState: (p: { nickname: string; isFriend: boolean; guessed: boolean }) =>
      `${p.nickname}${p.isFriend ? " (amigo)" : ""} ${p.guessed ? "lo ha adivinado" : "sigue adivinando"}`,
    gotOfGuessersCountGuessed: (p: { got: number; guessersCount: number }) =>
      `${p.got} de ${p.guessersCount} acertaron`,
    summaryOpenPlayersAndScores: (p: { summary: string }) =>
      `${p.summary}. Abrir jugadores y puntos.`,
  },

  accountDataDialog: {
    requestedOn: (p: { when: string; schemaVersion: number }) =>
      `Pedida ${p.when} · formato v${p.schemaVersion}`,
    exportAllowance: (p: { nextAllowed: string | null }) =>
      p.nextAllowed
        ? `Una exportación por semana; las listas caducan a los siete días. Puedes pedir otra el ${p.nextAllowed}.`
        : "Una exportación por semana; las listas caducan a los siete días.",
    couldNotLoadYourDataExports: "No se pudieron cargar tus exportaciones de datos.",
    couldNotRequestYourDataExport: "No se pudo pedir tu exportación de datos.",
    yourData: "Tus datos",
    downloadPrivateJsonCopyYourAccount: "Descarga una copia privada en JSON de tu cuenta y tus datos de juego. No incluye perfiles ni mensajes de otros jugadores.",
    dataExports: "Exportaciones de datos",
    loadingExports: "Cargando exportaciones…",
    youHaveNotRequestedExportYet: "Todavía no has pedido ninguna exportación.",
    download: "Descargar",
    close: "Cerrar",
    requesting: "Solicitando…",
    requestExport: "Solicitar exportación",
  },

  accountMenu: {
    noPasskeyWasUsed: "No se usó ninguna passkey. Puedes iniciar sesión con tu contraseña.",
    signedInWithRequests: (p: { name: string; waiting: number }) =>
      `Has iniciado sesión como ${p.name}. ${counted(p.waiting, {
        one: "solicitud de amistad",
        other: "solicitudes de amistad",
      })} esperando.`,
    friends: "Amigos",
    finishYourRole: (p: { role: "admin" | "moderator" }) =>
      `Completa tu rol de ${p.role === "admin" ? "administrador" : "moderador"}`,
    agreeToRules: "Al crear una cuenta aceptas seguir las {rules}.",
    reportBug: "Informar de un fallo",
    account: "Cuenta",
    settings: "Ajustes",
    myProfile: "Mi perfil",
    promptStats: "Estadísticas de palabras",
    createAccount: "Crear cuenta",
    logIn: "Iniciar sesión",
    myPromptLists: "Mis listas de palabras",
    rules: "Reglas",
    logOut: "Cerrar sesión",
    thatDoesNotLookLikeEmail: "Eso no parece una dirección de correo.",
    somethingWentWrongPleaseTryAgain: "Algo ha salido mal. Inténtalo de nuevo.",
    thatPasskeyWasNotAccepted: "Esa passkey no se aceptó.",
    thisAccountSignsWithPasskey: "Esta cuenta inicia sesión con una passkey.",
    or: "o",
    username: "Nombre de usuario",
    password: "Contraseña",
    codeFromYourAuthenticatorApp: "Código de tu aplicación de autenticación",
    recoveryCodeWorksHereTooCan: "Aquí también sirve un código de recuperación, y se puede usar una vez.",
    email: "Correo",
    optional: "opcional",
    letsYouResetYourPasswordLater: "Te permite restablecer la contraseña más adelante. No se usa para nada más.",
    rules2: "reglas",
    forgotYourPassword: "¿Olvidaste tu contraseña?",
    notNow: "Ahora no",
    createYourAccount: "Crea tu cuenta",
    createAnAccountToKeep: (p: { suggestedUsername: string }) =>
      `Crea una cuenta para conservar ${p.suggestedUsername} como nombre de usuario y guardar tus estadísticas en todos tus dispositivos.`,
    keepYourUsernameAndYour: "Conserva tu nombre de usuario y tus estadísticas en todos tus dispositivos.",
    waitingForYourDevice: "Esperando a tu dispositivo…",
    signInWithAPasskey: "Iniciar sesión con una passkey",
    pleaseWait: "Espera, por favor…",
    alreadyRegistered: "¿Ya tienes cuenta? ",
    newHere: "¿Eres nuevo? ",
    createAnAccount: "Crear una cuenta",
    guestIdentity: (p: { name: string }) =>
      `${p.name}. Tu nombre visible no está guardado.`,
    signedInAs: (p: { name: string }) =>
      `Sesión iniciada como ${p.name}`,
  },

  accountRecoveryPage: {
    thatConfirmationLinkCouldNotBe: "Ese enlace de confirmación no se pudo usar.",
    somethingWentWrongPleaseTryAgain: "Algo ha salido mal. Inténtalo de nuevo.",
    evenBestGuessersForgetSometimes: "Hasta los que mejor adivinan se olvidan a veces.",
    weRsquoLlSendSecureTime: "Enviaremos un enlace seguro y con caducidad al correo confirmado\n            de tu cuenta.",
    accountHelp: "Ayuda con la cuenta",
    backLobby: "Volver al vestíbulo",
    enterYourUsernameYourConfirmedEmail: "Introduce tu nombre de usuario o tu correo confirmado. Si la\n              cuenta se puede recuperar, el enlace ya va de camino.",
    usernameEmail: "Nombre de usuario o correo",
    thatResetLinkHasExpiredHas: "Ese enlace de restablecimiento ha caducado o ya se ha usado. Estos\n              enlaces sirven una vez y duran una hora.",
    sendNewOne: "Enviar uno nuevo",
    checkingThatLink: "Comprobando el enlace…",
    everySignedDeviceWillBeSigned: "Se cerrará la sesión en todos los dispositivos, incluidos los que\n              no reconozcas.",
    newPassword: "Contraseña nueva",
    addressIsConfirmedYouCan: (p: { address: string }) =>
      `${p.address} está confirmado. Ya puedes recuperar esta cuenta.`,
    yourPasswordIsSetAnd: "Tu contraseña está establecida y has vuelto a iniciar sesión.",
    resetYourPassword: "Restablece tu contraseña",
    thatLinkNoLongerWorks: "Ese enlace ya no funciona",
    chooseANewPassword: "Elige una contraseña nueva",
    confirmingYourEmail: "Confirmando tu correo",
    pleaseWait: "Espera, por favor…",
    sendAResetLink: "Enviar un enlace de restablecimiento",
    setPassword: "Establecer contraseña",
    oneMoment: "Un momento…",
    nothingToConfirm: "Nada que confirmar.",
    resetLinkOnItsWay:
      "Si esa cuenta existe y tiene una dirección de correo confirmada, te llegará un enlace para restablecer la contraseña.",
  },

  activeGameRoom: {
    leaveGame: "Salir de la partida",
    markedAfkByRoomVote: "La sala te ha marcado como ausente por votación.",
    inviteLinkCopied: "Enlace de invitación copiado.",
    couldnTCopyLinkCopyFrom: "No se pudo copiar el enlace. Cópialo de la barra de direcciones.",
    couldNotStartGamePleaseTry: "No se pudo empezar la partida. Inténtalo de nuevo.",
    couldNotStartRestartVote: "No se pudo iniciar una votación de reinicio.",
    couldNotRecordYourRestartVote: "No se pudo registrar tu voto de reinicio.",
    copyRoomInviteLink: "Copiar el enlace de invitación de la sala",
    clickCopyRoomInviteLink: "Haz clic para copiar el enlace de invitación",
    roomMenu: "Menú de la sala",
    afk: "Ausente",
    saveImage: "Guardar imagen",
    saveDrawnImageFile: "Guardar el dibujo en un archivo",
    playerSettings: "Ajustes del jugador",
    leaveRoom: "Salir de la sala",
    leave: "Salir",
    players: "Jugadores",
    youWereKickedFromThe: "Te expulsaron de la sala.",
    thisRoomWasOpenedIn: "Esta sala se abrió en otra pestaña.",
    startTheGame: "empezar la partida",
    startARestartVote: "iniciar una votación de reinicio",
    recordYourRestartVote: "registrar tu voto de reinicio",
    leaveDuringYourTurn: "¿Salir durante tu turno?",
    leaveActiveGame: "¿Salir de la partida en curso?",
    youReTheCurrentDrawer: "Estás dibujando. Si sales ahora, interrumpirás tu turno y la partida avanzará para todos.",
    theGameIsStillIn: "La partida sigue en curso. Saldrás de la sala y perderás tu sitio en esta partida.",
    restartVoteAvailableInRestartCooldownSeconds: (p: { restartCooldownSeconds: number }) =>
      `Votación de reinicio disponible en ${p.restartCooldownSeconds} segundos`,
    proposeRestartingTheGame: "Proponer reiniciar la partida",
    restartVoteAvailableInRestartCooldownSeconds2: (p: { restartCooldownSeconds: number }) =>
      `Votación de reinicio disponible en ${p.restartCooldownSeconds} s`,
    proposeAVoteToRestart: "Proponer una votación para reiniciar la partida",
    backFromAfk: "He vuelto",
    goAfk: "Marcarme ausente",
    closePlayers: "Cerrar jugadores",
    acceptTheColorSuggestion: "aceptar la sugerencia de color",
    dismissTheColorSuggestion: "descartar la sugerencia de color",
    couldNotAcceptSuggestion: "No se pudo aceptar la sugerencia de color.",
    couldNotDismissSuggestion: "No se pudo descartar la sugerencia de color.",
  },

  addEmailDialog: {
    followTheLink: (p: { address: string; replacing: boolean }) =>
      `Sigue el enlace enviado a ${p.address}. Hasta entonces, la dirección no está asociada a tu cuenta y no sirve para recuperarla${
        p.replacing ? ", y la que tenías sigue en su sitio." : "."
      }`,
    thatDoesNotLookLikeEmail: "Eso no parece una dirección de correo.",
    somethingWentWrongPleaseTryAgain: "Algo ha salido mal. Inténtalo de nuevo.",
    done: "Hecho",
    usedOnlyResetYourPasswordTell: "Se usa solo para restablecer tu contraseña y para avisarte si se\n              actúa sobre tu cuenta o sobre algo que compartiste. Nunca se\n              envía nada más aquí.",
    checkYourInbox: "Revisa tu bandeja de entrada",
    changeYourEmailAddress: "Cambia tu dirección de correo",
    addAnEmailAddress: "Añade una dirección de correo",
    newEmail: "Correo nuevo",
    email: "Correo",
    pleaseWait: "Espera, por favor…",
    sendConfirmation: "Enviar confirmación",
    close: "Cerrar",
    notNow: "Ahora no",
  },

  afkCheckDialog: {
    secondsUnit: (p: { count: number }) =>
      plural(p.count, { one: "segundo", other: "segundos" }),
    stillThere: "¿Sigues ahí?",
    youHaveBeenQuietWhileAnswer: "Llevas un rato en silencio. Responde y sigues jugando; si no, la\n          sala te marcará como ausente y seguirá sin ti.",
    stillTherePressButtonMoveMouse: "¿Sigues ahí? Pulsa el botón, o mueve el ratón, para seguir jugando.",
    iMHere: "Estoy aquí",
  },

  app: {
    serverUpdateInProgress: (p: { seconds: number }) =>
      p.seconds > 0
        ? `Actualización del servidor en curso. No pueden empezar salas ni partidas nuevas; a una partida en curso le quedan ${counted(p.seconds, { one: "segundo", other: "segundos" })}.`
        : "Actualización del servidor en curso. No pueden empezar salas ni partidas nuevas; las partidas en curso están terminando.",
    thisTabOutDateCannotPlay: "Esta pestaña está desactualizada y no puede jugar hasta que se recargue.",
    reload: "Recargar",
    newRoomsArePausedMaintenanceGames: "Las salas nuevas están pausadas por mantenimiento. Las partidas en curso\n          siguen con normalidad.",
    serverWasUpdatedBackAnyGame: "El servidor se actualizó y ya está de vuelta. Las partidas en curso terminaron.",
    dismiss: "Descartar",
  },

  appHeader: {
    playerSettings: "Ajustes del jugador",
  },

  bugReportDialog: {
    connectionSummary: (p: { connected: boolean; reconnects: number }) =>
      `${p.connected ? "conectado" : "sin conexión"} · ${counted(p.reconnects, {
        one: "reconexión",
        other: "reconexiones",
      })} en esta visita`,
    couldNotTakeScreenshot: "No se pudo hacer la captura.",
    thanksYourReportWithPeopleWho: "Gracias: tu informe está con quienes llevan Sketchy.",
    couldNotSendReport: "No se pudo enviar el informe.",
    reportBug: "Informar de un fallo",
    somethingBrokenNotSomethingSomeoneSaid: "Algo roto, no algo que alguien dijo. Esto llega a quienes llevan Sketchy, nunca a otros jugadores.",
    where: "Dónde",
    howBad: "Qué gravedad",
    oneLineSummary: "Resumen en una línea",
    whatWentWrongOneLine: "Qué ha fallado, en una línea",
    whatHappened: "Qué ha pasado",
    whatYouDidWhatYouExpected: "Qué hiciste, qué esperabas y qué pasó en su lugar.",
    screenshot: "Captura",
    optional: "Opcional",
    screenshotThatWillBeSentWith: "La captura que se enviará con este informe",
    thisDialogHidesItselfWhileShot: "Esta ventana se oculta mientras se toma la captura, así sale la página de detrás. Míralo antes de enviar: tú eliges qué compartir.",
    replace: "Sustituir",
    remove: "Quitar",
    opensYourBrowserSOwnPicker: "Abre el selector de tu navegador: elige esta pestaña. Esta ventana se oculta mientras se toma la captura, así sale la página de detrás.",
    recentClientErrors: "Errores recientes del cliente",
    sendMyDescriptionOnly: "Enviar solo mi descripción",
    dropsDetailsAboveAnyScreenshotWe: "Descarta los datos de arriba y cualquier captura. Lo leeremos igual, pero el fallo será mucho más difícil de reproducir.",
    cancel: "Cancelar",
    build: "Versión",
    page: "Página",
    room: "Sala",
    screen: "Pantalla",
    browser: "Navegador",
    connection: "Conexión",
    waitingForThePicker: "Esperando al selector…",
    attachAScreenshot: "Adjuntar una captura",
    whatWeAreLeavingOut: "Lo que dejamos fuera",
    whatWeSendWithThis: "Lo que enviamos con esto",
    noneOfThisIsBeing: "No se envía nada de esto: solo tu descripción de arriba.",
    theLast20ErrorsYour: "Los últimos 20 errores que registró tu navegador. Ninguna dirección de página más allá de la ruta, nada de lo que escribiste en el chat y nunca la palabra en juego.",
    sending: "Enviando…",
    sendReport: "Enviar informe",
    kilobytes: (p: { size: number }) =>
      `${number(p.size)} KB`,
    megabytes: (p: { size: number }) =>
      `${number(p.size)} MB`,
  },

  changePasswordDialog: {
    forgottenTheCurrentOne: "¿Has olvidado la actual?",
    twoNewPasswordsDoNotMatch: "Las dos contraseñas nuevas no coinciden.",
    passwordChangedEveryOtherDeviceHas: "Contraseña cambiada. Se ha cerrado la sesión en todos los demás dispositivos.",
    couldNotChangePasswordPleaseTry: "No se pudo cambiar la contraseña. Inténtalo de nuevo.",
    ifThatAccountHasVerifiedEmail: "Si esa cuenta tiene un correo verificado, ya va de camino un enlace\n              para poner una contraseña nueva. Sirve una vez y caduca.",
    done: "Hecho",
    everyDeviceSignsOutWhenPassword: "Al cambiar la contraseña se cierra la sesión en todos los dispositivos,\n              incluidos los que no querías dejar abiertos. Este se queda.",
    currentPassword: "Contraseña actual",
    newPassword: "Contraseña nueva",
    newPasswordAgain: "Repite la contraseña nueva",
    emailMeLinkInstead: "Mejor envíame un enlace",
    checkYourInbox: "Revisa tu bandeja de entrada",
    changeYourPassword: "Cambia tu contraseña",
    pleaseWait: "Espera, por favor…",
    changePassword: "Cambiar contraseña",
    close: "Cerrar",
    cancel: "Cancelar",
  },

  choosingPromptOverlay: {
    isChoosingPrompt: "{drawer} está eligiendo una palabra…",
    nextTurn: "Siguiente turno",
    drawingWillBeginAsSoonAs: "El dibujo empezará en cuanto elija.",
  },

  colorblindSafeSuggestionBanner: {
    colorblindSafeColorSuggestion: "Sugerencia de colores aptos para daltonismo",
    playerThisRoomPlaysWithColorblind: "Un jugador de esta sala juega con colores aptos para daltonismo.",
    switchRoomPaletteFutureDrawings: "¿Cambiar la paleta de la sala para los próximos dibujos?",
    switchColors: "Cambiar colores",
    notNow: "Ahora no",
  },

  confirmationDialog: {
    cancel: "Cancelar",
  },

  crashPage: {
    couldNotSendReport: "No se pudo enviar el informe.",
    bugCrawledOntoPage: "Un fallo se ha colado en la página",
    helpUsSquash: "Ayúdanos a aplastarlo",
    reportReadySendErrorWhatThis: "Hay un informe listo para enviar: el error y lo que esta pestaña sabe de sí misma.\n            Llega a quienes llevan Sketchy, nunca a otros jugadores.",
    whatWereYouDoing: "¿Qué estabas haciendo?",
    optional: "Opcional",
    lastThingYouClickedTypedIf: "Lo último que pulsaste o escribiste, si te acuerdas.",
    recentClientErrorsNewestFirst: "Errores recientes del cliente, los más nuevos primero",
    sendMyDescriptionOnly: "Enviar solo mi descripción",
    dropsDetailsAboveWeWillStill: "Descarta los datos de arriba. Lo leeremos igual, pero el fallo será mucho más difícil de encontrar.",
    thanksYourReportWithPeopleWho: "Gracias: tu informe está con quienes llevan Sketchy.",
    reload: "Recargar",
    backLobby: "Volver al vestíbulo",
    summary: "Resumen",
    build: "Versión",
    page: "Página",
    room: "Sala",
    screen: "Pantalla",
    browser: "Navegador",
    connection: "Conexión",
    thisRoomSScreenHit: "La pantalla de esta sala encontró un error y tuvo que detenerse. Tu sitio se guarda un momento: envía el informe de abajo y luego recarga para retomarlo o vuelve al vestíbulo.",
    thisScreenHitAnError: "Esta pantalla encontró un error y tuvo que detenerse. Tu cuenta y tus ajustes están a salvo. Envía el informe de abajo y podrás seguir.",
    whatWeAreLeavingOut: "Lo que dejamos fuera",
    whatWeSendWithThis: "Lo que enviamos con esto",
    noneOfThisIsBeing: "No se envía nada de esto: solo tu descripción de arriba.",
    theCrashTheLast20: "El fallo, los últimos 20 errores que registró tu navegador y en qué parte de la página ocurrió. Ninguna dirección de página más allá de la ruta, nada de lo que escribiste en el chat y nunca la palabra en juego.",
    sendingAgain: "Enviando de nuevo…",
    sending: "Enviando…",
    trySendingAgain: "Intentar enviar de nuevo",
    sendReport: "Enviar informe",
  },

  createRoomPage: {
    setupTiming: "Esta configuración dura {full} con una sala llena de {capacity}",
    setupTimingFull: (p: { minutes: number }) =>
      `unos ${counted(p.minutes, { one: "minuto", other: "minutos" })}`,
    setupTimingHalf: (p: { players: number }) => ` — más bien {half} si entran ${p.players}`,
    couldNotLoadYourRoomPresets: "No se pudieron cargar tus plantillas de sala.",
    couldNotApplyThatPreset: "No se pudo aplicar esa plantilla.",
    enterNameRoomPreset: "Ponle un nombre a la plantilla de sala.",
    couldNotSaveThatPreset: "No se pudo guardar esa plantilla.",
    couldNotUpdateThatPreset: "No se pudo actualizar esa plantilla.",
    couldNotDeleteThatPreset: "No se pudo borrar esa plantilla.",
    fixCustomPromptEntriesMarkedAbove: "Corrige las palabras propias marcadas arriba antes de crear la sala.",
    failedCreateRoom: "No se pudo crear la sala",
    roomSetup: "Configuración de la sala",
    createRoom: "Crear una sala",
    startFromSavedPreset: "Empezar desde una plantilla guardada",
    startFromPreset: "Empezar desde una plantilla…",
    nameThisPreset: "Nombra esta plantilla",
    save: "Guardar",
    cancel: "Cancelar",
    saveAsPreset: "Guardar como plantilla",
    update: "Actualizar",
    delete: "Borrar",
    undo: "Deshacer",
    saveAsReusableList: "Guardar como lista reutilizable",
    saveQuickPromptsAsA: "Guarda las palabras rápidas como lista y quita los códigos compartidos antes de guardar un ajuste predefinido.",
    appliedName: (p: { name: string }) =>
      `Se aplicó «${p.name}».`,
    savedName: (p: { name: string }) =>
      `Se guardó «${p.name}».`,
    updatedName: (p: { name: string }) =>
      `Se actualizó «${p.name}».`,
    deleteThisRoomSettingPreset: "¿Eliminar este ajuste predefinido de sala?",
    createTheRoom: "crear la sala",
    noScoring: "Sin puntuación",
    public: "Pública",
    private: "Privada",
    backToLobby: "Volver al vestíbulo",
    leaveBlankForARandom: "¡Déjalo en blanco para un nombre al azar!",
    creating: "Creando…",
    createRoom2: "Crear sala",
    playerCount: (p: { count: number }) =>
      counted(p.count, { one: "jugador", other: "jugadores" }),
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "ronda", other: "rondas" }),
  },

  customPromptsEditor: {
    usableCount: (p: { count: number }) =>
      counted(p.count, { one: "palabra propia utilizable", other: "palabras propias utilizables" }),
    duplicatesIgnored: (p: { count: number }) =>
      `${counted(p.count, { one: "duplicada", other: "duplicadas" })} ignoradas`,
    entriesTooLong: (p: { count: number; limit: number }) =>
      `${counted(p.count, { one: "entrada supera", other: "entradas superan" })} los ${number(p.limit)} caracteres`,
    entryLimit: (p: { limit: number }) => `Solo se permiten ${number(p.limit)} entradas`,
    customPromptsOptional: "Palabras propias (opcional)",
    onePromptPerLineSeparateEntries: "Una palabra por línea\no separa las entradas con comas",
    shortenRemoveOverlongEntriesBeforeCreating: "Acorta o quita las entradas demasiado largas antes de crear la sala.",
  },

  customPromptsPreview: {
    resultsMatching: (p: { shown: number; total: number }) =>
      `${number(p.shown)} de ${number(p.total)} palabras coinciden`,
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "palabra", other: "palabras" }),
    customPromptCount: (p: { count: number }) =>
      counted(p.count, { one: "palabra propia", other: "palabras propias" }),
    inspectPrompts: (p: { count: number }) =>
      `Ver ${counted(p.count, { one: "palabra propia", other: "palabras propias" })}`,
    couldNotLoadCustomPrompts: "No se pudieron cargar las palabras propias",
    loadingCustomPrompts: "Cargando palabras propias…",
    roomPromptCollection: "Colección de palabras de la sala",
    readOnlyListSuppliedByRoom: "Lista de solo lectura facilitada por el anfitrión.",
    findPrompt: "Buscar una palabra",
    searchCustomPrompts: "Buscar en las palabras propias…",
    filterPromptsByLength: "Filtrar palabras por longitud",
    noCustomPromptsMatchTheseFilters: "Ninguna palabra propia coincide con estos filtros.",
    all: "Todas",
    allPromptLengths: "Todas las longitudes",
    short: "Cortas",
    n5CharactersOrFewer: "5 caracteres o menos",
    medium: "Medianas",
    n6To10Characters: "De 6 a 10 caracteres",
    long: "Largas",
    n11CharactersOrMore: "11 caracteres o más",
    loadTheCustomPrompts: "cargar las palabras propias",
  },

  deleteAccountDialog: {
    whatIsRemoved: (p: { isGuest: boolean }) =>
      `${
        p.isGuest
          ? "Se eliminan el nombre, los puntos y el historial guardados en este navegador."
          : "Tu nombre se elimina de las partidas que jugaste."
      } Las puntuaciones y los dibujos se quedan, bajo «Jugador eliminado», porque también son partidas de otras personas. Esto no se puede deshacer.`,
    typeToConfirm: (p: { word: string }) => `Escribe ${p.word} para confirmar`,
    couldNotDeleteAccount: "No se pudo borrar la cuenta.",
    password: "Contraseña",
    deleteThisGuest: "Eliminar este invitado",
    deleteYourAccount: "Eliminar tu cuenta",
    deleting: "Eliminando…",
    deleteForGood: "Eliminar para siempre",
    keepPlaying: "Seguir jugando",
    keepMyAccount: "Conservar mi cuenta",
  },

  drawingReactionControl: {
    reactionSummary: (p: { total: number; chips: string }) =>
      `${counted(p.total, { one: "reacción", other: "reacciones" })}: ${p.chips}`,
    thatReactionCouldNotBeSent: "No se pudo enviar esa reacción.",
    reactThisDrawing: "Reaccionar a este dibujo",
    reactions: "Reacciones",
    createAccountReact: "Crea una cuenta para reaccionar.",
    createAccount: "Crear cuenta",
    noReactionsYet: "Aún no hay reacciones",
    reactToThisDrawingSummary: (p: { summary: string }) =>
      `Reaccionar a este dibujo. ${p.summary}`,
    labelYourReactionPressTo: (p: { label: string }) =>
      `${p.label}, tu reacción. Pulsa para quitarla`,
  },

  drawingRecapGallery: {
    drawingLabel: (p: { prompt: string; drawer: string }) =>
      `Dibujo de ${p.prompt} por ${p.drawer}`,
    drawnBy: "Dibujado por {drawer} · Ronda {round} · Turno {turn}",
    position: (p: { position: number; total: number }) => `${p.position} de ${p.total}`,
    thisDrawingCouldNotBeDecoded: "Este dibujo no se pudo descodificar.",
    drawingRecap: "Resumen de dibujos",
    saveImage: "Guardar imagen",
    close: "Cerrar",
    thisDrawingWasNotKept: "Este dibujo no se conservó.",
    roomRanOutRoomLaterTurns: "La sala se quedó sin sitio. En su lugar se guardaron turnos posteriores.",
    tryAgain: "Inténtalo de nuevo",
    loadingDrawing: "Cargando dibujo…",
    noDrawingWasCapturedThisTurn: "No se guardó ningún dibujo de este turno.",
    drawingRecapNavigation: "Navegación del resumen de dibujos",
    previous: "Anterior",
    next: "Siguiente",
    loadThisDrawing: "cargar este dibujo",
  },

  emailRecoveryReminder: {
    addEmail: "Añadir un correo",
    dismiss: "Descartar",
    confirmPendingAddressToFinishSetting: (p: { pendingAddress: string }) =>
      `Confirma ${p.pendingAddress} para terminar de configurar la recuperación de la cuenta.`,
    thisAccountHasNoEmail: "Esta cuenta no tiene dirección de correo, así que una contraseña olvidada no se puede restablecer.",
  },

  firstRunIdentity: {
    couldNotSaveThatNamePlease: "No se pudo guardar ese nombre. Inténtalo de nuevo.",
    keepYourUsernameYourStatsEvery: "Conserva tu nombre de usuario y tus estadísticas en todos los dispositivos.",
    createAccount: "Crear una cuenta",
    logIn: "Iniciar sesión",
    or: "o",
    displayName: "Nombre visible",
    beenHereBefore: "¿Ya has estado aquí?",
    playAsYourself: "Juega como tú",
    whatShouldWeCallYou: "¿Cómo te llamamos?",
    justPlayingOncePickA: "¿Solo una partida? Elige un nombre visible",
    play: "Jugar",
    playAsGuest: "Jugar como invitado",
  },

  friendButton: {
    requestSentTo: (p: { name: string }) => `Solicitud de amistad enviada a ${p.name}`,
    addFriend: "Añadir amigo",
    acceptRequest: "Aceptar solicitud",
    requestSent: "Solicitud enviada",
  },

  friendInviteNotice: {
    couldNotJoinThatGame: "No se pudo entrar en esa partida.",
    thatGameCouldNotBeJoined: "No se pudo entrar en esa partida.",
    invitedYouTheirGame: "te ha invitado a su partida.",
    join: "Entrar",
    dismissInvitation: "Descartar invitación",
  },

  friendsOverlay: {
    declineWarning: (p: { name: string }) =>
      `${p.name} no podrá volver a pedirlo. Tú sí puedes enviarle una solicitud más adelante.`,
    decline2: "Rechazar",
    youWillBothStopBeingAble: "Los dos dejaréis de poder entrar en las partidas del otro sin invitación. Cualquiera de los dos puede volver a pedirlo.",
    remove2: "Quitar",
    removeConfirm: (p: { name: string }) => `¿Quitar a ${p.name}?`,
    friends: "Amigos",
    close: "Cerrar",
    closeFriends: "Cerrar amigos",
    friendsNeedAccountGuestNameBelongs: "Para tener amigos hace falta una cuenta. Un nombre de invitado pertenece a\n              este navegador y no a ti, así que dentro de un mes no quedaría\n              nadie con quien ser amigo.",
    loading: "Cargando…",
    noFriendsYetAddSomebodyFrom: "Aún no tienes amigos. Añade a alguien desde el vestíbulo o desde una\n              partida en la que estéis los dos.",
    requests: "Solicitudes",
    accept: "Aceptar",
    decline: "Rechazar",
    sent: "Enviada",
    cancel: "Cancelar",
    remove: "Quitar",
    declineThisRequest: "¿Rechazar esta solicitud?",
    recentlyPlayedWith: "Jugado recientemente con",
  },

  gameEndOverlay: {
    continueLabel: "Continuar",
    youFinished: (p: { points: number }) =>
      `Has quedado {place} con ${counted(p.points, { one: "punto", other: "puntos" })}.`,
    continueToWaitingRoom: "Ir a la sala de espera",
    continueWithCountdown: (p: { seconds: number }) =>
      `Ir a la sala de espera, quedan ${counted(p.seconds, { one: "segundo", other: "segundos" })}`,
    gameOver: "Fin de la partida",
    you: "tú",
    friend: "Amigo",
    noScoresThisTimeJustRoom: "Esta vez no hay puntos: solo una sala llena de bocetos y conjeturas.",
    keep: "Quedarte",
    asYourUsername: "como tu nombre de usuario",
    createAccount: "Crear cuenta",
    highlights: "Momentos destacados",
    drawings: "Dibujos",
    stayHere: "Quedarme aquí",
    aGreatGameOfDrawing: "Una gran partida de dibujo",
    theRoomTakesTheCrown: "¡La sala se lleva la corona!",
    winnersCountPlayersShareTheCrown: (p: { winnersCount: number }) =>
      `¡${p.winnersCount} jugadores comparten la corona!`,
    takesTheCrown: " se lleva la corona!",
    shareTheCrown: " comparten la corona!",
  },

  gameHighlightsPanel: {
    lastGame: "Última partida",
    highlights: "Momentos destacados",
    closeHighlights: "Cerrar los destacados",
    thatGameWasTooShortSay: "Esa partida fue demasiado corta para decir gran cosa. Juega una más larga y\n            aquí aparecerán los momentos destacados.",
    seeIt: "Verlo",
    back: "Atrás",
  },

  inviteEntryPage: {
    roomCode: (p: { code: string }) => `Sala ${p.code}`,
    hereCount: (p: { here: number; capacity: number; full: boolean }) =>
      `${p.here}/${p.capacity} aquí${p.full ? " · llena" : ""}`,
    roomSummary: (p: { rounds: number; seconds: number; hintMode: string }) =>
      `${counted(p.rounds, { one: "ronda", other: "rondas" })} · ${p.seconds}s · ${p.hintMode}`,
    checkingYourInvite: "Comprobando tu invitación…",
    loadingRoomDetails: "Cargando los detalles de la sala.",
    roomUnavailable: "Sala no disponible",
    backLobby: "Volver al vestíbulo",
    players: "Jugadores",
    rounds: "Rondas",
    drawTime: "Tiempo de dibujo",
    scoring: "Puntuación",
    roomRules: "Reglas de la sala",
    thisGameAlreadyProgressJoiningAs: "Esta partida ya está en curso. Si entras como jugador, te tocará en un turno posterior.",
    playerSlotsAreFullSpectatingStill: "Las plazas de jugador están llenas. Todavía puedes mirar.",
    promptDetailsHidden: "Detalles de la palabra ocultos",
    timedHints: "Pistas por tiempo",
    buyableLetterHints: "Pistas de letras de pago",
    wheelOfFortune: "Ruleta de la suerte",
    noLetterHints: "Sin pistas de letras",
    publicRoom: "Sala pública",
    privateInvite: "Invitación privada",
    inProgress: "En curso",
    waiting: "Esperando",
    full: " · Llena",
    noScoring: "Sin puntuación",
    pressure: "Presión",
    default: "Estándar",
    everyToolAndColor: "Todas las herramientas y colores",
    spectatorsCanSeeThePrompt: "Los espectadores ven la palabra",
    spectatorsGuessAlong: "Los espectadores también adivinan",
    defaultPromptList: "Lista de palabras estándar",
    roomFull: "Sala llena",
    joining: "Uniéndote…",
    joinGameInProgress: "Unirse a la partida en curso",
    joinGame: "Unirse a la partida",
    spectate: "Mirar",
    customPromptsOnly: (p: { count: number }) =>
      `solo ${counted(p.count, { one: "palabra propia", other: "palabras propias" })}`,
    customPromptsPlusDefaults: (p: { count: number }) =>
      `${counted(p.count, { one: "palabra propia", other: "palabras propias" })} más las estándar`,
  },

  inviteFriendsList: {
    invitationCouldNotBeSent: "No se pudo enviar esa invitación.",
    invitationSent: (p: { name: string }) => `Invitación enviada a ${p.name}.`,
    thatInvitationCouldNotBeSent: "No se pudo enviar esa invitación.",
    friendsLobby: "Amigos en el vestíbulo",
    invited: "Invitado",
    invite: "Invitar",
  },

  languagePicker: {
    currentChoice: (p: { label: string; value: string }) => `${p.label}: ${p.value}`,
    everyLanguage: "Todos los idiomas",
  },

  lobbyBrowserPage: {
    filterByLanguage: "Filtrar por idioma",
    filtersWithCount: (p: { count: number }) =>
      p.count > 0 ? `Filtros · ${p.count}` : "Filtros",
    showRooms: (p: { count: number }) =>
      `Ver ${counted(p.count, { one: "sala", other: "salas" })}`,
    removedFromRoom: "Expulsado de la sala",
    ok: "Vale",
    roomCode: "Código de sala",
    abc123: "ABC123",
    thereNoRoomCodeClipboard: "No hay ningún código de sala en el portapapeles.",
    sketchyCouldNotReadClipboardPaste: "Sketchy no pudo leer el portapapeles. Pega en las casillas.",
    pleaseEnterRoomCode: "Introduce un código de sala",
    failedJoinRoom: "No se pudo entrar en la sala",
    joinByCode: "Entrar con código",
    createRoom: "Crear sala",
    publicRooms: "Salas públicas",
    searchRoomsByNameCode: "Buscar salas por nombre o código",
    hideFull: "Ocultar llenas",
    hideProgress: "Ocultar en curso",
    filters: "Filtros",
    clearFilters: "Quitar filtros",
    language: "Idioma",
    hideFullRooms: "Ocultar salas llenas",
    hideGamesProgress: "Ocultar partidas en curso",
    loadingPublicRooms: "Cargando salas públicas…",
    noPublicRoomsYetCreateOne: "Todavía no hay salas públicas. ¡Crea una!",
    noPublicRoomsMatchYourSearch: "Ninguna sala pública coincide con tu búsqueda.",
    createRoom2: "Crear una sala",
    joinWithCode: "Entrar con un código",
    paste: "Pegar",
    couldNotSaveThatName: "No se pudo guardar ese nombre. Inténtalo de nuevo.",
    joinAsASpectator: "unirte como espectador",
    joinTheRoom: "unirte a la sala",
    loading: "Cargando…",
    showingFilteredRoomsCountOfRoomsCount: (p: { filteredRoomsCount: number; roomsCount: number }) =>
      `Mostrando ${p.filteredRoomsCount} de ${p.roomsCount}`,
    n0Rooms: "0 salas",
    close: "Cerrar",
    joining: "Uniéndote…",
    joinTheRoom2: "Unirse a la sala",
    joiningAsSpectator: "Uniéndote como espectador…",
    watchWithoutPlaying: "Mirar sin jugar",
  },

  lobbyChatPanel: {
    reportThisLine: (p: { name: string }) => `Denunciar esta línea de ${p.name}`,
    couldNotSendThat: "No se pudo enviar.",
    chat: "Chat",
    lobbyChat: "Chat del vestíbulo",
    nobodyHasSaidAnythingYet: "Todavía no ha dicho nadie nada.",
    chooseNameChat: "Elige un nombre para chatear",
    saySomethingLobby: "Di algo al vestíbulo…",
    lobbyChatMessage: "Mensaje del chat del vestíbulo",
    send: "Enviar",
    couldNotSaveThatName: "No se pudo guardar ese nombre. Inténtalo de nuevo.",
    sendTheMessage: "enviar el mensaje",
  },

  lobbyPlayerMenu: {
    whatToDoAbout: (p: { name: string }) => `Qué hacer con ${p.name}`,
    openPlayerProfile: "Abrir el perfil del jugador",
    addAsFriend: "Añadir como amigo",
    report: "Denunciar",
  },

  promptTags: {
    "animals": "Animales",
    "food-and-drink": "Comida y bebida",
    "objects": "Objetos",
    "nature": "Naturaleza",
    "places": "Lugares",
    "people": "Personas",
    "actions": "Acciones",
    "sports-and-games": "Deportes y juegos",
    "transport": "Transporte",
    "entertainment": "Entretenimiento",
    "science-and-technology": "Ciencia y tecnología",
    "history-and-culture": "Historia y cultura",
    "holidays": "Fiestas",
    "fantasy": "Fantasía",
    "abstract": "Abstracto",
  },
  communityCataloguePage: {
    backToLobby: "Volver al vestíbulo",
    loading: "Cargando…",
    communityCatalogue: "Catálogo de la comunidad",
    listsPlayersPublished: "Listas que han publicado otros jugadores.",
    couldNotLoadTheCatalogue: "No se pudo cargar el catálogo de la comunidad.",
    couldNotOpenThatList: "No se pudo abrir esa lista.",
    language: "Idioma",
    everyLanguage: "Todos los idiomas",
    sortBy: "Ordenar por",
    mostStarred: "Más estrellas",
    newest: "Más recientes",
    onlyOnesIStarred: "Solo las que marqué",
    clearFilters: "Quitar filtros",
    nothingMatchesThoseFilters: "Ninguna lista coincide con esos filtros.",
    nothingPublishedYet: "Todavía no hay listas publicadas.",
    byOwner: (p: { owner: string }) => `de ${p.owner}`,
    community: "Comunidad",
    starred: "Con estrella",
    tags: "Etiquetas",
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "palabra", other: "palabras" }),
    starCount: (p: { count: number }) =>
      counted(p.count, { one: "estrella", other: "estrellas" }),
    starThisList: "Dar una estrella a esta lista",
    unstarThisList: "Quitar la estrella",
    showMore: "Ver más",
    star: "Dar estrella",
    unstar: "Quitar estrella",
    makeACopy: "Hacer una copia",
    report: "Denunciar",
    signInToStarCopyOrReport: "Hace falta una cuenta para dar estrellas, copiar o denunciar.",
    whatIsInIt: "Qué contiene",
    couldNotChangeTheStar: "No se pudo cambiar la estrella.",
    copiedToYourLists: "Copiada a tus listas de palabras.",
    couldNotCopyThatList: "No se pudo copiar esa lista.",
    reportSent: "Denuncia enviada.",
  },
  myPromptListsPage: {
    inCommunityCatalogue: "En el catálogo de la comunidad",
    notPublished: "Sin publicar",
    publishedExplainer: "Cualquiera puede encontrar esta lista, jugarla, darle una estrella o hacer su propia copia.",
    unpublishedExplainer: "Al publicarla, cualquiera podrá encontrar y jugar esta lista. Se puede retirar en cualquier momento.",
    publish: "Publicar",
    unpublish: "Retirar",
    promptListPublished: "Lista de palabras publicada.",
    promptListUnpublished: "Lista de palabras retirada.",
    couldNotChangePublication: "No se pudo cambiar si esta lista está publicada.",
    published: "Publicada",
    tags: "Etiquetas",
    tagsChosen: (p: { chosen: number; max: number }) => `${p.chosen} de ${p.max} elegidas`,
    tagsAreHowListsAreFound: "Las etiquetas son la forma de encontrar esta lista en el catálogo de la comunidad.",
    listSummary: (p: { prompts: number; visibility: string; moderationState: string | null }) =>
      `${counted(p.prompts, { one: "palabra", other: "palabras" })} · ${p.visibility}${
        p.moderationState ? ` · ${p.moderationState}` : ""
      }`,
    listUnderReview: (p: { state: string }) =>
      `Esta lista está ${p.state} y no se puede usar en partidas nuevas. Editarla no la restaura automáticamente; un moderador debe revisarla.`,
    needsReview: (p: { count: number }) => `Por revisar (${p.count})`,
    removePrompt: (p: { prompt: string }) => `Quitar ${p.prompt}`,
    couldNotLoadYourPromptLists: "No se pudieron cargar tus listas de palabras.",
    couldNotOpenThatPromptList: "No se pudo abrir esa lista de palabras.",
    addAtLeastOnePromptBefore: "Añade al menos una palabra antes de guardar.",
    couldNotSaveThisPromptList: "No se pudo guardar esta lista de palabras.",
    couldNotDeleteThisPromptList: "No se pudo borrar esta lista de palabras.",
    yourLibrary: "Tu biblioteca",
    reusablePromptLists: "Listas de palabras reutilizables",
    newList: "Lista nueva",
    createAccountSaveReviseSharePrompt: "Crea una cuenta para guardar, revisar y compartir listas de palabras. Las palabras rápidas de una sala son locales y efímeras.",
    yourPromptLists: "Tus listas de palabras",
    loading: "Cargando…",
    noSavedListsYet: "Todavía no hay listas guardadas.",
    name: "Nombre",
    description: "Descripción",
    language: "Idioma",
    visibility: "Visibilidad",
    private: "Privada",
    anyoneWithCode: "Cualquiera con el código",
    shareCode: "Código para compartir",
    couldNotCopyShareCode: "No se pudo copiar el código para compartir.",
    copy: "Copiar",
    addPrompts: "Añadir palabras",
    onePromptPerLineSeparateEntries: "Una palabra por línea\no separa las entradas con comas",
    addList: "Añadir a la lista",
    noPromptsYetPasteSomeAbove: "Todavía no hay palabras. Pega algunas arriba para empezar.",
    thisList: "En esta lista",
    searchPrompts: "Buscar palabras",
    nothingMatchesThatSearch: "Nada coincide con esa búsqueda.",
    deleteList: "Borrar lista…",
    promptListSaved: "Lista de palabras guardada.",
    deleteThisPromptListAnd: "¿Eliminar esta lista de palabras y todas sus revisiones?",
    promptListDeleted: "Lista de palabras eliminada.",
    backToLobby: "Volver al vestíbulo",
    promptsCountOfMaxListPrompts: (p: { promptsCount: number; MAX_LIST_PROMPTS: number }) =>
      `${p.promptsCount} de ${p.MAX_LIST_PROMPTS} palabras en esta lista`,
    saving: "Guardando…",
    saveList: "Guardar lista",
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "palabra", other: "palabras" }),
    visibleOfTotal: (p: { visible: number; total: number }) =>
      `${p.visible} de ${p.total}`,
  },

  notFoundPage: {
    nobodyDrewThisPage: "Nadie ha dibujado esta página",
    thatLinkDoesnTLeadAnywhere: "Ese enlace no lleva a ninguna parte de Sketchy.",
    backLobby: "Volver al vestíbulo",
  },

  onlinePlayersPanel: {
    couldNotJoinThatGame: "No se pudo entrar en esa partida.",
    whoOnline: "Quién está en línea",
    nobodyElseHereRightNow: "Ahora mismo no hay nadie más aquí.",
    friend: "Amigo",
    join: "Entrar",
    inAGame: "En una partida",
    inTheLobby: "En el vestíbulo",
  },

  pictureCropDialog: {
    fileNotAPicture: "Ese archivo no se pudo leer como imagen.",
    couldNotSetThatPicturePlease: "No se pudo poner esa imagen. Inténtalo de nuevo.",
    frameYourPicture: "Encuadra tu imagen",
    dragMoveZoomGetCloserCircle: "Arrastra para moverla y haz zoom para acercarte. El círculo es lo que ve todo el mundo.",
    pictureFramedArrowKeysMovePlus: "La imagen, encuadrada. Las flechas la mueven; más y menos hacen zoom.",
    zoom: "Zoom",
    cancel: "Cancelar",
    uploading: "Subiendo…",
    usePicture: "Usar imagen",
  },

  playerList: {
    requestCouldNotBeSent: "No se pudo enviar esa solicitud.",
    nowFriends: (p: { name: string }) => `${p.name} y tú ya sois amigos.`,
    friendRequestSent: (p: { name: string }) => `Solicitud de amistad enviada a ${p.name}.`,
    nothingToDoAbout: (p: { name: string }) => `Ahora mismo no hay nada que hacer con ${p.name}.`,
    rank: (p: { rank: number }) => `Puesto ${p.rank}`,
    moderationFor: (p: { name: string }) => `Moderación para ${p.name}`,
    moderationActionsFor: (p: { name: string }) => `Acciones de moderación para ${p.name}`,
    thatRequestCouldNotBeSent: "No se pudo enviar esa solicitud.",
    drawing: "Dibujando",
    gotIt: "Acertado ·",
    afk: "Ausente",
    you: "(tú)",
    host: "Anfitrión",
    friend: "Amigo",
    disconnected: "Desconectado",
    kick: "Expulsar",
    addFriend: "Añadir amigo",
    sendRequest: "Enviar una solicitud",
    report: "Denunciar",
    toAModerator: "A un moderador",
    voteAfkOrKickOr: "Votar ausente o expulsión, o denunciar",
    reportThisPlayer: "Denunciar a este jugador",
    undoVote: "Deshacer voto",
    vote: "Votar",
    voteKindAfk: "Ausente",
    voteKindKick: "Expulsión",
    undoVoteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Deshacer voto de ${p.kind} para ${p.nickname}, ${p.count} de ${p.required}`,
    voteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Votar ${p.kind} para ${p.nickname}, ${p.count} de ${p.required}`,
    votesFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Votos de ${p.kind} para ${p.nickname}, ${p.count} de ${p.required}`,
    votesForIncludingYours: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Votos de ${p.kind} para ${p.nickname}, ${p.count} de ${p.required}, incluido el tuyo`,
    guestName: (p: { nickname: string }) =>
      `${p.nickname} (invitado)`,
  },

  profilePage: {
    gamesPlayed: "Partidas jugadas",
    gamesWon: "Partidas ganadas",
    winRate: "Porcentaje de victorias",
    averageScore: "Puntuación media",
    turnsPlayed: "Turnos jugados",
    promptsGuessed: "Palabras adivinadas",
    drawingsMade: "Dibujos hechos",
    reactionsReceived: "Reacciones recibidas",
    totalScore: "Puntuación total",
    noSuchProfile: "No hay ningún jugador con ese perfil.",
    couldNotLoadProfile: "No se pudo cargar este perfil. Inténtalo de nuevo.",
    gameMeta: (p: { finishedAt: string; rounds: number; players: number }) =>
      `${p.finishedAt} · ${counted(p.rounds, { one: "ronda", other: "rondas" })} · ${counted(p.players, { one: "jugador", other: "jugadores" })}`,
    seatScore: (p: { points: number }) => `${number(p.points)} pts`,
    gameRules: (p: {
      scoringMode: string;
      scoringVersion: number;
      hintMode: string;
      seconds: number;
      promptSource: string;
    }) =>
      `Reglas: puntuación ${p.scoringMode}${
        p.scoringVersion > 0 ? ` v${p.scoringVersion}` : " (versión antigua desconocida)"
      } · pistas ${p.hintMode} · ${p.seconds} segundos · palabras ${p.promptSource}`,
    reportPlayer: (p: { name: string }) => `Denunciar a ${p.name}`,
    privateRoom: "sala privada",
    thisGameDidNotFinishSo: "Esta partida no terminó, así que estos son los puntos tal como estaban\n              al pararse, no una clasificación final.",
    loadingTurns: "Cargando turnos…",
    turnByTurn: "Turno a turno",
    round: "Ronda",
    prompt: "Palabra",
    drawnBy: "Dibujado por",
    time: "Tiempo",
    drawing: "Dibujando",
    reactions: "Reacciones",
    guesserOutcomes: "Resultados de quienes adivinaban",
    view: "Ver",
    couldNotLoadMoreGames: "No se pudieron cargar más partidas.",
    loading: "Cargando…",
    friend: "Amigo.",
    claimYourAccount: "Reclama tu cuenta",
    yourGamesAreAlreadyBeingRecorded: "Tus partidas ya se están registrando con este nombre visible.\n                Crea una cuenta para conservarlas y usarlo como nombre de usuario en todos los dispositivos.",
    createAccount: "Crear cuenta",
    statistics: "Estadísticas",
    gameHistory: "Historial de partidas",
    includeGamesThatFellApart: "Incluir partidas que se deshicieron",
    notKept: "no guardado",
    nothingDrawn: "nada dibujado",
    onlyThePlayersInThis: "Solo los jugadores de esta partida pueden ver sus turnos.",
    couldNotLoadTheTurns: "No se pudieron cargar los turnos de esta partida.",
    cutShort: "interrumpida",
    noAttempt: "sin intento",
    joinedLate: "se unió tarde",
    notEligibleEligibilityReason: (p: { eligibilityReason: string }) =>
      `no computa (${p.eligibilityReason})`,
    unknownPlayer: "Jugador desconocido",
    backToLobby: "Volver al vestíbulo",
    guestDisplayNameNotSaved: "Invitado: nombre visible no guardado",
    registeredPlayer: "Jugador registrado",
    noFinishedGamesYetPlay: "Aún no hay partidas terminadas. Juega una y aparecerá aquí.",
    noGamesToShowGames: "No hay partidas que mostrar. Las partidas de salas privadas solo se muestran a quienes estuvieron en ellas.",
    loadHistoryPageSizeMore: (p: { HISTORY_PAGE_SIZE: number }) =>
      `Cargar ${p.HISTORY_PAGE_SIZE} más`,
    correctWithPoints: (p: { points: number }) =>
      `acierto, ${p.points}`,
    wrongCount: (p: { count: number }) =>
      counted(p.count, { one: "fallo", other: "fallos" }),
    joinedOn: (p: { date: string }) =>
      `se unió el ${p.date}`,
  },

  promptContentReportDialog: {
    reportList: (p: { name: string }) => `Denunciar a ${p.name}`,
    couldNotSendReport: "No se pudo enviar el informe.",
    reportsAreReviewedAfterSubmissionList: "Las denuncias se revisan tras enviarlas. La lista sigue disponible salvo que un moderador la oculte.",
    content: "Contenido",
    entireList: "Lista entera",
    reason: "Motivo",
    whatShouldModeratorKnow: "¿Qué debería saber el moderador?",
    cancel: "Cancelar",
    inappropriateContent: "Contenido inapropiado",
    hatefulOrAbusiveContent: "Contenido de odio o abusivo",
    sexualContent: "Contenido sexual",
    violence: "Violencia",
    spam: "Spam",
    other: "Otro",
    sending: "Enviando…",
    sendReport: "Enviar denuncia",
  },

  promptDisplay: {
    couldNotDoAction: (p: { action: string }) => `No se pudo ${p.action}.`,
    nextHintCost: (p: { cost: number }) => `Siguiente pista: ${p.cost}`,
    hintSpendTotal: (p: { spent: number }) => `Total: ${p.spent}`,
    buyLetter: (p: { letter: string; price: number }) =>
      `Comprar «${p.letter}» por ${counted(p.price, { one: "punto", other: "puntos" })}`,
    maskedPrompt: (p: { shape: string }) => `Palabra oculta, ${p.shape} letras`,
    buyThisLetter: (p: { cost: number }) =>
      `Comprar esta letra por ${counted(p.cost, { one: "punto", other: "puntos" })}`,
    letterCount: (p: { count: number }) =>
      counted(p.count, { one: "letra", other: "letras" }),
    yourTurn: "Te toca",
    pickSomethingDraw: "Elige algo para dibujar",
    autoPicksWhenTimeRunsOut: "Se elige sola cuando se acaba el tiempo.",
    hintSpendLimitReached: "Límite de gasto en pistas alcanzado",
    deductedFromYourScoreIfYou: "Se resta de tu puntuación si adivinas la palabra",
    buyLetterRevealsEveryMatch: "Compra una letra: revela todas sus apariciones",
    selectThePrompt: "elegir la palabra",
    choosing: "Eligiendo…",
    buyTheHint: "comprar la pista",
    buyTheLetterHint: "comprar la pista de letra",
  },

  promptListPicker: {
    languageMismatch: (p: { listLanguage: string; roomLanguage: string }) =>
      `Esa lista está en ${p.listLanguage}; esta sala está en ${p.roomLanguage}.`,
    choicesUnavailable: (p: { reason: string }) =>
      `Las listas de palabras no están disponibles (${p.reason}). Tu selección actual no cambia.`,
    noListsInLanguage: (p: { language: string }) =>
      `Todavía no hay listas en ${p.language}: esta sala usa sus propias palabras.`,
    howListPlays: (p: { name: string }) => `Cómo se juegan las palabras de ${p.name}`,
    reportList: (p: { name: string }) => `Denunciar a ${p.name}`,
    failedLoadPromptLists: "No se pudieron cargar las listas de palabras",
    couldNotAddThatSharedList: "No se pudo añadir esa lista compartida.",
    loadingCuratedPromptLists: "Cargando listas de palabras…",
    promptLists: "Listas de palabras",
    addUnlistedListByCode: "Añadir una lista no listada con un código",
    namePromptCountPrompts: (p: { name: string; promptCount: number }) =>
      `${p.name} (${p.promptCount} palabras)`,
    adding: "Añadiendo…",
    add: "Añadir",
    reportSentForModeratorReview: "Denuncia enviada para revisión de un moderador.",
  },

  promptStatsPage: {
    noSuchList: "No hay ninguna lista de palabras con ese nombre.",
    couldNotLoadStats: "No se pudieron cargar estas estadísticas. Inténtalo de nuevo.",
    showMore: (p: { count: number }) => `Ver ${p.count} más`,
    showingOf: (p: { shown: number; total: number }) => `Mostrando ${p.shown} de ${p.total}`,
    couldNotLoadPromptListsPlease: "No se pudieron cargar las listas de palabras. Inténtalo de nuevo.",
    serverWide: "En todo el servidor",
    promptStats: "Estadísticas de palabras",
    everyPromptListHowHasActually: "Cada palabra de la lista y cómo ha funcionado en las partidas terminadas\n          de este servidor.",
    promptList: "Lista de palabras",
    sort: "Orden",
    period: "Periodo",
    scoring: "Puntuación",
    hints: "Pistas",
    findPrompt: "Buscar una palabra",
    rollerCoaster: "montaña rusa",
    loading: "Cargando…",
    prompt: "Palabra",
    howGoes: "Cómo va",
    guessed: "Adivinada",
    picked: "Elegida",
    drawn: "Dibujada",
    allTime: "Todo el tiempo",
    last30Days: "Últimos 30 días",
    last90Days: "Últimos 90 días",
    allScoringModes: "Todos los modos de puntuación",
    noScoring: "Sin puntuación",
    defaultScoring: "Puntuación estándar",
    pressureScoring: "Puntuación de presión",
    allHintModes: "Todos los modos de pista",
    noHints: "Sin pistas",
    checkpointHints: "Pistas por tiempo",
    purchasedHints: "Pistas compradas",
    letterWheel: "Ruleta de letras",
    backToLobby: "Volver al vestíbulo",
  },

  publicRoomCard: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "ronda", other: "rondas" }),
    promptLanguage: (p: { language: string }) => `Idioma de las palabras: ${p.language}`,
    seeWhoThisRoom: "Ver quién está en esta sala",
    rounds: "Rondas",
    drawingTime: "Tiempo de dibujo",
    full: "Llena",
    inProgress: "En curso",
    looking: "Buscando…",
    nobodySeatedYet: "Todavía no hay nadie sentado.",
    host: "Anfitrión",
    couldNotReadWhoIs: "No se pudo saber quién está en esta sala.",
    joining: "Uniéndote…",
    join: "Unirse",
    spectate: "Mirar",
  },

  reactionRequests: {
    thatReactionCouldNotBeSent: "No se pudo enviar esa reacción.",
  },

  recapDrawings: {
    thisDrawingCouldNotBeLoaded: "No se pudo cargar este dibujo.",
  },

  reportAccountDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Un moderador lo verá. A ${p.name} no le pasa nada ahora mismo, y no se le dice quién le ha denunciado.`,
    theirPicture: (p: { name: string }) => `imagen de ${p.name}`,
    thatReportCouldNotBeSent: "No se pudo enviar esa denuncia. Inténtalo de nuevo.",
    whatWrongWith: "Qué le pasa",
    reportedTheirNameTheyHaveNo: "Denunciado por su nombre. No tiene imagen que denunciar.",
    anythingElseOptional: "Algo más (opcional)",
    anythingModeratorShouldKnow: "Cualquier cosa que deba saber un moderador",
    sentWithWhatAboutAttached: "Enviada, con el motivo adjunto.",
    done: "Hecho",
    inappropriateName: "Nombre inapropiado",
    inappropriatePicture: "Imagen inapropiada",
    reportSent: "Denuncia enviada",
    reportDisplayName: (p: { displayName: string }) =>
      `Denunciar a ${p.displayName}`,
    thePictureOnTheAccount: "Se adjunta la imagen de la cuenta tal como está ahora.",
    theNameOnTheAccount: "Se adjunta el nombre de la cuenta tal como está ahora.",
    sending: "Enviando…",
    sendReport: "Enviar denuncia",
    close: "Cerrar",
    cancel: "Cancelar",
  },

  reportedDrawing: {
    thisDrawingCouldNotBeDecoded: "Este dibujo no se pudo descodificar.",
    drawingCouldNotBeLoaded: "No se pudo cargar el dibujo.",
    loadingTheDrawing: "Cargando el dibujo…",
  },

  reportLobbyLineDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Un moderador verá esta línea. A ${p.name} no le pasa nada ahora mismo, y no se le dice quién le ha denunciado.`,
    thatReportCouldNotBeSent: "No se pudo enviar esa denuncia. Inténtalo de nuevo.",
    whatWrongWith: "Qué le pasa",
    anythingElseOptional: "Algo más (opcional)",
    anythingModeratorShouldKnow: "Cualquier cosa que deba saber un moderador",
    thisLineAttachedWithWhatLobby: "Esta línea va adjunta, con lo que se dijo alrededor en el vestíbulo.",
    sentWithLineWhatWasSaid: "Enviada, con la línea y lo que se dijo alrededor adjunto.",
    done: "Hecho",
    harassmentOrAbuse: "Acoso o abuso",
    spam: "Spam",
    inappropriateName: "Nombre inapropiado",
    reportSent: "Denuncia enviada",
    reportDisplayName: (p: { displayName: string }) =>
      `Denunciar a ${p.displayName}`,
    sending: "Enviando…",
    sendReport: "Enviar denuncia",
    close: "Cerrar",
    cancel: "Cancelar",
  },

  reportPlayerDialog: {
    reportCouldNotBeSent: "No se pudo enviar esa denuncia.",
    recentMessages: (p: { count: number }) =>
      `${p.count} de sus ${plural(p.count, { one: "mensaje reciente", other: "mensajes recientes" })}`,
    nothingHappensYet: (p: { name: string }) =>
      `Un moderador lo verá. A ${p.name} no le pasa nada ahora mismo, y no se le dice quién le ha denunciado.`,
    whatHappened: "Qué ha pasado",
    anythingElseOptional: "Algo más (opcional)",
    whatTheySaidDrewWhen: "Qué dijo o dibujó, y cuándo",
    theirRecentMessagesThisRoomAre: "Sus mensajes recientes en esta sala se adjuntan automáticamente,\n                con lo que se dijo alrededor, así que esto puede quedar vacío.",
    includeTheirDrawing: "Incluir su dibujo",
    canvasAsRightNowSoModerator: "El lienzo tal como está ahora, para que un moderador vea lo\n                      que viste tú.",
    done: "Hecho",
    sentWithTheirDrawingAnd: (p: { messages: string }) =>
      `Enviada, con su dibujo y ${p.messages} adjuntos.`,
    sentWithTheirDrawingAttached: "Enviada, con su dibujo adjunto.",
    sentWithMessagesAttached: (p: { messages: string }) =>
      `Enviada, con ${p.messages} adjuntos.`,
    sentTheyHadSaidNothing: "Enviada. No había dicho nada en esta sala, así que no se adjuntan mensajes.",
    baseTheTurnHadEnded: (p: { base: string }) =>
      `${p.base} El turno había terminado, así que no se pudo adjuntar el dibujo.`,
    harassmentOrAbuse: "Acoso o abuso",
    offensiveDrawing: "Dibujo ofensivo",
    inappropriateName: "Nombre inapropiado",
    cheating: "Trampas",
    spam: "Spam",
    inappropriatePicture: "Imagen inapropiada",
    sendThatReport: "enviar esa denuncia",
    reportNickname: (p: { nickname: string }) =>
      `Denunciar a ${p.nickname}`,
    reportSent: "Denuncia enviada",
    sending: "Enviando…",
    sendReport: "Enviar denuncia",
    cancel: "Cancelar",
    close: "Cerrar",
  },

  reportsReviewedNotice: {
    reportsReviewed: (p: { count: number }) =>
      `${counted(p.count, { one: "denuncia que enviaste ha sido revisada", other: "denuncias que enviaste han sido revisadas" })}. Gracias.`,
  },

  restartVoteBanner: {
    voteTally: (p: { yes: number; no: number; pending: number }) =>
      `${p.yes} a favor, ${p.no} en contra, ${p.pending} pendientes`,
    restartingIn: (p: { seconds: number }) =>
      `Reiniciando en ${counted(p.seconds, { one: "segundo", other: "segundos" })}`,
    restartApproved: "¡Reinicio aprobado!",
    seconds: "segundos",
    voteRestartGame: "Votar para reiniciar la partida",
    restart: "Reiniciar",
    keepPlaying: "Seguir jugando",
    onlyEligiblePlayersPresentWhenVote: "Solo pueden votar los jugadores elegibles que estaban cuando empezó la votación.",
    proposerNicknameProposedRestartingRemainingS: (p: { proposerNickname: string; remaining: number }) =>
      `${p.proposerNickname} propuso reiniciar · ${p.remaining} s`,
    theCurrentGameIsRestarting: "La partida se está reiniciando ahora.",
    yesYesNoNoPending: (p: { yes: number; no: number; pending: number; requiredVotes: number }) =>
      `${p.yes} sí · ${p.no} no · ${p.pending} pendientes · ${p.requiredVotes} necesarios`,
  },

  roleChangeNotice: {
    youHaveBeenSignedOutEvery: "Se ha cerrado tu sesión en todos los dispositivos para que el cambio\n            surta efecto. Vuelve a iniciar sesión para continuar.",
    setUpNow: "Configurarlo ahora",
    later: "Más tarde",
    oneMoment: "Un momento…",
    signInAgain: "Volver a iniciar sesión",
    understood: "Entendido",
  },

  roomChatPanel: {
    unreadMessages: (p: { count: number }) =>
      `${counted(p.count, { one: "mensaje nuevo", other: "mensajes nuevos" })}`,
    correctWithPlace: (p: { place: string | null }) =>
      p.place ? `Correcto · ${p.place}` : "Correcto",
    couldNotSendMessage: "No se pudo enviar el mensaje",
    sent: "Enviado:",
    send: "Enviar",
    youReDrawingWatchGuessesCome: "Estás dibujando: mira cómo llegan las conjeturas.",
    yourGuessTrimmedDidNot: (p: { trimmed: string }) =>
      `Tu respuesta «${p.trimmed}» no llegó al servidor. Envíala otra vez.`,
    sendTheMessage: "enviar el mensaje",
    chatWhileYouWait: "Chatea mientras esperas",
    gameChat: "Chat de la partida",
    guessAndChat: "Adivina y chatea",
    guessesAndChat: "Respuestas y chat",
    roomChat: "Chat de la sala",
    sayHelloBeforeTheGame: "Saluda antes de que empiece la partida.",
    noMessagesYet: "Aún no hay mensajes.",
    typeYourGuess: "Escribe tu respuesta...",
    typeAMessage: "Escribe un mensaje...",
  },

  roomEntryState: {
    thisRoomNoLongerAvailable: "Esta sala ya no está disponible",
    couldNotJoinThisRoom: "No se pudo entrar en esta sala",
    thatNameIsReservedPlease: "Ese nombre está reservado. Elige otro.",
    thisRoomHasEndedAsk: "Esta sala ha terminado. Pide al anfitrión una invitación nueva.",
    loadThisRoom: "cargar esta sala",
    enterANicknameToContinue: "Escribe un apodo para continuar.",
    thePlayerSlotsJustFilled: "Las plazas de jugador se acaban de llenar, pero aún puedes mirar.",
    joinAsASpectator: "unirte como espectador",
    joinThisRoom: "unirte a esta sala",
    nicknameRule: "Usa de 3 a 16 caracteres: letras, números, guiones o guiones bajos. Sin espacios.",
  },

  roomMenuSheet: {
    startTheGameOver: "Empezar la partida de nuevo",
    startOverCooldown: (p: { seconds: number }) => ` · en ${p.seconds}s`,
    room: "Sala",
    playersScores: "Jugadores y puntos",
    copyInviteLink: "Copiar el enlace de invitación",
    saveThisDrawing: "Guardar este dibujo",
    settings: "Ajustes",
    leaveRoom: "Salir de la sala",
    iMBack: "Ya estoy aquí",
    goAwayForABit: "Ausentarme un rato",
  },

  roomPlayersPanel: {
    spectatorCount: (p: { count: number }) =>
      counted(p.count, { one: "espectador", other: "espectadores" }),
    spectatorsHeading: (p: { count: number }) => `Espectadores (${p.count})`,
    playersOfCapacity: (p: { here: number; capacity: number }) =>
      `${p.here} de ${p.capacity} jugadores`,
    readyCount: (p: { count: number }) => `${p.count} listos`,
    couldNotJoinAsPlayer: "No se pudo entrar como jugador",
    finalStandings: "Clasificación final",
    players: "Jugadores",
    joinAsAPlayer: "unirte como jugador",
    aPlayerSlotIsAvailable: "Hay una plaza de jugador libre.",
    playerSlotsAreCurrentlyFull: "Las plazas de jugador están llenas.",
    joining: "Uniéndote…",
    joinAsPlayer: "Unirse como jugador",
  },

  roomSettingsEditor: {
    couldNotLoadRoomRules: "No se pudieron cargar las reglas de la sala",
    roomRefusedThoseSettings: "La sala rechazó esos ajustes.",
    hostSettings: "Ajustes del anfitrión",
    editRoomRules: "Editar las reglas de la sala",
    loadingSettings: "Cargando ajustes…",
    cancel: "Cancelar",
    loadRoomRules: "cargar las reglas de la sala",
    saveRoomRules: "guardar las reglas de la sala",
    saving: "Guardando…",
    saveSettings: "Guardar ajustes",
    saved: "Guardado",
  },

  roomSetupForm: {
    language: "Idioma",
    visibility: "Visibilidad",
    maxPlayers: "Máximo de jugadores",
    rounds: "Rondas",
    drawingTime: "Tiempo de dibujo",
    onlyUseCustomPrompts: "Usar solo palabras propias",
    addUsableCustomPromptEnableThis: "Añade una palabra propia utilizable para activar esta opción.",
    allowedTools: "Herramientas permitidas",
    colors: "Colores",
    scoring: "Puntuación",
    hints: "Pistas",
    spectatorsCanSeePrompt: "Los espectadores ven la palabra",
    hideBlanks: "Ocultar los huecos",
    alsoTurnsHintsOffWithNo: "También apaga las pistas: sin huecos no hay nada que revelar.",
    promptTotal: (p: { count: number }) =>
      counted(p.count, { one: "palabra", other: "palabras" }),
    basics: "Básicos",
    roomName: "Nombre de la sala",
    public: "Pública",
    private: "Privada",
    prompts: "Palabras",
    drawing: "Dibujando",
    scoringHints: "Puntuación y pistas",
    hintsAreOffBecauseBlanksAre: "Las pistas están apagadas porque los huecos están ocultos.",
    pointPurchaseHintModesRequireScoring: "Los modos de pista de pago requieren puntuación.",
    allColors: "Todos los colores",
    noScoring: "Sin puntuación",
    listedInTheLobbyAnyone: "Aparece en el vestíbulo: cualquiera puede entrar.",
    joinableOnlyWithTheCode: "Solo se entra con el código o el enlace de invitación.",
    customCount: (p: { count: number }) =>
      counted(p.count, { one: "propia", other: "propias" }),
  },

  rulesPage: {
    sketchy: "Sketchy",
    theRules: "Las reglas",
    thisPage: "En esta página",
    forExample: "Por ejemplo",
    backToLobby: "Volver al vestíbulo",
  },

  sessionManagerDialog: {
    lastUsed: (p: { when: string }) => `Usado por última vez ${p.when}`,
    signsOutOn: (p: { when: string }) => `Se cierra sola ${p.when}`,
    usedElsewhere: (p: { when: string }) =>
      `Usado desde otro navegador el ${p.when}. Cierra este dispositivo si no eras tú.`,
    couldNotLoadSignedDevices: "No se pudieron cargar los dispositivos con sesión iniciada.",
    couldNotRevokeDevice: "No se pudo cerrar el dispositivo.",
    couldNotLogOutEverywhere: "No se pudo cerrar sesión en todas partes.",
    signedDevices: "Dispositivos con sesión iniciada",
    revokeAnyDeviceYouNoLonger: "Cierra cualquier dispositivo que ya no reconozcas. Los nombres son aproximados y no guardan versiones de navegador.\n          Un dispositivo que dejas de usar cierra su sesión a los noventa días.",
    loadingDevices: "Cargando dispositivos…",
    currentDevice: "Dispositivo actual",
    close: "Cerrar",
    revoking: "Revocando…",
    revoke: "Revocar",
    loggingOut: "Cerrando sesión…",
    logOutEverywhere: "Cerrar sesión en todas partes",
  },

  settingsOverlay: {
    email: "Correo",
    password: "Contraseña",
    twoFactorAuthentication: "Verificación en dos pasos",
    signedDevices: "Dispositivos con sesión iniciada",
    downloadEverything: "Descargar todo",
    colorScheme: "Esquema de color",
    appliesMomentYouPick: "Se aplica en cuanto lo eliges.",
    languageYouPlay: "Idioma en el que juegas",
    roomsThisLanguageComeFirstLobby: "Las salas en este idioma salen primero en el vestíbulo, y una sala que crees empieza en él. Es distinto del idioma en el que lees Sketchy.",
    interfaceLanguage: "Idioma en el que lees",
    interfaceLanguageHint: "Cada palabra del propio Sketchy. Distinto del idioma en el que juegas: leer en uno y jugar en otro es de lo más normal.",
    timeFormat: "Formato de hora",
    howEveryClockReadsChatTimestamps: "Cómo se lee cada reloj: marcas de chat, fechas de inicio de sesión, avisos. «Sistema» sigue a tu dispositivo.",
    iHaveTroubleTellingColorsApart: "Me cuesta distinguir los colores",
    nudgesHostsTowardRoomColorsThat: "Empuja a los anfitriones hacia colores de sala que se distingan con deuteranopía y protanopía, sin decirles quién lo pidió. Nada cambia solo.",
    brushCursor: "Cursor del pincel",
    crosshairPreciseAtPointOutlineShows: "Una cruz es precisa en el punto; un contorno muestra el ancho del trazo.",
    brushCursorStyle: "Estilo del cursor del pincel",
    soundEffects: "Efectos de sonido",
    chimesCorrectGuessStartRoundLast: "Sonidos al acertar, al empezar una ronda, en los últimos diez segundos y cuando entran o salen jugadores.",
    volume2: "Volumen",
    confetti: "Confeti",
    burstWhenYouGuessRightAgain: "Una explosión cuando aciertas, y otra para quien gane al final de la partida.",
    clickKeyRebindEachActionCan: "Haz clic en una tecla para reasignarla. Cada acción admite dos. Pulsa Esc para cancelar.",
    theseAreTheirSettings: (p: { name: string }) => `Ahora estos son los ajustes de ${p.name}.`,
    guestLivesInThisBrowser: (p: { name: string }) =>
      `${p.name} solo vive en este navegador. Una cuenta conserva el nombre, tus puntos y tu historial en todos los dispositivos, y te deja elegir un color.`,
    systemThemeNow: (p: { theme: "dark" | "light" }) => `Ahora: ${p.theme}`,
    needsAccount: "Necesita una cuenta",
    choosePicture: "Elegir una imagen",
    editPicture: "Editar la imagen",
    picture: "Imagen",
    changePicture: "Cambiar la imagen",
    removePicture: "Quitar la imagen",
    couldNotRemovePicture: "No se pudo quitar la imagen.",
    couldNotChangeYourDisplayName: "No se pudo cambiar tu nombre visible.",
    couldNotChangeYourDisplayName2: "No se pudo cambiar tu nombre visible. Inténtalo de nuevo.",
    themeSoundShortcutsCameFromAccount: "El tema, el sonido y los atajos\n            vienen de la cuenta. Lo que tenía este navegador sigue intacto y\n            vuelve si cierras sesión.",
    dismiss: "Descartar",
    playingAsGuest: "Juegas como invitado",
    createAccount: "Crear una cuenta",
    logIn: "Iniciar sesión",
    you: "Tú",
    displayName: "Nombre visible",
    cancel: "Cancelar",
    change: "Cambiar",
    nameColor: "Color del nombre",
    signingIn: "Inicio de sesión",
    changePassword: "Cambiar contraseña",
    manage: "Gestionar",
    yourData: "Tus datos",
    requestExport: "Pedir exportación",
    delete: "Borrar…",
    display: "Pantalla",
    theme: "Tema",
    accessibility: "Accesibilidad",
    theCanvas: "El lienzo",
    sound: "Sonido",
    volume: "Volumen",
    effects: "Efectos",
    noKeyboardThisDevice: "No hay teclado en este dispositivo",
    yourBindingsAreStillSavedStill: "Tus atajos siguen guardados y funcionando. Abre Sketchy con un teclado\n            conectado para cambiarlos.",
    drawingTools: "Herramientas de dibujo",
    resetDefaults: "Restablecer valores",
    settings: "Ajustes",
    close: "Cerrar",
    closeSettings: "Cerrar los ajustes",
    settingsSections: "Secciones de ajustes",
    account: "Cuenta",
    appearance: "Apariencia",
    soundEffects2: "Sonido y efectos",
    shortcuts: "Atajos",
    red: "Rojo",
    orange: "Naranja",
    yellow: "Amarillo",
    lime: "Lima",
    green: "Verde",
    teal: "Verde azulado",
    sky: "Celeste",
    blue: "Azul",
    indigo: "Índigo",
    purple: "Morado",
    magenta: "Magenta",
    pink: "Rosa",
    brown: "Marrón",
    light: "Claro",
    dark: "Oscuro",
    system: "Sistema",
    crosshair: "Cruz",
    outline: "Contorno",
    space: "Espacio",
    hideTheFullAddress: "Ocultar la dirección completa",
    showTheFullAddress: "Mostrar la dirección completa",
    hide: "Ocultar",
    showInFull: "Mostrar completa",
    verified: "Verificado",
    notVerified: "Sin verificar",
    saving: "Guardando…",
    save: "Guardar",
    aGuestHasNothingTo: "Un invitado no tiene nada que recuperar: no hay contraseña que olvidar.",
    withoutOneThereIsNo: "Sin él no hay forma de volver a esta cuenta si se olvida la contraseña.",
    addAnEmail: "Añadir un correo",
    guestsHaveNoPassword: "Los invitados no tienen contraseña.",
    changingItSignsEveryOther: "Cambiarla cierra la sesión en todos los demás dispositivos.",
    setThisUpAndThe: (p: { pendingRole: string }) =>
      `Configúralo y el rol de ${p.pendingRole} que te ofrecieron entrará en vigor.`,
    anAuthenticatorAppSCode: "Un código de una aplicación de autenticación, además de tu contraseña. Los moderadores y administradores deben tenerlo.",
    setUp: "Configurar",
    thisBrowserIsTheOnly: "Este navegador es el único lugar donde existes.",
    everyBrowserStillHoldingA: "Cada navegador que aún tiene una sesión, y una forma de cerrar cualquiera.",
    worksForAGuestToo: "También sirve para invitados: las partidas que jugaste son tuyas.",
    everyGameListAndSetting: "Cada partida, lista y ajuste que Sketchy guarda sobre ti, en un solo archivo JSON.",
    deleteThisGuest: "Eliminar este invitado",
    deleteYourAccount: "Eliminar tu cuenta",
    removesTheNameThePoints: "Elimina el nombre, los puntos y el historial guardados para este navegador.",
    gamesYouPlayedStayIn: "Las partidas que jugaste siguen en el historial de los demás, sin tu nombre.",
    clickToRebindTheSecond: "Haz clic para reasignar la segunda tecla",
    clickToRebind: "Haz clic para reasignar",
    pressKey: "Pulsa una tecla…",
    key: "+ tecla",
    none: "Ninguna",
  },

  stepUpDialog: {
    codeFromYourAuthenticatorApp2: "Código de tu aplicación de autenticación",
    passkeyNotUsed: "Esa passkey no se usó. Puedes intentarlo de nuevo.",
    thatCodeWasNotAccepted: "Ese código no se aceptó.",
    thatPasskeyWasNotAccepted: "Esa passkey no se aceptó.",
    confirmYou: "Confirma que eres tú",
    recoveryCode: "Código de recuperación",
    codeFromYourAuthenticatorApp: "Código de tu aplicación de autenticación",
    cancel: "Cancelar",
    waitingForYourDevice: "Esperando a tu dispositivo…",
    useYourPasskey: "Usar tu passkey",
    useYourAuthenticatorApp: "Usar tu aplicación de autenticación",
    useARecoveryCode: "Usar un código de recuperación",
    checking: "Comprobando…",
    confirm: "Confirmar",
  },

  suspensionNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Tu dibujo de ${p.prompt}, tal como se denunció`,
    recordedAs: "Registrado como {category}",
    yourAccountSuspended: "Tu cuenta está suspendida",
    youWereAskedDraw: "Te tocaba dibujar",
    theMessageThisWasAbout: "El mensaje en cuestión:",
    theMessagesThisWasAbout: "Los mensajes en cuestión:",
    theDrawingThisWasAbout: "El dibujo en cuestión:",
    theDrawingsThisWasAbout: "Los dibujos en cuestión:",
    signingOut: "Cerrando sesión…",
    signOut: "Cerrar sesión",
  },

  toastProvider: {
    notifications: "Notificaciones",
    dismissNotification: "Descartar notificación",
  },

  toolbar: {
    colorOption: (p: { color: string }) => `color ${p.color}`,
    adjustSize: (p: { tool: string }) => `Ajustar el tamaño de ${p.tool}`,
    sizeSnappingSlider: (p: { tool: string }) => `Control de tamaño con ajuste para ${p.tool}`,
    chooseToolCurrent: (p: { tool: string }) => `Elegir herramienta, actual: ${p.tool}`,
    chooseColorCurrent: (p: { color: string }) => `Elegir color, actual ${p.color}`,
    sizeWithWidth: (p: { tool: string; width: number }) => `${p.tool}, tamaño ${p.width}px`,
    sizeShortcutHint: (p: { tool: string; width: number }) =>
      `${p.tool}, tamaño: ${p.width}px ([ / ])`,
    widthReadout: (p: { width: number }) => `${p.width}px`,
    colorSwatch: (p: { color: string }) => `Color ${p.color}`,
    drawingTools: "Herramientas de dibujo",
    chooseTool: "Elegir herramienta",
    chooseColor: "Elegir color",
    undoLastStroke: "Deshacer el último trazo",
    undo: "Deshacer",
    clearCanvas: "Vaciar el lienzo",
    chooseCustomColor: "Elegir un color personalizado",
    colorPalette: "Paleta de colores",
    canvasActions: "Acciones del lienzo",
    undoLastStrokeCtrlZ: "Deshacer el último trazo (Ctrl+Z)",
    clear: "Vaciar",
    brush: "Pincel",
    fill: "Relleno",
    eraser: "Goma",
    rectangle: "Rectángulo",
    triangle: "Triángulo",
    ellipse: "Elipse",
    fillIsUnavailableForThe: "El relleno no está disponible durante el resto de este turno",
    drawingByHandIsUnavailable: "Dibujar a mano no está disponible durante el resto de este turno",
  },

  turnResultsOverlay: {
    yourTurnWithHints: (p: { base: number; hintSpend: number; points: number; rank: number }) =>
      `Tu turno: +${p.base} -${p.hintSpend} pistas = ${counted(p.points, { one: "punto", other: "puntos" })} · ahora #${p.rank}`,
    yourTurn: (p: { delta: number; rank: number }) =>
      `Tu turno: ${p.delta >= 0 ? "+" : ""}${p.delta} ${
        Math.abs(p.delta) === 1 ? "punto" : "puntos"
      } · ahora #${p.rank}`,
    promptWas: "La palabra era",
    noOneGuessedCorrectly: "Nadie ha acertado.",
    you: "(tú)",
    drewThisTurn: "Dibujó este turno",
    nextTurn: "Siguiente turno",
    turnResults: "Resultados del turno",
    turnComplete: "Turno terminado",
  },

  twoFactorDialog: {
    scanThisWithYourAuthenticatorApp: "Escanea esto con tu aplicación de autenticación para añadir esta cuenta",
    codeFromYourAuthenticatorApp: "Código de tu aplicación de autenticación",
    secondFactorState: (p: {
      recoveryCodesRemaining: number | null;
      confirmAuthenticator: boolean;
    }) =>
      [
        "La verificación en dos pasos está activada.",
        p.recoveryCodesRemaining === null
          ? null
          : `Te quedan ${counted(p.recoveryCodesRemaining, {
              one: "código de recuperación",
              other: "códigos de recuperación",
            })}.`,
        p.confirmAuthenticator
          ? "Antes de que esta cuenta pueda tener un rol de moderador o administrador, confirma con tu contraseña y un código que el autenticador es tuyo."
          : null,
        "Cada uno de los cambios de abajo sustituye una credencial, así que cada uno pide tu contraseña.",
      ]
        .filter(Boolean)
        .join(" "),
    confirmAuthenticatorFirst:
      "Antes de que esta cuenta pueda tener un rol de moderador o administrador, confirma con tu contraseña y un código que el autenticador es tuyo.",
    copied: (p: { what: string }) => `${p.what} copiado.`,
    couldNotCopy: (p: { what: string }) =>
      `No se pudo copiar ${p.what}. Selecciónalo y cópialo a mano.`,
    roleTaken: (p: { role: "admin" | "moderator" }) =>
      `Ahora eres ${p.role === "admin" ? "administrador" : "moderador"}. La verificación en dos pasos está activada y el rol que la esperaba ya está en vigor. Se ha cerrado la sesión en tus otros dispositivos; este sigue, y cada inicio de sesión desde aquí pedirá un código.`,
    recoveryCodesLeft: (p: { count: number }) =>
      `Te quedan ${counted(p.count, { one: "código de recuperación", other: "códigos de recuperación" })}.`,
    couldNotReadYourSecuritySettings: "No se pudieron leer tus ajustes de seguridad.",
    yourPasswordConfirmsAuthenticatorYours: "Tu contraseña confirma que el autenticador es tuyo.",
    yourPasswordConfirmsThisPasskeyYours: "Tu contraseña confirma que esta passkey es tuya.",
    passkeyAdded: "Passkey añadida.",
    thatPasskeyWasNotCreatedYou: "Esa passkey no se creó. Puedes intentarlo de nuevo.",
    yourPasswordNeededRemovePasskey: "Hace falta tu contraseña para quitar una passkey.",
    confirmedThisAccountCanNowBe: "Confirmado. Esta cuenta ya puede recibir un rol del equipo.",
    twoFactorAuthentication: "Verificación en dos pasos",
    saveTheseRecoveryCodesNow: "Guarda ahora estos códigos de recuperación.",
    eachOneSignsYouOnceIf: "Cada uno te permite iniciar\n              sesión una vez si pierdes tu aplicación de autenticación. No se\n              vuelven a mostrar: solo se guardan sus hashes.",
    recoveryCodes: "Códigos de recuperación",
    downloadAsFile: "Descargar como archivo",
    copyAll: "Copiar todos",
    iHaveSavedTheseSomewhereSafe: "Los he guardado en un sitio seguro",
    done: "Hecho",
    moderatorsAdministratorsSignWithPasskeyYour: "Los moderadores y administradores inician sesión con una passkey: tu\n              dispositivo confirma que eres tú — huella, cara o PIN — y no se\n              teclea nada que se pueda entregar.",
    yourPassword: "Tu contraseña",
    confirmsPasskeyBeingAddedByYou: "Confirma que la passkey la añades tú.",
    useAuthenticatorAppInstead: "Usar una aplicación de autenticación",
    scanCodeWithAuthenticatorAppThen: "Escanea el código con una aplicación de autenticación y teclea luego\n              los seis dígitos que muestre.",
    drawingCode: "Dibujando el código…",
    pointYourAppAtThis: "Apunta tu aplicación aquí.",
    setupKey: "Clave de configuración",
    copySetupKey: "Copiar la clave de configuración",
    useThisIfYouCanT: "Úsala si no puedes escanear.",
    confirmsAuthenticatorYours: "Confirma que el autenticador es tuyo.",
    codeFromYourApp: "Código de tu aplicación",
    cancel: "Cancelar",
    passkeys: "Passkeys",
    thisDeviceOnly: "· solo en este dispositivo",
    remove: "Quitar",
    confirmSYours: "Confirmar que es tuya",
    addPasskey: "Añadir una passkey",
    newRecoveryCodes: "Códigos de recuperación nuevos",
    turnOff: "Desactivar",
    addAuthenticatorApp: "Añadir una aplicación de autenticación",
    close: "Cerrar",
    couldNotStartSettingThis: "No se pudo empezar la configuración.",
    thatCodeWasNotAccepted: "Ese código no se aceptó.",
    couldNotAddThatPasskey: "No se pudo añadir esa passkey.",
    couldNotRemoveThatPasskey: "No se pudo quitar esa passkey.",
    couldNotConfirmIt: "No se pudo confirmar.",
    couldNotReplaceYourRecovery: "No se pudieron reemplazar tus códigos de recuperación.",
    couldNotTurnThisOff: "No se pudo desactivar.",
    waitingForYourDevice: "Esperando a tu dispositivo…",
    setUpAPasskey: "Configurar una passkey",
    noPasskeyOnThisDevice: "¿No hay passkey en este dispositivo? ",
    thisBrowserCannotMakeA: "Este navegador no puede crear una passkey. ",
    checking: "Comprobando…",
    confirm: "Confirmar",
  },

  useFriendArrivalNotices: {
    wantsToBeFriends: (p: { name: string }) => `${p.name} quiere ser tu amigo.`,
    acceptedYourRequest: (p: { name: string }) => `${p.name} ha aceptado tu solicitud de amistad.`,
    severalAccepted: (p: { count: number }) =>
      `${counted(p.count, { one: "persona ha aceptado", other: "personas han aceptado" })} tus solicitudes de amistad.`,
    accept: "Aceptar",
    open: "Abrir",
    manyArrived: (p: { name: string; others: number }) =>
      `${p.name} y ${counted(p.others, { one: "otra persona", other: "otras personas" })} quieren ser tus amigos.`,
  },

  useRoomSessionReconnect: {
    joinRoomFailed: "join_room failed",
  },

  waitingRoomPanel: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "ronda", other: "rondas" }),
    needMorePlayers: (p: { count: number }) =>
      `${counted(p.count, { one: "Falta 1 jugador", other: "Faltan más jugadores" })}`,
    hostWillStart: (p: { rematch: boolean }): string =>
      p.rematch ? "{host} empezará la revancha" : "{host} empezará la partida",
    copied: (p: { what: string }) => `${p.what} copiado.`,
    couldNotCopy: (p: { what: string }) =>
      `No se pudo copiar ${p.what}. Cópialo de la barra de direcciones.`,
    roomCodeLabel: (p: { code: string }) => `Código de sala ${p.code}`,
    rosterCount: (p: { here: number; capacity: number }) => `${p.here} de ${p.capacity}`,
    inviteYourFriends: "Invita a tus amigos",
    shareLink: "Comparte el enlace",
    copyCode: "Copiar código",
    inTheRoom: "En la sala",
    you: "(tú)",
    host: "Anfitrión",
    friend: "Amigo",
    invite: "Invitar",
    edit: "Editar",
    viewHighlights: "Ver los destacados",
    viewDrawings: "Ver los dibujos",
    spectatorsAfkAndDisconnectedPlayers: "Los espectadores, los ausentes y los desconectados no cuentan para los dos jugadores activos que necesita una partida.",
    joinMySketchyRoomCode: (p: { code: string }) =>
      `Únete a mi sala de Sketchy: ${p.code}`,
    inviteLink: "Enlace de invitación",
    customPromptsOnlyCustomPromptCount: (p: { customPromptCount: number }) =>
      `Solo palabras propias (${p.customPromptCount})`,
    customPromptCountCustomPromptsCuratedLists: (p: { customPromptCount: number }) =>
      `${p.customPromptCount} palabras propias + listas seleccionadas`,
    promptListSlugsCountCuratedPromptLists: (p: { promptListSlugsCount: number }) =>
      `${p.promptListSlugsCount} listas de palabras seleccionadas`,
    noScoring: "Sin puntuación",
    spectatorsSeeThePrompt: "Los espectadores ven la palabra",
    publicRoom: "Sala pública",
    privateRoom: "Sala privada",
    betweenGames: "entre partidas",
    waitingForPlayers: "esperando jugadores",
    roomCode: "Código de sala",
    starting: "Empezando…",
    rematch: "Revancha",
    startGame: "Empezar partida",
    waitingForAHost: "Esperando a un anfitrión",
  },

  warningNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Tu dibujo de ${p.prompt}, tal como se denunció`,
    recordedAs: "Registrado como {category}",
    whatAWarningMeans:
      "Se ha revisado una denuncia sobre tu comportamiento, y este es el resultado. No hay restricciones, pero otra denuncia podría llevar a la suspensión de tu cuenta.",
    youWereAskedDraw: "Te tocaba dibujar",
    yourPictureWasRemoved: "Se eliminó tu imagen",
    aModeratorWarning: "Un aviso de moderación",
    aReportAboutYourPicture: "Se revisó una denuncia sobre tu imagen y este es el resultado. No afecta a nada más de tu cuenta.",
    theMessageThisWasAbout: "El mensaje en cuestión:",
    theMessagesThisWasAbout: "Los mensajes en cuestión:",
    theDrawingThisWasAbout: "El dibujo en cuestión:",
    theDrawingsThisWasAbout: "Los dibujos en cuestión:",
    oneMoment: "Un momento…",
    understood: "Entendido",
  },
  connectionStatusBanner: {
    youReDisconnectedCheckYour: "Te has desconectado. Revisa tu conexión; Sketchy se reconectará solo.",
    couldnTReconnectToYour: "No se pudo volver a conectar con tu sala. Recarga la página para intentarlo de nuevo.",
    connectionLostReconnecting: "Conexión perdida: reconectando…",
  },
  accountData: {
    queued: "En cola",
    preparing: "Preparando…",
    ready: "Listo",
    tooLargeToPrepareHere: "Demasiado grande para prepararlo aquí",
    couldNotPrepare: "No se pudo preparar",
    yourDataIsLargerThan: "Tus datos superan lo que este servidor prepara en un solo documento. Pide al operador que suba el límite.",
    somethingWentWrongWhilePreparing: "Algo falló al prepararlo. Puedes solicitar otra exportación.",
  },
  recoveryCodeFile: {
    sketchyRecoveryCodes: "Códigos de recuperación de Sketchy",
    accountUsername: (p: { username: string }) =>
      `Cuenta: ${p.username}`,
    createdValue: (p: { value: string }) =>
      `Creado: ${p.value}`,
    eachCodeSignsYouIn: "Cada código te permite iniciar sesión una vez si pierdes tu aplicación de autenticación.",
    keepThisFile: "Guarda este archivo donde solo tú puedas llegar. Quien tenga estos códigos\ny tu contraseña puede iniciar sesión como tú.",
  },
  avatars: {
    chooseAPngJpegWebP: "Elige una imagen PNG, JPEG, WebP o GIF.",
    thatPictureIsTooLarge: "Esa imagen es demasiado grande para leerla: 10 MB como máximo.",
    thatFileCouldNotBe: "Ese archivo no se pudo leer como imagen.",
    thatPictureIsTooSmall: "Esa imagen es demasiado pequeña para sacar algo de ella.",
    thisBrowserCannotResizePictures: "Este navegador no puede redimensionar imágenes.",
    thatPictureIsTooDetailed: "Esa imagen tiene demasiado detalle. Prueba con una más sencilla o amplía una parte.",
  },
  settingsSync: {
    thatChangeAppliesHereBut: "Ese cambio se aplica aquí, pero no se pudo guardar en tu cuenta. Tus otros dispositivos no lo verán.",
  },
  promptStats: {
    hardestFirst: "Más difíciles primero",
    easiestFirst: "Más fáciles primero",
    mostPicked: "Más elegidas",
    getsGuessed: "Se adivina",
    usuallyGuessed: "Suele adivinarse",
    evenOdds: "Mitad y mitad",
    oftenMissed: "Se falla a menudo",
    rarelyGuessed: "Rara vez se adivina",
    notPlayedEnough: "Poco jugada",
    allRanked: (p: { count: number }) =>
      `Las ${p.count} palabras se han jugado lo suficiente para clasificarlas.`,
    noneRanked: (p: { unrated: number; guessers: number }) =>
      `Ninguna de estas ${p.unrated} palabras ha tenido aún ${p.guessers} jugadores adivinando, así que ninguna está clasificada. Jugad algunas partidas y su dificultad aparecerá aquí.`,
    someRanked: (p: { rated: number; unrated: number; guessers: number }) =>
      `${p.rated} clasificadas. ${plural(p.unrated, { one: `Queda ${p.unrated} palabra sin clasificar`, other: `Quedan ${p.unrated} palabras sin clasificar` })}: menos de ${p.guessers} jugadores las han visto.`,
    noMatch: (p: { query: string }) =>
      `Ninguna palabra coincide con «${p.query}».`,
    matching: (p: { count: number; query: string }) =>
      `${counted(p.count, { one: "palabra coincide", other: "palabras coinciden" })} con «${p.query}».`,
  },
  gameHeaderStatus: {
    roundRoundNumberOfTotalRounds: (p: { roundNumber: number; totalRounds: number }) =>
      `Ronda ${p.roundNumber} de ${p.totalRounds}`,
  },
  gameRoomRegions: {
    theNextPlayer: "El siguiente jugador",
    drawingCanvasYouAreDrawing: "Lienzo de dibujo. Estás dibujando.",
    yourTurnToDraw: "Te toca dibujar.",
    canvasSpectating: (p: { drawer: string }) =>
      `Lienzo de dibujo. Estás mirando a ${p.drawer}.`,
    canvasSomeoneDrawing: (p: { drawer: string }) =>
      `Lienzo de dibujo. ${p.drawer} está dibujando.`,
    someoneIsDrawing: (p: { drawer: string }) =>
      `${p.drawer} está dibujando.`,
    theDrawer: "quien dibuja",
    aPlayer: "Alguien",
  },
  useToolbarState: {
    fillIsUnavailableForThe: "El relleno no está disponible durante el resto de este turno.",
    drawingByHandIsUnavailable: "Dibujar a mano no está disponible durante el resto de este turno. Las formas siguen funcionando.",
  },
  timer: {
    n10SecondsRemaining: "Quedan 10 segundos",
    timeIsUp: "Se acabó el tiempo",
  },
  chatAnnouncements: {
    nicknameGuessedThePrompt: (p: { nickname: string }) =>
      `${p.nickname} adivinó la palabra.`,
  },
  canvasSnapshot: {
    drawingOfDownloadPrompt: (p: { downloadPrompt: string }) =>
      `Dibujo de ${p.downloadPrompt}`,
    savedDrawing: "Dibujo guardado",
  },
  roomSetup: {
    default: "Estándar",
    fasterGuessesEarnMore100: "Acertar antes da más puntos, de 100 a 300.",
    pressure: "Presión",
    pointsDecayEverySecondTwice: "Los puntos bajan cada segundo, el doble de rápido cuando alguien acierta.",
    noScoring: "Sin puntuación",
    justDrawAndGuessNo: "Solo dibujar y adivinar. Sin clasificación.",
    timedHints: "Pistas por tiempo",
    lettersRevealToEveryoneAt: "Las letras se revelan a todos en momentos fijos.",
    noHints: "Sin pistas",
    blanksOnlyAllTurnLong: "Solo huecos, todo el turno.",
    buyLetters: "Comprar letras",
    revealALetterSlotJust: "Revela una letra solo para ti, pagada con los puntos de ese turno.",
    wheelOfFortune: "Ruleta de la suerte",
    pickALetterPayIts: "Elige una letra y paga su precio; las vocales cuestan más.",
    hiddenPrompt: "Palabra oculta",
    defaultScoring: "Puntuación estándar",
    pressureScoring: "Puntuación de presión",
  },
  screenCapture: {
    thisBrowserCouldNotEncode: "Este navegador no pudo codificar la captura.",
    theCaptureWasEmpty: "La captura estaba vacía.",
    thisBrowserCouldNotRead: "Este navegador no pudo leer la captura.",
    thatScreenshotIsTooLarge: "Esa captura es demasiado grande para enviarla.",
  },
  accountRecovery: {
    youCanRecoverThisAccount: (p: { address: string }) =>
      `Puedes recuperar esta cuenta a través de ${p.address}.`,
    checkPendingAddressForAConfirmation: (p: { pendingAddress: string }) =>
      `Busca en ${p.pendingAddress} un enlace de confirmación. Hasta que lo sigas, esta cuenta no tiene forma de recuperarse.`,
    thisServerCannotSendEmail: "Este servidor no puede enviar correos, así que una contraseña perdida la tiene que restablecer quien lo administra.",
    addAnEmailAddressSo: "Añade una dirección de correo para poder volver a entrar si olvidas tu contraseña.",
  },
  friends: {
    aFriend: "Un amigo",
  },
  lobbyPresence: {
    showingShownOfOnlineCount: (p: { shown: number; onlineCount: number }) =>
      `Mostrando ${p.shown} de ${p.onlineCount}`,
    onlineCount: (p: { count: number }) =>
      `${number(p.count)} en línea`,
  },
  authStore: {
    chooseANameToPlay: "Elige un nombre con el que jugar.",
  },
  passkeys: {
    noPasskeyWasCreated: "No se creó ninguna passkey.",
    noPasskeyWasUsed: "No se usó ninguna passkey.",
  },
  useGameSocketListeners: {
    nicknameJoinedTheRoom: (p: { nickname: string }) =>
      `${p.nickname} se unió a la sala`,
    gameStarted: "¡Empezó la partida!",
    drawerNicknameIsChoosingAPrompt: (p: { drawerNickname: string }) =>
      `${p.drawerNickname} está eligiendo una palabra...`,
    thePromptWasPrompt: (p: { prompt: string }) =>
      `La palabra era «${p.prompt}»`,
    gotIt: (p: { nickname: string; time: string | null; points: number | null }) =>
      `${p.nickname} acertó${p.time === null ? "" : ` · ${p.time}`}${p.points === null ? "" : ` (+${p.points})`}`,
    playerReconnected: (p: { nickname: string }) =>
      `${p.nickname} se volvió a conectar`,
    playerDisconnected: (p: { nickname: string }) =>
      `${p.nickname} se desconectó`,
  },
  settingsStore: {
    brushTool: "Pincel",
    fillTool: "Relleno",
    eraserTool: "Goma",
    rectangleTool: "Rectángulo",
    triangleTool: "Triángulo",
    ellipseTool: "Elipse",
    decreaseBrushSize: "Reducir el pincel",
    increaseBrushSize: "Agrandar el pincel",
    undoStroke: "Deshacer trazo",
  },
  reactions: {
    loveIt: "Me encanta",
    funny: "Divertido",
    wow: "Guau",
    fire: "Fuego",
    reaction: "Reacción",
  },
  drawingRules: {
    brush: "Pincel",
    theBrushAndTheEraser: "El pincel y la goma.",
    fill: "Relleno",
    theFillTool: "La herramienta de relleno.",
    shapes: "Formas",
    rectangleEllipseAndTriangle: "Rectángulo, elipse y triángulo.",
    allColors: "Todos los colores",
    thePaletteAndTheCustom: "La paleta y el selector de color personalizado.",
    paletteOnly: "Solo la paleta",
    theBuiltInSwatchesNo: "Las muestras incluidas; sin colores personalizados.",
    colorblindSafe: "Apto para daltonismo",
    colorsThatStayApartFor: "Colores que se distinguen bien para jugadores daltónicos.",
    blackAndWhite: "Blanco y negro",
    blackAndWhiteOnly: "Solo blanco y negro.",
    allTools: "Todas las herramientas",
    onlyTool: (p: { tool: string }) =>
      `solo ${p.tool}`,
    toolList: (p: { rest: string; last: string }) =>
      `${p.rest} y ${p.last}`,
  },
  socket: {
    sketchyIsFullRightNow: "Sketchy está lleno ahora mismo. Inténtalo de nuevo en unos minutos.",
    connectionLostWhileTryingTo: (p: { action: string }) =>
      `Se perdió la conexión al intentar ${p.action}. Inténtalo de nuevo.`,
    theRequestToActionTimed: (p: { action: string }) =>
      `La solicitud para ${p.action} tardó demasiado. Inténtalo de nuevo.`,
    couldNotActionPleaseTry: (p: { action: string }) =>
      `No se pudo ${p.action}. Inténtalo de nuevo.`,
  },
  bugReports: {
    drawingAndCanvas: "Dibujo y lienzo",
    guessingAndChat: "Adivinar y chat",
    roundsScoringAndResults: "Rondas, puntuación y resultados",
    roomsAndLobby: "Salas y vestíbulo",
    promptLists: "Listas de palabras",
    accountAndSettings: "Cuenta y ajustes",
    connectionAndSync: "Conexión y sincronización",
    performance: "Rendimiento",
    accessibility: "Accesibilidad",
    somethingElse: "Otra cosa",
    blocksPlayICouldNot: "Bloquea el juego: no pude seguir",
    majorHardToPlayAround: "Grave: difícil de esquivar",
    minorWorthFixingOneDay: "Leve: vale la pena arreglarlo algún día",
    notInARoom: "No está en una sala",
    codeNotInARound: (p: { code: string }) =>
      `${p.code} · fuera de ronda`,
    codeRoundRoundOfTotal: (p: { code: string; round: number; total: number }) =>
      `${p.code} · ronda ${p.round} de ${p.total}`,
  },
  suspension: {
    thisSuspensionHasNoEnd: "Esta suspensión no tiene fecha de fin.",
    thisSuspensionHasEndedTry: "Esta suspensión ha terminado; prueba a iniciar sesión otra vez.",
    thisSuspensionLastsUntilEnds: (p: { ends: string }) =>
      `Esta suspensión dura hasta ${p.ends}.`,
  },
  clock: {
    unknown: "Desconocido",
  },
  protocol: {
    theServerWasUpdated: "El servidor se ha actualizado.",
  },
  passwordPolicy: {
    tooShort: (p: { count: number }) =>
      `Una contraseña necesita al menos ${p.count} caracteres.`,
  },
  operatorAccess: {
    administrator: "administrador",
    moderator: "moderador",
    pendingTitle: "El rol de moderador te está esperando",
    pendingBody: "Un administrador te ha ofrecido el rol de moderador. Entra en vigor cuando configures la autenticación en dos pasos: los moderadores inician sesión con un código de una aplicación de autenticación, y el rol empieza en cuanto eso está listo. Tus otros dispositivos cerrarán sesión entonces. Nada cambia hasta que lo configures, y la oferta te espera en Ajustes si ahora no es buen momento.",
    grantedTitle: "Ahora eres moderador",
    grantedBody: "Un administrador te ha dado el rol de moderador. Ha aparecido una entrada de Moderación en el menú de tu cuenta: ahí se revisan las denuncias sobre jugadores y palabras. Nada cambia en tu forma de jugar.",
    removedTitle: "Ya no eres moderador",
    removedBody: "Un administrador ha quitado el rol de moderador de tu cuenta. La entrada de Moderación ha desaparecido de tu menú. Nada más de tu cuenta ni de tus partidas se ve afectado.",
  },
  moderationCategories: {
    harassment: "acoso",
    offensive_drawing: "un dibujo ofensivo",
    inappropriate_name: "un nombre inapropiado",
    cheating: "trampas",
    spam: "spam",
    inappropriate_avatar: "una imagen inapropiada",
  },
  roomNotices: {
    kickedByVote: "Te expulsaron de la sala por votación.",
    roomClosed: "Un administrador cerró esta sala.",
    removedByAdmin: "Un administrador te sacó.",
    accountDeleted: "Tu cuenta se eliminó.",
    accountSuspended: "Tu cuenta fue suspendida.",
  },
};
