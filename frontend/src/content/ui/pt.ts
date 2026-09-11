/** Every word the interface says, in Portuguese.

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

const { counted, number, ordinal, plural } = formattersFor("pt", {"other":"º"});


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
      return `A palavra-passe tem de ter pelo menos ${count(detail, 12)} caracteres.`;
    case "too_long":
      return `A palavra-passe tem de ter no máximo ${count(detail, 128)} caracteres.`;
    case "common":
      return "Esta palavra-passe é uma das mais usadas que há. Escolhe outra.";
    case "common_repeated":
      return "É uma palavra-passe comum, apenas repetida. Escolhe outra.";
    case "short_repeated":
      return "Esta palavra-passe é uma curta repetida. Escolhe outra.";
    case "too_few_characters":
      return `Esta palavra-passe usa apenas ${count(detail, 4)} caracteres diferentes. Escolhe outra.`;
    case "keyboard_walk":
      return "Esta palavra-passe é sobretudo uma fila de teclas seguidas. Escolhe outra.";
    case "contains_identity":
      return "Uma palavra-passe não pode conter o teu nome, o teu e-mail nem o nome deste site.";
    case "common_with_digits":
      return "É uma palavra-passe comum com dígitos acrescentados. Escolhe outra.";
    default:
      return "Escolhe uma palavra-passe diferente.";
  }
}

/** *Create an account to …* - one refusal, said about the thing it refused. */
function accountRequired(params: MessageParams): string {
  switch (params.action) {
    case "avatar":
      return "Cria uma conta para escolheres uma imagem.";
    case "prompt_lists":
      return "Cria uma conta para guardares listas de palavras reutilizáveis.";
    case "name_color":
      return "Cria uma conta para escolheres uma cor de nome.";
    case "password":
      return "Cria uma conta para definires uma palavra-passe.";
    case "second_factor":
      return "Cria uma conta antes de configurares a verificação em dois passos.";
    case "friends":
      return "Cria uma conta para adicionares amigos.";
    default:
      return "Cria uma conta para fazeres isso.";
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
      return "está a decorrer uma atualização do servidor";
    case "too_few_players":
      return "restam menos de dois jogadores ativos";
    case "prompt_lists_unavailable":
      return "não foi possível carregar as listas de palavras";
    case "everybody_left":
      return "foram-se todos embora antes de começar";
    default:
      return "já não podia avançar";
  }
}

type Sentence = string | ((params: MessageParams) => string);

/** Why the server refused, said to the player.

One entry per `ErrorCode`; `Record` makes it exhaustive, so a code the server
adds without a sentence here fails the build rather than the player
(R-I18N-04). */
const REFUSALS: Record<ErrorCode, Sentence> = {
  // Payloads and arguments
  invalid_payload: "O Sketchy não conseguiu ler esse pedido.",
  invalid_nickname: "Este nome não pode ser usado aqui.",
  invalid_name_color: "Escolhe uma cor que se leia bem na lista de jogadores clara e na escura.",
  invalid_hint: "Esta pista não é válida.",
  invalid_letter: "Esta letra não é válida.",
  invalid_prompt_lists: "Estas listas de palavras não podem ser usadas em conjunto.",
  invalid_custom_prompts: "Não foi possível ler essas palavras próprias.",
  max_players_below_seated: (params) =>
  `O máximo de jogadores não pode ser inferior aos ${count(params.seated, 2)} que já estão na sala.`,
  empty_message: "Escreve algo primeiro.",

  // Rate and capacity
  too_fast: "Estás a ir demasiado depressa. Abranda um pouco.",
  seat_changing_too_fast: "Este lugar muda de mãos demasiado depressa. Tenta daqui a um minuto.",
  joining_too_fast: "Estás a entrar em salas demasiado depressa. Tenta daqui a um minuto.",
  room_quota: "Já tens tantas salas abertas quantas podes ter ao mesmo tempo.",
  room_full: "Esta sala está cheia.",
  spectators_full: "Esta sala já não aceita mais espectadores.",
  player_slots_full: "Todos os lugares de jogador estão ocupados.",

  // Server and account state
  server_draining: "O Sketchy está a reiniciar. Tenta daqui a um instante.",
  server_paused: "O Sketchy não está a aceitar salas novas neste momento.",
  database_busy: "O Sketchy está com dificuldade em chegar à base de dados. Tenta de novo.",
  account_ended: "Esta conta já não está ativa.",
  account_required: accountRequired,
  identity_unavailable: "O Sketchy não conseguiu confirmar quem és. Recarrega e tenta de novo.",

  // Rooms
  not_in_room: "Não estás nesta sala.",
  room_not_found: "Sala não encontrada.",
  room_ended: "Esta sala terminou.",
  could_not_create_room: "Não foi possível criar a sala.",
  no_session_to_resume: "Não há nenhuma sessão tua para retomar nesta sala.",
  host_only: "Só o anfitrião pode fazer isso.",
  players_only: "Só os jogadores podem fazer isso.",
  waiting_room_only: "Isso só está disponível na sala de espera.",
  already_a_player: "Já és jogador.",
  registered_name_fixed: "Os jogadores registados jogam com o seu nome de utilizador.",
  name_taken_by_account: "Este nome pertence a um jogador registado.",
  guests_cannot_choose_color: "Cria uma conta para escolheres uma cor de nome.",
  suggestion_inactive: "Esta sugestão já não está ativa.",
  drawing_not_found: "Desenho não encontrado.",
  drawing_not_kept: "Este desenho não foi guardado.",

  // Games and turns
  not_in_game: "Não estás numa partida a decorrer.",
  game_in_progress: "A partida já está a decorrer.",
  game_starting: "A partida ainda está a começar.",
  need_two_players: "São precisos dois jogadores ativos para começar.",
  room_not_startable: "Esta sala não pode começar uma partida agora.",
  prompt_not_ready: "A partida ainda não está pronta para uma palavra.",
  prompt_unavailable: "Essa palavra já não está disponível.",
  hints_disabled: "As pistas estão desligadas nesta sala.",
  hint_spend_limit: "Chegaste ao limite de gasto em pistas desta ronda.",
  hint_unavailable: "Essa pista não está disponível.",

  // Canvas
  drawer_only: "Só quem desenha pode fazer isso.",
  canvas_stale_generation: "A tela avançou. A recuperar.",
  canvas_sequence_committed: "Isso já foi desenhado.",
  canvas_out_of_sequence: "As ações de desenho chegaram fora de ordem. A recuperar.",
  canvas_out_of_sync: "A tela está dessincronizada. A recuperar.",
  nothing_to_undo: "Não há nada para desfazer.",

  // Votes and restarts
  spectators_cannot_vote: "Os espectadores não podem votar.",
  spectators_cannot_be_targets: "Um espectador não pode ser alvo de uma votação.",
  invalid_vote_target: "Não podes votar sobre esse jogador.",
  not_eligible: "Só jogadores ativos podem propor um reinício.",
  restart_vote_active: "Já há uma votação de reinício a decorrer.",
  restart_vote_cooldown: "Acabou de haver uma votação de reinício. Espera um pouco antes de propores outra.",
  no_restart_vote: "Não há nenhuma votação de reinício para responder.",
  restart_vote_closed: "Essa votação de reinício já está fechada.",

  // Reactions
  spectators_cannot_react: "Os espectadores não podem reagir a um desenho.",
  guests_cannot_react: "Cria uma conta para reagires a um desenho.",
  reaction_not_visible: "Não podes reagir a um desenho que não vês.",
  own_drawing: "Não podes reagir ao teu próprio desenho.",
  game_still_saving: "Essa partida ainda está a ser guardada. Tenta daqui a um instante.",
  game_not_recorded: "Essa partida não foi registada.",
  reaction_not_accepted: "Não foi possível enviar essa reação.",

  // Friends
  friends_unavailable: "Os amigos não estão disponíveis neste momento.",
  friend_refused: "Não foi possível concluir esse pedido de amizade.",
  friend_not_in_game: "O teu amigo não está em nenhuma partida neste momento.",
  friend_in_several_games: "Esse amigo está em mais do que uma partida. Pede-lhe um convite.",
  not_friends: "Só podes entrar na partida de um amigo.",
  friends_only_uninvited: "Só os amigos do anfitrião podem entrar sem convite. Pede-lhe um.",
  invite_expired: "Esse convite expirou.",

  // Moderation, from the reporter's side
  reporting_unavailable: "As denúncias não estão disponíveis neste servidor.",
  no_such_player: "Esse jogador não existe.",
  cannot_report: "Esse jogador não pode ser denunciado.",
  already_reported: "Já denunciaste isto, e um moderador ainda não o analisou.",

  // Lobby chat
  name_required: "Escolhe um nome antes de dizeres alguma coisa no átrio.",
  not_watching_lobby: "Já não estás a ver o átrio.",

  // Versioning
  protocol_mismatch: "Este separador está a usar uma versão antiga do Sketchy. Recarrega a página para continuares.",

  // Sessions and accounts
  sign_in_required: "Inicia sessão primeiro.",
  credentials_incorrect: "Nome de utilizador ou palavra-passe incorretos.",
  password_incorrect: "A palavra-passe está incorreta.",
  account_suspended: "Esta conta está suspensa.",
  already_signed_in: "Já tens sessão iniciada numa conta.",
  username_taken: "Esse nome de utilizador está ocupado.",
  invalid_username: "Esse nome de utilizador não pode ser usado.",
  weak_password: weakPassword,
  password_change_failed: "Não foi possível mudar a palavra-passe.",
  session_not_found: "Esse dispositivo já não tem sessão iniciada.",
  session_replaced: "Esta sessão foi substituída. Recarrega e tenta de novo.",
  guest_progress_unlinked: "Não foi possível associar o progresso de convidado a esta conta.",
  not_taking_visitors: "O Sketchy não está a aceitar novos visitantes neste momento. Tenta mais tarde.",
  account_delete_refused: "Não foi possível eliminar a conta agora. Tenta de novo.",
  password_required_to_delete: "Introduz a tua palavra-passe para eliminares a conta.",

  // Second factor and passkeys
  second_factor_required: "Introduz o código da tua aplicação de autenticação.",
  second_factor_passkey_only: "Inicia sessão com a tua passkey.",
  second_factor_not_enrolled:
  "Esta conta precisa de verificação em dois passos antes de poder iniciar sessão. Pede ajuda a um administrador para a configurar.",
  second_factor_not_set_up: "A verificação em dois passos não está configurada.",
  second_factor_code_wrong: "Esse código não está certo.",
  second_factor_throttled: "Demasiados códigos errados. Espera um pouco e tenta de novo.",
  step_up_required: "Confirma que és tu antes de fazeres isso.",
  passkey_sign_in_required: "Inicia sessão com a tua passkey.",
  passkey_not_registered: "Essa passkey não está registada aqui.",
  passkey_not_found: "Essa passkey não existe.",
  passkey_refused:
  "As passkeys são para contas de moderador e administrador. Ser-te-á pedido que cries uma se alguma vez te oferecerem um papel.",
  last_factor: "É a única forma que tens de provar que és tu. Adiciona outra antes de removeres esta.",
  second_factor_required_for_role: "O papel desta conta exige verificação em dois passos.",
  second_factor_not_proved:
  "Este autenticador ainda não foi confirmado como teu. Usa uma passkey, ou confirma-o com a tua palavra-passe nas definições.",

  // Email, verification and recovery
  invalid_email: "Isso não parece um endereço de e-mail.",
  email_in_use: "Esse endereço já está em uso.",
  email_change_refused: "Esse endereço não pode ser adicionado a esta conta.",
  verification_link_invalid: "Essa ligação de confirmação expirou ou já foi usada.",
  reset_link_invalid: "Essa ligação de reposição expirou ou já foi usada.",

  // Account data export
  export_not_found: "Exportação não encontrada.",
  export_expired: "A exportação expirou.",
  export_not_ready: "A exportação não está pronta.",
  export_unreadable: "Não foi possível ler o documento da exportação. Pede uma nova.",
  export_not_yet_allowed: "Pediste uma exportação há pouco tempo. Tenta mais tarde.",
  export_refused: "Não foi possível iniciar essa exportação. Tenta de novo.",

  // Rate limits reached over HTTP
  too_many_attempts: "Demasiadas tentativas. Espera um pouco e tenta de novo.",
  too_many_requests: "Demasiados pedidos. Espera um pouco e tenta de novo.",
  too_many_reports: "Demasiadas denúncias. Espera antes de enviares outra.",
  too_many_bug_reports: "Demasiados relatórios de erro. Espera antes de enviares outro.",
  too_many_pictures: "Demasiadas imagens. Espera um pouco e tenta de novo.",

  // Pictures
  unsupported_picture_type: "Isso não é uma imagem WebP nem PNG.",
  picture_not_found: "Essa imagem não existe.",
  picture_refused: "Essa imagem não pode ser usada aqui.",

  // Bug reports
  screenshot_unreadable: "Não foi possível ler a captura de ecrã.",
  screenshot_too_large: (params) =>
  `Essa captura é demasiado grande. O limite é ${megabytes(params.limitBytes, "2 MB")}.`,
  screenshot_unsupported_type: "Uma captura tem de ser uma imagem PNG ou WebP.",
  bug_report_context_too_large: "Esse relatório leva demasiado contexto.",

  // Friends, over HTTP
  friends_throttled: "Enviaste muitos pedidos de amizade. Tenta mais tarde.",
  that_is_you: "Esse és tu.",

  // Profiles and history
  no_such_game: "Essa partida não existe.",
  no_such_drawing: "Esse desenho não existe.",
  drawing_unreadable: "Não foi possível ler esse desenho.",

  // Prompt lists
  prompt_list_not_found: "Lista de palavras não encontrada.",
  shared_prompt_list_not_found: "Não foi encontrada nenhuma lista de palavras partilhada.",
  prompt_list_conflict: "Outra pessoa alterou essa lista. Recarrega-a e tenta de novo.",
  prompt_list_invalid: "Não foi possível guardar essa lista de palavras.",
  prompt_list_forbidden: "Essa lista de palavras não é tua para alterares.",
  unknown_sort: "O Sketchy não consegue ordenar por isso.",
  timezone_required: "Inclui um fuso horário com essa data.",
  range_reversed: "O início do intervalo tem de vir antes do fim.",

  // Room presets
  room_preset_not_found: "Predefinição de sala não encontrada.",
  room_preset_conflict: "Já tens uma predefinição com esse nome.",
  room_preset_unavailable: "Essa predefinição não pode ser usada agora.",
  room_preset_forbidden: "Essa predefinição não é tua.",

  // Blocks
  cannot_block_yourself: "Não te podes bloquear a ti próprio.",
  block_list_full: (params) =>
  `A tua lista de bloqueios está cheia${
    typeof params.limit === "number" ? ` em ${params.limit}` : ""
  }. Desbloqueia alguém primeiro.`,

  // Settings
  setting_refused: "Não foi possível guardar essa definição.",

  // Role notices
  no_such_notice: "Esse aviso não existe.",

  // Reporting, from the reporter's side
  cannot_report_yourself: "Não te podes denunciar a ti próprio.",
  cannot_report_own_prompt_list: "Não podes denunciar a tua própria lista de palavras.",
  no_reportable_prompt_list: "Não foi encontrada nenhuma lista de palavras denunciável.",
  prompt_not_in_list: "Essa palavra não pertence a esta lista.",
  no_picture_to_report: "Esse jogador não tem imagem para denunciar.",
  no_such_game_context: "Esse contexto de partida não existe.",
  no_such_turn_context: "Esse contexto de ronda não existe.",
  turn_not_in_game: "A ronda não pertence a essa partida.",
  evidence_unavailable: "Uma ou mais mensagens selecionadas não estão disponíveis.",
  evidence_mixed_scopes: "As mensagens do átrio e da sala não podem ser misturadas numa denúncia.",
  evidence_several_rooms: "As mensagens selecionadas têm de vir da mesma sala.",
  evidence_not_theirs: "As provas têm de ser do jogador denunciado.",
  evidence_not_received: "Não podes selecionar uma mensagem que não recebeste.",
  evidence_not_in_game: "A mensagem selecionada não pertence a essa partida.",
  evidence_not_in_turn: "A mensagem selecionada não pertence a essa ronda.",
  no_such_warning: "Esse aviso não existe.",
  no_drawing: "Sem desenho.",};

