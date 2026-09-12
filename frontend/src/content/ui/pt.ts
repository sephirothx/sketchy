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
  prompt_list_allowance_reached: (params: Record<string, unknown>) => {
    const max = typeof params.max === "number" ? params.max : 25;
    return `Esta conta já tem ${max} listas de palavras, o máximo permitido. É preciso eliminar uma para abrir espaço.`;
  },
  email_verification_required: (params: Record<string, unknown>) => {
    switch (params.action) {
      case "publish":
        return "Para publicar uma lista é preciso um endereço de email confirmado.";
      case "star":
        return "Para dar uma estrela a uma lista é preciso um endereço de email confirmado.";
      default:
        return "Para isso é preciso um endereço de email confirmado.";
    }
  },
  warning_unread: (params: Record<string, unknown>) => {
    switch (params.action) {
      case "publish":
        return "Antes de publicar uma lista é preciso ler o aviso da moderação.";
      case "star":
        return "Antes de dar uma estrela é preciso ler o aviso da moderação.";
      default:
        return "Primeiro é preciso ler o aviso da moderação.";
    }
  },
  prompt_list_hidden: "Esta lista está oculta e não pode ser publicada. Primeiro tem de ser revista pela moderação.",
  unknown_prompt_tag: (params: Record<string, unknown>) => {
    const tag = String(params.tag ?? "");
    return `«${tag}» não é uma etiqueta que uma lista possa ter.`;
  },
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
    duplicatesAlreadyInTheList: (p: { duplicates: number }) =>
      `${p.duplicates} já na lista`,
    tooLongCountOverMaxListPrompt: (p: { tooLongCount: number; MAX_LIST_PROMPT_LENGTH: number }) =>
      `${p.tooLongCount} com mais de ${p.MAX_LIST_PROMPT_LENGTH} caracteres`,
    overLimitPastTheMaxList: (p: { overLimit: number; MAX_LIST_PROMPTS: number }) =>
      `${p.overLimit} acima do limite de ${p.MAX_LIST_PROMPTS}`,
    keptSkippedSkipped: (p: { kept: string; skipped: string }) =>
      `${p.kept}; ignoradas: ${p.skipped}.`,
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
    hardestPrompt: "Palavra mais difícil",
    fastestGuess: "Palpite mais rápido",
    bestDrawer: "Melhor desenhador",
    quickestOnAverage: "Mais rápido em média",
    mostReactedDrawing: "Desenho com mais reações",
    guessedItOf: (p: { correct: number; total: number }) =>
      plural(p.correct, { one: `${p.correct} de ${p.total} acertou`, other: `${p.correct} de ${p.total} acertaram` }),
    percentGuessed: (p: { percent: string }) =>
      `${p.percent} acertado`,
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
    gotOfGuessersCountGuessed: (p: { got: number; guessersCount: number }) =>
      `${p.got} de ${p.guessersCount} acertaram`,
    summaryOpenPlayersAndScores: (p: { summary: string }) =>
      `${p.summary}. Abrir jogadores e pontuações.`,
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
    requesting: "A pedir…",
    requestExport: "Pedir exportação",
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
    createYourAccount: "Cria a tua conta",
    createAnAccountToKeep: (p: { suggestedUsername: string }) =>
      `Cria uma conta para manteres ${p.suggestedUsername} como nome de utilizador e guardares as tuas estatísticas em todos os dispositivos.`,
    keepYourUsernameAndYour: "Mantém o teu nome de utilizador e as tuas estatísticas em todos os dispositivos.",
    waitingForYourDevice: "À espera do teu dispositivo…",
    signInWithAPasskey: "Iniciar sessão com uma passkey",
    pleaseWait: "Aguarda…",
    alreadyRegistered: "Já tens conta? ",
    newHere: "És novo por cá? ",
    createAnAccount: "Criar uma conta",
    guestIdentity: (p: { name: string }) =>
      `${p.name}. O teu nome a mostrar não está guardado.`,
    signedInAs: (p: { name: string }) =>
      `Sessão iniciada como ${p.name}`,
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
    addressIsConfirmedYouCan: (p: { address: string }) =>
      `${p.address} está confirmado. Já podes recuperar esta conta.`,
    yourPasswordIsSetAnd: "A tua palavra-passe está definida e voltaste a iniciar sessão.",
    resetYourPassword: "Repõe a tua palavra-passe",
    thatLinkNoLongerWorks: "Essa ligação já não funciona",
    chooseANewPassword: "Escolhe uma palavra-passe nova",
    confirmingYourEmail: "A confirmar o teu e-mail",
    pleaseWait: "Aguarda…",
    sendAResetLink: "Enviar uma ligação de reposição",
    setPassword: "Definir palavra-passe",
    oneMoment: "Um momento…",
    nothingToConfirm: "Nada para confirmar.",
    resetLinkOnItsWay:
      "Se essa conta existir e tiver um endereço de e-mail confirmado, vai chegar uma ligação para repor a palavra-passe.",
  },

  activeGameRoom: {
    leaveGame: "Sair da partida",
    markedAfkByRoomVote: "A sala marcou-te como ausente por votação.",
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
    youWereKickedFromThe: "Foste expulso da sala.",
    thisRoomWasOpenedIn: "Esta sala foi aberta noutro separador.",
    startTheGame: "começar o jogo",
    startARestartVote: "iniciar uma votação para recomeçar",
    recordYourRestartVote: "registar o teu voto para recomeçar",
    leaveDuringYourTurn: "Sair durante a tua vez?",
    leaveActiveGame: "Sair do jogo em curso?",
    youReTheCurrentDrawer: "És tu quem está a desenhar. Se saíres agora, interrompes a tua vez e o jogo avança para todos.",
    theGameIsStillIn: "O jogo ainda está a decorrer. Vais sair da sala e perder o teu lugar neste jogo.",
    restartVoteAvailableInRestartCooldownSeconds: (p: { restartCooldownSeconds: number }) =>
      `Votação para recomeçar disponível daqui a ${p.restartCooldownSeconds} segundos`,
    proposeRestartingTheGame: "Propor recomeçar o jogo",
    restartVoteAvailableInRestartCooldownSeconds2: (p: { restartCooldownSeconds: number }) =>
      `Votação para recomeçar daqui a ${p.restartCooldownSeconds} s`,
    proposeAVoteToRestart: "Propor uma votação para recomeçar o jogo",
    backFromAfk: "Voltei",
    goAfk: "Ficar ausente",
    closePlayers: "Fechar jogadores",
    acceptTheColorSuggestion: "aceitar a sugestão de cores",
    dismissTheColorSuggestion: "dispensar a sugestão de cores",
    couldNotAcceptSuggestion: "Não foi possível aceitar a sugestão de cores.",
    couldNotDismissSuggestion: "Não foi possível dispensar a sugestão de cores.",
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
    checkYourInbox: "Vê a tua caixa de entrada",
    changeYourEmailAddress: "Muda o teu endereço de e-mail",
    addAnEmailAddress: "Adiciona um endereço de e-mail",
    newEmail: "E-mail novo",
    email: "E-mail",
    pleaseWait: "Aguarda…",
    sendConfirmation: "Enviar confirmação",
    close: "Fechar",
    notNow: "Agora não",
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
    build: "Versão",
    page: "Página",
    room: "Sala",
    screen: "Ecrã",
    browser: "Navegador",
    connection: "Ligação",
    waitingForThePicker: "À espera do seletor…",
    attachAScreenshot: "Anexar uma captura de ecrã",
    whatWeAreLeavingOut: "O que deixamos de fora",
    whatWeSendWithThis: "O que enviamos com isto",
    noneOfThisIsBeing: "Nada disto é enviado — só a tua descrição acima.",
    theLast20ErrorsYour: "Os últimos 20 erros que o teu navegador registou. Nenhum endereço de página além do caminho, nada do que escreveste no chat e nunca a palavra em jogo.",
    sending: "A enviar…",
    sendReport: "Enviar relatório",
    kilobytes: (p: { size: number }) =>
      `${number(p.size)} KB`,
    megabytes: (p: { size: number }) =>
      `${number(p.size)} MB`,
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
    checkYourInbox: "Vê a tua caixa de entrada",
    changeYourPassword: "Muda a tua palavra-passe",
    pleaseWait: "Aguarda…",
    changePassword: "Mudar palavra-passe",
    close: "Fechar",
    cancel: "Cancelar",
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
    summary: "Resumo",
    build: "Versão",
    page: "Página",
    room: "Sala",
    screen: "Ecrã",
    browser: "Navegador",
    connection: "Ligação",
    thisRoomSScreenHit: "O ecrã desta sala encontrou um erro e teve de parar. O teu lugar fica guardado por um momento: envia o relatório abaixo e depois recarrega para o retomar, ou volta ao átrio.",
    thisScreenHitAnError: "Este ecrã encontrou um erro e teve de parar. A tua conta e as tuas definições estão seguras. Envia o relatório abaixo e podes seguir em frente.",
    whatWeAreLeavingOut: "O que deixamos de fora",
    whatWeSendWithThis: "O que enviamos com isto",
    noneOfThisIsBeing: "Nada disto é enviado — só a tua descrição acima.",
    theCrashTheLast20: "A falha, os últimos 20 erros que o teu navegador registou e onde na página aconteceu. Nenhum endereço de página além do caminho, nada do que escreveste no chat e nunca a palavra em jogo.",
    sendingAgain: "A enviar de novo…",
    sending: "A enviar…",
    trySendingAgain: "Tentar enviar de novo",
    sendReport: "Enviar relatório",
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
    saveQuickPromptsAsA: "Guarda as palavras rápidas como lista e remove os códigos partilhados antes de guardar uma predefinição.",
    appliedName: (p: { name: string }) =>
      `«${p.name}» aplicada.`,
    savedName: (p: { name: string }) =>
      `«${p.name}» guardada.`,
    updatedName: (p: { name: string }) =>
      `«${p.name}» atualizada.`,
    deleteThisRoomSettingPreset: "Eliminar esta predefinição de sala?",
    createTheRoom: "criar a sala",
    noScoring: "Sem pontuação",
    public: "Pública",
    private: "Privada",
    backToLobby: "Voltar ao átrio",
    leaveBlankForARandom: "Deixa em branco para um nome aleatório!",
    creating: "A criar…",
    createRoom2: "Criar sala",
    playerCount: (p: { count: number }) =>
      counted(p.count, { one: "jogador", other: "jogadores" }),
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "ronda", other: "rondas" }),
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
    all: "Todas",
    allPromptLengths: "Todos os comprimentos",
    short: "Curtas",
    n5CharactersOrFewer: "5 caracteres ou menos",
    medium: "Médias",
    n6To10Characters: "De 6 a 10 caracteres",
    long: "Longas",
    n11CharactersOrMore: "11 caracteres ou mais",
    loadTheCustomPrompts: "carregar as palavras próprias",
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
    deleteThisGuest: "Eliminar este convidado",
    deleteYourAccount: "Eliminar a tua conta",
    deleting: "A eliminar…",
    deleteForGood: "Eliminar de vez",
    keepPlaying: "Continuar a jogar",
    keepMyAccount: "Manter a minha conta",
  },

  drawingReactionControl: {
    reactionSummary: (p: { total: number; chips: string }) =>
      `${counted(p.total, { one: "reação", other: "reações" })}: ${p.chips}`,
    thatReactionCouldNotBeSent: "Não foi possível enviar essa reação.",
    reactThisDrawing: "Reagir a este desenho",
    reactions: "Reações",
    createAccountReact: "Cria uma conta para reagires.",
    createAccount: "Criar conta",
    noReactionsYet: "Ainda sem reações",
    reactToThisDrawingSummary: (p: { summary: string }) =>
      `Reagir a este desenho. ${p.summary}`,
    labelYourReactionPressTo: (p: { label: string }) =>
      `${p.label}, a tua reação. Carrega para a retirar`,
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
    loadThisDrawing: "carregar este desenho",
  },

  emailRecoveryReminder: {
    addEmail: "Adicionar um e-mail",
    dismiss: "Dispensar",
    confirmPendingAddressToFinishSetting: (p: { pendingAddress: string }) =>
      `Confirma ${p.pendingAddress} para acabares de configurar a recuperação da conta.`,
    thisAccountHasNoEmail: "Esta conta não tem endereço de e-mail, por isso uma palavra-passe esquecida não pode ser reposta.",
  },

  firstRunIdentity: {
    couldNotSaveThatNamePlease: "Não foi possível guardar esse nome. Tenta de novo.",
    keepYourUsernameYourStatsEvery: "Mantém o teu nome de utilizador e as tuas estatísticas em todos os dispositivos.",
    createAccount: "Criar uma conta",
    logIn: "Iniciar sessão",
    or: "ou",
    displayName: "Nome a mostrar",
    beenHereBefore: "Já cá estiveste?",
    playAsYourself: "Joga como tu",
    whatShouldWeCallYou: "Como te devemos chamar?",
    justPlayingOncePickA: "Só uma partida? Escolhe um nome a mostrar",
    play: "Jogar",
    playAsGuest: "Jogar como convidado",
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
    aGreatGameOfDrawing: "Um grande jogo de desenho",
    theRoomTakesTheCrown: "A sala inteira fica com a coroa!",
    winnersCountPlayersShareTheCrown: (p: { winnersCount: number }) =>
      `${p.winnersCount} jogadores partilham a coroa!`,
    takesTheCrown: " fica com a coroa!",
    shareTheCrown: " partilham a coroa!",
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
    promptDetailsHidden: "Detalhes da palavra ocultos",
    timedHints: "Pistas temporizadas",
    buyableLetterHints: "Pistas de letras compráveis",
    wheelOfFortune: "Roda da sorte",
    noLetterHints: "Sem pistas de letras",
    publicRoom: "Sala pública",
    privateInvite: "Convite privado",
    inProgress: "A decorrer",
    waiting: "À espera",
    full: " · Cheia",
    noScoring: "Sem pontuação",
    pressure: "Pressão",
    default: "Padrão",
    everyToolAndColor: "Todas as ferramentas e cores",
    spectatorsCanSeeThePrompt: "Os espectadores veem a palavra",
    spectatorsGuessAlong: "Os espectadores também adivinham",
    defaultPromptList: "Lista de palavras padrão",
    roomFull: "Sala cheia",
    joining: "A entrar…",
    joinGameInProgress: "Entrar no jogo em curso",
    joinGame: "Entrar no jogo",
    spectate: "Assistir",
    customPromptsOnly: (p: { count: number }) =>
      `só ${counted(p.count, { one: "palavra própria", other: "palavras próprias" })}`,
    customPromptsPlusDefaults: (p: { count: number }) =>
      `${counted(p.count, { one: "palavra própria", other: "palavras próprias" })} mais as padrão`,
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
    couldNotSaveThatName: "Não foi possível guardar esse nome. Tenta de novo.",
    joinAsASpectator: "entrar como espectador",
    joinTheRoom: "entrar na sala",
    loading: "A carregar…",
    showingFilteredRoomsCountOfRoomsCount: (p: { filteredRoomsCount: number; roomsCount: number }) =>
      `A mostrar ${p.filteredRoomsCount} de ${p.roomsCount}`,
    n0Rooms: "0 salas",
    close: "Fechar",
    joining: "A entrar…",
    joinTheRoom2: "Entrar na sala",
    joiningAsSpectator: "A entrar como espectador…",
    watchWithoutPlaying: "Assistir sem jogar",
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
    couldNotSaveThatName: "Não foi possível guardar esse nome. Tenta de novo.",
    sendTheMessage: "enviar a mensagem",
  },

  lobbyPlayerMenu: {
    whatToDoAbout: (p: { name: string }) => `O que fazer com ${p.name}`,
    openPlayerProfile: "Abrir o perfil do jogador",
    addAsFriend: "Adicionar como amigo",
    report: "Denunciar",
  },

  promptTags: {
    "animals": "Animais",
    "food-and-drink": "Comida e bebida",
    "objects": "Objetos",
    "nature": "Natureza",
    "places": "Lugares",
    "people": "Pessoas",
    "actions": "Ações",
    "sports-and-games": "Desporto e jogos",
    "transport": "Transportes",
    "entertainment": "Entretenimento",
    "science-and-technology": "Ciência e tecnologia",
    "history-and-culture": "História e cultura",
    "holidays": "Festividades",
    "fantasy": "Fantasia",
    "abstract": "Abstrato",
  },
  myPromptListsPage: {
    inCommunityCatalogue: "No catálogo da comunidade",
    notPublished: "Não publicada",
    publishedExplainer: "Qualquer pessoa pode encontrar esta lista, jogá-la, dar-lhe uma estrela ou fazer uma cópia sua.",
    unpublishedExplainer: "Ao publicar, qualquer pessoa pode encontrar e jogar esta lista. Pode ser retirada a qualquer momento.",
    publish: "Publicar",
    unpublish: "Retirar",
    promptListPublished: "Lista de palavras publicada.",
    promptListUnpublished: "Lista de palavras retirada.",
    couldNotChangePublication: "Não foi possível alterar a publicação desta lista.",
    published: "Publicada",
    tags: "Etiquetas",
    tagsChosen: (p: { chosen: number; max: number }) => `${p.chosen} de ${p.max} escolhidas`,
    tagsAreHowListsAreFound: "As etiquetas são a forma de encontrar esta lista no catálogo da comunidade.",
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
    promptListSaved: "Lista de palavras guardada.",
    deleteThisPromptListAnd: "Eliminar esta lista de palavras e todas as suas revisões?",
    promptListDeleted: "Lista de palavras eliminada.",
    backToLobby: "Voltar ao átrio",
    promptsCountOfMaxListPrompts: (p: { promptsCount: number; MAX_LIST_PROMPTS: number }) =>
      `${p.promptsCount} de ${p.MAX_LIST_PROMPTS} palavras nesta lista`,
    saving: "A guardar…",
    saveList: "Guardar lista",
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "palavra", other: "palavras" }),
    visibleOfTotal: (p: { visible: number; total: number }) =>
      `${p.visible} de ${p.total}`,
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
    inAGame: "Num jogo",
    inTheLobby: "No átrio",
  },

  pictureCropDialog: {
    fileNotAPicture: "Não foi possível ler esse ficheiro como imagem.",
    couldNotSetThatPicturePlease: "Não foi possível definir essa imagem. Tenta de novo.",
    frameYourPicture: "Enquadra a tua imagem",
    dragMoveZoomGetCloserCircle: "Arrasta para a moveres e usa o zoom para te aproximares. O círculo é o que toda a gente vê.",
    pictureFramedArrowKeysMovePlus: "A imagem, enquadrada. As setas movem-na; mais e menos fazem zoom.",
    zoom: "Zoom",
    cancel: "Cancelar",
    uploading: "A carregar…",
    usePicture: "Usar imagem",
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
    voteAfkOrKickOr: "Votar ausente ou expulsão, ou denunciar",
    reportThisPlayer: "Denunciar este jogador",
    undoVote: "Anular voto",
    vote: "Votar",
    voteKindAfk: "Ausente",
    voteKindKick: "Expulsão",
    undoVoteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Anular voto de ${p.kind} em ${p.nickname}, ${p.count} de ${p.required}`,
    voteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Votar ${p.kind} em ${p.nickname}, ${p.count} de ${p.required}`,
    votesFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Votos de ${p.kind} em ${p.nickname}, ${p.count} de ${p.required}`,
    votesForIncludingYours: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Votos de ${p.kind} em ${p.nickname}, ${p.count} de ${p.required}, incluindo o teu`,
    guestName: (p: { nickname: string }) =>
      `${p.nickname} (convidado)`,
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
    notKept: "não guardado",
    nothingDrawn: "nada desenhado",
    onlyThePlayersInThis: "Só os jogadores deste jogo podem ver as suas vezes.",
    couldNotLoadTheTurns: "Não foi possível carregar as vezes deste jogo.",
    cutShort: "interrompido",
    noAttempt: "sem tentativa",
    joinedLate: "entrou tarde",
    notEligibleEligibilityReason: (p: { eligibilityReason: string }) =>
      `não conta (${p.eligibilityReason})`,
    unknownPlayer: "Jogador desconhecido",
    backToLobby: "Voltar ao átrio",
    guestDisplayNameNotSaved: "Convidado — nome a mostrar não guardado",
    registeredPlayer: "Jogador registado",
    noFinishedGamesYetPlay: "Ainda não há jogos terminados. Joga um e ele aparece aqui.",
    noGamesToShowGames: "Não há jogos para mostrar. Os jogos de salas privadas só aparecem a quem esteve neles.",
    loadHistoryPageSizeMore: (p: { HISTORY_PAGE_SIZE: number }) =>
      `Carregar mais ${p.HISTORY_PAGE_SIZE}`,
    correctWithPoints: (p: { points: number }) =>
      `certo, ${p.points}`,
    wrongCount: (p: { count: number }) =>
      counted(p.count, { one: "erro", other: "erros" }),
    joinedOn: (p: { date: string }) =>
      `aderiu a ${p.date}`,
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
    inappropriateContent: "Conteúdo impróprio",
    hatefulOrAbusiveContent: "Conteúdo de ódio ou abusivo",
    sexualContent: "Conteúdo sexual",
    violence: "Violência",
    spam: "Spam",
    other: "Outro",
    sending: "A enviar…",
    sendReport: "Enviar denúncia",
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
    selectThePrompt: "escolher a palavra",
    choosing: "A escolher…",
    buyTheHint: "comprar a pista",
    buyTheLetterHint: "comprar a pista de letra",
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
    namePromptCountPrompts: (p: { name: string; promptCount: number }) =>
      `${p.name} (${p.promptCount} palavras)`,
    adding: "A adicionar…",
    add: "Adicionar",
    reportSentForModeratorReview: "Denúncia enviada para revisão dos moderadores.",
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
    allTime: "Desde sempre",
    last30Days: "Últimos 30 dias",
    last90Days: "Últimos 90 dias",
    allScoringModes: "Todos os modos de pontuação",
    noScoring: "Sem pontuação",
    defaultScoring: "Pontuação padrão",
    pressureScoring: "Pontuação sob pressão",
    allHintModes: "Todos os modos de pistas",
    noHints: "Sem pistas",
    checkpointHints: "Pistas temporizadas",
    purchasedHints: "Pistas compradas",
    letterWheel: "Roda de letras",
    backToLobby: "Voltar ao átrio",
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
    couldNotReadWhoIs: "Não foi possível ver quem está nesta sala.",
    joining: "A entrar…",
    join: "Entrar",
    spectate: "Assistir",
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
    inappropriateName: "Nome impróprio",
    inappropriatePicture: "Imagem imprópria",
    reportSent: "Denúncia enviada",
    reportDisplayName: (p: { displayName: string }) =>
      `Denunciar ${p.displayName}`,
    thePictureOnTheAccount: "A imagem da conta é anexada tal como está agora.",
    theNameOnTheAccount: "O nome da conta é anexado tal como está agora.",
    sending: "A enviar…",
    sendReport: "Enviar denúncia",
    close: "Fechar",
    cancel: "Cancelar",
  },

  reportedDrawing: {
    thisDrawingCouldNotBeDecoded: "Não foi possível descodificar este desenho.",
    drawingCouldNotBeLoaded: "Não foi possível carregar o desenho.",
    loadingTheDrawing: "A carregar o desenho…",
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
    harassmentOrAbuse: "Assédio ou abuso",
    spam: "Spam",
    inappropriateName: "Nome impróprio",
    reportSent: "Denúncia enviada",
    reportDisplayName: (p: { displayName: string }) =>
      `Denunciar ${p.displayName}`,
    sending: "A enviar…",
    sendReport: "Enviar denúncia",
    close: "Fechar",
    cancel: "Cancelar",
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
    sentWithTheirDrawingAnd: (p: { messages: string }) =>
      `Enviada, com o desenho e ${p.messages} em anexo.`,
    sentWithTheirDrawingAttached: "Enviada, com o desenho em anexo.",
    sentWithMessagesAttached: (p: { messages: string }) =>
      `Enviada, com ${p.messages} em anexo.`,
    sentTheyHadSaidNothing: "Enviada. Essa pessoa não tinha dito nada nesta sala, por isso não há mensagens em anexo.",
    baseTheTurnHadEnded: (p: { base: string }) =>
      `${p.base} A vez já tinha terminado, por isso não foi possível anexar o desenho.`,
    harassmentOrAbuse: "Assédio ou abuso",
    offensiveDrawing: "Desenho ofensivo",
    inappropriateName: "Nome impróprio",
    cheating: "Batota",
    spam: "Spam",
    inappropriatePicture: "Imagem imprópria",
    sendThatReport: "enviar essa denúncia",
    reportNickname: (p: { nickname: string }) =>
      `Denunciar ${p.nickname}`,
    reportSent: "Denúncia enviada",
    sending: "A enviar…",
    sendReport: "Enviar denúncia",
    cancel: "Cancelar",
    close: "Fechar",
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
    proposerNicknameProposedRestartingRemainingS: (p: { proposerNickname: string; remaining: number }) =>
      `${p.proposerNickname} propôs recomeçar · ${p.remaining} s`,
    theCurrentGameIsRestarting: "O jogo está a recomeçar agora.",
    yesYesNoNoPending: (p: { yes: number; no: number; pending: number; requiredVotes: number }) =>
      `${p.yes} sim · ${p.no} não · ${p.pending} por votar · ${p.requiredVotes} necessários`,
  },

  roleChangeNotice: {
    youHaveBeenSignedOutEvery: "A tua sessão foi terminada em todos os dispositivos para que a mudança\n            tenha efeito. Inicia sessão outra vez para continuares.",
    setUpNow: "Configurar agora",
    later: "Mais tarde",
    oneMoment: "Um momento…",
    signInAgain: "Iniciar sessão de novo",
    understood: "Percebido",
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
    yourGuessTrimmedDidNot: (p: { trimmed: string }) =>
      `O teu palpite «${p.trimmed}» não chegou ao servidor. Envia-o de novo.`,
    sendTheMessage: "enviar a mensagem",
    chatWhileYouWait: "Conversa enquanto esperas",
    gameChat: "Chat do jogo",
    guessAndChat: "Adivinha e conversa",
    guessesAndChat: "Palpites e chat",
    roomChat: "Chat da sala",
    sayHelloBeforeTheGame: "Diz olá antes de o jogo começar.",
    noMessagesYet: "Ainda não há mensagens.",
    typeYourGuess: "Escreve o teu palpite...",
    typeAMessage: "Escreve uma mensagem...",
  },

  roomEntryState: {
    thisRoomNoLongerAvailable: "Esta sala já não está disponível",
    couldNotJoinThisRoom: "Não foi possível entrar nesta sala",
    thatNameIsReservedPlease: "Esse nome está reservado. Escolhe outro.",
    thisRoomHasEndedAsk: "Esta sala terminou. Pede um convite novo ao anfitrião.",
    loadThisRoom: "carregar esta sala",
    enterANicknameToContinue: "Escreve uma alcunha para continuar.",
    thePlayerSlotsJustFilled: "Os lugares de jogador acabaram de encher, mas ainda podes assistir.",
    joinAsASpectator: "entrar como espectador",
    joinThisRoom: "entrar nesta sala",
    nicknameRule: "Usa de 3 a 16 caracteres: letras, números, hífenes ou sublinhados. Sem espaços.",
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
    iMBack: "Voltei",
    goAwayForABit: "Ausentar-me um bocado",
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
    joinAsAPlayer: "entrar como jogador",
    aPlayerSlotIsAvailable: "Há um lugar de jogador livre.",
    playerSlotsAreCurrentlyFull: "Os lugares de jogador estão cheios.",
    joining: "A entrar…",
    joinAsPlayer: "Entrar como jogador",
  },

  roomSettingsEditor: {
    couldNotLoadRoomRules: "Não foi possível carregar as regras da sala",
    roomRefusedThoseSettings: "A sala recusou essas definições.",
    hostSettings: "Definições do anfitrião",
    editRoomRules: "Editar as regras da sala",
    loadingSettings: "A carregar definições…",
    cancel: "Cancelar",
    loadRoomRules: "carregar as regras da sala",
    saveRoomRules: "guardar as regras da sala",
    saving: "A guardar…",
    saveSettings: "Guardar definições",
    saved: "Guardado",
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
    allColors: "Todas as cores",
    noScoring: "Sem pontuação",
    listedInTheLobbyAnyone: "Aparece no átrio — qualquer pessoa pode entrar.",
    joinableOnlyWithTheCode: "Só se entra com o código ou a ligação de convite.",
    customCount: (p: { count: number }) =>
      counted(p.count, { one: "própria", other: "próprias" }),
  },

  rulesPage: {
    sketchy: "Sketchy",
    theRules: "As regras",
    thisPage: "Nesta página",
    forExample: "Por exemplo",
    backToLobby: "Voltar ao átrio",
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
    revoking: "A revogar…",
    revoke: "Revogar",
    loggingOut: "A terminar sessão…",
    logOutEverywhere: "Terminar sessão em todo o lado",
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
    account: "Conta",
    appearance: "Aspeto",
    soundEffects2: "Som e efeitos",
    shortcuts: "Atalhos",
    red: "Vermelho",
    orange: "Laranja",
    yellow: "Amarelo",
    lime: "Lima",
    green: "Verde",
    teal: "Verde-azulado",
    sky: "Azul-céu",
    blue: "Azul",
    indigo: "Índigo",
    purple: "Roxo",
    magenta: "Magenta",
    pink: "Cor-de-rosa",
    brown: "Castanho",
    light: "Claro",
    dark: "Escuro",
    system: "Sistema",
    crosshair: "Mira",
    outline: "Contorno",
    space: "Espaço",
    hideTheFullAddress: "Ocultar o endereço completo",
    showTheFullAddress: "Mostrar o endereço completo",
    hide: "Ocultar",
    showInFull: "Mostrar por inteiro",
    verified: "Verificado",
    notVerified: "Não verificado",
    saving: "A guardar…",
    save: "Guardar",
    aGuestHasNothingTo: "Um convidado não tem nada para recuperar: não há palavra-passe para esquecer.",
    withoutOneThereIsNo: "Sem ele não há forma de voltar a esta conta se a palavra-passe for esquecida.",
    addAnEmail: "Adicionar um e-mail",
    guestsHaveNoPassword: "Os convidados não têm palavra-passe.",
    changingItSignsEveryOther: "Mudá-la termina a sessão em todos os outros dispositivos.",
    setThisUpAndThe: (p: { pendingRole: string }) =>
      `Configura isto e o papel de ${p.pendingRole} que te foi oferecido entra em vigor.`,
    anAuthenticatorAppSCode: "Um código de uma aplicação de autenticação, além da tua palavra-passe. Moderadores e administradores têm de a ter.",
    setUp: "Configurar",
    thisBrowserIsTheOnly: "Este navegador é o único sítio onde existes.",
    everyBrowserStillHoldingA: "Todos os navegadores que ainda têm uma sessão, e uma forma de terminar qualquer uma.",
    worksForAGuestToo: "Também funciona para convidados: os jogos que jogaste são teus.",
    everyGameListAndSetting: "Todos os jogos, listas e definições que o Sketchy guarda sobre ti, num único ficheiro JSON.",
    deleteThisGuest: "Eliminar este convidado",
    deleteYourAccount: "Eliminar a tua conta",
    removesTheNameThePoints: "Remove o nome, os pontos e o histórico associados a este navegador.",
    gamesYouPlayedStayIn: "Os jogos que jogaste ficam no histórico dos outros jogadores, sem o teu nome.",
    clickToRebindTheSecond: "Clica para reatribuir a segunda tecla",
    clickToRebind: "Clica para reatribuir",
    pressKey: "Carrega numa tecla…",
    key: "+ tecla",
    none: "Nenhuma",
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
    waitingForYourDevice: "À espera do teu dispositivo…",
    useYourPasskey: "Usar a tua passkey",
    useYourAuthenticatorApp: "Usar a tua aplicação de autenticação",
    useARecoveryCode: "Usar um código de recuperação",
    checking: "A verificar…",
    confirm: "Confirmar",
  },

  suspensionNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `O teu desenho de ${p.prompt}, tal como foi denunciado`,
    recordedAs: "Registado como {category}",
    yourAccountSuspended: "A tua conta está suspensa",
    youWereAskedDraw: "Era a tua vez de desenhar",
    theMessageThisWasAbout: "A mensagem em causa:",
    theMessagesThisWasAbout: "As mensagens em causa:",
    theDrawingThisWasAbout: "O desenho em causa:",
    theDrawingsThisWasAbout: "Os desenhos em causa:",
    signingOut: "A terminar sessão…",
    signOut: "Terminar sessão",
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
    brush: "Pincel",
    fill: "Preencher",
    eraser: "Borracha",
    rectangle: "Retângulo",
    triangle: "Triângulo",
    ellipse: "Elipse",
    fillIsUnavailableForThe: "O preenchimento não está disponível no resto desta vez",
    drawingByHandIsUnavailable: "Desenhar à mão livre não está disponível no resto desta vez",
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
    turnResults: "Resultados da vez",
    turnComplete: "Vez terminada",
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
    couldNotStartSettingThis: "Não foi possível começar a configuração.",
    thatCodeWasNotAccepted: "Esse código não foi aceite.",
    couldNotAddThatPasskey: "Não foi possível adicionar essa passkey.",
    couldNotRemoveThatPasskey: "Não foi possível remover essa passkey.",
    couldNotConfirmIt: "Não foi possível confirmar.",
    couldNotReplaceYourRecovery: "Não foi possível substituir os teus códigos de recuperação.",
    couldNotTurnThisOff: "Não foi possível desativar.",
    waitingForYourDevice: "À espera do teu dispositivo…",
    setUpAPasskey: "Configurar uma passkey",
    noPasskeyOnThisDevice: "Sem passkey neste dispositivo? ",
    thisBrowserCannotMakeA: "Este navegador não consegue criar uma passkey. ",
    checking: "A verificar…",
    confirm: "Confirmar",
  },

  useFriendArrivalNotices: {
    wantsToBeFriends: (p: { name: string }) => `${p.name} quer ser teu amigo.`,
    acceptedYourRequest: (p: { name: string }) => `${p.name} aceitou o teu pedido de amizade.`,
    severalAccepted: (p: { count: number }) =>
      `${counted(p.count, { one: "pessoa aceitou", other: "pessoas aceitaram" })} os teus pedidos de amizade.`,
    accept: "Aceitar",
    open: "Abrir",
    manyArrived: (p: { name: string; others: number }) =>
      `${p.name} e ${counted(p.others, { one: "outra pessoa", other: "outras pessoas" })} querem ser teus amigos.`,
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
    spectatorsAfkAndDisconnectedPlayers: "Espectadores, ausentes e jogadores desligados não contam para os dois jogadores ativos de que um jogo precisa.",
    joinMySketchyRoomCode: (p: { code: string }) =>
      `Entra na minha sala do Sketchy: ${p.code}`,
    inviteLink: "Ligação de convite",
    customPromptsOnlyCustomPromptCount: (p: { customPromptCount: number }) =>
      `Só palavras próprias (${p.customPromptCount})`,
    customPromptCountCustomPromptsCuratedLists: (p: { customPromptCount: number }) =>
      `${p.customPromptCount} palavras próprias + listas selecionadas`,
    promptListSlugsCountCuratedPromptLists: (p: { promptListSlugsCount: number }) =>
      `${p.promptListSlugsCount} listas de palavras selecionadas`,
    noScoring: "Sem pontuação",
    spectatorsSeeThePrompt: "Os espectadores veem a palavra",
    publicRoom: "Sala pública",
    privateRoom: "Sala privada",
    betweenGames: "entre jogos",
    waitingForPlayers: "à espera de jogadores",
    roomCode: "Código da sala",
    starting: "A começar…",
    rematch: "Desforra",
    startGame: "Começar jogo",
    waitingForAHost: "À espera de um anfitrião",
  },

  warningNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `O teu desenho de ${p.prompt}, tal como foi denunciado`,
    recordedAs: "Registado como {category}",
    whatAWarningMeans:
      "Uma denúncia sobre o teu comportamento foi analisada, e este é o resultado. Não há nada restringido, mas outra denúncia pode levar à suspensão da tua conta.",
    youWereAskedDraw: "Era a tua vez de desenhar",
    yourPictureWasRemoved: "A tua imagem foi removida",
    aModeratorWarning: "Um aviso da moderação",
    aReportAboutYourPicture: "Uma denúncia sobre a tua imagem foi analisada, e este é o resultado. Nada mais na tua conta é afetado.",
    theMessageThisWasAbout: "A mensagem em causa:",
    theMessagesThisWasAbout: "As mensagens em causa:",
    theDrawingThisWasAbout: "O desenho em causa:",
    theDrawingsThisWasAbout: "Os desenhos em causa:",
    oneMoment: "Um momento…",
    understood: "Percebido",
  },
  connectionStatusBanner: {
    youReDisconnectedCheckYour: "Estás desligado. Verifica a tua ligação; o Sketchy volta a ligar-se sozinho.",
    couldnTReconnectToYour: "Não foi possível voltar a ligar à tua sala. Recarrega a página para tentar de novo.",
    connectionLostReconnecting: "Ligação perdida — a religar…",
  },
  accountData: {
    queued: "Em fila",
    preparing: "A preparar…",
    ready: "Pronto",
    tooLargeToPrepareHere: "Grande demais para preparar aqui",
    couldNotPrepare: "Não foi possível preparar",
    yourDataIsLargerThan: "Os teus dados excedem o que este servidor prepara num só documento. Pede ao operador para aumentar o limite.",
    somethingWentWrongWhilePreparing: "Algo correu mal durante a preparação. Podes pedir outra exportação.",
  },
  recoveryCodeFile: {
    sketchyRecoveryCodes: "Códigos de recuperação do Sketchy",
    accountUsername: (p: { username: string }) =>
      `Conta: ${p.username}`,
    createdValue: (p: { value: string }) =>
      `Criado: ${p.value}`,
    eachCodeSignsYouIn: "Cada código inicia a tua sessão uma vez se perderes a tua aplicação de autenticação.",
    keepThisFile: "Guarda este ficheiro onde só tu consigas chegar. Quem tiver estes códigos\ne a tua palavra-passe pode iniciar sessão como tu.",
  },
  avatars: {
    chooseAPngJpegWebP: "Escolhe uma imagem PNG, JPEG, WebP ou GIF.",
    thatPictureIsTooLarge: "Essa imagem é grande demais para ler: no máximo 10 MB.",
    thatFileCouldNotBe: "Não foi possível ler esse ficheiro como imagem.",
    thatPictureIsTooSmall: "Essa imagem é pequena demais para se fazer alguma coisa com ela.",
    thisBrowserCannotResizePictures: "Este navegador não consegue redimensionar imagens.",
    thatPictureIsTooDetailed: "Essa imagem tem demasiado detalhe. Experimenta uma mais simples, ou aproxima uma parte dela.",
  },
  settingsSync: {
    thatChangeAppliesHereBut: "Essa alteração aplica-se aqui, mas não foi possível guardá-la na tua conta. Os teus outros dispositivos não a vão ver.",
  },
  promptStats: {
    hardestFirst: "Mais difíceis primeiro",
    easiestFirst: "Mais fáceis primeiro",
    mostPicked: "Mais escolhidas",
    getsGuessed: "É adivinhada",
    usuallyGuessed: "Costuma ser adivinhada",
    evenOdds: "Meio por meio",
    oftenMissed: "Falhada muitas vezes",
    rarelyGuessed: "Raramente adivinhada",
    notPlayedEnough: "Pouco jogada",
    allRanked: (p: { count: number }) =>
      `As ${p.count} palavras foram jogadas o suficiente para serem classificadas.`,
    noneRanked: (p: { unrated: number; guessers: number }) =>
      `Nenhuma destas ${p.unrated} palavras teve ainda ${p.guessers} jogadores a adivinhar, por isso nenhuma está classificada. Joguem umas partidas e a dificuldade delas aparece aqui.`,
    someRanked: (p: { rated: number; unrated: number; guessers: number }) =>
      `${p.rated} classificadas. ${plural(p.unrated, { one: `Falta classificar ${p.unrated} palavra`, other: `Faltam classificar ${p.unrated} palavras` })}: menos de ${p.guessers} jogadores as viram.`,
    noMatch: (p: { query: string }) =>
      `Nenhuma palavra corresponde a «${p.query}».`,
    matching: (p: { count: number; query: string }) =>
      `${counted(p.count, { one: "palavra corresponde", other: "palavras correspondem" })} a «${p.query}».`,
  },
  gameHeaderStatus: {
    roundRoundNumberOfTotalRounds: (p: { roundNumber: number; totalRounds: number }) =>
      `Ronda ${p.roundNumber} de ${p.totalRounds}`,
  },
  gameRoomRegions: {
    theNextPlayer: "O próximo jogador",
    drawingCanvasYouAreDrawing: "Tela de desenho. Estás a desenhar.",
    yourTurnToDraw: "É a tua vez de desenhar.",
    canvasSpectating: (p: { drawer: string }) =>
      `Tela de desenho. Estás a ver ${p.drawer}.`,
    canvasSomeoneDrawing: (p: { drawer: string }) =>
      `Tela de desenho. ${p.drawer} está a desenhar.`,
    someoneIsDrawing: (p: { drawer: string }) =>
      `${p.drawer} está a desenhar.`,
    theDrawer: "quem desenha",
    aPlayer: "Alguém",
  },
  useToolbarState: {
    fillIsUnavailableForThe: "O preenchimento não está disponível no resto desta vez.",
    drawingByHandIsUnavailable: "Desenhar à mão livre não está disponível no resto desta vez. As formas continuam a funcionar.",
  },
  timer: {
    n10SecondsRemaining: "Faltam 10 segundos",
    timeIsUp: "Acabou o tempo",
  },
  chatAnnouncements: {
    nicknameGuessedThePrompt: (p: { nickname: string }) =>
      `${p.nickname} adivinhou a palavra.`,
  },
  canvasSnapshot: {
    drawingOfDownloadPrompt: (p: { downloadPrompt: string }) =>
      `Desenho de ${p.downloadPrompt}`,
    savedDrawing: "Desenho guardado",
  },
  roomSetup: {
    default: "Padrão",
    fasterGuessesEarnMore100: "Acertar mais depressa vale mais, de 100 a 300 pontos.",
    pressure: "Pressão",
    pointsDecayEverySecondTwice: "Os pontos descem a cada segundo — duas vezes mais depressa quando alguém acerta.",
    noScoring: "Sem pontuação",
    justDrawAndGuessNo: "Só desenhar e adivinhar. Sem classificação.",
    timedHints: "Pistas temporizadas",
    lettersRevealToEveryoneAt: "As letras revelam-se a todos em momentos fixos.",
    noHints: "Sem pistas",
    blanksOnlyAllTurnLong: "Só espaços em branco, a vez toda.",
    buyLetters: "Comprar letras",
    revealALetterSlotJust: "Revela uma letra só para ti — paga com os pontos dessa vez.",
    wheelOfFortune: "Roda da sorte",
    pickALetterPayIts: "Escolhe uma letra e paga o preço — as vogais custam mais.",
    hiddenPrompt: "Palavra oculta",
    defaultScoring: "Pontuação padrão",
    pressureScoring: "Pontuação sob pressão",
  },
  screenCapture: {
    thisBrowserCouldNotEncode: "Este navegador não conseguiu codificar a captura.",
    theCaptureWasEmpty: "A captura estava vazia.",
    thisBrowserCouldNotRead: "Este navegador não conseguiu ler a captura.",
    thatScreenshotIsTooLarge: "Essa captura é grande demais para enviar.",
  },
  accountRecovery: {
    youCanRecoverThisAccount: (p: { address: string }) =>
      `Podes recuperar esta conta através de ${p.address}.`,
    checkPendingAddressForAConfirmation: (p: { pendingAddress: string }) =>
      `Procura em ${p.pendingAddress} uma ligação de confirmação. Até a seguires, esta conta não tem forma de ser recuperada.`,
    thisServerCannotSendEmail: "Este servidor não consegue enviar e-mails, por isso uma palavra-passe perdida tem de ser reposta por quem o gere.",
    addAnEmailAddressSo: "Adiciona um endereço de e-mail para poderes voltar a entrar se te esqueceres da palavra-passe.",
  },
  friends: {
    aFriend: "Um amigo",
  },
  lobbyPresence: {
    showingShownOfOnlineCount: (p: { shown: number; onlineCount: number }) =>
      `A mostrar ${p.shown} de ${p.onlineCount}`,
    onlineCount: (p: { count: number }) =>
      `${number(p.count)} online`,
  },
  authStore: {
    chooseANameToPlay: "Escolhe um nome com que jogar.",
  },
  passkeys: {
    noPasskeyWasCreated: "Não foi criada nenhuma passkey.",
    noPasskeyWasUsed: "Não foi usada nenhuma passkey.",
  },
  useGameSocketListeners: {
    nicknameJoinedTheRoom: (p: { nickname: string }) =>
      `${p.nickname} entrou na sala`,
    gameStarted: "O jogo começou!",
    drawerNicknameIsChoosingAPrompt: (p: { drawerNickname: string }) =>
      `${p.drawerNickname} está a escolher uma palavra...`,
    thePromptWasPrompt: (p: { prompt: string }) =>
      `A palavra era «${p.prompt}»`,
    gotIt: (p: { nickname: string; time: string | null; points: number | null }) =>
      `${p.nickname} acertou${p.time === null ? "" : ` · ${p.time}`}${p.points === null ? "" : ` (+${p.points})`}`,
    playerReconnected: (p: { nickname: string }) =>
      `${p.nickname} voltou a ligar-se`,
    playerDisconnected: (p: { nickname: string }) =>
      `${p.nickname} desligou-se`,
  },
  settingsStore: {
    brushTool: "Pincel",
    fillTool: "Preencher",
    eraserTool: "Borracha",
    rectangleTool: "Retângulo",
    triangleTool: "Triângulo",
    ellipseTool: "Elipse",
    decreaseBrushSize: "Diminuir o pincel",
    increaseBrushSize: "Aumentar o pincel",
    undoStroke: "Anular traço",
  },
  reactions: {
    loveIt: "Adoro",
    funny: "Engraçado",
    wow: "Uau",
    fire: "Fogo",
    reaction: "Reação",
  },
  drawingRules: {
    brush: "Pincel",
    theBrushAndTheEraser: "O pincel e a borracha.",
    fill: "Preencher",
    theFillTool: "A ferramenta de preenchimento.",
    shapes: "Formas",
    rectangleEllipseAndTriangle: "Retângulo, elipse e triângulo.",
    allColors: "Todas as cores",
    thePaletteAndTheCustom: "A paleta e o seletor de cor livre.",
    paletteOnly: "Só a paleta",
    theBuiltInSwatchesNo: "As amostras incluídas; sem cores livres.",
    colorblindSafe: "Próprias para daltonismo",
    colorsThatStayApartFor: "Cores que continuam distintas para jogadores daltónicos.",
    blackAndWhite: "Preto e branco",
    blackAndWhiteOnly: "Só preto e branco.",
    allTools: "Todas as ferramentas",
    onlyTool: (p: { tool: string }) =>
      `só ${p.tool}`,
    toolList: (p: { rest: string; last: string }) =>
      `${p.rest} e ${p.last}`,
  },
  socket: {
    sketchyIsFullRightNow: "O Sketchy está cheio neste momento. Tenta de novo daqui a uns minutos.",
    connectionLostWhileTryingTo: (p: { action: string }) =>
      `A ligação perdeu-se ao tentar ${p.action}. Tenta de novo.`,
    theRequestToActionTimed: (p: { action: string }) =>
      `O pedido para ${p.action} excedeu o tempo. Tenta de novo.`,
    couldNotActionPleaseTry: (p: { action: string }) =>
      `Não foi possível ${p.action}. Tenta de novo.`,
  },
  bugReports: {
    drawingAndCanvas: "Desenho e tela",
    guessingAndChat: "Palpites e chat",
    roundsScoringAndResults: "Rondas, pontuação e resultados",
    roomsAndLobby: "Salas e átrio",
    promptLists: "Listas de palavras",
    accountAndSettings: "Conta e definições",
    connectionAndSync: "Ligação e sincronização",
    performance: "Desempenho",
    accessibility: "Acessibilidade",
    somethingElse: "Outra coisa",
    blocksPlayICouldNot: "Bloqueia o jogo — não consegui continuar",
    majorHardToPlayAround: "Grave — difícil de contornar",
    minorWorthFixingOneDay: "Pequeno — vale a pena corrigir um dia",
    notInARoom: "Fora de uma sala",
    codeNotInARound: (p: { code: string }) =>
      `${p.code} · fora de ronda`,
    codeRoundRoundOfTotal: (p: { code: string; round: number; total: number }) =>
      `${p.code} · ronda ${p.round} de ${p.total}`,
  },
  suspension: {
    thisSuspensionHasNoEnd: "Esta suspensão não tem data de fim.",
    thisSuspensionHasEndedTry: "Esta suspensão terminou; tenta iniciar sessão de novo.",
    thisSuspensionLastsUntilEnds: (p: { ends: string }) =>
      `Esta suspensão dura até ${p.ends}.`,
  },
  clock: {
    unknown: "Desconhecido",
  },
  protocol: {
    theServerWasUpdated: "O servidor foi atualizado.",
  },
  passwordPolicy: {
    tooShort: (p: { count: number }) =>
      `Uma palavra-passe precisa de pelo menos ${p.count} caracteres.`,
  },
  operatorAccess: {
    administrator: "administrador",
    moderator: "moderador",
    pendingTitle: "O papel de moderador está à tua espera",
    pendingBody: "Um administrador ofereceu-te o papel de moderador. Entra em vigor quando configurares a autenticação de dois fatores: os moderadores iniciam sessão com um código de uma aplicação de autenticação, e o papel começa assim que isso estiver pronto. Os teus outros dispositivos terminam a sessão nesse momento. Nada muda até o configurares, e a oferta fica à tua espera nas Definições se agora não for boa altura.",
    grantedTitle: "Agora és moderador",
    grantedBody: "Um administrador deu-te o papel de moderador. Apareceu uma entrada Moderação no menu da tua conta: é aí que se analisam as denúncias sobre jogadores e palavras. Nada muda na forma como jogas.",
    removedTitle: "Já não és moderador",
    removedBody: "Um administrador retirou o papel de moderador da tua conta. A entrada Moderação desapareceu do teu menu. Nada mais na tua conta ou nos teus jogos é afetado.",
  },
  moderationCategories: {
    harassment: "assédio",
    offensive_drawing: "um desenho ofensivo",
    inappropriate_name: "um nome impróprio",
    cheating: "batota",
    spam: "spam",
    inappropriate_avatar: "uma imagem imprópria",
  },
  roomNotices: {
    kickedByVote: "Foste expulso da sala por votação.",
    roomClosed: "Um administrador fechou esta sala.",
    removedByAdmin: "Um administrador removeu-te.",
    accountDeleted: "A tua conta foi eliminada.",
    accountSuspended: "A tua conta foi suspensa.",
  },
};