/** What the room says about itself. One entry per `AnnouncementCode`. */
const ANNOUNCEMENTS: Record<AnnouncementCode, (params: MessageParams) => string> = {
  nickname_changed: (p) =>
  `${text(p.previous)} passou a chamar-se ${text(p.nickname)}.`,
  joined_as_player: (p) => `${text(p.nickname)} entrou como jogador.`,
  kicked_by_vote: (p) => `${text(p.nickname)} foi expulso por votação.`,
  marked_afk_by_vote: (p) => `${text(p.nickname)} foi marcado como ausente por votação.`,

  restart_vote_started: (p) =>
  `${text(p.nickname)} começou uma votação para reiniciar a partida.`,
  restart_vote_passed: (p) =>
  `A votação de reinício passou. A reiniciar dentro de ${count(p.seconds, 5)} segundos.`,
  restart_vote_rejected: () => "A votação de reinício foi rejeitada.",
  restart_vote_expired: () => "A votação de reinício expirou sem passar.",
  restart_vote_abandoned: () =>
  "A votação de reinício foi cancelada porque restam menos de dois jogadores ativos.",
  restart_cancelled: (p) => `O reinício foi cancelado porque ${cancelReason(p.reason)}.`,
  game_restarted_by_vote: () => "A partida foi reiniciada por votação dos jogadores.",

  hint_letter_found: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pts - encontrada ${counted(count(p.count, 1), {
    one: "vez",
    other: "vezes",
  })}!`,
  hint_letter_missing: (p) =>
  `'${text(p.letter)}' -${count(p.cost)} pts - não está na palavra.`,
  guess_very_close: (p) => `«${text(p.text)}» está muito perto!`,
  guess_some_words_correct: () => "Algumas palavras estão certas",};

export const PT: Catalogue = {
  refusals: REFUSALS,
  announcements: ANNOUNCEMENTS,

  /** What the document itself says: the tab, and what a link preview shows.

      Rendered into `index.html` for a crawler, which arrives before any
      script, and rewritten here for the reader once their locale is known. */
  document: {
    description: "Desenha, adivinha e ri-te com os amigos!",
  },

  /** Shapes that belong to the language rather than to any one screen. */
  format: {
    /** `1st`, `2nd`, `3rd`; a language with no ordinal form gets the number. */
    ordinal: (p: { value: number }) => ordinal(p.value),
  },

  promptListDrafts: {
    promptsAdded: (p: { count: number }) =>
      `${counted(p.count, { one: "palavra adicionada", other: "palavras adicionadas" })}`,
  },

  lastSeen: {
    online: "online",
    justNow: "visto agora mesmo",
    lastSeenAgo: (p: { count: number; unit: "minute" | "hour" | "day" }) => {
      const words = {
        minute: { one: "minuto", other: "minutos" },
        hour: { one: "hora", other: "horas" },
        day: { one: "dia", other: "dias" },
      }[p.unit];
      return `visto há ${counted(p.count, words)}`;
    },
  },

  gameHighlights: {
    reactionCount: (p: { count: number }) =>
      counted(p.count, { one: "reação", other: "reações" }),
  },

  versionBadge: {
    buildDetails: (p: { commitDate: string; builtAt: string }) =>
      `Data do commit: ${p.commitDate} | Compilado: ${p.builtAt}`,
  },

  segmentedCodeInput: {
    digitPosition: (p: { label: string; index: number; length: number }) =>
      `${p.label}, dígito ${p.index} de ${p.length}`,
  },

  roomSetupControls: {
    decrease: (p: { label: string }) => `Diminuir ${p.label}`,
    increase: (p: { label: string }) => `Aumentar ${p.label}`,
  },

  guessPips: {
    playerGuessState: (p: { nickname: string; isFriend: boolean; guessed: boolean }) =>
      `${p.nickname}${p.isFriend ? " (amigo)" : ""} ${p.guessed ? "acertou" : "ainda está a tentar"}`,
  },

  accountDataDialog: {
    requestedOn: (p: { when: string; schemaVersion: number }) =>
      `Pedida ${p.when} · formato v${p.schemaVersion}`,
    exportAllowance: (p: { nextAllowed: string | null }) =>
      p.nextAllowed
        ? `Uma exportação por semana; as que ficam prontas expiram ao fim de sete dias. Podes pedir outra a ${p.nextAllowed}.`
        : "Uma exportação por semana; as que ficam prontas expiram ao fim de sete dias.",
    couldNotLoadYourDataExports: "Não foi possível carregar as tuas exportações de dados.",
    couldNotRequestYourDataExport: "Não foi possível pedir a tua exportação de dados.",
    yourData: "Os teus dados",
    downloadPrivateJsonCopyYourAccount: "Descarrega uma cópia privada em JSON da tua conta e dos teus dados de jogo. Os perfis e mensagens de outros jogadores não vão incluídos.",
    dataExports: "Exportações de dados",
    loadingExports: "A carregar exportações…",
    youHaveNotRequestedExportYet: "Ainda não pediste nenhuma exportação.",
    download: "Descarregar",
    close: "Fechar",
  },

  accountMenu: {
    noPasskeyWasUsed: "Não foi usada nenhuma passkey. Podes iniciar sessão com a tua palavra-passe.",
    signedInWithRequests: (p: { name: string; waiting: number }) =>
      `Sessão iniciada como ${p.name}. ${counted(p.waiting, {
        one: "pedido de amizade à espera",
        other: "pedidos de amizade à espera",
      })}.`,
    friends: "Amigos",
    finishYourRole: (p: { role: "admin" | "moderator" }) =>
      `Conclui o teu papel de ${p.role === "admin" ? "administrador" : "moderador"}`,
    agreeToRules: "Ao criares uma conta aceitas seguir as {rules}.",
    reportBug: "Comunicar um erro",
    account: "Conta",
    settings: "Definições",
    myProfile: "O meu perfil",
    promptStats: "Estatísticas de palavras",
    createAccount: "Criar conta",
    logIn: "Iniciar sessão",
    myPromptLists: "As minhas listas de palavras",
    rules: "Regras",
    logOut: "Terminar sessão",
    thatDoesNotLookLikeEmail: "Isso não parece um endereço de e-mail.",
    somethingWentWrongPleaseTryAgain: "Algo correu mal. Tenta de novo.",
    thatPasskeyWasNotAccepted: "Essa passkey não foi aceite.",
    thisAccountSignsWithPasskey: "Esta conta inicia sessão com uma passkey.",
    or: "ou",
    username: "Nome de utilizador",
    password: "Palavra-passe",
    codeFromYourAuthenticatorApp: "Código da tua aplicação de autenticação",
    recoveryCodeWorksHereTooCan: "Um código de recuperação também serve aqui, e pode ser usado uma vez.",
    email: "E-mail",
    optional: "opcional",
    letsYouResetYourPasswordLater: "Permite-te repor a palavra-passe mais tarde. Não serve para mais nada.",
    rules2: "regras",
    forgotYourPassword: "Esqueceste-te da palavra-passe?",
    notNow: "Agora não",
  },

  accountRecoveryPage: {
    thatConfirmationLinkCouldNotBe: "Não foi possível usar essa ligação de confirmação.",
    somethingWentWrongPleaseTryAgain: "Algo correu mal. Tenta de novo.",
    evenBestGuessersForgetSometimes: "Até os melhores a adivinhar se esquecem às vezes.",
    weRsquoLlSendSecureTime: "Vamos enviar uma ligação segura e com prazo para o e-mail confirmado\n            da tua conta.",
    accountHelp: "Ajuda com a conta",
    backLobby: "Voltar ao átrio",
    enterYourUsernameYourConfirmedEmail: "Introduz o teu nome de utilizador ou o teu e-mail confirmado. Se a\n              conta puder ser recuperada, já vai uma ligação a caminho.",
    usernameEmail: "Nome de utilizador ou e-mail",
    thatResetLinkHasExpiredHas: "Essa ligação de reposição expirou ou já foi usada. Estas ligações\n              servem uma vez e duram uma hora.",
    sendNewOne: "Enviar uma nova",
    checkingThatLink: "A verificar a ligação…",
    everySignedDeviceWillBeSigned: "Todos os dispositivos com sessão iniciada serão desligados, incluindo\n              os que não reconheceste.",
    newPassword: "Nova palavra-passe",
  },

  activeGameRoom: {
    leaveGame: "Sair da partida",
    markedAfkByRoomVote: "A sala marcou-te como ausente por votação.",
    couldNotChangeSuggestion: (p: { action: string }) =>
      `Não foi possível ${p.action} a sugestão de cores.`,
    inviteLinkCopied: "Ligação de convite copiada.",
    couldnTCopyLinkCopyFrom: "Não foi possível copiar a ligação. Copia-a da barra de endereço.",
    couldNotStartGamePleaseTry: "Não foi possível começar a partida. Tenta de novo.",
    couldNotStartRestartVote: "Não foi possível iniciar uma votação de reinício.",
    couldNotRecordYourRestartVote: "Não foi possível registar o teu voto de reinício.",
    copyRoomInviteLink: "Copiar a ligação de convite da sala",
    clickCopyRoomInviteLink: "Clica para copiar a ligação de convite",
    roomMenu: "Menu da sala",
    afk: "Ausente",
    saveImage: "Guardar imagem",
    saveDrawnImageFile: "Guardar o desenho num ficheiro",
    playerSettings: "Definições do jogador",
    leaveRoom: "Sair da sala",
    leave: "Sair",
    players: "Jogadores",
  },

  addEmailDialog: {
    followTheLink: (p: { address: string; replacing: boolean }) =>
      `Segue a ligação enviada para ${p.address}. Até lá, o endereço não está associado à tua conta e não serve para a recuperar${
        p.replacing ? ", e o que tinhas fica como estava." : "."
      }`,
    thatDoesNotLookLikeEmail: "Isso não parece um endereço de e-mail.",
    somethingWentWrongPleaseTryAgain: "Algo correu mal. Tenta de novo.",
    done: "Concluído",
    usedOnlyResetYourPasswordTell: "Serve apenas para repor a tua palavra-passe e para te avisar se a tua\n              conta ou algo que partilhaste for alvo de uma decisão. Nunca é\n              enviado mais nada para aqui.",
  },

  afkCheckDialog: {
    secondsUnit: (p: { count: number }) =>
      plural(p.count, { one: "segundo", other: "segundos" }),
    stillThere: "Ainda aí?",
    youHaveBeenQuietWhileAnswer: "Estás calado há algum tempo. Responde e continuas a jogar; caso\n          contrário a sala marca-te como ausente e segue sem ti.",
    stillTherePressButtonMoveMouse: "Ainda aí? Carrega no botão, ou mexe o rato, para continuares a jogar.",
    iMHere: "Estou aqui",
  },

  app: {
    serverUpdateInProgress: (p: { seconds: number }) =>
      p.seconds > 0
        ? `Atualização do servidor a decorrer. Não podem começar salas nem partidas novas; uma partida a decorrer tem mais ${counted(p.seconds, { one: "segundo", other: "segundos" })}.`
        : "Atualização do servidor a decorrer. Não podem começar salas nem partidas novas; as partidas a decorrer estão a terminar.",
    thisTabOutDateCannotPlay: "Este separador está desatualizado e não pode jogar enquanto não for recarregado.",
    reload: "Recarregar",
    newRoomsArePausedMaintenanceGames: "As salas novas estão em pausa por manutenção. As partidas já a decorrer\n          seguem normalmente.",
    serverWasUpdatedBackAnyGame: "O servidor foi atualizado e já voltou. As partidas a decorrer terminaram.",
    dismiss: "Dispensar",
  },

  appHeader: {
    playerSettings: "Definições do jogador",
  },

  bugReportDialog: {
    connectionSummary: (p: { connected: boolean; reconnects: number }) =>
      `${p.connected ? "ligado" : "offline"} · ${counted(p.reconnects, {
        one: "reconexão",
        other: "reconexões",
      })} nesta visita`,
    couldNotTakeScreenshot: "Não foi possível tirar a captura.",
    thanksYourReportWithPeopleWho: "Obrigado — o teu relatório está com quem gere o Sketchy.",
    couldNotSendReport: "Não foi possível enviar o relatório.",
    reportBug: "Comunicar um erro",
    somethingBrokenNotSomethingSomeoneSaid: "Algo avariado, não algo que alguém disse. Isto chega a quem gere o Sketchy — nunca a outros jogadores.",
    where: "Onde",
    howBad: "Gravidade",
    oneLineSummary: "Resumo numa linha",
    whatWentWrongOneLine: "O que correu mal, numa linha",
    whatHappened: "O que aconteceu",
    whatYouDidWhatYouExpected: "O que fizeste, o que esperavas, o que aconteceu em vez disso.",
    screenshot: "Captura de ecrã",
    optional: "Opcional",
    screenshotThatWillBeSentWith: "A captura que será enviada com este relatório",
    thisDialogHidesItselfWhileShot: "Esta janela esconde-se enquanto a captura é tirada, por isso apanhas a página por trás. Vê-a antes de enviares — escolhes tu o que partilhas.",
    replace: "Substituir",
    remove: "Remover",
    opensYourBrowserSOwnPicker: "Abre o seletor do teu navegador — escolhe este separador. Esta janela esconde-se enquanto a captura é tirada, por isso apanhas a página por trás.",
    recentClientErrors: "Erros recentes do cliente",
    sendMyDescriptionOnly: "Enviar só a minha descrição",
    dropsDetailsAboveAnyScreenshotWe: "Descarta os detalhes acima e qualquer captura. Vamos ler na mesma, mas o erro fica muito mais difícil de reproduzir.",
    cancel: "Cancelar",
  },

  changePasswordDialog: {
    forgottenTheCurrentOne: "Esqueceste-te da atual?",
    twoNewPasswordsDoNotMatch: "As duas palavras-passe novas não coincidem.",
    passwordChangedEveryOtherDeviceHas: "Palavra-passe alterada. Todos os outros dispositivos foram desligados.",
    couldNotChangePasswordPleaseTry: "Não foi possível mudar a palavra-passe. Tenta de novo.",
    ifThatAccountHasVerifiedEmail: "Se essa conta tiver um e-mail verificado, já vai a caminho uma ligação\n              para definir uma palavra-passe nova. Serve uma vez e expira.",
    done: "Concluído",
    everyDeviceSignsOutWhenPassword: "Ao mudar a palavra-passe, todos os dispositivos são desligados, incluindo\n              os que não querias deixar com sessão iniciada. Este fica.",
    currentPassword: "Palavra-passe atual",
    newPassword: "Nova palavra-passe",
    newPasswordAgain: "Repetir a palavra-passe nova",
    emailMeLinkInstead: "Envia-me antes uma ligação",
  },

  choosingPromptOverlay: {
    isChoosingPrompt: "{drawer} está a escolher uma palavra…",
    nextTurn: "Ronda seguinte",
    drawingWillBeginAsSoonAs: "O desenho começa assim que escolher.",
  },

  colorblindSafeSuggestionBanner: {
    colorblindSafeColorSuggestion: "Sugestão de cores próprias para daltonismo",
    playerThisRoomPlaysWithColorblind: "Um jogador desta sala joga com cores próprias para daltonismo.",
    switchRoomPaletteFutureDrawings: "Mudar a paleta da sala para os próximos desenhos?",
    switchColors: "Mudar as cores",
    notNow: "Agora não",
  },

  confirmationDialog: {
    cancel: "Cancelar",
  },

  crashPage: {
    couldNotSendReport: "Não foi possível enviar o relatório.",
    bugCrawledOntoPage: "Um erro trepou para a página",
    helpUsSquash: "Ajuda-nos a esmagá-lo",
    reportReadySendErrorWhatThis: "Há um relatório pronto a enviar: o erro e o que este separador sabe de si\n            próprio. Chega a quem gere o Sketchy — nunca a outros jogadores.",
    whatWereYouDoing: "O que estavas a fazer?",
    optional: "Opcional",
    lastThingYouClickedTypedIf: "A última coisa em que clicaste ou que escreveste, se te lembrares.",
    recentClientErrorsNewestFirst: "Erros recentes do cliente, os mais novos primeiro",
    sendMyDescriptionOnly: "Enviar só a minha descrição",
    dropsDetailsAboveWeWillStill: "Descarta os detalhes acima. Vamos ler na mesma, mas a falha fica muito mais difícil de encontrar.",
    thanksYourReportWithPeopleWho: "Obrigado — o teu relatório está com quem gere o Sketchy.",
    reload: "Recarregar",
    backLobby: "Voltar ao átrio",
  },

  createRoomPage: {
    setupTiming: "Esta configuração demora {full} com uma sala cheia de {capacity}",
    setupTimingFull: (p: { minutes: number }) =>
      `cerca de ${counted(p.minutes, { one: "minuto", other: "minutos" })}`,
    setupTimingHalf: (p: { players: number }) => ` — mais perto de {half} se entrarem ${p.players}`,
    couldNotLoadYourRoomPresets: "Não foi possível carregar as tuas predefinições de sala.",
    couldNotApplyThatPreset: "Não foi possível aplicar essa predefinição.",
    enterNameRoomPreset: "Dá um nome à predefinição de sala.",
    couldNotSaveThatPreset: "Não foi possível guardar essa predefinição.",
    couldNotUpdateThatPreset: "Não foi possível atualizar essa predefinição.",
    couldNotDeleteThatPreset: "Não foi possível eliminar essa predefinição.",
    fixCustomPromptEntriesMarkedAbove: "Corrige as palavras próprias assinaladas acima antes de criares a sala.",
    failedCreateRoom: "Não foi possível criar a sala",
    roomSetup: "Configuração da sala",
    createRoom: "Criar uma sala",
    startFromSavedPreset: "Começar a partir de uma predefinição guardada",
    startFromPreset: "Começar a partir de uma predefinição…",
    nameThisPreset: "Dá um nome a esta predefinição",
    save: "Guardar",
    cancel: "Cancelar",
    saveAsPreset: "Guardar como predefinição",
    update: "Atualizar",
    delete: "Eliminar",
    undo: "Desfazer",
    saveAsReusableList: "Guardar como lista reutilizável",
  },

  customPromptsEditor: {
    usableCount: (p: { count: number }) =>
      counted(p.count, { one: "palavra própria utilizável", other: "palavras próprias utilizáveis" }),
    duplicatesIgnored: (p: { count: number }) =>
      `${counted(p.count, { one: "duplicada", other: "duplicadas" })} ignoradas`,
    entriesTooLong: (p: { count: number; limit: number }) =>
      `${counted(p.count, { one: "entrada passa", other: "entradas passam" })} dos ${number(p.limit)} caracteres`,
    entryLimit: (p: { limit: number }) => `Só são permitidas ${number(p.limit)} entradas`,
    customPromptsOptional: "Palavras próprias (opcional)",
    onePromptPerLineSeparateEntries: "Uma palavra por linha\nou separa as entradas com vírgulas",
    shortenRemoveOverlongEntriesBeforeCreating: "Encurta ou remove as entradas demasiado longas antes de criares a sala.",
  },

  customPromptsPreview: {
    resultsMatching: (p: { shown: number; total: number }) =>
      `${number(p.shown)} de ${number(p.total)} palavras correspondem`,
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "palavra", other: "palavras" }),
    customPromptCount: (p: { count: number }) =>
      counted(p.count, { one: "palavra própria", other: "palavras próprias" }),
    inspectPrompts: (p: { count: number }) =>
      `Ver ${counted(p.count, { one: "palavra própria", other: "palavras próprias" })}`,
    couldNotLoadCustomPrompts: "Não foi possível carregar as palavras próprias",
    loadingCustomPrompts: "A carregar palavras próprias…",
    roomPromptCollection: "Coleção de palavras da sala",
    readOnlyListSuppliedByRoom: "Lista só de leitura fornecida pelo anfitrião.",
    findPrompt: "Encontrar uma palavra",
    searchCustomPrompts: "Procurar nas palavras próprias…",
    filterPromptsByLength: "Filtrar palavras por comprimento",
    noCustomPromptsMatchTheseFilters: "Nenhuma palavra própria corresponde a estes filtros.",
  },

  deleteAccountDialog: {
    whatIsRemoved: (p: { isGuest: boolean }) =>
      `${
        p.isGuest
          ? "O nome, os pontos e o histórico guardados neste navegador são removidos."
          : "O teu nome é removido das partidas que jogaste."
      } As pontuações e os desenhos ficam, sob «Jogador eliminado», porque também são partidas de outras pessoas. Isto não pode ser desfeito.`,
    typeToConfirm: (p: { word: string }) => `Escreve ${p.word} para confirmares`,
    couldNotDeleteAccount: "Não foi possível eliminar a conta.",
    password: "Palavra-passe",
  },

  drawingReactionControl: {
    reactionSummary: (p: { total: number; chips: string }) =>
      `${counted(p.total, { one: "reação", other: "reações" })}: ${p.chips}`,
    thatReactionCouldNotBeSent: "Não foi possível enviar essa reação.",
    reactThisDrawing: "Reagir a este desenho",
    reactions: "Reações",
    createAccountReact: "Cria uma conta para reagires.",
    createAccount: "Criar conta",
  },

  drawingRecapGallery: {
    drawingLabel: (p: { prompt: string; drawer: string }) =>
      `Desenho de ${p.prompt} por ${p.drawer}`,
    drawnBy: "Desenhado por {drawer} · Ronda {round} · Vez {turn}",
    position: (p: { position: number; total: number }) => `${p.position} de ${p.total}`,
    thisDrawingCouldNotBeDecoded: "Não foi possível descodificar este desenho.",
    drawingRecap: "Resumo dos desenhos",
    saveImage: "Guardar imagem",
    close: "Fechar",
    thisDrawingWasNotKept: "Este desenho não foi guardado.",
    roomRanOutRoomLaterTurns: "A sala ficou sem espaço para ele. Em vez disso ficaram rondas posteriores.",
    tryAgain: "Tentar de novo",
    loadingDrawing: "A carregar o desenho…",
    noDrawingWasCapturedThisTurn: "Não foi guardado nenhum desenho desta ronda.",
    drawingRecapNavigation: "Navegação do resumo dos desenhos",
    previous: "Anterior",
    next: "Seguinte",
  },

  emailRecoveryReminder: {
    addEmail: "Adicionar um e-mail",
    dismiss: "Dispensar",
  },

  firstRunIdentity: {
    couldNotSaveThatNamePlease: "Não foi possível guardar esse nome. Tenta de novo.",
    keepYourUsernameYourStatsEvery: "Mantém o teu nome de utilizador e as tuas estatísticas em todos os dispositivos.",
    createAccount: "Criar uma conta",
    logIn: "Iniciar sessão",
    or: "ou",
    displayName: "Nome a mostrar",
  },

  friendButton: {
    requestSentTo: (p: { name: string }) => `Pedido de amizade enviado a ${p.name}`,
    addFriend: "Adicionar amigo",
    acceptRequest: "Aceitar pedido",
    requestSent: "Pedido enviado",
  },

  friendInviteNotice: {
    couldNotJoinThatGame: "Não foi possível entrar nessa partida.",
    thatGameCouldNotBeJoined: "Não foi possível entrar nessa partida.",
    invitedYouTheirGame: "convidou-te para a partida dele.",
    join: "Entrar",
    dismissInvitation: "Dispensar o convite",
  },

  friendsOverlay: {
    declineWarning: (p: { name: string }) =>
      `${p.name} não vai poder pedir outra vez. Tu ainda lhe podes enviar um pedido mais tarde.`,
    decline2: "Recusar",
    youWillBothStopBeingAble: "Os dois deixam de poder entrar nas partidas um do outro sem convite. Qualquer um pode pedir outra vez.",
    remove2: "Remover",
    removeConfirm: (p: { name: string }) => `Remover ${p.name}?`,
    friends: "Amigos",
    close: "Fechar",
    closeFriends: "Fechar os amigos",
    friendsNeedAccountGuestNameBelongs: "Para teres amigos é preciso uma conta. Um nome de convidado pertence a\n              este navegador e não a ti, por isso daqui a um mês não sobraria\n              ninguém para ser teu amigo.",
    loading: "A carregar…",
    noFriendsYetAddSomebodyFrom: "Ainda não tens amigos. Adiciona alguém a partir do átrio, ou de uma\n              partida onde estejam os dois.",
    requests: "Pedidos",
    accept: "Aceitar",
    decline: "Recusar",
    sent: "Enviado",
    cancel: "Cancelar",
    remove: "Remover",
    declineThisRequest: "Recusar este pedido?",
    recentlyPlayedWith: "Jogaste recentemente com",
  },

  gameEndOverlay: {
    continueLabel: "Continuar",
    youFinished: (p: { points: number }) =>
      `Ficaste em {place} com ${counted(p.points, { one: "ponto", other: "pontos" })}.`,
    continueToWaitingRoom: "Ir para a sala de espera",
    continueWithCountdown: (p: { seconds: number }) =>
      `Ir para a sala de espera, faltam ${counted(p.seconds, { one: "segundo", other: "segundos" })}`,
    gameOver: "Fim da partida",
    you: "tu",
    friend: "Amigo",
    noScoresThisTimeJustRoom: "Desta vez não há pontos — só uma sala cheia de rabiscos e palpites.",
    keep: "Ficar",
    asYourUsername: "como o teu nome de utilizador",
    createAccount: "Criar conta",
    highlights: "Melhores momentos",
    drawings: "Desenhos",
    stayHere: "Ficar aqui",
  },

  gameHighlightsPanel: {
    lastGame: "Última partida",
    highlights: "Melhores momentos",
    closeHighlights: "Fechar os melhores momentos",
    thatGameWasTooShortSay: "Essa partida foi curta demais para se dizer grande coisa. Joga uma mais\n            longa e os melhores momentos aparecem aqui.",
    seeIt: "Ver",
    back: "Voltar",
  },

  inviteEntryPage: {
    roomCode: (p: { code: string }) => `Sala ${p.code}`,
    hereCount: (p: { here: number; capacity: number; full: boolean }) =>
      `${p.here}/${p.capacity} aqui${p.full ? " · cheia" : ""}`,
    roomSummary: (p: { rounds: number; seconds: number; hintMode: string }) =>
      `${counted(p.rounds, { one: "ronda", other: "rondas" })} · ${p.seconds}s · ${p.hintMode}`,
    checkingYourInvite: "A verificar o teu convite…",
    loadingRoomDetails: "A carregar os detalhes da sala.",
    roomUnavailable: "Sala indisponível",
    backLobby: "Voltar ao átrio",
    players: "Jogadores",
    rounds: "Rondas",
    drawTime: "Tempo de desenho",
    scoring: "Pontuação",
    roomRules: "Regras da sala",
    thisGameAlreadyProgressJoiningAs: "Esta partida já está a decorrer. Ao entrares como jogador, ficas para uma ronda seguinte.",
    playerSlotsAreFullSpectatingStill: "Os lugares de jogador estão cheios. Ainda podes assistir.",
  },

  inviteFriendsList: {
    invitationCouldNotBeSent: "Não foi possível enviar esse convite.",
    invitationSent: (p: { name: string }) => `Convite enviado a ${p.name}.`,
    thatInvitationCouldNotBeSent: "Não foi possível enviar esse convite.",
    friendsLobby: "Amigos no átrio",
    invited: "Convidado",
    invite: "Convidar",
  },

  languagePicker: {
    currentChoice: (p: { label: string; value: string }) => `${p.label}: ${p.value}`,
    everyLanguage: "Todos os idiomas",
  },

  lobbyBrowserPage: {
    filterByLanguage: "Filtrar por idioma",
    filtersWithCount: (p: { count: number }) =>
      p.count > 0 ? `Filtros · ${p.count}` : "Filtros",
    showRooms: (p: { count: number }) =>
      `Ver ${counted(p.count, { one: "sala", other: "salas" })}`,
    removedFromRoom: "Removido da sala",
    ok: "OK",
    roomCode: "Código da sala",
    abc123: "ABC123",
    thereNoRoomCodeClipboard: "Não há nenhum código de sala na área de transferência.",
    sketchyCouldNotReadClipboardPaste: "O Sketchy não conseguiu ler a área de transferência. Cola nas caixas.",
    pleaseEnterRoomCode: "Introduz um código de sala",
    failedJoinRoom: "Não foi possível entrar na sala",
    joinByCode: "Entrar com código",
    createRoom: "Criar sala",
    publicRooms: "Salas públicas",
    searchRoomsByNameCode: "Procurar salas por nome ou código",
    hideFull: "Ocultar cheias",
    hideProgress: "Ocultar a decorrer",
    filters: "Filtros",
    clearFilters: "Limpar filtros",
    language: "Idioma",
    hideFullRooms: "Ocultar salas cheias",
    hideGamesProgress: "Ocultar partidas a decorrer",
    loadingPublicRooms: "A carregar salas públicas…",
    noPublicRoomsYetCreateOne: "Ainda não há salas públicas. Cria uma!",
    noPublicRoomsMatchYourSearch: "Nenhuma sala pública corresponde à tua procura.",
    createRoom2: "Criar uma sala",
    joinWithCode: "Entrar com um código",
    paste: "Colar",
  },

  lobbyChatPanel: {
    reportThisLine: (p: { name: string }) => `Denunciar esta linha de ${p.name}`,
    couldNotSendThat: "Não foi possível enviar.",
    chat: "Conversa",
    lobbyChat: "Conversa do átrio",
    nobodyHasSaidAnythingYet: "Ainda ninguém disse nada.",
    chooseNameChat: "Escolhe um nome para conversares",
    saySomethingLobby: "Diz alguma coisa ao átrio…",
    lobbyChatMessage: "Mensagem da conversa do átrio",
    send: "Enviar",
  },

  lobbyPlayerMenu: {
    whatToDoAbout: (p: { name: string }) => `O que fazer com ${p.name}`,
    openPlayerProfile: "Abrir o perfil do jogador",
    addAsFriend: "Adicionar como amigo",
    report: "Denunciar",
  },

  myPromptListsPage: {
    listSummary: (p: { prompts: number; visibility: string; moderationState: string | null }) =>
      `${counted(p.prompts, { one: "palavra", other: "palavras" })} · ${p.visibility}${
        p.moderationState ? ` · ${p.moderationState}` : ""
      }`,
    listUnderReview: (p: { state: string }) =>
      `Esta lista está ${p.state} e não pode ser usada em partidas novas. Editá-la não a repõe automaticamente; um moderador tem de a analisar.`,
    needsReview: (p: { count: number }) => `A analisar (${p.count})`,
    removePrompt: (p: { prompt: string }) => `Remover ${p.prompt}`,
    couldNotLoadYourPromptLists: "Não foi possível carregar as tuas listas de palavras.",
    couldNotOpenThatPromptList: "Não foi possível abrir essa lista de palavras.",
    addAtLeastOnePromptBefore: "Adiciona pelo menos uma palavra antes de guardares.",
    couldNotSaveThisPromptList: "Não foi possível guardar esta lista de palavras.",
    couldNotDeleteThisPromptList: "Não foi possível eliminar esta lista de palavras.",
    yourLibrary: "A tua biblioteca",
    reusablePromptLists: "Listas de palavras reutilizáveis",
    newList: "Lista nova",
    createAccountSaveReviseSharePrompt: "Cria uma conta para guardares, reveres e partilhares listas de palavras. As palavras rápidas de uma sala ficam locais e efémeras.",
    yourPromptLists: "As tuas listas de palavras",
    loading: "A carregar…",
    noSavedListsYet: "Ainda não há listas guardadas.",
    name: "Nome",
    description: "Descrição",
    language: "Idioma",
    visibility: "Visibilidade",
    private: "Privada",
    anyoneWithCode: "Qualquer pessoa com o código",
    shareCode: "Código de partilha",
    couldNotCopyShareCode: "Não foi possível copiar o código de partilha.",
    copy: "Copiar",
    addPrompts: "Adicionar palavras",
    onePromptPerLineSeparateEntries: "Uma palavra por linha\nou separa as entradas com vírgulas",
    addList: "Adicionar à lista",
    noPromptsYetPasteSomeAbove: "Ainda não há palavras. Cola algumas acima para começares.",
    thisList: "Nesta lista",
    searchPrompts: "Procurar palavras",
    nothingMatchesThatSearch: "Nada corresponde a essa procura.",
    deleteList: "Eliminar lista…",
  },

  notFoundPage: {
    nobodyDrewThisPage: "Ninguém desenhou esta página",
    thatLinkDoesnTLeadAnywhere: "Essa ligação não leva a lado nenhum no Sketchy.",
    backLobby: "Voltar ao átrio",
  },

  onlinePlayersPanel: {
    couldNotJoinThatGame: "Não foi possível entrar nessa partida.",
    whoOnline: "Quem está online",
    nobodyElseHereRightNow: "Neste momento não está aqui mais ninguém.",
    friend: "Amigo",
    join: "Entrar",
  },

  pictureCropDialog: {
    fileNotAPicture: "Não foi possível ler esse ficheiro como imagem.",
    couldNotSetThatPicturePlease: "Não foi possível definir essa imagem. Tenta de novo.",
    frameYourPicture: "Enquadra a tua imagem",
    dragMoveZoomGetCloserCircle: "Arrasta para a moveres e usa o zoom para te aproximares. O círculo é o que toda a gente vê.",
    pictureFramedArrowKeysMovePlus: "A imagem, enquadrada. As setas movem-na; mais e menos fazem zoom.",
    zoom: "Zoom",
    cancel: "Cancelar",
  },

  playerList: {
    requestCouldNotBeSent: "Não foi possível enviar esse pedido.",
    nowFriends: (p: { name: string }) => `Tu e ${p.name} são agora amigos.`,
    friendRequestSent: (p: { name: string }) => `Pedido de amizade enviado a ${p.name}.`,
    nothingToDoAbout: (p: { name: string }) => `Não há nada a fazer com ${p.name} neste momento.`,
    rank: (p: { rank: number }) => `Lugar ${p.rank}`,
    moderationFor: (p: { name: string }) => `Moderação para ${p.name}`,
    moderationActionsFor: (p: { name: string }) => `Ações de moderação para ${p.name}`,
    thatRequestCouldNotBeSent: "Não foi possível enviar esse pedido.",
    drawing: "A desenhar",
    gotIt: "Acertou ·",
    afk: "Ausente",
    you: "(tu)",
    host: "Anfitrião",
    friend: "Amigo",
    disconnected: "Desligado",
    kick: "Expulsar",
    addFriend: "Adicionar amigo",
    sendRequest: "Enviar um pedido",
    report: "Denunciar",
    toAModerator: "A um moderador",
  },

  profilePage: {
    gamesPlayed: "Partidas jogadas",
    gamesWon: "Partidas ganhas",
    winRate: "Taxa de vitórias",
    averageScore: "Pontuação média",
    turnsPlayed: "Rondas jogadas",
    promptsGuessed: "Palavras adivinhadas",
    drawingsMade: "Desenhos feitos",
    reactionsReceived: "Reações recebidas",
    totalScore: "Pontuação total",
    noSuchProfile: "Não há nenhum jogador com esse perfil.",
    couldNotLoadProfile: "Não foi possível carregar este perfil. Tenta de novo.",
    gameMeta: (p: { finishedAt: string; rounds: number; players: number }) =>
      `${p.finishedAt} · ${counted(p.rounds, { one: "ronda", other: "rondas" })} · ${counted(p.players, { one: "jogador", other: "jogadores" })}`,
    seatScore: (p: { points: number }) => `${number(p.points)} pts`,
    gameRules: (p: {
      scoringMode: string;
      scoringVersion: number;
      hintMode: string;
      seconds: number;
      promptSource: string;
    }) =>
      `Regras: pontuação ${p.scoringMode}${
        p.scoringVersion > 0 ? ` v${p.scoringVersion}` : " (versão antiga desconhecida)"
      } · pistas ${p.hintMode} · ${p.seconds} segundos · palavras ${p.promptSource}`,
    reportPlayer: (p: { name: string }) => `Denunciar ${p.name}`,
    privateRoom: "sala privada",
    thisGameDidNotFinishSo: "Esta partida não chegou ao fim, por isso estes são os pontos tal como\n              estavam quando parou e não uma classificação final.",
    loadingTurns: "A carregar as rondas…",
    turnByTurn: "Ronda a ronda",
    round: "Ronda",
    prompt: "Palavra",
    drawnBy: "Desenhado por",
    time: "Tempo",
    drawing: "A desenhar",
    reactions: "Reações",
    guesserOutcomes: "Resultados de quem adivinhava",
    view: "Ver",
    couldNotLoadMoreGames: "Não foi possível carregar mais partidas.",
    loading: "A carregar…",
    friend: "Amigo.",
    claimYourAccount: "Reclama a tua conta",
    yourGamesAreAlreadyBeingRecorded: "As tuas partidas já estão a ser registadas com este nome a mostrar.\n                Cria uma conta para as guardares e o usares como nome de utilizador em todos os dispositivos.",
    createAccount: "Criar conta",
    statistics: "Estatísticas",
    gameHistory: "Histórico de partidas",
    includeGamesThatFellApart: "Incluir partidas que se desfizeram",
  },

  promptContentReportDialog: {
    reportList: (p: { name: string }) => `Denunciar ${p.name}`,
    couldNotSendReport: "Não foi possível enviar o relatório.",
    reportsAreReviewedAfterSubmissionList: "As denúncias são analisadas depois de enviadas. A lista continua disponível a menos que um moderador a oculte.",
    content: "Conteúdo",
    entireList: "Lista inteira",
    reason: "Motivo",
    whatShouldModeratorKnow: "O que deve o moderador saber?",
    cancel: "Cancelar",
  },

  promptDisplay: {
    couldNotDoAction: (p: { action: string }) => `Não foi possível ${p.action}.`,
    nextHintCost: (p: { cost: number }) => `Pista seguinte: ${p.cost}`,
    hintSpendTotal: (p: { spent: number }) => `Total: ${p.spent}`,
    buyLetter: (p: { letter: string; price: number }) =>
      `Comprar «${p.letter}» por ${counted(p.price, { one: "ponto", other: "pontos" })}`,
    maskedPrompt: (p: { shape: string }) => `Palavra escondida, ${p.shape} letras`,
    buyThisLetter: (p: { cost: number }) =>
      `Comprar esta letra por ${counted(p.cost, { one: "ponto", other: "pontos" })}`,
    letterCount: (p: { count: number }) =>
      counted(p.count, { one: "letra", other: "letras" }),
    yourTurn: "É a tua vez",
    pickSomethingDraw: "Escolhe algo para desenhar",
    autoPicksWhenTimeRunsOut: "Escolhe sozinho quando o tempo acabar.",
    hintSpendLimitReached: "Limite de gasto em pistas atingido",
    deductedFromYourScoreIfYou: "É descontado da tua pontuação se adivinhares a palavra",
    buyLetterRevealsEveryMatch: "Compra uma letra — revela todas as ocorrências",
  },

  promptListPicker: {
    languageMismatch: (p: { listLanguage: string; roomLanguage: string }) =>
      `Essa lista está em ${p.listLanguage}; esta sala está em ${p.roomLanguage}.`,
    choicesUnavailable: (p: { reason: string }) =>
      `As listas de palavras estão indisponíveis (${p.reason}). A tua seleção atual mantém-se.`,
    noListsInLanguage: (p: { language: string }) =>
      `Ainda não há listas em ${p.language} — esta sala usa as suas próprias palavras.`,
    howListPlays: (p: { name: string }) => `Como se jogam as palavras de ${p.name}`,
    reportList: (p: { name: string }) => `Denunciar ${p.name}`,
    failedLoadPromptLists: "Não foi possível carregar as listas de palavras",
    couldNotAddThatSharedList: "Não foi possível adicionar essa lista partilhada.",
    loadingCuratedPromptLists: "A carregar listas de palavras…",
    promptLists: "Listas de palavras",
    addUnlistedListByCode: "Adicionar uma lista não listada com um código",
  },

  promptStatsPage: {
    noSuchList: "Não há nenhuma lista de palavras com esse nome.",
    couldNotLoadStats: "Não foi possível carregar estas estatísticas. Tenta de novo.",
    showMore: (p: { count: number }) => `Ver mais ${p.count}`,
    showingOf: (p: { shown: number; total: number }) => `A mostrar ${p.shown} de ${p.total}`,
    couldNotLoadPromptListsPlease: "Não foi possível carregar as listas de palavras. Tenta de novo.",
    serverWide: "Em todo o servidor",
    promptStats: "Estatísticas de palavras",
    everyPromptListHowHasActually: "Cada palavra da lista, e como correu mesmo nas partidas terminadas\n          neste servidor.",
    promptList: "Lista de palavras",
    sort: "Ordenação",
    period: "Período",
    scoring: "Pontuação",
    hints: "Pistas",
    findPrompt: "Encontrar uma palavra",
    rollerCoaster: "montanha-russa",
    loading: "A carregar…",
    prompt: "Palavra",
    howGoes: "Como corre",
    guessed: "Adivinhada",
    picked: "Escolhida",
    drawn: "Desenhada",
  },

  publicRoomCard: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "ronda", other: "rondas" }),
    promptLanguage: (p: { language: string }) => `Idioma das palavras: ${p.language}`,
    seeWhoThisRoom: "Ver quem está nesta sala",
    rounds: "Rondas",
    drawingTime: "Tempo de desenho",
    full: "Cheia",
    inProgress: "A decorrer",
    looking: "À procura…",
    nobodySeatedYet: "Ainda não se sentou ninguém.",
    host: "Anfitrião",
  },

  reactionRequests: {
    thatReactionCouldNotBeSent: "Não foi possível enviar essa reação.",
  },

  recapDrawings: {
    thisDrawingCouldNotBeLoaded: "Não foi possível carregar este desenho.",
  },

  reportAccountDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Um moderador vai ver isto. Não acontece nada a ${p.name} neste momento, e não lhe é dito quem denunciou.`,
    theirPicture: (p: { name: string }) => `imagem de ${p.name}`,
    thatReportCouldNotBeSent: "Não foi possível enviar essa denúncia. Tenta de novo.",
    whatWrongWith: "O que está mal",
    reportedTheirNameTheyHaveNo: "Denunciado pelo nome. Não tem imagem para denunciar.",
    anythingElseOptional: "Mais alguma coisa (opcional)",
    anythingModeratorShouldKnow: "Tudo o que um moderador deva saber",
    sentWithWhatAboutAttached: "Enviada, com o que lhe diz respeito em anexo.",
    done: "Concluído",
  },

  reportedDrawing: {
    thisDrawingCouldNotBeDecoded: "Não foi possível descodificar este desenho.",
    drawingCouldNotBeLoaded: "Não foi possível carregar o desenho.",
  },

  reportLobbyLineDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Um moderador vai ver esta linha. Não acontece nada a ${p.name} neste momento, e não lhe é dito quem denunciou.`,
    thatReportCouldNotBeSent: "Não foi possível enviar essa denúncia. Tenta de novo.",
    whatWrongWith: "O que está mal",
    anythingElseOptional: "Mais alguma coisa (opcional)",
    anythingModeratorShouldKnow: "Tudo o que um moderador deva saber",
    thisLineAttachedWithWhatLobby: "Esta linha vai em anexo, com o que o átrio disse à volta.",
    sentWithLineWhatWasSaid: "Enviada, com a linha e o que se disse à volta em anexo.",
    done: "Concluído",
  },

  reportPlayerDialog: {
    reportCouldNotBeSent: "Não foi possível enviar essa denúncia.",
    recentMessages: (p: { count: number }) =>
      `${p.count} das suas ${plural(p.count, { one: "mensagem recente", other: "mensagens recentes" })}`,
    nothingHappensYet: (p: { name: string }) =>
      `Um moderador vai ver isto. Não acontece nada a ${p.name} neste momento, e não lhe é dito quem denunciou.`,
    whatHappened: "O que aconteceu",
    anythingElseOptional: "Mais alguma coisa (opcional)",
    whatTheySaidDrewWhen: "O que disse ou desenhou, e quando",
    theirRecentMessagesThisRoomAre: "As mensagens recentes desta pessoa nesta sala vão em anexo automaticamente,\n                com o que se disse à volta, por isso isto pode ficar vazio.",
    includeTheirDrawing: "Incluir o desenho dela",
    canvasAsRightNowSoModerator: "A tela tal como está agora, para que um moderador veja o que\n                      tu viste.",
    done: "Concluído",
  },

  reportsReviewedNotice: {
    reportsReviewed: (p: { count: number }) =>
      `${counted(p.count, { one: "denúncia que enviaste foi analisada", other: "denúncias que enviaste foram analisadas" })}. Obrigado.`,
  },

  restartVoteBanner: {
    voteTally: (p: { yes: number; no: number; pending: number }) =>
      `${p.yes} a favor, ${p.no} contra, ${p.pending} por decidir`,
    restartingIn: (p: { seconds: number }) =>
      `A reiniciar dentro de ${counted(p.seconds, { one: "segundo", other: "segundos" })}`,
    restartApproved: "Reinício aprovado!",
    seconds: "segundos",
    voteRestartGame: "Votar para reiniciar a partida",
    restart: "Reiniciar",
    keepPlaying: "Continuar a jogar",
    onlyEligiblePlayersPresentWhenVote: "Só podem votar os jogadores elegíveis presentes quando a votação começou.",
  },

  roleChangeNotice: {
    youHaveBeenSignedOutEvery: "A tua sessão foi terminada em todos os dispositivos para que a mudança\n            tenha efeito. Inicia sessão outra vez para continuares.",
    setUpNow: "Configurar agora",
    later: "Mais tarde",
  },

  roomChatPanel: {
    unreadMessages: (p: { count: number }) =>
      `${counted(p.count, { one: "mensagem nova", other: "mensagens novas" })}`,
    correctWithPlace: (p: { place: string | null }) =>
      p.place ? `Certo · ${p.place}` : "Certo",
    couldNotSendMessage: "Não foi possível enviar a mensagem",
    sent: "Enviado:",
    send: "Enviar",
    youReDrawingWatchGuessesCome: "Estás a desenhar — vê os palpites a chegar.",
  },

  roomEntryState: {
    thisRoomNoLongerAvailable: "Esta sala já não está disponível",
    couldNotJoinThisRoom: "Não foi possível entrar nesta sala",
  },

  roomMenuSheet: {
    startTheGameOver: "Recomeçar a partida",
    startOverCooldown: (p: { seconds: number }) => ` · daqui a ${p.seconds}s`,
    room: "Sala",
    playersScores: "Jogadores e pontos",
    copyInviteLink: "Copiar a ligação de convite",
    saveThisDrawing: "Guardar este desenho",
    settings: "Definições",
    leaveRoom: "Sair da sala",
  },

  roomPlayersPanel: {
    spectatorCount: (p: { count: number }) =>
      counted(p.count, { one: "espectador", other: "espectadores" }),
    spectatorsHeading: (p: { count: number }) => `Espectadores (${p.count})`,
    playersOfCapacity: (p: { here: number; capacity: number }) =>
      `${p.here} de ${p.capacity} jogadores`,
    readyCount: (p: { count: number }) => `${p.count} prontos`,
    couldNotJoinAsPlayer: "Não foi possível entrar como jogador",
    finalStandings: "Classificação final",
    players: "Jogadores",
  },

  roomSettingsEditor: {
    couldNotLoadRoomRules: "Não foi possível carregar as regras da sala",
    roomRefusedThoseSettings: "A sala recusou essas definições.",
    hostSettings: "Definições do anfitrião",
    editRoomRules: "Editar as regras da sala",
    loadingSettings: "A carregar definições…",
    cancel: "Cancelar",
  },

  roomSetupForm: {
    language: "Idioma",
    visibility: "Visibilidade",
    maxPlayers: "Máximo de jogadores",
    rounds: "Rondas",
    drawingTime: "Tempo de desenho",
    onlyUseCustomPrompts: "Usar apenas palavras próprias",
    addUsableCustomPromptEnableThis: "Adiciona uma palavra própria utilizável para ativares esta opção.",
    allowedTools: "Ferramentas permitidas",
    colors: "Cores",
    scoring: "Pontuação",
    hints: "Pistas",
    spectatorsCanSeePrompt: "Os espectadores veem a palavra",
    hideBlanks: "Esconder os espaços",
    alsoTurnsHintsOffWithNo: "Também desliga as pistas: sem espaços não há nada para revelar.",
    promptTotal: (p: { count: number }) =>
      counted(p.count, { one: "palavra", other: "palavras" }),
    basics: "Básico",
    roomName: "Nome da sala",
    public: "Pública",
    private: "Privada",
    prompts: "Palavras",
    drawing: "A desenhar",
    scoringHints: "Pontuação e pistas",
    hintsAreOffBecauseBlanksAre: "As pistas estão desligadas porque os espaços estão escondidos.",
    pointPurchaseHintModesRequireScoring: "Os modos de pista pagos precisam de pontuação.",
  },

  rulesPage: {
    sketchy: "Sketchy",
    theRules: "As regras",
    thisPage: "Nesta página",
    forExample: "Por exemplo",
  },

  sessionManagerDialog: {
    lastUsed: (p: { when: string }) => `Usado pela última vez ${p.when}`,
    signsOutOn: (p: { when: string }) => `Termina a sessão sozinho ${p.when}`,
    usedElsewhere: (p: { when: string }) =>
      `Usado a partir de outro navegador a ${p.when}. Revoga este dispositivo se não foste tu.`,
    couldNotLoadSignedDevices: "Não foi possível carregar os dispositivos com sessão iniciada.",
    couldNotRevokeDevice: "Não foi possível revogar o dispositivo.",
    couldNotLogOutEverywhere: "Não foi possível terminar a sessão em todo o lado.",
    signedDevices: "Dispositivos com sessão iniciada",
    revokeAnyDeviceYouNoLonger: "Revoga qualquer dispositivo que já não reconheças. Os nomes dos dispositivos são aproximados e não guardam versões de navegador.\n          Um dispositivo que deixas de usar termina a sessão sozinho ao fim de noventa dias.",
    loadingDevices: "A carregar dispositivos…",
    currentDevice: "Dispositivo atual",
    close: "Fechar",
  },

  settingsOverlay: {
    email: "E-mail",
    password: "Palavra-passe",
    twoFactorAuthentication: "Verificação em dois passos",
    signedDevices: "Dispositivos com sessão iniciada",
    downloadEverything: "Descarregar tudo",
    colorScheme: "Esquema de cores",
    appliesMomentYouPick: "Aplica-se assim que o escolhes.",
    languageYouPlay: "Idioma em que jogas",
    roomsThisLanguageComeFirstLobby: "As salas neste idioma aparecem primeiro no átrio, e uma sala que crias começa nele. É separado do idioma em que lês o Sketchy.",
    interfaceLanguage: "Idioma em que lês",
    interfaceLanguageHint: "Cada palavra do próprio Sketchy. Separado do idioma em que jogas: ler num e jogar noutro é perfeitamente normal.",
    timeFormat: "Formato da hora",
    howEveryClockReadsChatTimestamps: "Como se lê cada relógio: horas na conversa, datas de início de sessão, avisos. «Sistema» segue o teu dispositivo.",
    iHaveTroubleTellingColorsApart: "Tenho dificuldade em distinguir cores",
    nudgesHostsTowardRoomColorsThat: "Encaminha os anfitriões para cores de sala que continuam distinguíveis com deuteranopia e protanopia, sem lhes dizer quem pediu. Nada muda sozinho.",
    brushCursor: "Cursor do pincel",
    crosshairPreciseAtPointOutlineShows: "Uma mira é precisa no ponto; um contorno mostra a largura do traço.",
    brushCursorStyle: "Estilo do cursor do pincel",
    soundEffects: "Efeitos sonoros",
    chimesCorrectGuessStartRoundLast: "Sons para um acerto, o início de uma ronda, os últimos dez segundos, e jogadores a entrar e a sair.",
    volume2: "Volume",
    confetti: "Confetes",
    burstWhenYouGuessRightAgain: "Um jorro quando acertas, e outro para quem ganhar no fim da partida.",
    clickKeyRebindEachActionCan: "Clica numa tecla para a reatribuir. Cada ação pode ter duas. Carrega em Esc para cancelar.",
    theseAreTheirSettings: (p: { name: string }) => `Estas são agora as definições de ${p.name}.`,
    guestLivesInThisBrowser: (p: { name: string }) =>
      `${p.name} só existe neste navegador. Uma conta guarda o nome, os teus pontos e o teu histórico em todos os dispositivos, e deixa-te escolher uma cor.`,
    systemThemeNow: (p: { theme: "dark" | "light" }) => `Agora: ${p.theme}`,
    needsAccount: "Precisa de uma conta",
    choosePicture: "Escolher uma imagem",
    editPicture: "Editar a imagem",
    picture: "Imagem",
    changePicture: "Mudar a imagem",
    removePicture: "Remover a imagem",
    couldNotRemovePicture: "Não foi possível remover a imagem.",
    couldNotChangeYourDisplayName: "Não foi possível mudar o teu nome a mostrar.",
    couldNotChangeYourDisplayName2: "Não foi possível mudar o teu nome a mostrar. Tenta de novo.",
    themeSoundShortcutsCameFromAccount: "O tema, o som e os atalhos\n            vieram da conta. O que este navegador tinha fica intacto e volta se\n            terminares sessão.",
    dismiss: "Dispensar",
    playingAsGuest: "A jogar como convidado",
    createAccount: "Criar uma conta",
    logIn: "Iniciar sessão",
    you: "Tu",
    displayName: "Nome a mostrar",
    cancel: "Cancelar",
    change: "Mudar",
    nameColor: "Cor do nome",
    signingIn: "Início de sessão",
    changePassword: "Mudar a palavra-passe",
    manage: "Gerir",
    yourData: "Os teus dados",
    requestExport: "Pedir exportação",
    delete: "Eliminar…",
    display: "Ecrã",
    theme: "Tema",
    accessibility: "Acessibilidade",
    theCanvas: "A tela",
    sound: "Som",
    volume: "Volume",
    effects: "Efeitos",
    noKeyboardThisDevice: "Não há teclado neste dispositivo",
    yourBindingsAreStillSavedStill: "Os teus atalhos continuam guardados e a funcionar. Abre o Sketchy com um\n            teclado ligado para os mudares.",
    drawingTools: "Ferramentas de desenho",
    resetDefaults: "Repor os valores predefinidos",
    settings: "Definições",
    close: "Fechar",
    closeSettings: "Fechar as definições",
    settingsSections: "Secções das definições",
  },

  stepUpDialog: {
    codeFromYourAuthenticatorApp2: "Código da tua aplicação de autenticação",
    passkeyNotUsed: "Essa passkey não foi usada. Podes tentar de novo.",
    thatCodeWasNotAccepted: "Esse código não foi aceite.",
    thatPasskeyWasNotAccepted: "Essa passkey não foi aceite.",
    confirmYou: "Confirma que és tu",
    recoveryCode: "Código de recuperação",
    codeFromYourAuthenticatorApp: "Código da tua aplicação de autenticação",
    cancel: "Cancelar",
  },

  suspensionNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `O teu desenho de ${p.prompt}, tal como foi denunciado`,
    recordedAs: "Registado como {category}",
    yourAccountSuspended: "A tua conta está suspensa",
    youWereAskedDraw: "Era a tua vez de desenhar",
  },

  toastProvider: {
    notifications: "Notificações",
    dismissNotification: "Dispensar a notificação",
  },

  toolbar: {
    colorOption: (p: { color: string }) => `cor ${p.color}`,
    adjustSize: (p: { tool: string }) => `Ajustar o tamanho de ${p.tool}`,
    sizeSnappingSlider: (p: { tool: string }) => `Cursor de tamanho com encaixe para ${p.tool}`,
    chooseToolCurrent: (p: { tool: string }) => `Escolher ferramenta, atual: ${p.tool}`,
    chooseColorCurrent: (p: { color: string }) => `Escolher cor, atual ${p.color}`,
    sizeWithWidth: (p: { tool: string; width: number }) => `${p.tool}, tamanho ${p.width}px`,
    sizeShortcutHint: (p: { tool: string; width: number }) =>
      `${p.tool}, tamanho: ${p.width}px ([ / ])`,
    widthReadout: (p: { width: number }) => `${p.width}px`,
    colorSwatch: (p: { color: string }) => `Cor ${p.color}`,
    drawingTools: "Ferramentas de desenho",
    chooseTool: "Escolher ferramenta",
    chooseColor: "Escolher cor",
    undoLastStroke: "Desfazer o último traço",
    undo: "Desfazer",
    clearCanvas: "Limpar a tela",
    chooseCustomColor: "Escolher uma cor personalizada",
    colorPalette: "Paleta de cores",
    canvasActions: "Ações da tela",
    undoLastStrokeCtrlZ: "Desfazer o último traço (Ctrl+Z)",
    clear: "Limpar",
  },

  turnResultsOverlay: {
    yourTurnWithHints: (p: { base: number; hintSpend: number; points: number; rank: number }) =>
      `A tua vez: +${p.base} -${p.hintSpend} pistas = ${counted(p.points, { one: "ponto", other: "pontos" })} · agora #${p.rank}`,
    yourTurn: (p: { delta: number; rank: number }) =>
      `A tua vez: ${p.delta >= 0 ? "+" : ""}${p.delta} ${
        Math.abs(p.delta) === 1 ? "ponto" : "pontos"
      } · agora #${p.rank}`,
    promptWas: "A palavra era",
    noOneGuessedCorrectly: "Ninguém acertou.",
    you: "(tu)",
    drewThisTurn: "Desenhou nesta ronda",
    nextTurn: "Ronda seguinte",
  },

  twoFactorDialog: {
    scanThisWithYourAuthenticatorApp: "Digitaliza isto com a tua aplicação de autenticação para adicionares esta conta",
    codeFromYourAuthenticatorApp: "Código da tua aplicação de autenticação",
    secondFactorState: (p: {
      recoveryCodesRemaining: number | null;
      confirmAuthenticator: boolean;
    }) =>
      [
        "A verificação em dois passos está ligada.",
        p.recoveryCodesRemaining === null
          ? null
          : `Ainda tens ${counted(p.recoveryCodesRemaining, {
              one: "código de recuperação",
              other: "códigos de recuperação",
            })}.`,
        p.confirmAuthenticator
          ? "Antes de esta conta poder receber um papel de moderador ou administrador, confirma com a tua palavra-passe e um código que o autenticador é teu."
          : null,
        "Cada uma das mudanças abaixo troca uma credencial, por isso cada uma pede a tua palavra-passe.",
      ]
        .filter(Boolean)
        .join(" "),
    confirmAuthenticatorFirst:
      "Antes de esta conta poder receber um papel de moderador ou administrador, confirma com a tua palavra-passe e um código que o autenticador é teu.",
    copied: (p: { what: string }) => `${p.what} copiado.`,
    couldNotCopy: (p: { what: string }) =>
      `Não foi possível copiar ${p.what}. Seleciona-o e copia à mão.`,
    roleTaken: (p: { role: "admin" | "moderator" }) =>
      `Agora és ${p.role === "admin" ? "administrador" : "moderador"}. A verificação em dois passos está ligada, e o papel que estava à espera dela entrou em vigor. Os teus outros dispositivos foram desligados; este continua, e cada início de sessão a partir daqui pede um código.`,
    recoveryCodesLeft: (p: { count: number }) =>
      `Ainda tens ${counted(p.count, { one: "código de recuperação", other: "códigos de recuperação" })}.`,
    couldNotReadYourSecuritySettings: "Não foi possível ler as tuas definições de segurança.",
    yourPasswordConfirmsAuthenticatorYours: "A tua palavra-passe confirma que o autenticador é teu.",
    yourPasswordConfirmsThisPasskeyYours: "A tua palavra-passe confirma que esta passkey é tua.",
    passkeyAdded: "Passkey adicionada.",
    thatPasskeyWasNotCreatedYou: "Essa passkey não foi criada. Podes tentar de novo.",
    yourPasswordNeededRemovePasskey: "É precisa a tua palavra-passe para remover uma passkey.",
    confirmedThisAccountCanNowBe: "Confirmado. Esta conta já pode receber um papel da equipa.",
    twoFactorAuthentication: "Verificação em dois passos",
    saveTheseRecoveryCodesNow: "Guarda já estes códigos de recuperação.",
    eachOneSignsYouOnceIf: "Cada um inicia a tua sessão\n              uma vez se perderes a tua aplicação de autenticação. Não voltam a\n              ser mostrados — só os seus hashes ficam guardados.",
    recoveryCodes: "Códigos de recuperação",
    downloadAsFile: "Descarregar como ficheiro",
    copyAll: "Copiar todos",
    iHaveSavedTheseSomewhereSafe: "Guardei-os num sítio seguro",
    done: "Concluído",
    moderatorsAdministratorsSignWithPasskeyYour: "Os moderadores e administradores iniciam sessão com uma passkey: o teu\n              dispositivo confirma que és tu — impressão digital, rosto ou o\n              PIN — e não se escreve nada que possa ser entregue.",
    yourPassword: "A tua palavra-passe",
    confirmsPasskeyBeingAddedByYou: "Confirma que és tu a adicionar a passkey.",
    useAuthenticatorAppInstead: "Usar antes uma aplicação de autenticação",
    scanCodeWithAuthenticatorAppThen: "Digitaliza o código com uma aplicação de autenticação e escreve depois\n              os seis dígitos que ela mostrar.",
    drawingCode: "A desenhar o código…",
    pointYourAppAtThis: "Aponta a tua aplicação para aqui.",
    setupKey: "Chave de configuração",
    copySetupKey: "Copiar a chave de configuração",
    useThisIfYouCanT: "Usa isto se não conseguires digitalizar.",
    confirmsAuthenticatorYours: "Confirma que o autenticador é teu.",
    codeFromYourApp: "Código da tua aplicação",
    cancel: "Cancelar",
    passkeys: "Passkeys",
    thisDeviceOnly: "· só neste dispositivo",
    remove: "Remover",
    confirmSYours: "Confirmar que é tua",
    addPasskey: "Adicionar uma passkey",
    newRecoveryCodes: "Códigos de recuperação novos",
    turnOff: "Desligar",
    addAuthenticatorApp: "Adicionar uma aplicação de autenticação",
    close: "Fechar",
  },

  useFriendArrivalNotices: {
    wantsToBeFriends: (p: { name: string }) => `${p.name} quer ser teu amigo.`,
    acceptedYourRequest: (p: { name: string }) => `${p.name} aceitou o teu pedido de amizade.`,
    severalAccepted: (p: { count: number }) =>
      `${counted(p.count, { one: "pessoa aceitou", other: "pessoas aceitaram" })} os teus pedidos de amizade.`,
  },

  useRoomSessionReconnect: {
    joinRoomFailed: "join_room failed",
  },

  waitingRoomPanel: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "ronda", other: "rondas" }),
    needMorePlayers: (p: { count: number }) =>
      `${counted(p.count, { one: "Falta 1 jogador", other: "Faltam mais jogadores" })}`,
    hostWillStart: (p: { rematch: boolean }): string =>
      p.rematch ? "{host} vai começar a desforra" : "{host} vai começar a partida",
    copied: (p: { what: string }) => `${p.what} copiado.`,
    couldNotCopy: (p: { what: string }) =>
      `Não foi possível copiar ${p.what}. Copia-o da barra de endereço.`,
    roomCodeLabel: (p: { code: string }) => `Código da sala ${p.code}`,
    rosterCount: (p: { here: number; capacity: number }) => `${p.here} de ${p.capacity}`,
    inviteYourFriends: "Convida os teus amigos",
    shareLink: "Partilha a ligação",
    copyCode: "Copiar o código",
    inTheRoom: "Na sala",
    you: "(tu)",
    host: "Anfitrião",
    friend: "Amigo",
    invite: "Convidar",
    edit: "Editar",
    viewHighlights: "Ver os melhores momentos",
    viewDrawings: "Ver os desenhos",
  },

  warningNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `O teu desenho de ${p.prompt}, tal como foi denunciado`,
    recordedAs: "Registado como {category}",
    whatAWarningMeans:
      "Uma denúncia sobre o teu comportamento foi analisada, e este é o resultado. Não há nada restringido, mas outra denúncia pode levar à suspensão da tua conta.",
    youWereAskedDraw: "Era a tua vez de desenhar",
  },
};
