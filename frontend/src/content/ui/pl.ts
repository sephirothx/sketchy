/** Every word the interface says, in Polish.

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
import type { PromptShelf } from "../../lib/promptListTree.ts";
import type { AnnouncementCode } from "../../lib/announcements.ts";
import type { ErrorCode } from "../../types.ts";

const { counted, number, ordinal, plural } = formattersFor("pl", {"other":"."});

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
      return `Hasło do konta musi mieć co najmniej ${counted(count(detail, 12), { one: "znak", few: "znaki", many: "znaków", other: "znaku" })}.`;
    case "too_long":
      return `Hasło do konta może mieć najwyżej ${counted(count(detail, 128), { one: "znak", few: "znaki", many: "znaków", other: "znaku" })}.`;
    case "common":
      return "To hasło należy do najczęściej używanych. Wybierz inne.";
    case "common_repeated":
      return "To popularne hasło, tylko powtórzone. Wybierz inne.";
    case "short_repeated":
      return "To hasło to powtórzony krótki ciąg znaków. Wybierz inne.";
    case "too_few_characters":
      return `To hasło składa się tylko z ${count(detail, 4)} różnych znaków. Wybierz inne.`;
    case "keyboard_walk":
      return "To hasło to głównie ciąg kolejnych klawiszy. Wybierz inne.";
    case "contains_identity":
      return "Hasło do konta nie może zawierać twojej nazwy, twojego adresu e-mail ani nazwy tej strony.";
    case "common_with_digits":
      return "To popularne hasło z dopisanymi cyframi. Wybierz inne.";
    default:
      return "Wybierz inne hasło do konta.";
  }
}

/** *Create an account to …* - one refusal, said about the thing it refused. */
function accountRequired(params: MessageParams): string {
  switch (params.action) {
    case "avatar":
      return "Utwórz konto, aby wybrać zdjęcie.";
    case "prompt_lists":
      return "Utwórz konto, aby zapisywać listy haseł.";
    case "name_color":
      return "Utwórz konto, aby wybrać kolor nazwy.";
    case "password":
      return "Utwórz konto, aby ustawić hasło do konta.";
    case "second_factor":
      return "Utwórz konto, zanim skonfigurujesz weryfikację dwuetapową.";
    case "friends":
      return "Utwórz konto, aby dodawać znajomych.";
    case "stars":
      return "Utwórz konto, aby oznaczać listy haseł gwiazdką.";
    default:
      return "Utwórz konto, aby to zrobić.";
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
      return "trwa aktualizacja serwera";
    case "too_few_players":
      return "zostało mniej niż dwóch aktywnych graczy";
    case "prompt_lists_unavailable":
      return "nie udało się wczytać list haseł";
    case "everybody_left":
      return "wszyscy wyszli, zanim się zaczął";
    default:
      return "nie mógł się już odbyć";
  }
}

type Sentence = string | ((params: MessageParams) => string);

/** Why the server refused, said to the player.

One entry per `ErrorCode`; `Record` makes it exhaustive, so a code the server
adds without a sentence here fails the build rather than the player
(R-I18N-04). */
const REFUSALS: Record<ErrorCode, Sentence> = {
  // Payloads and arguments
  invalid_payload: "Nie udało się odczytać tego żądania.",
  invalid_nickname: "Tej nazwy nie można tu użyć.",
  invalid_name_color: "Wybierz kolor czytelny zarówno na jasnej, jak i na ciemnej liście graczy.",
  invalid_hint: "Ta podpowiedź jest nieprawidłowa.",
  invalid_letter: "Ta litera jest nieprawidłowa.",
  invalid_prompt_lists: "Tych list haseł nie można używać razem.",
  invalid_custom_prompts: "Nie udało się odczytać tych własnych haseł.",
  mixed_room_list_unsupported: "W pokojach mieszanych można używać tylko list dostępnych we wszystkich językach lub oznaczonych jako „Dowolny język”.",
  too_many_player_prompt_lists: "Pokój może korzystać z najwyżej 20 list stworzonych przez graczy.",
  mixed_room_custom_prompts: "W pokojach mieszanych nie można używać własnych haseł: każdy gracz musi dostać hasło w swoim języku.",
  max_players_below_seated: (params) =>
  `Limit graczy nie może być niższy niż liczba graczy, którzy już są w pokoju (${count(params.seated, 2)}).`,
  empty_message: "Najpierw coś wpisz.",

  // Rate and capacity
  too_fast: "Robisz to zbyt szybko. Spróbuj ponownie za chwilę.",
  seat_changing_too_fast: "Twoje miejsce w tym pokoju zbyt często przechodziło między kartami lub połączeniami. Spróbuj ponownie za minutę.",
  joining_too_fast: "Zbyt szybko dołączasz do pokoi. Spróbuj ponownie za minutę.",
  room_quota: "Masz już otwartych tyle pokoi, ile można mieć jednocześnie.",
  room_full: "Ten pokój jest pełny.",
  spectators_full: "Ten pokój nie przyjmuje już widzów.",
  player_slots_full: "Wszystkie miejsca dla graczy są zajęte.",

  // Server and account state
  server_draining: "Sketchy uruchamia się ponownie. Spróbuj ponownie za chwilę.",
  server_paused: "Sketchy nie przyjmuje teraz nowych pokoi.",
  server_busy: "Serwer Sketchy jest teraz zajęty. Spróbuj ponownie za chwilę.",
  database_busy: "Sketchy ma problem z połączeniem z bazą danych. Spróbuj ponownie.",
  account_ended: "To konto nie jest już aktywne.",
  account_required: accountRequired,
  identity_unavailable: "Nie udało się potwierdzić, kim jesteś. Odśwież stronę i spróbuj ponownie.",

  // Rooms
  not_in_room: "Nie jesteś w tym pokoju.",
  room_not_found: "Nie znaleziono pokoju.",
  room_ended: "Ten pokój został zamknięty.",
  could_not_create_room: "Nie udało się utworzyć pokoju.",
  no_session_to_resume: "Nie jesteś już w tym pokoju. Dołącz do niego ponownie.",
  host_only: "Tylko gospodarz może to zrobić.",
  players_only: "Tylko gracze mogą to zrobić.",
  waiting_room_only: "To jest dostępne tylko w poczekalni.",
  kicked_from_room: "Wyrzucono cię z tego pokoju i nie możesz do niego wrócić.",
  already_a_player: "Już jesteś graczem.",
  registered_name_fixed: "Zarejestrowani gracze grają pod swoją nazwą użytkownika.",
  name_taken_by_account: "Ta nazwa należy do zarejestrowanego gracza.",
  name_in_use: "Ktoś online już gra pod tą nazwą. Wybierz inną.",
  guests_cannot_choose_color: "Utwórz konto, aby wybrać kolor nazwy.",
  suggestion_inactive: "Ta propozycja nie jest już aktywna.",
  drawing_not_found: "Nie znaleziono rysunku.",
  drawing_not_kept: "Ten rysunek nie został zachowany.",

  // Games and turns
  not_in_game: "Nie bierzesz udziału w trwającej grze.",
  game_in_progress: "Gra już trwa.",
  game_starting: "Gra wciąż się rozpoczyna.",
  need_two_players: "Do rozpoczęcia potrzeba dwóch aktywnych graczy.",
  room_not_startable: "W tym pokoju nie można teraz rozpocząć gry.",
  prompt_not_ready: "Gra nie jest jeszcze gotowa na hasło.",
  prompt_unavailable: "To hasło nie jest już dostępne.",
  hints_disabled: "Podpowiedzi są wyłączone w tym pokoju.",
  hint_spend_limit: "Wykorzystano już limit punktów na podpowiedzi w tej turze.",
  hint_unavailable: "Ta podpowiedź jest niedostępna.",

  // Canvas
  drawer_only: "Tylko rysujący może to zrobić.",
  canvas_stale_generation: "Płótno już się zmieniło. Trwa synchronizacja.",
  canvas_sequence_committed: "To zostało już narysowane.",
  canvas_out_of_sequence: "Ruchy rysowania dotarły w złej kolejności. Trwa synchronizacja.",
  canvas_out_of_sync: "Płótno jest niezsynchronizowane. Trwa synchronizacja.",
  nothing_to_undo: "Nie ma czego cofnąć.",

  // Votes and restarts
  spectators_cannot_vote: "Widzowie nie mogą głosować.",
  spectators_cannot_be_targets: "Głosowanie nie może dotyczyć widza.",
  invalid_vote_target: "Nie możesz głosować w sprawie tego gracza.",
  not_eligible: "Tylko aktywni gracze mogą zaproponować restart.",
  restart_vote_active: "Głosowanie za restartem już trwa.",
  restart_vote_cooldown: "Przed chwilą głosowano nad restartem. Zaczekaj chwilę, zanim zaproponujesz kolejny.",
  no_restart_vote: "Nie trwa żadne głosowanie za restartem.",
  restart_vote_closed: "To głosowanie za restartem już się zakończyło.",

  // Reactions
  spectators_cannot_react: "Widzowie nie mogą reagować na rysunki.",
  guests_cannot_react: "Utwórz konto, aby reagować na rysunki.",
  reaction_not_visible: "Nie możesz zareagować na rysunek, którego nie widzisz.",
  own_drawing: "Nie możesz reagować na własny rysunek.",
  game_still_saving: "Ta gra jest jeszcze zapisywana. Spróbuj ponownie za chwilę.",
  game_not_recorded: "Ta gra nie została zapisana.",
  reaction_not_accepted: "Nie udało się wysłać tej reakcji.",
  spectators_cannot_share: "Widzowie nie mogą udostępniać rysunków.",
  share_not_visible: "Tego rysunku nie można już stąd udostępnić.",
  share_not_allowed: "Tego rysunku nie można udostępnić.",
  share_withdrawn: "Osoba, która go narysowała, zdjęła go z galerii.",
  share_not_accepted: "Nie udało się udostępnić tego rysunku. Spróbuj ponownie za chwilę.",

  // Friends
  friends_unavailable: "Znajomi są teraz niedostępni.",
  friend_refused: "Nie udało się obsłużyć tego zaproszenia do znajomych.",
  friend_not_in_game: "Twój znajomy nie gra teraz w żadnej grze.",
  friend_in_several_games: "Ten znajomy jest w więcej niż jednej grze. Poproś go o zaproszenie.",
  not_friends: "Możesz dołączyć tylko do gry znajomego.",
  friends_only_uninvited: "Bez zaproszenia do tej gry mogą dołączyć tylko znajomi gospodarza. Poproś o zaproszenie.",
  invite_expired: "To zaproszenie wygasło.",

  // Moderation, from the reporter's side
  reporting_unavailable: "Zgłaszanie jest niedostępne na tym serwerze.",
  no_such_player: "Nie znaleziono gracza.",
  cannot_report: "Tego gracza nie można zgłosić.",
  already_reported: "To zgłoszenie już zostało wysłane, a moderator jeszcze go nie sprawdził.",

  // Lobby chat
  name_required: "Wybierz nazwę, zanim cokolwiek napiszesz w lobby.",
  not_watching_lobby: "Nie obserwujesz już lobby.",

  // Versioning
  protocol_mismatch: "Ta karta używa starszej wersji Sketchy. Odśwież stronę, aby kontynuować.",

  // Sessions and accounts
  sign_in_required: "Najpierw się zaloguj.",
  credentials_incorrect: "Nieprawidłowa nazwa użytkownika lub hasło do konta.",
  password_incorrect: "Nieprawidłowe hasło do konta.",
  account_suspended: "To konto jest zawieszone.",
  already_signed_in: "Ta przeglądarka jest już zalogowana na konto.",
  username_taken: "Ta nazwa użytkownika jest zajęta.",
  invalid_username: "Tej nazwy użytkownika nie można użyć.",
  weak_password: weakPassword,
  password_change_failed: "Nie udało się zmienić hasła do konta.",
  session_not_found: "To urządzenie nie jest już zalogowane.",
  session_replaced: "Logowanie w tej przeglądarce zmieniło się od wczytania tej strony. Odśwież ją i spróbuj ponownie.",
  guest_progress_unlinked: "Nie udało się połączyć postępów gościa z tym kontem.",
  not_taking_visitors: "Sketchy nie przyjmuje teraz nowych odwiedzających. Spróbuj ponownie później.",
  account_delete_refused: "Nie udało się teraz usunąć konta. Spróbuj ponownie.",
  password_required_to_delete: "Aby usunąć konto, wpisz hasło do konta.",

  // Second factor and passkeys
  second_factor_required: "Wpisz kod z aplikacji uwierzytelniającej.",
  second_factor_passkey_only: "Zaloguj się kluczem dostępu.",
  second_factor_not_enrolled:
  "To konto wymaga weryfikacji dwuetapowej przed zalogowaniem. Poproś administratora o pomoc w jej skonfigurowaniu.",
  second_factor_not_set_up: "Weryfikacja dwuetapowa nie jest skonfigurowana.",
  second_factor_code_wrong: "Ten kod jest nieprawidłowy.",
  second_factor_throttled: "Zbyt wiele błędnych kodów. Spróbuj ponownie później.",
  step_up_required: "Zanim to zrobisz, potwierdź, że to ty.",
  passkey_sign_in_required: "Zaloguj się kluczem dostępu.",
  passkey_not_registered: "Ten klucz dostępu nie jest tu zarejestrowany.",
  passkey_not_found: "Nie znaleziono klucza dostępu.",
  passkey_refused:
  "Klucze dostępu są przeznaczone dla kont moderatorów i administratorów. Jeśli kiedyś otrzymasz taką rolę, poprosimy cię o skonfigurowanie klucza.",
  last_factor: "To jedyny sposób, w jaki możesz potwierdzić, że to ty. Dodaj inny, zanim usuniesz ten.",
  second_factor_required_for_role: "Rola tego konta wymaga weryfikacji dwuetapowej.",
  second_factor_not_proved:
  "Nie potwierdzono, że ta aplikacja uwierzytelniająca należy do ciebie. Użyj klucza dostępu albo potwierdź ją hasłem do konta w Ustawieniach.",

  // Email, verification and recovery
  invalid_email: "To nie wygląda na adres e-mail.",
  email_in_use: "Ten adres jest już używany.",
  email_change_refused: "Tego adresu nie można dodać do tego konta.",
  verification_link_invalid: "Ten link potwierdzający wygasł lub został już użyty.",
  reset_link_invalid: "Ten link do resetowania hasła wygasł lub został już użyty.",

  // Account data export
  export_not_found: "Nie znaleziono eksportu.",
  export_expired: "Eksport wygasł.",
  export_not_ready: "Eksport nie jest jeszcze gotowy.",
  export_unreadable: "Nie udało się odczytać pliku eksportu. Zleć nowy eksport.",
  export_not_yet_allowed: "Eksport był niedawno zlecany. Spróbuj ponownie później.",
  export_refused: "Nie udało się rozpocząć tego eksportu. Spróbuj ponownie.",

  // Rate limits reached over HTTP
  too_many_attempts: "Zbyt wiele prób. Spróbuj ponownie później.",
  too_many_requests: "Zbyt wiele żądań. Spróbuj ponownie później.",
  too_many_reports: "Zbyt wiele zgłoszeń. Spróbuj ponownie później.",
  too_many_bug_reports: "Zbyt wiele zgłoszeń błędów. Spróbuj ponownie później.",
  too_many_pictures: "Zbyt wiele zdjęć. Spróbuj ponownie później.",

  // Pictures
  unsupported_picture_type: "To nie jest obraz WebP, PNG ani JPEG.",
  picture_not_found: "Nie znaleziono zdjęcia.",
  picture_refused: "Tego zdjęcia nie można tu użyć.",

  // Bug reports
  screenshot_unreadable: "Nie udało się odczytać zrzutu ekranu.",
  screenshot_too_large: (params) =>
  `Ten zrzut ekranu jest za duży. Limit to ${megabytes(params.limitBytes, "2 MB")}.`,
  screenshot_unsupported_type: "Zrzut ekranu musi być obrazem PNG lub WebP.",
  bug_report_context_too_large: "To zgłoszenie zawiera zbyt dużo danych kontekstowych.",

  // Friends, over HTTP
  friends_throttled: "Wysyłasz zbyt wiele zaproszeń do znajomych. Spróbuj ponownie później.",
  that_is_you: "To ty.",

  // Profiles and history
  no_such_game: "Nie znaleziono gry.",
  no_such_drawing: "Nie znaleziono rysunku.",
  drawing_unreadable: "Nie udało się odczytać tego rysunku.",
  pinned_drawings_full: "Nie możesz przypiąć więcej rysunków. Najpierw odepnij któryś w swoim profilu.",

  // Prompt lists
  prompt_list_not_found: "Nie znaleziono listy haseł.",
  prompt_list_conflict: "Ktoś inny zmienił tę listę. Wczytaj ją ponownie i spróbuj jeszcze raz.",
  prompt_list_invalid: "Nie udało się zapisać tej listy haseł.",
  prompt_list_forbidden: "Nie możesz zmieniać tej listy haseł, bo nie należy do ciebie.",
  prompt_list_allowance_reached: (params: Record<string, unknown>) => {
    const max = typeof params.max === "number" ? params.max : 25;
    return `Masz już ${max} ${plural(max, { one: "listę", few: "listy", many: "list", other: "listy" })} haseł – to maksimum dla jednego konta. Usuń którąś, aby zrobić miejsce.`;
  },
  email_verification_required: (params: Record<string, unknown>) => {
    switch (params.action) {
      case "publish":
        return "Potwierdź adres e-mail, zanim opublikujesz listę.";
      case "star":
        return "Potwierdź adres e-mail, zanim oznaczysz listę gwiazdką.";
      default:
        return "Potwierdź adres e-mail, aby to zrobić.";
    }
  },
  warning_unread: (params: Record<string, unknown>) => {
    switch (params.action) {
      case "publish":
        return "Przeczytaj ostrzeżenie od moderatora, zanim opublikujesz listę.";
      case "star":
        return "Przeczytaj ostrzeżenie od moderatora, zanim oznaczysz listę gwiazdką.";
      case "play":
        return "Przeczytaj ostrzeżenie od moderatora, zanim dołączysz do gry.";
      default:
        return "Najpierw przeczytaj ostrzeżenie od moderatora.";
    }
  },
  prompt_list_hidden: "Ta lista jest ukryta, więc nie można jej opublikować. Najpierw musi ją sprawdzić moderator.",
  unknown_prompt_tag: (params: Record<string, unknown>) => {
    const tag = String(params.tag ?? "");
    return `„${tag}” nie należy do tagów, które może mieć lista.`;
  },
  unknown_sort: "Nie można sortować według tego kryterium.",
  timezone_required: "Podaj strefę czasową razem z tą datą.",
  range_reversed: "Początek zakresu musi poprzedzać jego koniec.",

  // Room presets
  room_preset_not_found: "Nie znaleziono szablonu pokoju.",
  room_preset_conflict: "Masz już szablon o tej nazwie.",
  room_preset_unavailable: "Tego szablonu nie można teraz użyć.",
  room_preset_forbidden: "Ten szablon nie należy do ciebie.",

  // Blocks
  cannot_block_yourself: "Nie możesz zablokować siebie.",
  block_list_full: (params) =>
  `Twoja lista zablokowanych jest pełna${
    typeof params.limit === "number" ? ` (limit: ${params.limit})` : ""
  }. Najpierw kogoś odblokuj.`,

  // Settings
  setting_refused: "Nie udało się zapisać tego ustawienia.",

  // Role notices
  no_such_notice: "Nie znaleziono powiadomienia.",

  // Reporting, from the reporter's side
  cannot_report_yourself: "Nie możesz zgłosić siebie.",
  cannot_copy_own_prompt_list: "Ta lista już należy do ciebie. Zamiast tego zduplikuj ją w sekcji „Moje listy haseł”.",
  cannot_duplicate_prompt_list: (params: Record<string, unknown>) =>
    params.reason === "copy"
      ? "Listy skopiowanej od innej osoby nie można zduplikować – dzięki temu zachowuje informację o autorze."
      : "Listy, którą moderator sprawdza lub ukrył, nie można zduplikować.",
  cannot_report_own_prompt_list: "Nie możesz zgłosić własnej listy haseł.",
  no_reportable_prompt_list: "Nie znaleziono listy haseł.",
  prompt_not_in_list: "To hasło nie należy do tej listy.",
  no_picture_to_report: "Ten gracz nie ma zdjęcia, które można by zgłosić.",
  no_such_game_context: "Nie znaleziono gry.",
  no_such_turn_context: "Nie znaleziono tury.",
  turn_not_in_game: "Ta tura nie należy do tej gry.",
  evidence_unavailable: "Co najmniej jedna z wybranych wiadomości jest niedostępna.",
  evidence_mixed_scopes: "W jednym zgłoszeniu nie można łączyć wiadomości z lobby i z pokoju.",
  evidence_several_rooms: "Wybrane wiadomości muszą pochodzić z jednego pokoju.",
  evidence_not_theirs: "Można dołączyć tylko wiadomości wysłane przez zgłaszanego gracza.",
  evidence_not_received: "Możesz wybrać tylko wiadomości, które do ciebie dotarły.",
  evidence_not_in_game: "Wybrana wiadomość nie należy do tej gry.",
  evidence_not_in_turn: "Wybrana wiadomość nie należy do tej tury.",
  no_such_warning: "Nie znaleziono ostrzeżenia.",
  no_drawing: "Nie znaleziono rysunku.",};

/** What the room says about itself. One entry per `AnnouncementCode`. */
const ANNOUNCEMENTS: Record<AnnouncementCode, (params: MessageParams) => string> = {
  nickname_changed: (p) =>
  `${text(p.previous)} nazywa się teraz ${text(p.nickname)}.`,
  joined_as_player: (p) => `${text(p.nickname)} dołącza jako gracz.`,
  kicked_by_vote: (p) => `Wyrzucono w głosowaniu: ${text(p.nickname)}.`,
  marked_afk_by_vote: (p) => `Oznaczono jako AFK w głosowaniu: ${text(p.nickname)}.`,

  restart_vote_started: (p) =>
  `${text(p.nickname)} rozpoczyna głosowanie za restartem gry.`,
  restart_vote_passed: (p) =>
  `Głosowanie za restartem przeszło. Restart za ${counted(count(p.seconds, 5), { one: "sekundę", few: "sekundy", many: "sekund", other: "sekundy" })}.`,
  restart_vote_rejected: () => "Głosowanie za restartem zostało odrzucone.",
  restart_vote_expired: () => "Głosowanie za restartem wygasło bez wymaganej większości.",
  restart_vote_abandoned: () =>
  "Głosowanie za restartem zostało anulowane, bo zostało mniej niż dwóch aktywnych graczy.",
  restart_cancelled: (p) => `Restart został anulowany, bo ${cancelReason(p.reason)}.`,
  game_restarted_by_vote: () => "Gra została zrestartowana w głosowaniu graczy.",
  game_ended_too_few_players: () => "Gra zakończona: zostało mniej niż dwóch graczy.",

  hint_letter_found: (p) => {
    const found = count(p.count, 1);
    return `Kupiono „${text(p.letter)}” za ${counted(count(p.cost), { one: "punkt", few: "punkty", many: "punktów", other: "punktu" })}: ${
      found === 1 ? "występuje raz" : `występuje ${counted(found, { one: "raz", few: "razy", many: "razy", other: "raza" })}`
    }.`;
  },
  hint_letter_missing: (p) =>
    `Kupiono „${text(p.letter)}” za ${counted(count(p.cost), { one: "punkt", few: "punkty", many: "punktów", other: "punktu" })}: nie ma jej w haśle.`,
  guess_very_close: (p) => `„${text(p.text)}” – bardzo blisko!`,
  guess_some_words_correct: () => "Niektóre słowa są poprawne.",
  guess_answer_in_another_language: (p) => `„${text(p.text)}” to odpowiedź w innym języku.`,
};

export const PL: Catalogue = {
  refusals: REFUSALS,
  announcements: ANNOUNCEMENTS,

  /** What the document itself says: the tab, and what a link preview shows.

      Rendered into `index.html` for a crawler, which arrives before any
      script, and rewritten here for the reader once their locale is known. */
  document: {
    description: "Rysuj, zgaduj i śmiej się ze znajomymi!",
  },

  /** Shapes that belong to the language rather than to any one screen. */
  format: {
    /** `1st`, `2nd`, `3rd`; a language with no ordinal form gets the number. */
    ordinal: (p: { value: number }) => ordinal(p.value),
    /** A score, as every place that prints one writes it: `1,182`. */
    number: (p: { value: number }) => number(p.value),
  },

  promptListDrafts: {
    promptsAdded: (p: { count: number }) =>
      `Dodano ${counted(p.count, { one: "hasło", few: "hasła", many: "haseł", other: "hasła" })}`,
    duplicatesAlreadyInTheList: (p: { duplicates: number }) => `${p.duplicates} już na liście`,
    tooLongCountOverMaxListPrompt:
      (p: { tooLongCount: number; MAX_LIST_PROMPT_LENGTH: number }) => `${p.tooLongCount} powyżej limitu ${p.MAX_LIST_PROMPT_LENGTH} znaków`,
    overLimitPastTheMaxList:
      (p: { overLimit: number; MAX_LIST_PROMPTS: number }) => `${p.overLimit} ponad limit ${p.MAX_LIST_PROMPTS}`,
    keptSkippedSkipped: (p: { kept: string; skipped: string }) => `${p.kept}; pominięto: ${p.skipped}.`,
  },

  lastSeen: {
    online: "online",
    justNow: "ostatnio online przed chwilą",
    lastSeenAgo: (p: { count: number; unit: "minute" | "hour" | "day" }) => {
      const words = {
        minute: { one: "minutę", few: "minuty", many: "minut", other: "minuty" },
        hour: { one: "godzinę", few: "godziny", many: "godzin", other: "godziny" },
        day: { one: "dzień", few: "dni", many: "dni", other: "dnia" },
      }[p.unit];
      return `ostatnio online ${counted(p.count, words)} temu`;
    },
  },

  gameHighlights: {
    reactionCount: (p: { count: number }) =>
      counted(p.count, { one: "reakcja", few: "reakcje", many: "reakcji", other: "reakcji" }),
    hardestPrompt: "Najtrudniejsze hasło",
    fastestGuess: "Najszybsze trafienie",
    bestDrawer: "Najlepszy rysujący",
    quickestOnAverage: "Średnio najszybciej",
    mostReactedDrawing: "Rysunek z największą liczbą reakcji",
    gotItOf: (p: { correct: number; total: number }) =>
      `Trafienia: ${p.correct} z ${p.total}`,
    percentGuessed: (p: { percent: string }) =>
      `Zgadło ${p.percent}`,
  },

  segmentedCodeInput: {
    digitPosition: (p: { label: string; index: number; length: number }) =>
      `${p.label}, cyfra ${p.index} z ${p.length}`,
  },

  roomSetupControls: {
    decrease: (p: { label: string }) => `Zmniejsz: ${p.label}`,
    increase: (p: { label: string }) => `Zwiększ: ${p.label}`,
  },

  guessPips: {
    playerGuessState: (p: { nickname: string; isFriend: boolean; guessed: boolean }) =>
      `${p.nickname}${p.isFriend ? " (znajomy)" : ""} ${p.guessed ? "już wie" : "wciąż zgaduje"}`,
    gotOfGuessersCountGuessed:
      (p: { got: number; guessersCount: number }) => `Zgadło: ${p.got} z ${p.guessersCount}`,
    summaryOpenPlayersAndScores:
      (p: { summary: string }) => `${p.summary}. Otwórz listę graczy i wyniki.`,
  },

  accountDataDialog: {
    requestedOn: (p: { when: string }) =>
      `Zlecono: ${p.when}`,
    exportAllowance: (p: { nextAllowed: string | null }) =>
      p.nextAllowed
        ? `Jeden eksport na tydzień; gotowe eksporty wygasają po siedmiu dniach. Kolejny możesz zlecić: ${p.nextAllowed}.`
        : "Jeden eksport na tydzień; gotowe eksporty wygasają po siedmiu dniach.",
    couldNotLoadYourDataExports: "Nie udało się wczytać twoich eksportów danych.",
    couldNotRequestYourDataExport: "Nie udało się zlecić eksportu danych.",
    yourData: "Twoje dane",
    downloadPrivateJsonCopyYourAccount: "Pobierz prywatną kopię danych konta i rozgrywek w formacie JSON. Profile i wiadomości innych graczy nie są w niej uwzględnione.",
    dataExports: "Eksporty danych",
    loadingExports: "Wczytywanie eksportów…",
    youHaveNotRequestedExportYet: "Nie zlecono jeszcze żadnego eksportu.",
    download: "Pobierz",
    requesting: "Zlecanie…",
    requestExport: "Zleć eksport",
  },

  accountMenu: {
    noPasskeyWasUsed: "Nie użyto klucza dostępu. Możesz zamiast tego zalogować się hasłem do konta.",
    signedInWithRequests: (p: { name: string; waiting: number }) =>
      `Zalogowano jako ${p.name}. ${counted(p.waiting, {
        one: "zaproszenie do znajomych czeka",
        few: "zaproszenia do znajomych czekają",
        many: "zaproszeń do znajomych czeka",
        other: "zaproszenia do znajomych czeka",
      })}.`,
    friends: "Znajomi",
    finishYourRole: (p: { role: "admin" | "moderator" }) =>
      `Dokończ konfigurację roli ${p.role === "admin" ? "administratora" : "moderatora"}`,
    agreeToRules: "Tworząc konto, zgadzasz się przestrzegać {rules}.",
    reportBug: "Zgłoś błąd",
    account: "Konto",
    settings: "Ustawienia",
    myProfile: "Mój profil",
    promptStats: "Statystyki haseł",
    createAccount: "Utwórz konto",
    logIn: "Zaloguj się",
    myPromptLists: "Moje listy haseł",
    rules: "Zasady",
    logOut: "Wyloguj się",
    thatDoesNotLookLikeEmail: "To nie wygląda na adres e-mail.",
    somethingWentWrongPleaseTryAgain: "Coś poszło nie tak. Spróbuj ponownie.",
    thatPasskeyWasNotAccepted: "Ten klucz dostępu nie został zaakceptowany.",
    thisAccountSignsWithPasskey: "To konto loguje się kluczem dostępu.",
    username: "Nazwa użytkownika",
    password: "Hasło do konta",
    codeFromYourAuthenticatorApp: "Kod z aplikacji uwierzytelniającej",
    email: "E-mail",
    optional: "(opcjonalnie)",
    letsYouResetYourPasswordLater: "Pozwala później zresetować hasło do konta. Do niczego więcej nie służy.",
    rules2: "zasad",
    forgotYourPassword: "Nie pamiętasz hasła?",
    notNow: "Nie teraz",
    createYourAccount: "Utwórz konto",
    createAnAccountToKeep:
      (p: { suggestedUsername: string }) => `Utwórz konto, aby zachować nazwę użytkownika ${p.suggestedUsername} i mieć swoje statystyki na każdym urządzeniu.`,
    keepYourUsernameAndYour: "Zachowaj nazwę użytkownika i statystyki na każdym urządzeniu.",
    waitingForYourDevice: "Czekamy na twoje urządzenie…",
    signInWithAPasskey: "Zaloguj się kluczem dostępu",
    staffSignInWithPasskey: "Zespół: zaloguj się kluczem dostępu",
    pleaseWait: "Poczekaj…",
    alreadyRegistered: "Masz już konto? ",
    newHere: "Pierwszy raz tutaj? ",
    guestIdentity: (p: { name: string }) => `${p.name}. Twoja wyświetlana nazwa nie jest zapisana.`,
    guestNameNotSaved: "Nazwa gościa, niezapisana na koncie",
    signedInAs: (p: { name: string }) => `Zalogowano jako ${p.name}`,
  },

  accountRecoveryPage: {
    thatConfirmationLinkCouldNotBe: "Nie udało się użyć tego linku potwierdzającego.",
    somethingWentWrongPleaseTryAgain: "Coś poszło nie tak. Spróbuj ponownie.",
    evenBestGuessersForgetSometimes: "Nawet najlepszym zgadującym zdarza się zapomnieć.",
    asideForgot: "Link działa raz i jest ważny przez godzinę.",
    asideReset: "Wybierz hasło, którego nie używasz nigdzie indziej.",
    asideVerify: "Potwierdzony e-mail pozwoli ci wrócić na konto, jeśli kiedyś zapomnisz hasła.",
    asideVerifyHeading: "Zapasowy klucz do twojego konta.",
    backLobby: "Wróć do lobby",
    enterYourUsernameYourConfirmedEmail: "Podaj nazwę użytkownika lub potwierdzony adres e-mail. Jeśli\n              konto da się odzyskać, link jest już w drodze.",
    usernameEmail: "Nazwa użytkownika lub e-mail",
    thatResetLinkHasExpiredHas: "Ten link do resetu hasła wygasł lub został już użyty. Linki do resetu\n              działają raz i są ważne przez godzinę.",
    sendNewOne: "Wyślij nowy",
    checkingThatLink: "Sprawdzanie linku…",
    everySignedDeviceWillBeSigned: "Wszystkie zalogowane urządzenia zostaną wylogowane, także te, których\n              nie rozpoznajesz.",
    newPassword: "Nowe hasło do konta",
    addressIsConfirmedYouCan:
      (p: { address: string }) => `Adres ${p.address} jest potwierdzony. Możesz teraz odzyskać to konto.`,
    yourPasswordIsSetAnd: "Hasło zostało ustawione. Zalogowano cię ponownie.",
    yourPasswordIsSetSignIn: "Hasło zostało ustawione. Zaloguj się ponownie z weryfikacją dwuetapową.",
    yourPasswordIsSetSuspended: "Hasło zostało ustawione, ale to konto jest zawieszone, więc nie można się na nie zalogować.",
    resetYourPassword: "Zresetuj hasło do konta",
    thatLinkNoLongerWorks: "Ten link już nie działa",
    chooseANewPassword: "Wybierz nowe hasło do konta",
    confirmingYourEmail: "Potwierdzanie adresu e-mail",
    emailConfirmed: "E-mail potwierdzony",
    couldNotConfirmYourEmail: "Nie udało się potwierdzić adresu e-mail",
    pleaseWait: "Poczekaj…",
    sendAResetLink: "Wyślij link do resetu",
    setPassword: "Ustaw hasło",
    nothingToConfirm: "Nie ma nic do potwierdzenia.",
    resetLinkOnItsWay:
      "Jeśli to konto istnieje i ma potwierdzony adres e-mail, link do resetu hasła jest już w drodze.",
  },

  activeGameRoom: {
    leaveGame: "Opuść grę",
    markedAfkByRoomVote: "Pokój oznaczył cię w głosowaniu jako AFK.",
    inviteLinkCopied: "Skopiowano link z zaproszeniem.",
    couldNotCopyLink: "Nie udało się skopiować linku. Skopiuj go z paska adresu.",
    couldNotStartGamePleaseTry: "Nie udało się rozpocząć gry. Spróbuj ponownie.",
    couldNotStartRestartVote: "Nie udało się rozpocząć głosowania za restartem.",
    couldNotRecordYourRestartVote: "Nie udało się zapisać twojego głosu za restartem.",
    roomMenu: "Menu pokoju",
    leaveRoom: "Opuść pokój",
    players: "Gracze",
    youWereKickedFromThe: "Wyrzucono cię z pokoju.",
    thisRoomWasOpenedIn: "Ten pokój otwarto w innej karcie.",
    startTheGame: "rozpoczęcie gry",
    startARestartVote: "rozpoczęcie głosowania za restartem",
    recordYourRestartVote: "zapisanie twojego głosu za restartem",
    leaveDuringYourTurn: "Wyjść w trakcie swojej tury?",
    leaveActiveGame: "Opuścić trwającą grę?",
    youReTheCurrentDrawer:
      "Teraz ty rysujesz. Jeśli teraz wyjdziesz, przerwiesz swoją turę, a gra przejdzie dalej dla wszystkich.",
    theGameIsStillIn:
      "Gra wciąż trwa. Opuścisz pokój i stracisz swoje miejsce w tej grze.",
    backFromAfk: "Wracam z AFK",
    closePlayers: "Zamknij listę graczy",
    acceptTheColorSuggestion: "przyjęcie sugestii kolorów",
    dismissTheColorSuggestion: "odrzucenie sugestii kolorów",
    couldNotAcceptSuggestion: "Nie udało się przyjąć sugestii kolorów.",
    couldNotDismissSuggestion: "Nie udało się odrzucić sugestii kolorów.",
  },

  addEmailDialog: {
    followTheLink: (p: { address: string; replacing: boolean }) =>
      `Jeśli adresu ${p.address} można użyć, link potwierdzający jest już w drodze. Dopóki go nie otworzysz, adres nie jest powiązany z twoim kontem i nie można go użyć do odzyskania konta${
        p.replacing ? ", a dotychczasowy adres pozostaje bez zmian." : "."
      }`,
    thatDoesNotLookLikeEmail: "To nie wygląda na adres e-mail.",
    somethingWentWrongPleaseTryAgain: "Coś poszło nie tak. Spróbuj ponownie.",
    done: "OK",
    usedOnlyResetYourPasswordTell: "Służy wyłącznie do resetu hasła i do powiadomienia cię, jeśli wobec twojego konta\n              lub czegoś, co udostępniasz, zostaną podjęte działania. Nic innego\n              nigdy tu nie trafia.",
    checkYourInbox: "Sprawdź skrzynkę odbiorczą",
    changeYourEmailAddress: "Zmień adres e-mail",
    addAnEmailAddress: "Dodaj adres e-mail",
    newEmail: "Nowy e-mail",
    email: "E-mail",
    pleaseWait: "Poczekaj…",
    sendConfirmation: "Wyślij potwierdzenie",
    yourPassword: "Twoje hasło do konta",
    passwordConfirmsItIsYou: "Hasło do konta potwierdza, że to ty: ten adres służy do odzyskania konta.",
    enterYourPasswordToConfirm: "Wpisz hasło do konta, aby potwierdzić zmianę.",
    notNow: "Nie teraz",
  },

  afkCheckDialog: {
    secondsUnit: (p: { count: number }) =>
      plural(p.count, { one: "sekunda", few: "sekundy", many: "sekund", other: "sekundy" }),
    stillThere: "Jesteś tam?",
    youHaveBeenQuietWhileAnswer: "Od dłuższej chwili nic nie robisz. Odpowiedz, a grasz dalej;\n          w przeciwnym razie pokój oznaczy cię jako AFK i zagra bez ciebie.",
    stillTherePressButtonMoveMouse: "Jesteś tam? Naciśnij przycisk albo porusz myszą, aby grać dalej.",
    iMHere: "Jestem",
  },

  app: {
    serverUpdateInProgress: (p: { seconds: number }) =>
      p.seconds > 0
        ? `Trwa aktualizacja serwera. Nie można tworzyć nowych pokoi ani zaczynać gier; trwająca gra ma ${counted(p.seconds, { one: "sekundę", few: "sekundy", many: "sekund", other: "sekundy" })} na zakończenie.`
        : "Trwa aktualizacja serwera. Nie można tworzyć nowych pokoi ani zaczynać gier; trwające gry właśnie się kończą.",
    thisTabOutDateCannotPlay: "Ta karta jest nieaktualna i nie da się w niej grać, dopóki jej nie przeładujesz.",
    reload: "Przeładuj",
    newRoomsArePausedMaintenanceGames: "Tworzenie nowych pokoi jest wstrzymane z powodu prac serwisowych. Trwające gry\n          toczą się normalnie.",
    serverWasUpdatedBackAnyGame: "Serwer został zaktualizowany i znów działa. Trwające gry zostały zakończone.",
    dismiss: "Zamknij",
    couldNotOpenThis: "Nie udało się tego otworzyć. Sprawdź połączenie i spróbuj ponownie.",
    tryAgain: "Spróbuj ponownie",
  },

  appHeader: {
    playerSettings: "Ustawienia gracza",
    sketchyHome: "Przejdź do lobby",
    /** The header's site links (desktop), as one landmark. */
    siteNav: "Strony",
    /** The header's link names for two pages whose titles are long in some
        languages. English keeps the page title; a language whose title
        does not fit the bar at 1200px shortens it, still naming the page. */
    communityLink: "Katalog",
    promptStatsLink: "Statystyki haseł",
  },

  bugReportDialog: {
    connectionSummary: (p: { connected: boolean; reconnects: number }) =>
      `${p.connected ? "online" : "offline"} · ${counted(p.reconnects, {
        one: "ponowne połączenie",
        few: "ponowne połączenia",
        many: "ponownych połączeń",
        other: "ponownego połączenia",
      })} podczas tej wizyty`,
    couldNotTakeScreenshot: "Nie udało się zrobić zrzutu ekranu.",
    thanksYourReportWithPeopleWho: "Dzięki — twoje zgłoszenie trafiło do zespołu Sketchy.",
    thanksSentWithoutScreenshot: "Dzięki — twoje zgłoszenie trafiło do zespołu Sketchy. Tym razem nie udało się zachować zrzutu ekranu.",
    couldNotSendReport: "Nie udało się wysłać zgłoszenia.",
    reportBug: "Zgłoś błąd",
    somethingBrokenNotSomethingSomeoneSaid: "Coś nie działa — a nie ktoś coś napisał. To trafia do zespołu Sketchy, nigdy do innych graczy.",
    where: "Gdzie",
    howBad: "Jak poważne",
    oneLineSummary: "Krótkie podsumowanie",
    whatWentWrongOneLine: "Co poszło nie tak, w jednym zdaniu",
    whatHappened: "Co się stało",
    whatYouDidWhatYouExpected: "Co robisz, czego oczekujesz i co dzieje się zamiast tego.",
    screenshot: "Zrzut ekranu",
    optional: "(opcjonalnie)",
    screenshotThatWillBeSentWith: "Zrzut ekranu, który zostanie wysłany z tym zgłoszeniem",
    thisDialogHidesItselfWhileShot: "To okno chowa się na czas robienia zrzutu, więc widać na nim stronę pod spodem. Obejrzyj go przed wysłaniem — to ty decydujesz, co udostępniasz.",
    replace: "Zamień",
    remove: "Usuń",
    opensYourBrowserSOwnPicker: "Otwiera okno wyboru przeglądarki — wybierz tę kartę. To okno chowa się na czas robienia zrzutu, więc widać na nim stronę pod spodem.",
    recentClientErrors: "Ostatnie błędy klienta",
    sendMyDescriptionOnly: "Wyślij tylko mój opis",
    dropsDetailsAboveAnyScreenshotWe: "Pomija powyższe szczegóły i zrzut ekranu. Nadal przeczytamy zgłoszenie, ale błąd będzie znacznie trudniej odtworzyć.",
    cancel: "Anuluj",
    build: "Wersja",
    page: "Strona",
    room: "Pokój",
    screen: "Ekran",
    browser: "Przeglądarka",
    connection: "Połączenie",
    waitingForThePicker: "Czekamy na okno wyboru…",
    attachAScreenshot: "Dołącz zrzut ekranu",
    whatWeAreLeavingOut: "Czego nie wysyłamy",
    whatWeSendWithThis: "Co wysyłamy razem ze zgłoszeniem",
    noneOfThisIsBeing: "Nic z tego nie zostanie wysłane — tylko twój opis powyżej.",
    theLast20ErrorsYour:
      "Ostatnie 20 błędów zapisanych przez przeglądarkę. Z adresów stron tylko ścieżka, nic z tego, co piszesz na czacie, i nigdy hasło z bieżącej tury.",
    sending: "Wysyłanie…",
    sendReport: "Wyślij zgłoszenie",
    kilobytes: (p: { size: number }) =>
      `${number(p.size)} KB`,
    megabytes: (p: { size: number }) =>
      `${number(p.size)} MB`,
  },

  changePasswordDialog: {
    forgottenTheCurrentOne: "Nie pamiętasz obecnego?",
    twoNewPasswordsDoNotMatch: "Nowe hasła nie są takie same.",
    passwordChangedEveryOtherDeviceHas: "Hasło zmienione. Wszystkie inne urządzenia zostały wylogowane.",
    couldNotChangePasswordPleaseTry: "Nie udało się zmienić hasła. Spróbuj ponownie.",
    ifThatAccountHasConfirmedEmail: "Jeśli to konto ma potwierdzony adres e-mail, link do ustawienia nowego\n              hasła jest już w drodze. Działa raz i wygasa.",
    done: "OK",
    everyDeviceSignsOutWhenPassword: "Po zmianie hasła wszystkie urządzenia zostają wylogowane, także te\n              pozostawione zalogowane przez przypadek. To urządzenie zostaje.",
    currentPassword: "Obecne hasło",
    newPassword: "Nowe hasło",
    newPasswordAgain: "Powtórz nowe hasło",
    emailMeLinkInstead: "Wyślij mi zamiast tego link e-mailem",
    checkYourInbox: "Sprawdź skrzynkę odbiorczą",
    changeYourPassword: "Zmień hasło do konta",
    pleaseWait: "Poczekaj…",
    changePassword: "Zmień hasło",
    cancel: "Anuluj",
  },

  choosingPromptOverlay: {
    isChoosingPrompt: "{drawer} wybiera hasło…",
    nextTurn: "Następna tura",
    drawingWillBeginAsSoonAs: "Rysowanie zacznie się, gdy tylko hasło zostanie wybrane.",
  },

  colorblindSafeSuggestionBanner: {
    colorblindSafeColorSuggestion: "Sugestia kolorów przyjaznych dla daltonistów",
    playerThisRoomPlaysWithColorblind: "Ktoś w tym pokoju gra z kolorami przyjaznymi dla daltonistów.",
    switchRoomPaletteFutureDrawings: "Zmienić paletę pokoju dla kolejnych rysunków?",
    switchColors: "Zmień kolory",
    notNow: "Nie teraz",
  },

  /** Words every dialog shares: its ✕, and the line a notice shows when
      its acknowledgement did not land. */
  dialog: {
    close: "Zamknij",
    cancel: "Anuluj",
    couldNotSave: "Nie udało się zapisać. Spróbuj ponownie.",
  },

  confirmationDialog: {
    cancel: "Anuluj",
  },

  crashPage: {
    couldNotSendReport: "Nie udało się wysłać zgłoszenia.",
    bugCrawledOntoPage: "Na stronę wpełzł robal",
    helpUsSquash: "Pomóż nam go zgnieść",
    reportReadySendErrorWhatThis: "Zgłoszenie jest gotowe do wysłania: błąd i to, co ta karta wie o sobie.\n            Trafia do zespołu Sketchy — nigdy do innych graczy.",
    whatWereYouDoing: "Co się działo przed błędem?",
    optional: "(opcjonalnie)",
    lastThingYouClickedTypedIf: "Ostatnie kliknięcie lub wpisany tekst, jeśli pamiętasz.",
    recentClientErrorsNewestFirst: "Ostatnie błędy klienta, od najnowszych",
    sendMyDescriptionOnly: "Wyślij tylko mój opis",
    dropsDetailsAboveWeWillStill: "Pomija powyższe szczegóły. Nadal przeczytamy zgłoszenie, ale awarię będzie znacznie trudniej znaleźć.",
    thanksYourReportWithPeopleWho: "Dzięki — twoje zgłoszenie trafiło do zespołu Sketchy.",
    reload: "Przeładuj",
    backLobby: "Wróć do lobby",
    summary: "Podsumowanie",
    build: "Wersja",
    page: "Strona",
    room: "Pokój",
    screen: "Ekran",
    browser: "Przeglądarka",
    connection: "Połączenie",
    thisRoomSScreenHit:
      "Ekran tego pokoju napotkał błąd i musiał się zatrzymać. Twoje miejsce jest przez chwilę zarezerwowane: wyślij zgłoszenie poniżej, a potem przeładuj stronę, aby do niego wrócić, albo wróć do lobby.",
    thisScreenHitAnError:
      "Ten ekran napotkał błąd i musiał się zatrzymać. Twoje konto i ustawienia są bezpieczne. Wyślij zgłoszenie poniżej i możesz grać dalej.",
    whatWeAreLeavingOut: "Czego nie wysyłamy",
    whatWeSendWithThis: "Co wysyłamy razem ze zgłoszeniem",
    noneOfThisIsBeing: "Nic z tego nie zostanie wysłane — tylko twój opis powyżej.",
    theCrashTheLast20:
      "Awaria, ostatnie 20 błędów zapisanych przez przeglądarkę i miejsce na stronie, w którym do niej doszło. Z adresów stron tylko ścieżka, nic z tego, co piszesz na czacie, i nigdy hasło z bieżącej tury.",
    sendingAgain: "Ponowne wysyłanie…",
    sending: "Wysyłanie…",
    trySendingAgain: "Spróbuj wysłać ponownie",
    sendReport: "Wyślij zgłoszenie",
  },

  createRoomPage: {
    setupTiming: "Z tymi ustawieniami gra trwa {full} przy komplecie {capacity} graczy",
    setupTimingFull: (p: { minutes: number }) =>
      `około ${counted(p.minutes, { one: "minuty", few: "minut", many: "minut", other: "minuty" })}`,
    setupTimingHalf: (p: { players: number }) => ` — raczej {half}, jeśli graczy będzie ${p.players}`,
    couldNotLoadYourRoomPresets: "Nie udało się wczytać twoich szablonów pokoju.",
    couldNotApplyThatPreset: "Nie udało się zastosować tego szablonu.",
    enterNameRoomPreset: "Wpisz nazwę szablonu pokoju.",
    couldNotSaveThatPreset: "Nie udało się zapisać tego szablonu.",
    couldNotUpdateThatPreset: "Nie udało się zaktualizować tego szablonu.",
    couldNotDeleteThatPreset: "Nie udało się usunąć tego szablonu.",
    fixCustomPromptEntriesMarkedAbove: "Popraw oznaczone powyżej własne hasła przed utworzeniem pokoju.",
    couldNotCreateRoom: "Nie udało się utworzyć pokoju.",
    createRoom: "Utwórz pokój",
    startFromSavedPreset: "Zacznij od zapisanego szablonu",
    startFromPreset: "Zacznij od szablonu…",
    nameThisPreset: "Nazwij ten szablon",
    save: "Zapisz",
    cancel: "Anuluj",
    saveAsPreset: "Zapisz jako szablon",
    update: "Aktualizuj",
    delete: "Usuń",
    undo: "Cofnij",
    saveAsPromptList: "Zapisz jako listę haseł",
    saveCustomPromptsAsAList: "Zapisz własne hasła jako listę haseł, zanim zapiszesz szablon.",
    appliedName: (p: { name: string }) => `Zastosowano „${p.name}”.`,
    savedName: (p: { name: string }) => `Zapisano „${p.name}”.`,
    updatedName: (p: { name: string }) => `Zaktualizowano „${p.name}”.`,
    deleteThisRoomSettingPreset: "Usunąć ten szablon ustawień pokoju?",
    deletePresetDescription: "Nie wpłynie to na pokoje, które już z nim utworzono.",
    createTheRoom: "utworzenie pokoju",
    private: "Prywatny",
    backToLobby: "Wróć do lobby",
    leaveBlankForARandom: "Zostaw puste, aby wylosować nazwę!",
    creating: "Tworzenie…",
    createRoom2: "Utwórz pokój",
    yourRoom: "Twój pokój",
    aRandomName: "Losowa nazwa",
  },

  customPromptsEditor: {
    usableCount: (p: { count: number }) =>
      counted(p.count, { one: "własne hasło do użycia", few: "własne hasła do użycia", many: "własnych haseł do użycia", other: "własnego hasła do użycia" }),
    duplicatesIgnored: (p: { count: number }) =>
      `Pominięto ${counted(p.count, { one: "duplikat", few: "duplikaty", many: "duplikatów", other: "duplikatu" })}`,
    entriesTooLong: (p: { count: number; limit: number }) =>
      `${counted(p.count, { one: "wpis przekracza", few: "wpisy przekraczają", many: "wpisów przekracza", other: "wpisu przekracza" })} limit ${number(p.limit)} znaków`,
    entryLimit: (p: { limit: number }) => `Limit wpisów: ${number(p.limit)}`,
    customPromptsOptional: "Własne hasła (opcjonalnie)",
    onePromptPerLineSeparateEntries: "Jedno hasło w wierszu\nalbo oddzielaj wpisy przecinkami",
    shortenRemoveOverlongEntriesBeforeCreating: "Skróć lub usuń zbyt długie wpisy przed utworzeniem pokoju.",
  },

  customPromptsPreview: {
    resultsMatching: (p: { shown: number; total: number }) =>
      `Pasujące hasła: ${number(p.shown)} z ${number(p.total)}`,
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "hasło", few: "hasła", many: "haseł", other: "hasła" }),
    customPromptCount: (p: { count: number }) =>
      counted(p.count, { one: "własne hasło", few: "własne hasła", many: "własnych haseł", other: "własnego hasła" }),
    inspectPrompts: (p: { count: number }) =>
      `Przejrzyj ${counted(p.count, { one: "własne hasło", few: "własne hasła", many: "własnych haseł", other: "własnego hasła" })}`,
    couldNotLoadCustomPrompts: "Nie udało się wczytać własnych haseł.",
    loadingCustomPrompts: "Wczytywanie własnych haseł…",
    roomPromptCollection: "Zbiór haseł pokoju",
    readOnlyListSuppliedByRoom: "Lista tylko do odczytu, przygotowana przez gospodarza pokoju.",
    findPrompt: "Znajdź hasło",
    searchCustomPrompts: "Szukaj we własnych hasłach…",
    filterPromptsByLength: "Filtruj hasła według długości",
    noCustomPromptsMatchTheseFilters: "Żadne własne hasło nie pasuje do tych filtrów.",
    all: "Wszystkie",
    allPromptLengths: "Hasła o dowolnej długości",
    short: "Krótkie",
    n5CharactersOrFewer: "Do 5 znaków",
    medium: "Średnie",
    n6To10Characters: "Od 6 do 10 znaków",
    long: "Długie",
    n11CharactersOrMore: "11 znaków lub więcej",
    loadTheCustomPrompts: "wczytanie własnych haseł",
  },

  deleteAccountDialog: {
    whatIsRemoved: (p: { isGuest: boolean }) =>
      `${
        p.isGuest
          ? "Nazwa, punkty i historia powiązane z tą przeglądarką zostaną usunięte."
          : "Twoja nazwa zostanie usunięta z rozegranych gier."
      } Wyniki i rysunki zostają pod nazwą „Usunięty gracz”, bo to także gry innych osób. Tego nie da się cofnąć.`,
    typeToConfirm: (p: { word: string }) => `Wpisz ${p.word}, aby potwierdzić`,
    couldNotDeleteAccount: "Nie udało się usunąć konta.",
    password: "Hasło do konta",
    deleteThisGuest: "Usuń tego gościa",
    deleteYourAccount: "Usuń konto",
    deleting: "Usuwanie…",
    deleteForGood: "Usuń na zawsze",
  },

  drainCue: {
    title: "Aktualizacja serwera",
    gameEndsIn: (p: { seconds: number }) =>
      p.seconds > 0 ? `Ta gra skończy się za ${counted(p.seconds, { one: "sekundę", few: "sekundy", many: "sekund", other: "sekundy" })}.` : "Ta gra właśnie się kończy.",
    noNewGames: "Do czasu powrotu serwera nie można zaczynać nowych gier.",
    ok: "OK",
    finalCountdown: (p: { seconds: number }) => `Koniec gry za ${counted(p.seconds, { one: "sekundę", few: "sekundy", many: "sekund", other: "sekundy" })}`,
  },

  drawingReactionControl: {
    reactionSummary: (p: { total: number; chips: string }) =>
      `${counted(p.total, { one: "reakcja", few: "reakcje", many: "reakcji", other: "reakcji" })}: ${p.chips}`,
    thatReactionCouldNotBeSent: "Nie udało się wysłać tej reakcji.",
    reactThisDrawing: "Zareaguj na ten rysunek",
    reactions: "Reakcje",
    createAccountReact: "Utwórz konto, aby reagować.",
    createAccount: "Utwórz konto",
    noReactionsYet: "Jeszcze brak reakcji",
    reactToThisDrawingSummary: (p: { summary: string }) => `Zareaguj na ten rysunek. ${p.summary}`,
    labelYourReactionPressTo:
      (p: { label: string }) => `${p.label} – twoja reakcja. Naciśnij, aby ją usunąć`,
  },

  pinControl: {
    pin: "Przypnij",
    pinned: "Przypięty",
    pinThisDrawing: "Przypnij ten rysunek do profilu i udostępnij go w galerii",
    unpinThisDrawing: "Odepnij ten rysunek od profilu",
    thatDrawingCouldNotBePinned: "Nie udało się przypiąć tego rysunku.",
  },

  shareControl: {
    share: "Udostępnij w galerii",
    shared: "Udostępniony",
    takeOut: "Zdejmij z galerii",
    shareThisDrawing: "Umieść ten rysunek w publicznej galerii",
    takeBackYourShare: "Cofnij udostępnienie",
    takeThisDrawingOut: "Zdejmij ten rysunek z galerii dla wszystkich",
    theDrawerKeptItOut: "Osoba, która go narysowała, zdjęła go z galerii.",
    inTheGallery: "W galerii",
    inTheGallerySharedBy: "W galerii · udostępnienie: {sharer}",
    inTheGallerySharedByYou: "W galerii · udostępniony przez ciebie",
    inTheGallerySharedByTheDrawer: "W galerii · udostępniony przez osobę, która go narysowała",
    thatDrawingCouldNotBeShared: "Nie udało się udostępnić tego rysunku.",
    thatCouldNotBeTakenBack: "Nie udało się tego cofnąć. Spróbuj ponownie.",
    takeOutTitle: "Zdjąć ten rysunek z galerii?",
    takeOutDescription: "Zniknie z galerii dla wszystkich i ze wszystkich profili, do których jest przypięty. Tylko ty możesz go przywrócić.",
    takeOutConfirm: "Zdejmij",
  },

  drawingRecapGallery: {
    drawingLabel: (p: { prompt: string; drawer: string }) =>
      `Rysunek: ${p.prompt}. Autor: ${p.drawer}`,
    drawnBy: "Autor: {drawer} · Runda {round} · Tura {turn}",
    position: (p: { position: number; total: number }) => `${p.position} z ${p.total}`,
    thisDrawingCouldNotBeDecoded: "Nie udało się odczytać tego rysunku.",
    drawingRecap: "Podsumowanie rysunków",
    saveImage: "Zapisz obraz",
    closeDrawings: "Zamknij rysunki",
    thisDrawingWasNotKept: "Ten rysunek nie został zachowany.",
    earlierDrawingsFilledTheSpace: "Wcześniejsze rysunki z tej gry zajęły całe miejsce, które pokój na nie przeznacza.",
    tryAgain: "Spróbuj ponownie",
    loadingDrawing: "Wczytywanie rysunku…",
    noDrawingWasCapturedThisTurn: "W tej turze nie zapisano żadnego rysunku.",
    drawingRecapNavigation: "Nawigacja po podsumowaniu rysunków",
    previous: "Poprzedni",
    next: "Następny",
    loadThisDrawing: "wczytanie tego rysunku",
  },

  emailRecoveryReminder: {
    addEmail: "Dodaj e-mail",
    dismiss: "Zamknij",
    confirmPendingAddressToFinishSetting:
      (p: { pendingAddress: string }) => `Potwierdź adres ${p.pendingAddress}, aby dokończyć konfigurację odzyskiwania konta.`,
    thisAccountHasNoEmail:
      "To konto nie ma adresu e-mail, więc zapomnianego hasła nie da się zresetować.",
  },

  firstRunIdentity: {
    /** The name tag's one rule it can still break: its field only takes allowed characters. */
    nameTooShort: (p: { min: number }) =>
      `Nazwa musi mieć co najmniej ${counted(p.min, { one: "znak", few: "znaki", many: "znaków", other: "znaku" })}.`,
    nameInUse: (p: { name: string }) =>
      `Ktoś online gra już jako „${p.name}”. Wybierz inną nazwę, aby grać dalej.`,
    couldNotSaveThatNamePlease: "Nie udało się zapisać tej nazwy. Spróbuj ponownie.",
    createAccount: "Utwórz konto",
    logIn: "Zaloguj się",
    displayName: "Wyświetlana nazwa",
    whatShouldWeCallYou: "Jak mamy cię nazywać?",
    beenHereBefore: "Grasz tu nie pierwszy raz?",
    helloMyNameIs: "Cześć, mam na imię",
    stickItOn: "Przyklej",
    saving: "Zapisywanie…",
    oneLineExplainer: "Jeden gracz rysuje, reszta próbuje zgadnąć. Bez konta, bez instalacji, bez talentu.",
    /* One is picked per visit (lib/firstRunLines.ts). Not a translation of
       the English pool: the misread-drawing joke needs a pair of words that
       are far apart in this language. */
    lines: [
      "To ma być łódź podwodna? Wygląda jak szczoteczka do zębów.",
      "Czas udowodnić, że nauczycielka plastyki nie miała racji.",
      "Kubizm, tylko przypadkiem.",
      "To ty, Michale Aniele?",
      "Wow, wygląda jak Pollock!",
    ],
  },

  friendButton: {
    requestSentTo: (p: { name: string }) => `Wysłano zaproszenie do znajomych: ${p.name}`,
    addFriend: "Dodaj do znajomych",
    acceptRequest: "Przyjmij zaproszenie",
    requestSent: "Zaproszenie wysłane",
  },

  friendInviteNotice: {
    couldNotJoinThatGame: "Nie udało się dołączyć do tej gry.",
    invitedYouTheirGame: "zaprasza cię do swojej gry.",
    join: "Dołącz",
    dismissInvitation: "Odrzuć zaproszenie",
    notNow: "Nie teraz",
    leaveAndJoin: "Wyjdź i dołącz",
    leaveYourTurnForTheirGame: (p: { name: string }) =>
      `Teraz ty rysujesz. Jeśli dołączysz do gry, w której jest ${p.name}, przerwiesz swoją turę, a ta gra przejdzie dalej dla wszystkich.`,
    leaveThisGameForTheirs: (p: { name: string }) =>
      `Gra wciąż trwa. Stracisz w niej miejsce, aby dołączyć do gry, w której jest ${p.name}.`,
  },

  friendsOverlay: {
    declineWarning: (p: { name: string }) =>
      `${p.name} nie będzie mieć możliwości ponownego wysłania zaproszenia. Ty nadal możesz później wysłać zaproszenie.`,
    youWillBothStopBeingAble: "Żadne z was nie będzie już mogło dołączać do gier drugiej osoby bez zaproszenia. Każde z was może ponownie wysłać zaproszenie.",
    removeConfirm: (p: { name: string }) => `Usunąć ze znajomych: ${p.name}?`,
    friends: "Znajomi",
    closeFriends: "Zamknij listę znajomych",
    friendsNeedAnAccount: "Znajomi wymagają konta, żeby mogli cię znowu znaleźć. Utwórz konto lub zaloguj się, aby dodawać znajomych.",
    loading: "Wczytywanie…",
    noFriendsYetAddSomebodyFrom: "Nie masz jeszcze znajomych. Dodaj kogoś z lobby albo z gry, w której\n              oboje jesteście.",
    requests: "Zaproszenia",
    accept: "Przyjmij",
    decline: "Odrzuć",
    sent: "Wysłane",
    cancel: "Anuluj",
    remove: "Usuń",
    declineThisRequest: "Odrzucić to zaproszenie?",
    recentlyPlayedWith: "Ostatnie wspólne gry",
  },

  gameEndOverlay: {
    // Between the last two named winners: "Ada and Grace".
    nameListAnd: " i ",
    continueLabel: "Kontynuuj",
    youFinished: (p: { points: number }) =>
      `Zajmujesz {place} miejsce — ${counted(p.points, { one: "punkt", few: "punkty", many: "punktów", other: "punktu" })}.`,
    continueToWaitingRoom: "Przejdź do poczekalni",
    continueWithCountdown: (p: { seconds: number }) =>
      `Przejdź do poczekalni, pozostały czas: ${counted(p.seconds, { one: "sekunda", few: "sekundy", many: "sekund", other: "sekundy" })}`,
    gameOver: "Koniec gry",
    you: "ty",
    friend: "Znajomy",
    noScoresThisTimeJustRoom: "Tym razem bez punktów — tylko pokój pełen rysunków i odpowiedzi.",
    keep: "Zachowaj",
    asYourUsername: "jako nazwę użytkownika",
    createAccount: "Utwórz konto",
    highlights: "Najlepsze momenty",
    drawings: "Rysunki",
    stayHere: "Zostań tutaj",
    aGreatGameOfDrawing: "Świetna rysunkowa rozgrywka",
    theRoomTakesTheCrown: "Korona dla całego pokoju!",
    winnersCountPlayersShareTheCrown:
      (p: { winnersCount: number }) => `${p.winnersCount} graczy dzieli się koroną!`,
    takesTheCrown: " zdobywa koronę!",
    shareTheCrown: " dzielą się koroną!",
  },

  gameHighlightsPanel: {
    lastGame: "Ostatnia gra",
    highlights: "Najlepsze momenty",
    closeHighlights: "Zamknij najlepsze momenty",
    thatGameWasTooShortSay: "Ta gra była za krótka, żeby coś o niej powiedzieć. Zagraj dłużej, a\n            najlepsze momenty pojawią się tutaj.",
    seeIt: "Zobacz",
  },

  inviteEntryPage: {
    haveAnAccount: "Masz konto?",
    roomCode: (p: { code: string }) => `Pokój ${p.code}`,
    checkingYourInvite: "Sprawdzanie zaproszenia…",
    loadingRoomDetails: "Wczytywanie szczegółów pokoju.",
    roomUnavailable: "Pokój niedostępny",
    backLobby: "Wróć do lobby",
    roomRules: "Zasady pokoju",
    thisGameAlreadyProgressJoiningAs: "Ta gra już trwa. Jako gracz dołączysz w jednej z kolejnych tur.",
    noPlayerSeatsOpenSpectate: "Brak wolnych miejsc dla graczy. Nadal możesz oglądać jako widz.",
    publicRoom: "Pokój publiczny",
    privateInvite: "Prywatne zaproszenie",
    inProgress: "W trakcie",
    waiting: "Oczekuje",
    spectatorsCanSeeThePrompt: "Widzowie widzą hasło",
    roomFull: "Pokój pełny",
    joining: "Dołączanie…",
    joinGameInProgress: "Dołącz do trwającej gry",
    join: "Dołącz",
    spectate: "Oglądaj",
    customPromptsOnly: (p: { count: number }) =>
      `tylko ${counted(p.count, { one: "własne hasło", few: "własne hasła", many: "własnych haseł", other: "własnego hasła" })}`,
    customPromptsPlusDefaults: (p: { count: number }) =>
      `${counted(p.count, { one: "własne hasło", few: "własne hasła", many: "własnych haseł", other: "własnego hasła" })} plus domyślne`,
  },

  inviteFriendsList: {
    invitationCouldNotBeSent: "Nie udało się wysłać tego zaproszenia.",
    invitationSent: (p: { name: string }) => `Wysłano zaproszenie: ${p.name}.`,
    friendsLobby: "Znajomi w lobby",
    invited: "Zaproszono",
    invite: "Zaproś",
  },

  languagePicker: {
    currentChoice: (p: { label: string; value: string }) => `${p.label}: ${p.value}`,
    everyLanguage: "Wszystkie języki",
    /** A prompt list in no language (#821): played in a room of any
    language (GLOSSARY: Any language). */
    anyLanguage: "Dowolny język",
    /** A mixed-language room (#1182): each seat plays in its own language
    (GLOSSARY: Mixed-language room). */
    mixed: "Mieszany",
  },

  lobbyBrowserPage: {
    quickPlay: "Szybka gra",
    lobby: "Lobby",
    quickPlayBusy: "Szukanie pokoju…",
    couldNotFindOrOpenARoom: "Nie udało się znaleźć ani otworzyć pokoju.",
    filterByLanguage: "Filtruj według języka",
    filtersWithCount: (p: { count: number }) =>
      p.count > 0 ? `Filtry · ${p.count}` : "Filtry",
    showRooms: (p: { count: number }) =>
      `Pokaż ${counted(p.count, { one: "pokój", few: "pokoje", many: "pokoi", other: "pokoju" })}`,
    kickedFromRoom: "Wyrzucono cię z pokoju",
    noLongerInRoom: "Nie jesteś już w pokoju",
    ok: "OK",
    roomCode: "Kod pokoju",
    abc123: "ABC123",
    thereNoRoomCodeClipboard: "W schowku nie ma kodu pokoju.",
    sketchyCouldNotReadClipboardPaste: "Sketchy nie może odczytać schowka. Wklej kod bezpośrednio w pola.",
    enterRoomCode: "Wpisz kod pokoju.",
    couldNotJoinRoom: "Nie udało się dołączyć do pokoju.",
    joinByCode: "Dołącz przez kod",
    createRoom: "Utwórz pokój",
    publicRooms: "Pokoje publiczne",
    searchRoomsByNameCode: "Szukaj pokoi po nazwie lub kodzie",
    hideFull: "Ukryj pełne",
    hideProgress: "Ukryj trwające",
    filters: "Filtry",
    clearFilters: "Wyczyść filtry",
    language: "Język",
    hideFullRooms: "Ukryj pełne pokoje",
    hideGamesProgress: "Ukryj trwające gry",
    loadingPublicRooms: "Wczytywanie pokoi publicznych…",
    noPublicRoomsYet: "Nie ma jeszcze pokoi publicznych",
    noPublicRoomsYetBody: "Szybka gra otworzy pokój dla ciebie. Możesz też utworzyć własny.",
    noPublicRoomsMatchYourSearch: "Żaden pokój publiczny nie pasuje do kryteriów wyszukiwania.",
    paste: "Wklej",
    couldNotSaveThatName: "Nie udało się zapisać tego pseudonimu. Spróbuj ponownie.",
    joinAsASpectator: "dołączenie jako widz",
    joinTheRoom: "dołączenie do pokoju",
    showingFilteredRoomsCountOfRoomsCount:
      (p: { filteredRoomsCount: number; roomsCount: number }) => `Wyświetlono ${p.filteredRoomsCount} z ${p.roomsCount}`,
    close: "Zamknij",
    joining: "Dołączanie…",
    join: "Dołącz",
    joiningAsSpectator: "Dołączanie jako widz…",
    spectate: "Oglądaj",
  },

  lobbyChatPanel: {
    reportThisLine: (p: { name: string }) => `Zgłoś tę wiadomość (${p.name})`,
    couldNotSendThat: "Nie udało się tego wysłać.",
    chat: "Czat",
    lobbyChat: "Czat lobby",
    nobodyHasSaidAnythingYet: "Nikt jeszcze nic nie napisał.",
    chooseNameChat: "Wybierz pseudonim, żeby pisać na czacie",
    saySomethingLobby: "Napisz coś do lobby…",
    lobbyChatMessage: "Wiadomość na czacie lobby",
    send: "Wyślij",
    couldNotSaveThatName: "Nie udało się zapisać tego pseudonimu. Spróbuj ponownie.",
    sendTheMessage: "wysłanie wiadomości",
  },

  lobbyPlayerMenu: {
    whatToDoAbout: (p: { name: string }) => `${p.name}: co chcesz zrobić?`,
    openPlayerProfile: "Otwórz profil gracza",
    addAsFriend: "Dodaj do znajomych",
    report: "Zgłoś",
  },

  promptTags: {
    "animals": "Zwierzęta",
    "food-and-drink": "Jedzenie i picie",
    "objects": "Przedmioty",
    "nature": "Przyroda",
    "places": "Miejsca",
    "people": "Ludzie",
    "actions": "Czynności",
    "sports-and-games": "Sport i gry",
    "transport": "Transport",
    "entertainment": "Rozrywka",
    "video-games": "Gry wideo",
    "science-and-technology": "Nauka i technika",
    "history-and-culture": "Historia i kultura",
    "holidays": "Święta",
    "fantasy": "Fantastyka",
    "abstract": "Abstrakcja",
  },
  communityCataloguePage: {
    playThisList: "Zagraj tą listą",
    backToLobby: "Wróć do lobby",
    loading: "Wczytywanie…",
    communityCatalogue: "Katalog społeczności",
    listsPlayersPublished: "Listy opublikowane przez graczy, dostępne dla każdego.",
    couldNotLoadTheCatalogue: "Nie udało się wczytać katalogu społeczności.",
    couldNotOpenThatList: "Nie udało się otworzyć tej listy.",
    language: "Język",
    sortBy: "Sortuj według",
    mostStarred: "Najwięcej gwiazdek",
    newest: "Najnowsze",
    onlyOnesIStarred: "Tylko oznaczone przeze mnie gwiazdką",
    clearFilters: "Wyczyść filtry",
    nothingMatchesThoseFilters: "Żadna lista nie pasuje do tych filtrów.",
    nothingPublishedYet: "Nikt jeszcze nie opublikował listy.",
    byOwner: (p: { owner: string }) => `autor: ${p.owner}`,
    starred: "Z gwiazdką",
    tags: "Tagi",
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "hasło", few: "hasła", many: "haseł", other: "hasła" }),
    starCount: (p: { count: number }) =>
      counted(p.count, { one: "gwiazdka", few: "gwiazdki", many: "gwiazdek", other: "gwiazdki" }),
    copyCount: (p: { count: number }) =>
      counted(p.count, { one: "kopia", few: "kopie", many: "kopii", other: "kopii" }),
    copiedFrom: "Skopiowano z listy {list} (autor: {owner})",
    copiedFromADeletedList: "Skopiowano z listy, która została usunięta",
    showMore: "Pokaż więcej",
    makeACopy: "Utwórz kopię",
    thisIsYourList: "To twoja lista.",
    editInMyPromptLists: "Edytuj w „Moich listach haseł”",
    report: "Zgłoś",
    signInToStarCopyOrReport: "Zaloguj się, aby oznaczyć listę gwiazdką, skopiować ją lub zgłosić.",
    whatIsInIt: "Zawartość",
    couldNotChangeTheStar: "Nie udało się zmienić gwiazdki.",
    copiedToYourLists: "Skopiowano do twoich list haseł.",
    couldNotCopyThatList: "Nie udało się skopiować tej listy.",
    // The count is part of the name: a screen reader hears one control, so it
    // has to hear both what the control does and the number it shows.
    starButton: (p: { count: number; starred: boolean }) =>
      p.starred ? `Usuń swoją gwiazdkę (${counted(p.count, { one: "gwiazdka", few: "gwiazdki", many: "gwiazdek", other: "gwiazdki" })})` : `Oznacz tę listę gwiazdką (${counted(p.count, { one: "gwiazdka", few: "gwiazdki", many: "gwiazdek", other: "gwiazdki" })})`,
    chooseAList: "Wybierz listę, aby zobaczyć jej zawartość",
    chooseAListBody: "Jej tagi i wszystkie hasła.",
    promptsHeading: "Hasła",
    inTheAuthorsOrder: "W kolejności autora",
    shownOfTotal: (p: { shown: number; total: number }) => `Widoczne: ${number(p.shown)} z ${number(p.total)}`,
    exploreAll: (p: { count: number }) => `Przeglądaj wszystkie hasła (${number(p.count)})`,
    allPrompts: (p: { count: number }) => `Wszystkie hasła (${number(p.count)})`,
    searchPrompts: "Szukaj haseł",
    matchesOfTotal: (p: { matches: number; total: number }) => `${number(p.matches)} z ${number(p.total)}`,
    order: "Kolejność",
    authorsOrder: "Kolejność autora",
    alphabetical: "A–Z",
    noPromptMatches: (p: { query: string }) => `Żadne hasło nie zawiera „${p.query}”.`,
    allLists: "Wszystkie listy",
  },
  galleryPage: {
    gallery: "Galeria",
    backToLobby: "Wróć do lobby",
    drawingsPlayersShared: "Rysunki, które gracze postanowili udostępnić.",
    loading: "Wczytywanie…",
    sortBy: "Sortuj według",
    hot: "Na czasie",
    new: "Nowe",
    top: "Najlepsze",
    window: "Okres",
    allTime: "Od początku",
    thisMonth: "W tym miesiącu",
    thisWeek: "W tym tygodniu",
    nothingThisWeek: "W tym tygodniu jeszcze nic nie ma.",
    nothingHereYet: "Nie ma jeszcze rysunków",
    signInToSeeTheGallery: "Zaloguj się, aby zobaczyć galerię",
    couldNotLoadTheGallery: "Nie udało się wczytać galerii.",
    couldNotLoadThisDrawing: "Nie udało się wczytać tego rysunku.",
    showMore: "Pokaż więcej",
    tryAgain: "Spróbuj ponownie",
    openDrawing: (p: { prompt: string; drawer: string }) => `Otwórz „${p.prompt}” (autor: ${p.drawer})`,
    ago: (p: { count: number; unit: "minute" | "hour" | "day" }) => `${counted(p.count, { minute: { one: "minutę", few: "minuty", many: "minut", other: "minuty" }, hour: { one: "godzinę", few: "godziny", many: "godzin", other: "godziny" }, day: { one: "dzień", few: "dni", many: "dni", other: "dnia" } }[p.unit])} temu`,
    justNow: "przed chwilą",
    byDrawerPrefix: "autor:",
    sharedBy: "udostępnienie: {sharer}",
    thatIsAllOfIt: "To już wszystko",
    endOfHot: "Wszystko z ostatnich dwóch tygodni, od najgorętszych.",
    endOfTheRest: "W tym widoku nie ma nic więcej.",
    tryTopOverAllTime: "Resztę znajdziesz w widoku Najlepsze od początku",
    findARoom: "Znajdź pokój",
    backToTop: "Wróć na górę",
    topOfTheWeek: "Najlepsze w tym tygodniu",
    nothingHereYetBody: "Udostępnij rysunek z wyników lub podsumowania gry, a pojawi się tu jako pierwszy.",
    signInBody: "Możesz też wybrać pseudonim w lobby i rozejrzeć się jako gość.",
    backToGallery: "Wróć do galerii",
    replay: "Powtórka",
    pause: "Pauza",
    play: "Odtwórz",
    replayPosition: "Pozycja odtwarzania",
    percentDrawn: (p: { percent: number }) => `Narysowano ${number(p.percent)}%`,
    saveImage: "Zapisz obraz",
    notInTheGallery: "Tego rysunku nie ma w galerii",
    notInTheGalleryBody: "Mógł zostać zdjęty, usunięty lub ukryty albo nigdy nie został udostępniony.",
  },
  myPromptListsPage: {
    inCommunityCatalogue: "W katalogu społeczności",
    notPublished: "Nieopublikowana",
    publishedExplainer: "Każdy może znaleźć tę listę, zagrać nią, oznaczyć ją gwiazdką lub zrobić sobie jej kopię.",
    unpublishedExplainer: "Po opublikowaniu każdy może znaleźć tę listę i nią zagrać. W każdej chwili możesz wycofać publikację.",
    saveBeforePublishing: "Najpierw zapisz listę. Pozostanie prywatna, dopóki jej nie opublikujesz.",
    publishNeedsAnEmail: "Aby publikować, dodaj do konta adres e-mail i go potwierdź. Adres pozostaje prywatny: dzięki niemu opublikowana lista jest powiązana z prawdziwą osobą.",
    publishNeedsConfirmation: (p: { address: string }) => `Potwierdź adres ${p.address}, korzystając z wysłanego przez nas e-maila, a potem możesz publikować.`,
    publishNeedsEmailDelivery: "Publikowanie wymaga potwierdzonego adresu e-mail, a ten serwer nie może wysyłać e-maili.",
    addAnEmail: "Dodaj e-mail",
    changeEmail: "Zmień e-mail",
    duplicate: "Zduplikuj",
    duplicateName: (p: { name: string }) => `${p.name} (kopia)`,
    listDuplicated: (p: { name: string }) => `Zduplikowano jako „${p.name}”.`,
    couldNotDuplicateThisList: "Nie udało się zduplikować tej listy.",
    reload: "Wczytaj ponownie",
    starCount: (p: { count: number }) =>
      counted(p.count, { one: "gwiazdka", few: "gwiazdki", many: "gwiazdek", other: "gwiazdki" }),
    copyCount: (p: { count: number }) =>
      counted(p.count, { one: "kopia", few: "kopie", many: "kopii", other: "kopii" }),
    copiedFrom: "Skopiowano z listy {list} (autor: {owner})",
    copiedFromADeletedList: "Skopiowano z listy, która została usunięta",
    publish: "Opublikuj",
    unpublish: "Wycofaj publikację",
    promptListPublished: "Opublikowano listę haseł.",
    promptListUnpublished: "Wycofano publikację listy haseł.",
    couldNotChangePublication: "Nie udało się zmienić stanu publikacji tej listy.",
    unpublishedChanges: "Nieopublikowane zmiany",
    unpublishedChangesExplainer: "Inni nadal widzą wersję, którą opublikowano ostatnio. Opublikuj aktualizację, aby pokazać im zmiany, albo je odrzuć, aby wrócić do tamtej wersji.",
    updateUnderReview: "Aktualizacja w weryfikacji",
    updateUnderReviewExplainer: "Inni nadal widzą wersję, którą opublikowano ostatnio. Aktualizacja pojawi się, gdy zatwierdzi ją moderator.",
    publicationUnderReview: "Czeka na weryfikację",
    publicationUnderReviewExplainer: "Moderator sprawdza tę listę, zanim pojawi się w katalogu społeczności.",
    publishUpdate: "Opublikuj aktualizację",
    discardChanges: "Odrzuć zmiany",
    publishUpdateTitle: "Opublikować tę aktualizację?",
    publishUpdateOrderOnly: "Inni zobaczą hasła w nowej kolejności.",
    discardChangesTitle: "Odrzucić zmiany?",
    discardChangesDescription: "Lista wraca do wersji, którą widzą inni. Wszystko, co zmieniono od ostatniej publikacji, przepadnie.",
    promptsAdded: (p: { count: number; prompts: string }) => `Dodane (${p.count}): ${p.prompts}.`,
    promptsRemoved: (p: { count: number; prompts: string }) => `Usunięte (${p.count}): ${p.prompts}.`,
    promptsReworded: (p: { count: number; prompts: string }) => `Przeredagowane (${p.count}): ${p.prompts}.`,
    nameChanged: "Nowa nazwa.",
    descriptionChanged: "Nowy opis.",
    tagsChanged: "Nowe tagi.",
    saveBeforePublishingUpdate: "Najpierw zapisz zmiany: aktualizacja publikuje zapisaną listę.",
    promptListUpdatePublished: "Aktualizacja opublikowana.",
    promptListUpdateSentForReview: "Aktualizacja wysłana do weryfikacji.",
    changesDiscarded: "Zmiany odrzucone.",
    couldNotDiscardChanges: "Nie udało się odrzucić zmian.",
    couldNotReadPublishedVersion: "Nie udało się wczytać opublikowanej wersji do porównania.",
    changedSinceReview: "Zmieniono od wysłania do weryfikacji",
    changedSinceReviewExplainer: "Wersja w weryfikacji nie zawiera ostatnich zmian. Opublikuj aktualizację, aby wysłać tę wersję zamiast niej.",
    replacesPendingVersion: "Ta wersja zastąpi tę, która jest w weryfikacji.",
    andNMore: (p: { count: number }) => `i ${p.count} więcej`,
    published: "Opublikowana",
    tags: "Tagi",
    tagsChosen: (p: { chosen: number; max: number }) => `Wybrano ${p.chosen} z ${p.max}`,
    addTag: "Dodaj",
    tagsDone: "Gotowe",
    changeTags: "Zmień",
    removeTag: (p: { tag: string }) => `Usuń: ${p.tag}`,
    listSummary: (p: { prompts: number; visibility: string; moderationState: string | null }) =>
      `${counted(p.prompts, { one: "hasło", few: "hasła", many: "haseł", other: "hasła" })} · ${p.visibility}${
        p.moderationState ? ` · ${p.moderationState}` : ""
      }`,
    underReview: "W weryfikacji",
    hidden: "Ukryta",
    listUnderReviewWarning: "Ta lista jest w weryfikacji i nie można jej używać w nowych grach. Edycja nie przywraca jej automatycznie – listę musi sprawdzić moderator.",
    listHiddenWarning: "Ta lista jest ukryta i nie można jej używać w nowych grach. Edycja nie przywraca jej automatycznie – listę musi sprawdzić moderator.",
    needsReview: (p: { count: number }) => `Do sprawdzenia (${p.count})`,
    removePrompt: (p: { prompt: string }) => `Usuń: ${p.prompt}`,
    couldNotLoadYourPromptLists: "Nie udało się wczytać twoich list haseł.",
    couldNotOpenThatPromptList: "Nie udało się otworzyć tej listy haseł.",
    addAtLeastOnePromptBefore: "Przed zapisaniem dodaj co najmniej jedno hasło.",
    couldNotSaveThisPromptList: "Nie udało się zapisać tej listy haseł.",
    couldNotDeleteThisPromptList: "Nie udało się usunąć tej listy haseł.",
    myPromptLists: "Moje listy haseł",
    newList: "Nowa lista",
    promptListsNeedAnAccount: "Listy haseł wymagają konta",
    promptListsNeedAnAccountBody: "Konto przechowuje twoje listy, żeby można było nimi grać w każdym pokoju, którego jesteś gospodarzem, i – jeśli chcesz – je publikować. Własne hasła wpisane w pokoju nie są zapisywane.",
    loading: "Wczytywanie…",
    noSavedListsYet: "Nie masz jeszcze zapisanych list.",
    name: "Nazwa",
    description: "Opis",
    language: "Język",
    private: "Prywatna",
    addPrompts: "Dodaj hasła",
    onePromptPerLineSeparateEntries: "Jedno hasło w wierszu\nlub oddzielaj wpisy przecinkami",
    addList: "Dodaj do listy",
    noPromptsYetPasteSomeAbove: "Nie ma jeszcze haseł. Wklej kilka powyżej, żeby zacząć.",
    thisList: "Na tej liście",
    searchPrompts: "Szukaj haseł",
    nothingMatchesThatSearch: "Nic nie pasuje do wyszukiwania.",
    deleteList: "Usuń listę…",
    promptListSaved: "Zapisano listę haseł.",
    deleteListTitle: (p: { name: string }) => `Usunąć „${p.name}”?`,
    deleteListDescription: "Zniknie z twoich list, a jeśli jest opublikowana – także z katalogu społeczności. Rozegrane już gry zachowają użyte hasła.",
    deleteListConfirm: "Usuń listę",
    promptListDeleted: "Usunięto listę haseł.",
    backToLobby: "Wróć do lobby",
    promptsCountOfMaxListPrompts:
      (p: { promptsCount: number; MAX_LIST_PROMPTS: number }) => `${p.promptsCount} z ${p.MAX_LIST_PROMPTS} haseł na tej liście`,
    saving: "Zapisywanie…",
    saveList: "Zapisz listę",
    promptCount: (p: { count: number }) =>
      counted(p.count, { one: "hasło", few: "hasła", many: "haseł", other: "hasła" }),
    visibleOfTotal: (p: { visible: number; total: number }) =>
      `${p.visible} z ${p.total}`,
  },

  notFoundPage: {
    nobodyDrewThisPage: "Nikt nie narysował tej strony",
    pageNotFound: "Nie znaleziono strony",
    thatLinkDoesnTLeadAnywhere: "Ten link nie prowadzi nigdzie w Sketchy.",
    backLobby: "Wróć do lobby",
  },

  onlinePlayersPanel: {
    couldNotJoinThatGame: "Nie udało się dołączyć do tej gry.",
    whoOnline: "Kto jest online",
    nobodyElseHereRightNow: "Nikogo innego tu teraz nie ma.",
    friend: "Znajomy",
    join: "Dołącz",
    inAGame: "W grze",
    inTheLobby: "W lobby",
  },

  pictureCropDialog: {
    fileNotAPicture: "Tego pliku nie da się odczytać jako obrazu.",
    couldNotSetThatPicturePlease: "Nie udało się ustawić tego zdjęcia. Spróbuj ponownie.",
    frameYourPicture: "Wykadruj zdjęcie",
    dragMoveZoomGetCloserCircle: "Przeciągnij, żeby przesunąć, i powiększ, żeby przybliżyć. Wszyscy widzą to, co jest w kółku.",
    pictureFramedArrowKeysMovePlus: "Wykadrowane zdjęcie. Strzałki je przesuwają, plus i minus zmieniają powiększenie.",
    zoom: "Powiększenie",
    cancel: "Anuluj",
    uploading: "Przesyłanie…",
    usePicture: "Użyj zdjęcia",
  },

  playerList: {
    requestCouldNotBeSent: "Nie udało się wysłać tego zaproszenia.",
    nowFriends: (p: { name: string }) => `Ty i ${p.name} jesteście teraz znajomymi.`,
    friendRequestSent: (p: { name: string }) => `Wysłano zaproszenie do znajomych: ${p.name}.`,
    rank: (p: { rank: number }) => `Miejsce ${p.rank}`,
    actionsFor: (p: { name: string; canVote: boolean; canReport: boolean }) =>
      p.canVote
        ? p.canReport ? `Głosowanie za wyrzuceniem, głosowanie AFK lub zgłoszenie: ${p.name}` : `Głosowanie za wyrzuceniem lub głosowanie AFK: ${p.name}`
        : `Zgłoś: ${p.name}`,
    whatToDoAbout: (p: { name: string }) => `${p.name}: co chcesz zrobić?`,
    drawing: "Rysuje",
    gotIt: "Trafione ·",
    afk: "AFK",
    you: "(ty)",
    host: "Gospodarz",
    friend: "Znajomy",
    disconnected: "Brak połączenia",
    kick: "Wyrzuć",
    addFriend: "Dodaj znajomego",
    sendRequest: "Wyślij zaproszenie",
    report: "Zgłoś",
    toAModerator: "Do moderatora",
    choosing: "Wybiera",
    undoVote: "Cofnij głos",
    vote: "Głosuj",
    voteKindAfk: "AFK",
    voteKindKick: "Wyrzucenie",
    undoVoteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Cofnij głos (${p.kind}) – ${p.nickname}, ${p.count} z ${p.required}`,
    voteFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Zagłosuj (${p.kind}) – ${p.nickname}, ${p.count} z ${p.required}`,
    votesFor: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Głosy (${p.kind}) – ${p.nickname}, ${p.count} z ${p.required}`,
    votesForIncludingYours: (p: { kind: string; nickname: string; count: number; required: number }) =>
      `Głosy (${p.kind}) – ${p.nickname}, ${p.count} z ${p.required}, w tym twój`,
    guestName: (p: { nickname: string }) =>
      `${p.nickname} (gość)`,
  },

  profilePage: {
    playsIn: (p: { language: string }) => `Język gry: ${p.language}`,
    playsInAlso: (p: { language: string; others: string }) => `Język gry: ${p.language}; także: ${p.others}`,
    gamesPlayed: "Rozegrane gry",
    gamesWon: "Wygrane gry",
    winRate: "Odsetek wygranych",
    averageScore: "Średni wynik",
    turnsPlayed: "Rozegrane tury",
    promptsGuessed: "Odgadnięte hasła",
    drawingsMade: "Wykonane rysunki",
    reactionsReceived: "Otrzymane reakcje",
    totalScore: "Łączny wynik",
    noSuchProfile: "Nie ma gracza z takim profilem.",
    couldNotLoadProfile: "Nie udało się wczytać tego profilu. Spróbuj ponownie.",
    gameMeta: (p: { finishedAt: string; rounds: number; players: number }) =>
      `${p.finishedAt} · ${counted(p.rounds, { one: "runda", few: "rundy", many: "rund", other: "rundy" })} · ${counted(p.players, { one: "gracz", few: "graczy", many: "graczy", other: "gracza" })}`,
    seatScore: (p: { points: number }) => counted(p.points, { one: "punkt", few: "punkty", many: "punktów", other: "punktu" }),
    gameRules: (p: { scoring: string; hints: string; seconds: number; promptSource: string }) =>
      `Zasady: ${p.scoring} · ${p.hints} · ${p.seconds} s · ${p.promptSource}`,
    reportPlayer: (p: { name: string }) => `Zgłoś: ${p.name}`,
    privateRoom: "pokój prywatny",
    thisGameEndedEarly: "Ta gra zakończyła się przedwcześnie, więc to wyniki z chwili jej przerwania, a nie końcowa klasyfikacja.",
    loadingTurns: "Wczytywanie tur…",
    turnByTurn: "Tura po turze",
    round: "Runda",
    prompt: "Hasło",
    drawnBy: "Rysujący",
    time: "Czas",
    drawing: "Rysunek",
    reactions: "Reakcje",
    guesserOutcomes: "Wyniki zgadujących",
    view: "Pokaż",
    couldNotLoadMoreGames: "Nie udało się wczytać kolejnych gier.",
    loading: "Wczytywanie…",
    friend: "Znajomy.",
    claimYourAccount: "Przejmij swoje konto",
    yourGamesAreAlreadyBeingRecorded: "Twoje gry są już zapisywane pod tą wyświetlaną nazwą.\n                Utwórz konto, aby je zachować i używać tej nazwy jako nazwy użytkownika na każdym urządzeniu.",
    createAccount: "Utwórz konto",
    statistics: "Statystyki",
    gameHistory: "Historia gier",
    includeAbandonedGames: "Pokaż porzucone gry",
    winsAndScoresAppearAfterFirstGame: "Wygrane i wyniki pojawią się po pierwszej ukończonej grze.",
    notKept: "nie zachowano",
    pinnedDrawings: "Przypięte rysunki",
    nothingPinnedYet: "Nic jeszcze nie przypięto. Przypnij rysunek z podsumowania gry albo z gry w historii poniżej.",
    openPinnedDrawing: (p: { prompt: string; drawer: string }) => `Otwórz ${p.prompt} (autor: ${p.drawer})`,
    moveLeft: "Przesuń w lewo",
    moveRight: "Przesuń w prawo",
    unpin: "Odepnij",
    couldNotUpdatePinnedDrawings: "Nie udało się zaktualizować przypiętych rysunków. Spróbuj ponownie.",
    couldNotLoadThisDrawing: "Nie udało się wczytać tego rysunku.",
    nothingDrawn: "nic nie narysowano",
    onlyThePlayersInThis: "Tury tej gry widzą tylko jej gracze.",
    couldNotLoadTheTurns: "Nie udało się wczytać tur tej gry.",
    cutShort: "przerwana",
    abandoned: "porzucona",
    noAttempt: "bez próby",
    joinedLate: "dołączenie w trakcie",
    notEligibleAfk: "nie liczy się (AFK)",
    notEligibleDisconnected: "nie liczy się (brak połączenia)",
    notEligible: "nie liczy się",
    noGuessers: "brak zgadujących",
    promptSourceCurated: "Wyselekcjonowane hasła",
    promptSourceCustom: "Własne hasła",
    promptSourceMixed: "Mieszane hasła",
    promptSourceBuiltinFallback: "Wbudowane hasła zapasowe",
    unknownPlayer: "Nieznany gracz",
    backToLobby: "Wróć do lobby",
    guest: "Gość",
    registeredPlayer: "Zarejestrowany gracz",
    noFinishedGamesYetPlay: "Nie ma jeszcze ukończonych gier. Zagraj, a gra pojawi się tutaj.",
    noGamesToShowGames:
      "Brak gier do wyświetlenia. Gry z pokoi prywatnych widzą tylko gracze, którzy w nich byli.",
    loadHistoryPageSizeMore:
      (p: { HISTORY_PAGE_SIZE: number }) => `Wczytaj jeszcze ${p.HISTORY_PAGE_SIZE}`,
    correctWithPoints: (p: { points: number }) =>
      `trafione, ${p.points}`,
    wrongCount: (p: { count: number }) =>
      `błędne: ${p.count}`,
    joinedOn: (p: { date: string }) =>
      `dołączenie: ${p.date}`,
  },

  promptContentReportDialog: {
    reportList: (p: { name: string }) => `Zgłoś: ${p.name}`,
    reportsAreReviewedAfterSubmissionList: "Zgłoszenia są sprawdzane po wysłaniu. Lista pozostaje dostępna, chyba że moderator ją ukryje.",
    sentWithTheListAttached: "Wysłano wraz z kopią listy w obecnej postaci.",
    content: "Treść",
    entireList: "Cała lista",
    reason: "Powód",
    inappropriateContent: "Nieodpowiednie treści",
    hatefulOrAbusiveContent: "Treści nienawistne lub obraźliwe",
    sexualContent: "Treści seksualne",
    violence: "Przemoc",
    spam: "Spam",
    other: "Inne",
  },

  promptDisplay: {
    couldNotDoAction: (p: { action: string }) => `Nie udało się: ${p.action}.`,
    nextHintCost: (p: { cost: number }) =>
      `Wybierz puste pole, aby je odsłonić · ${counted(p.cost, { one: "punkt", few: "punkty", many: "punktów", other: "punktu" })}`,
    hintSpendTotal: (p: { spent: number }) =>
      `Razem: ${counted(p.spent, { one: "punkt", few: "punkty", many: "punktów", other: "punktu" })}`,
    buyLetter: (p: { letter: string; price: number }) =>
      `Kup „${p.letter}” za ${counted(p.price, { one: "punkt", few: "punkty", many: "punktów", other: "punktu" })}`,
    maskedPrompt: (p: { shape: string }) => `Ukryte hasło, liczba liter: ${p.shape}`,
    buyThisLetter: (p: { cost: number }) =>
      `Kup tę literę za ${counted(p.cost, { one: "punkt", few: "punkty", many: "punktów", other: "punktu" })}`,
    letterCount: (p: { count: number }) =>
      counted(p.count, { one: "litera", few: "litery", many: "liter", other: "litery" }),
    yourTurn: "Twoja tura",
    pickSomethingDraw: "Wybierz, co narysujesz",
    autoPicksWhenTimeRunsOut: "Gdy skończy się czas, wybór nastąpi automatycznie.",
    hintSpendLimitReached: "Osiągnięto limit wydatków na podpowiedzi",
    hintSpendComesOutOfTurnPoints: "Zostanie odjęte od punktów za tę turę, jeśli odgadniesz hasło.",
    buyALetter: "Kup literę",
    buyLetterRevealsEveryMatch: "Kup literę — odsłania wszystkie wystąpienia",
    selectThePrompt: "wybór hasła",
    choosing: "Wybieranie…",
    buyTheHint: "kupno podpowiedzi",
    buyTheLetterHint: "kupno litery",
  },

  promptListPicker: {
    listsYouStarred: "Listy oznaczone przez ciebie gwiazdką",
    starredNotAllShown: (p: { shown: number }) => `Wyświetlono tylko pierwsze listy oznaczone przez ciebie gwiazdką (${number(p.shown)}).`,
    choicesUnavailable: (p: { reason: string }) =>
      `Wybór list haseł jest niedostępny (${p.reason}). Twój obecny wybór się nie zmienił.`,
    noListsInLanguage: (p: { language: string }) =>
      `Nie ma jeszcze list haseł w języku: ${p.language} — ten pokój korzysta z własnych haseł.`,
    howListPlays: (p: { name: string }) => `Jak wypadają hasła z listy ${p.name}`,
    couldNotLoadPromptLists: "Nie udało się wczytać list haseł.",
    loadingCuratedPromptLists: "Wczytywanie wyselekcjonowanych list haseł…",
    promptLists: "Listy haseł",
    namePromptCountPrompts:
      (p: { name: string; promptCount: number }) => `${p.name} (hasła: ${p.promptCount})`,
    yourLists: "Twoje listy",
    fromCommunityCatalogue: "Z katalogu społeczności",
    /** A shelf's name, by its slug (`lib/promptListTree.ts`, R-PROMPT-14). */
    shelves: { everyday: "Na co dzień", "video-games": "Gry wideo", "pop-culture": "Popkultura", places: "Miejsca" } satisfies Record<PromptShelf, string>,
    /** A series's name, by its slug; one without falls back to its slug. */
    series: { pokemon: "Pokémon" } as Record<string, string>,
    chosenCount: (p: { count: number }) => `wybrano: ${number(p.count)}`,
    seriesChosen: (p: { chosen: number; total: number }) => `${number(p.chosen)} z ${number(p.total)}`,
    showSeries: (p: { name: string }) => `Pokaż listy: ${p.name}`,
    hideSeries: (p: { name: string }) => `Ukryj listy: ${p.name}`,
    tooManyLists: (p: { max: number }) => `Pokój może korzystać z najwyżej ${number(p.max)} list. Odznacz kilka, zanim przejdziesz dalej.`,
  },

  promptStatsPage: {
    noSuchList: "Nie ma listy haseł o tej nazwie.",
    couldNotLoadStats: "Nie udało się wczytać statystyk haseł. Spróbuj ponownie.",
    showMore: (p: { count: number }) => `Pokaż jeszcze ${p.count}`,
    showingOf: (p: { shown: number; total: number }) => `Wyświetlono ${p.shown} z ${p.total}`,
    couldNotLoadPromptListsPlease: "Nie udało się wczytać list haseł. Spróbuj ponownie.",
    serverWide: "Cały serwer",
    promptStats: "Statystyki haseł",
    everyPromptListHowHasActually: "Każde hasło z listy i to, jak naprawdę wypadało w ukończonych\n          grach na tym serwerze.",
    promptList: "Lista haseł",
    sort: "Sortowanie",
    period: "Okres",
    scoring: "Punktacja",
    hints: "Podpowiedzi",
    findPrompt: "Znajdź hasło",
    loading: "Wczytywanie…",
    prompt: "Hasło",
    howHard: "Trudność",
    guessed: "Odgadnięte",
    picked: "Wybrane",
    drawn: "Narysowane",
    allTime: "Od początku",
    last30Days: "Ostatnie 30 dni",
    last90Days: "Ostatnie 90 dni",
    allScoringModes: "Wszystkie tryby punktacji",
    noScoring: "Bez punktacji",
    defaultScoring: "Punktacja domyślna",
    pressureScoring: "Punktacja pod presją",
    allHintModes: "Wszystkie tryby podpowiedzi",
    backToLobby: "Wróć do lobby",
  },

  publicRoomCard: {
    roundCount: (p: { count: number }) =>
      counted(p.count, { one: "runda", few: "rundy", many: "rund", other: "rundy" }),
    promptLanguage: (p: { language: string }) => `Język haseł: ${p.language}`,
    seeWhoThisRoom: "Zobacz, kto jest w tym pokoju",
    rounds: "Rundy",
    drawingTime: "Czas rysowania",
    full: "Pełny",
    inProgress: "Gra trwa",
    loading: "Wczytywanie…",
    nobodySeatedYet: "Nikt jeszcze nie zajął miejsca.",
    host: "Gospodarz",
    couldNotReadWhoIs: "Nie udało się sprawdzić, kto jest w tym pokoju.",
    joining: "Dołączanie…",
    join: "Dołącz",
    spectate: "Oglądaj",
    waiting: "Oczekiwanie",
    seatsOpen: (p: { count: number }) => `Wolne miejsca: ${number(p.count)}`,
    noSeatsOpen: "Brak wolnych miejsc",
    watching: (p: { count: number }) => `Widzowie: ${number(p.count)}`,
    gameLength: (p: { minutes: number }) => `~${number(p.minutes)} min`,
    gameLengthRange: (p: { low: number; high: number }) => `~${number(p.low)}–${number(p.high)} min`,
    standardRules: "Standardowe zasady",
    moreRules: (p: { count: number }) => `+${number(p.count)} więcej`,
    columnRoom: "Pokój",
    columnSeats: "Miejsca",
    columnLength: "Długość",
    columnRoomRules: "Zasady pokoju",
  },

  recapDrawings: {
    thisDrawingCouldNotBeLoaded: "Nie udało się wczytać tego rysunku.",
  },

  reportAccountDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Zobaczy to moderator. ${p.name} na razie nie ponosi żadnych konsekwencji i nie dowie się, kto to zgłosił.`,
    theirPicture: (p: { name: string }) => `Zdjęcie: ${p.name}`,
    whatWrongWith: "Co jest nie tak",
    reportedTheirNameTheyHaveNo: "Zgłoszenie dotyczy nazwy. Ten gracz nie ma zdjęcia do zgłoszenia.",
    sentWithWhatAboutAttached: "Wysłano wraz z tym, czego dotyczy zgłoszenie.",
    inappropriateName: "Nieodpowiednia nazwa",
    inappropriatePicture: "Nieodpowiednie zdjęcie",
    reportDisplayName: (p: { displayName: string }) => `Zgłoś: ${p.displayName}`,
    thePictureOnTheAccount: "Dołączono zdjęcie z konta w obecnej postaci.",
    theNameOnTheAccount: "Dołączono nazwę z konta w obecnej postaci.",
  },
  reportDialog: {
    sendReport: "Wyślij zgłoszenie",
    sending: "Wysyłanie…",
    reportSent: "Zgłoszenie wysłane",
    anythingElseOptional: "Coś jeszcze (opcjonalnie)",
    anythingModeratorShouldKnow: "Wszystko, co moderator powinien wiedzieć",
    couldNotSend: "Nie udało się wysłać zgłoszenia.",
    charactersLeft: (p: { count: number }) =>
      `${plural(p.count, { one: "Pozostał", few: "Pozostały", many: "Pozostało", other: "Pozostało" })} ${counted(p.count, { one: "znak", few: "znaki", many: "znaków", other: "znaku" })}`,
  },
  reportDrawingDialog: {
    reportThisDrawing: "Zgłoś ten rysunek",
    nothingHappensYet: "Moderator obejrzy rysunek. Do tego czasu gracz nie ponosi żadnych konsekwencji.",
    sentWithTheDrawingAttached: "Wysłano wraz z rysunkiem.",
  },

  reportedDrawing: {
    thisDrawingCouldNotBeDecoded: "Nie udało się odkodować tego rysunku.",
    drawingCouldNotBeLoaded: "Nie udało się wczytać rysunku.",
    loadingTheDrawing: "Wczytywanie rysunku…",
  },

  reportLobbyLineDialog: {
    nothingHappensYet: (p: { name: string }) =>
      `Moderator zobaczy tę wiadomość. ${p.name} na razie nie ponosi żadnych konsekwencji i nie dowie się, kto to zgłosił.`,
    whatWrongWith: "Co jest nie tak",
    thisLineAttachedWithWhatLobby: "Ta wiadomość zostanie dołączona wraz z tym, co pisano wokół niej w lobby.",
    sentWithLineWhatWasSaid: "Wysłano wraz z wiadomością i tym, co pisano wokół niej.",
    harassmentOrAbuse: "Nękanie lub obraźliwe zachowanie",
    spam: "Spam",
    inappropriateName: "Nieodpowiednia nazwa",
    reportDisplayName: (p: { displayName: string }) => `Zgłoś: ${p.displayName}`,
  },

  reportPlayerDialog: {
    recentMessages: (p: { count: number }) =>
      `${p.count} ${plural(p.count, { one: "ostatnia wiadomość", few: "ostatnie wiadomości", many: "ostatnich wiadomości", other: "ostatniej wiadomości" })} gracza`,
    nothingHappensYet: (p: { name: string }) =>
      `Zobaczy to moderator. ${p.name} na razie nie ponosi żadnych konsekwencji i nie dowie się, kto to zgłosił.`,
    whatHappened: "Co się stało",
    whatTheySaidDrewWhen: "Co ten gracz napisał lub narysował i kiedy",
    theirRecentMessagesThisRoomAre: "Ostatnie wiadomości tego gracza w tym pokoju są dołączane automatycznie\n                wraz z kontekstem, więc to pole można zostawić puste.",
    includeTheirDrawing: "Dołącz rysunek gracza",
    canvasAsRightNowSoModerator: "Płótno w obecnej postaci, żeby moderator zobaczył to,\n                      co ty.",
    sentWithTheirDrawingAnd:
      (p: { messages: string }) => `Wysłano. Dołączono: rysunek gracza i ${p.messages}.`,
    sentWithTheirDrawingAttached: "Wysłano wraz z rysunkiem gracza.",
    sentWithMessagesAttached: (p: { messages: string }) => `Wysłano. Dołączono: ${p.messages}.`,
    sentTheyHadSaidNothing:
      "Wysłano. Ten gracz nic nie napisał w tym pokoju, więc nie dołączono żadnych wiadomości.",
    baseTheTurnHadEnded:
      (p: { base: string }) => `${p.base} Tura już się skończyła, więc nie udało się dołączyć rysunku.`,
    harassmentOrAbuse: "Nękanie lub obraźliwe zachowanie",
    offensiveDrawing: "Obraźliwy rysunek",
    inappropriateName: "Nieodpowiednia nazwa",
    cheating: "Oszukiwanie",
    spam: "Spam",
    inappropriatePicture: "Nieodpowiednie zdjęcie",
    sendThatReport: "wysłanie zgłoszenia",
    reportNickname: (p: { nickname: string }) => `Zgłoś: ${p.nickname}`,
  },

  restartVoteBanner: {
    proposerProposedRestarting: (p: { proposerNickname: string }) =>
      `${p.proposerNickname} proponuje restart gry.`,
    restartingIn: (p: { seconds: number }) =>
      `Restart za ${counted(p.seconds, { one: "sekundę", few: "sekundy", many: "sekund", other: "sekundy" })}`,
    restartApproved: "Restart zatwierdzony!",
    voteRestartGame: "Głosuj za restartem gry",
    restart: "Restart",
    keepPlaying: "Grajmy dalej",
    onlyEligiblePlayersPresentWhenVote: "Głosować mogą tylko uprawnieni gracze obecni w chwili rozpoczęcia głosowania.",
    proposerNicknameProposedRestartingRemainingS:
      (p: { proposerNickname: string; remaining: number }) => `${p.proposerNickname} proponuje restart · ${p.remaining} s`,
    theCurrentGameIsRestarting: "Gra właśnie zaczyna się od nowa.",
    yesYesNoNoPending:
      (p: { yes: number; no: number; pending: number; requiredVotes: number }) => `za: ${p.yes} · przeciw: ${p.no} · bez głosu: ${p.pending} · potrzeba: ${p.requiredVotes}`,
  },

  roomChatPanel: {
    unreadMessages: (p: { count: number }) =>
      `${counted(p.count, { one: "nowa wiadomość", few: "nowe wiadomości", many: "nowych wiadomości", other: "nowej wiadomości" })}`,
    correctWithPlace: (p: { place: string | null }) =>
      p.place ? `Trafione · ${p.place}` : "Trafione",
    couldNotSendMessage: "Nie udało się wysłać wiadomości.",
    sent: "Wysłano:",
    send: "Wyślij",
    youReDrawingWatchGuessesCome: "Rysujesz — patrz, jak spływają odpowiedzi.",
    yourGuessTrimmedDidNot:
      (p: { trimmed: string }) => `Twoja odpowiedź „${p.trimmed}” nie dotarła do serwera. Wyślij ją ponownie.`,
    sendTheMessage: "wysłanie wiadomości",
    chatWhileYouWait: "Pogadaj na czacie, czekając",
    gameChat: "Czat gry",
    guessAndChat: "Zgaduj i pisz",
    guessesAndChat: "Odpowiedzi i czat",
    roomChat: "Czat pokoju",
    sayHelloBeforeTheGame: "Przywitaj się przed rozpoczęciem gry.",
    noMessagesYet: "Nie ma jeszcze wiadomości.",
    typeYourGuess: "Wpisz odpowiedź…",
    youGuessFromTheNextTurn: "Na razie tylko czat: zgadujesz od następnej tury",
    typeAMessage: "Napisz wiadomość…",
  },

  roomEntryState: {
    thisRoomNoLongerAvailable: "Ten pokój nie jest już dostępny.",
    couldNotJoinThisRoom: "Nie udało się dołączyć do tego pokoju.",
    thatNameIsReservedPlease: "Ten pseudonim jest zarezerwowany. Wybierz inny.",
    thisRoomHasEndedAsk: "Ten pokój został zamknięty. Poproś gospodarza o nowe zaproszenie.",
    loadThisRoom: "wczytanie tego pokoju",
    enterANicknameToContinue: "Wpisz pseudonim, aby kontynuować.",
    theLastPlayerSeatWasTaken: "Ostatnie miejsce dla gracza właśnie zostało zajęte, ale nadal możesz oglądać.",
    joinAsASpectator: "dołączenie jako widz",
    joinThisRoom: "dołączenie do tego pokoju",
    nicknameRule: "Od 3 do 16 znaków: litery, cyfry, łączniki lub podkreślenia. Bez spacji.",
  },

  roomFacts: {
    seats: "Miejsca",
    customShort: (p: { count: number }) =>
      `własne: ${number(p.count)}`,
    customOnlyShort: (p: { count: number }) =>
      `tylko własne: ${number(p.count)}`,
    listsShort: (p: { count: number }) =>
      counted(p.count, { one: "lista", few: "listy", many: "list", other: "listy" }),
    also: "Także",
    spectatorsSeeThePrompt: "Widzowie widzą hasło",
  },

  roomMenuSheet: {
    afk: "AFK",
    startTheGameOver: "Zacznij grę od nowa",
    startOverCooldown: (p: { seconds: number }) => ` · za ${p.seconds} s`,
    room: "Pokój",
    close: "Zamknij",
    playersScores: "Gracze i wyniki",
    copyInviteLink: "Skopiuj link z zaproszeniem",
    saveImage: "Zapisz obraz",
    leaveRoom: "Opuść pokój",
    backFromAfk: "Wróć z AFK",
    goAfk: "Przejdź w tryb AFK",
  },

  roomNoticeChips: {
    serverUpdateWord: "Aktualizacja ·",
    restartVote: "Głosowanie za restartem ·",
    restarting: "Restart ·",
    serverUpdateSeconds: (p: { seconds: number }) =>
      p.seconds > 0 ? `${p.seconds} s` : "teraz",
    reconnecting: "Ponowne łączenie",
    disconnected: "Rozłączono",
    rejoinFailed: "Nie udało się wrócić",
    invitation: "Zaproszenie",
    friendRequest: (p: { count: number }) =>
      plural(p.count, { one: "Zaproszenie do znajomych", few: "Zaproszenia do znajomych", many: "Zaproszenia do znajomych", other: "Zaproszenia do znajomych" }),
    serverUpdateStarted: "Trwa aktualizacja serwera. Ta gra wkrótce się zakończy.",
  },

  roomPlayersPanel: {
    you: "(ty)",
    spectatorCount: (p: { count: number }) =>
      counted(p.count, { one: "widz", few: "widzów", many: "widzów", other: "widza" }),
    spectatorsHeading: (p: { count: number }) => `Widzowie (${p.count})`,
    playersOfCapacity: (p: { here: number; capacity: number }) =>
      `${p.here} z ${p.capacity} graczy`,
    readyCount: (p: { count: number }) => `Gotowi: ${p.count}`,
    couldNotJoinAsPlayer: "Nie udało się dołączyć jako gracz.",
    finalStandings: "Klasyfikacja końcowa",
    players: "Gracze",
    joinAsAPlayer: "dołączenie jako gracz",
    youAreSpectating: "Oglądasz grę.",
    aPlayerSeatIsOpen: "Jest wolne miejsce dla gracza.",
    noPlayerSeatsOpen: "Brak wolnych miejsc dla graczy.",
    joining: "Dołączanie…",
    joinAsPlayer: "Dołącz jako gracz",
  },

  roomSettingsEditor: {
    couldNotLoadRoomRules: "Nie udało się wczytać zasad pokoju.",
    roomRefusedThoseRules: "Pokój nie przyjął tych zasad.",
    editRoomRules: "Edytuj zasady pokoju",
    loadingRoomRules: "Wczytywanie zasad pokoju…",
    cancel: "Anuluj",
    loadRoomRules: "wczytanie zasad pokoju",
    saveRoomRules: "zapisanie zasad pokoju",
    saving: "Zapisywanie…",
    saveRules: "Zapisz zasady pokoju",
  },

  roomSetupForm: {
    promptLanguage: "Język haseł",
    customPromptsOffInMixedRooms: "W pokoju mieszanym własne hasła są wyłączone: każdy gracz potrzebuje hasła we własnym języku.",
    visibility: "Widoczność",
    maxPlayers: "Maks. liczba graczy",
    rounds: "Rundy",
    drawingTime: "Czas rysowania",
    onlyUseCustomPrompts: "Używaj tylko własnych haseł",
    addUsableCustomPromptEnableThis: "Dodaj co najmniej jedno poprawne własne hasło, aby włączyć tę opcję.",
    allowedTools: "Dozwolone narzędzia",
    colors: "Kolory",
    scoring: "Punktacja",
    hints: "Podpowiedzi",
    spectatorsCanSeePrompt: "Widzowie widzą hasło",
    hideLetterTiles: "Ukryj pola liter",
    alsoTurnsHintsOffWithNo: "Wyłącza też podpowiedzi: bez pól nie ma czego odsłaniać.",
    promptTotal: (p: { count: number }) =>
      counted(p.count, { one: "hasło", few: "hasła", many: "haseł", other: "hasła" }),
    basics: "Podstawy",
    roomName: "Nazwa pokoju",
    public: "Publiczny",
    private: "Prywatny",
    prompts: "Hasła",
    drawing: "Rysowanie",
    scoringHints: "Punktacja i podpowiedzi",
    hintsAreOffBecauseTilesAreHidden: "Podpowiedzi są wyłączone, bo pola liter są ukryte.",
    buyLettersAndWheelNeedScoring: "Kupowanie liter i Koło fortuny wymagają punktacji.",
    allColors: "Wszystkie kolory",
    noScoring: "Bez punktacji",
    listedInTheLobbyAnyone: "Widoczny w lobby — każdy może wejść.",
    joinableOnlyWithTheCode: "Dołączyć można tylko przez kod lub link z zaproszeniem.",
    customCount: (p: { count: number }) =>
      `własne: ${number(p.count)}`,
  },

  scratchPad: {
    title: "Brudnopis",
    drawWhileYouWait: "Porysuj, czekając",
    canvasLabel: "Brudnopis. Tylko ty widzisz, co tu rysujesz.",
    save: "Zapisz",
    backToTheRoom: "Wróć do pokoju",
  },

  roomStageNotice: {
    connectionLost: "Utracono połączenie",
    serverUpdating: "Aktualizacja serwera",
    reconnectingSeatKept: "Ponowne łączenie… Twoje miejsce jest przez chwilę zarezerwowane.",
    youReDisconnected: "Brak połączenia. Sketchy połączy się ponownie, gdy tylko połączenie wróci.",
    serverIsUpdating: "Serwer jest aktualizowany, więc ta gra się kończy.",
    couldNotRejoin: "Nie udało się wrócić do tego pokoju",
    couldNotRejoinDetail: "Połączenie wróciło, ale pokój nie przyjął cię z powrotem. Odśwież stronę, aby spróbować ponownie, albo przejdź do lobby.",
    gameEnded: "Ta gra się zakończyła",
    endedServerUpdate: "Serwer został zaktualizowany i trwająca gra nie mogła być kontynuowana.",
    endedRoomClosed: "Pokój został zamknięty, gdy nie było połączenia.",
    kickedFromRoom: "Wyrzucono cię z pokoju",
    backToLobby: "Wróć do lobby",
  },

  rulesPage: {
    theRules: "Zasady",
    thisPage: "Na tej stronie",
    forExample: "Na przykład",
    backToLobby: "Wróć do lobby",
  },

  sessionManagerDialog: {
    lastUsed: (p: { when: string }) => `Ostatnio używane: ${p.when}`,
    signsOutOn: (p: { when: string }) => `Automatyczne wylogowanie: ${p.when}`,
    usedElsewhere: (p: { when: string }) =>
      `Użyte w innej przeglądarce: ${p.when}. Jeśli to nie ty, usuń dostęp temu urządzeniu.`,
    couldNotLoadSignedDevices: "Nie udało się wczytać zalogowanych urządzeń.",
    couldNotRevokeDevice: "Nie udało się usunąć dostępu urządzenia.",
    couldNotSignOutEverywhere: "Nie udało się wylogować ze wszystkich urządzeń.",
    signedDevices: "Zalogowane urządzenia",
    revokeAnyDeviceYouNoLonger: "Usuń dostęp każdemu urządzeniu, którego nie rozpoznajesz. Nazwy urządzeń są ogólne i nie zawierają wersji przeglądarki.\n          Nieużywane urządzenie wylogowuje się samo po dziewięćdziesięciu dniach.",
    loadingDevices: "Wczytywanie urządzeń…",
    currentDevice: "Bieżące urządzenie",
    revoking: "Usuwanie dostępu…",
    revoke: "Usuń dostęp",
    signingOut: "Wylogowywanie…",
    signOutEverywhere: "Wyloguj wszędzie",
    logOutEverywhereTitle: "Wylogować wszędzie?",
    logOutEverywhereBody: "Wszystkie urządzenia zalogowane na tym koncie zostaną wylogowane, łącznie z tym. Tutaj też trzeba będzie zalogować się ponownie.",
  },

  avatarDoodles: {
    fox: "Lis",
    cat: "Kot",
    owl: "Sowa",
    frog: "Żaba",
    crab: "Krab",
    penguin: "Pingwin",
    fish: "Ryba",
    bear: "Miś",
    ladybug: "Biedronka",
    butterfly: "Motyl",
    turtle: "Żółw",
    alien: "Kosmita",
    ghost: "Duch",
    robot: "Robot",
    rocket: "Rakieta",
    kite: "Latawiec",
    boat: "Łódka",
    balloon: "Balon",
    umbrella: "Parasol",
    coffee: "Kawa",
    cactus: "Kaktus",
    mushroom: "Grzyb",
    cloud: "Chmurka",
    flower: "Kwiatek",
    donut: "Donut",
    icecream: "Lody",
  },
  avatarDoodleDialog: {
    title: "Wybierz bazgroł",
    intro: "Rysowany w kolorze twojej nazwy, wszędzie tam, gdzie ona się pojawia.",
    wearing: "Używasz teraz",
    couldNotChoose: "Nie udało się zmienić bazgroła.",
  },
  playLanguagesQuestion: {
    title: "W jakich językach grasz?",
    changeLater: "Możesz to zmienić w każdej chwili: Ustawienia → Wygląd.",
    done: "Gotowe",
  },
  settingsOverlay: {
    email: "E-mail",
    password: "Hasło do konta",
    twoFactorAuthentication: "Weryfikacja dwuetapowa",
    signedDevices: "Zalogowane urządzenia",
    downloadEverything: "Pobierz wszystko",
    colorScheme: "Schemat kolorów",
    appliesMomentYouPick: "Działa od razu po wybraniu.",
    languageYouPlay: "Twój język",
    roomsThisLanguageComeFirstLobby: "Pokoje w tym języku są w lobby na początku, a w pokoju mieszanym to w nim dostajesz hasła. To coś innego niż język, w którym czytasz Sketchy.",
    alsoPlayIn: "Swobodnie grasz też w",
    alsoPlayInHint: "Pokoje w tych językach pojawiają się w lobby po pokojach mieszanych, w tej kolejności. Przeciągnij język albo użyj jego strzałek, żeby go przesunąć.",
    addPlayLanguage: "Dodaj język, w którym grasz",
    addPlayLanguageButton: "Dodaj",
    movePlayLanguageEarlier: (p: { name: string }) => `Przesuń wyżej: ${p.name}`,
    movePlayLanguageLater: (p: { name: string }) => `Przesuń niżej: ${p.name}`,
    removePlayLanguage: (p: { name: string }) => `Usuń: ${p.name}`,
    playLanguageMoved: (p: { name: string; position: number; total: number }) => `${p.name} jest teraz na pozycji ${p.position} z ${p.total}`,
    yourBrowserAlsoReads: "Twoja przeglądarka ma ustawione również:",
    addSuggestedPlayLanguage: (p: { name: string }) => `Dodaj: ${p.name}`,
    notNow: "Nie teraz",
    interfaceLanguage: "Język interfejsu",
    interfaceLanguageHint: "Każde słowo samego Sketchy. Niezależny od języka, w którym grasz: czytanie w jednym, a granie w innym to nic niezwykłego.",
    timeFormat: "Format czasu",
    howEveryClockReadsChatTimestamps: "Jak wyświetlany jest każdy czas: godziny w czacie, daty logowania, powiadomienia. „Systemowy” dopasowuje się do urządzenia.",
    iHaveTroubleTellingColorsApart: "Mam trudność z rozróżnianiem kolorów",
    nudgesHostsTowardRoomColorsThat: "Podsuwa gospodarzom kolory pokoju, które da się rozróżnić przy deuteranopii i protanopii, nie mówiąc im, kto o to prosił. Nic nie zmienia się samo.",
    brushCursor: "Kursor pędzla",
    crosshairPreciseAtPointOutlineShows: "Celownik jest precyzyjny w punkcie; obrys pokazuje, jak szerokie będzie pociągnięcie.",
    penPressure: "Nacisk pióra",
    aLighterHandDrawsThinnerBrush: "Z piórem czułym na nacisk lżejsza ręka rysuje cieńsze pociągnięcie pędzla. Rozmiar pędzla to największa możliwa szerokość.",
    defaultBrushSize: "Domyślny rozmiar pędzla",
    theSizeTheBrushStartsEveryTurnAt: "Rozmiar, od którego pędzel zaczyna każdą turę. Zaznaczony na suwaku rozmiaru.",
    brushCursorStyle: "Styl kursora pędzla",
    soundEffects: "Efekty dźwiękowe",
    chimesCorrectGuessStartTurnLast: "Dźwięki przy trafieniu, na początku tury, w ostatnich dziesięciu sekundach oraz gdy gracze dołączają i wychodzą.",
    confetti: "Konfetti",
    burstWhenYouGuessRightAgain: "Wybuch konfetti, gdy zgadniesz, i jeszcze raz dla zwycięzcy na koniec gry.",
    clickKeyRebindEachActionCan: "Kliknij klawisz, żeby go zmienić. Każda akcja może mieć dwa. Naciśnij Esc, żeby anulować.",
    theseAreTheirSettings: (p: { name: string }) => `Teraz obowiązują ustawienia konta ${p.name}.`,
    guestLivesInThisBrowser: (p: { name: string }) =>
      `${p.name} istnieje tylko w tej przeglądarce. Konto zachowuje nazwę, twoje punkty i historię na każdym urządzeniu oraz pozwala wybrać kolor.`,
    systemThemeNow: (p: { theme: string }) => `Teraz: ${p.theme}`,
    twelveHour: "12-godzinny",
    twentyFourHour: "24-godzinny",
    choosePicture: "Wybierz zdjęcie",
    editPicture: "Edytuj zdjęcie",
    picture: "Zdjęcie",
    pickDoodle: "Wybierz bazgroł",
    uploadPicture: "Prześlij zdjęcie",
    removePicture: "Usuń zdjęcie",
    removeDoodle: "Usuń bazgroł",
    couldNotRemovePicture: "Nie udało się usunąć zdjęcia.",
    couldNotChangeYourDisplayName: "Nie udało się zmienić wyświetlanej nazwy.",
    couldNotChangeYourDisplayName2: "Nie udało się zmienić wyświetlanej nazwy. Spróbuj ponownie.",
    themeSoundShortcutsCameFromAccount: "Motyw, dźwięk i\n            skróty pochodzą z konta. Ustawienia tej przeglądarki pozostały nietknięte i\n            wrócą, jeśli się wylogujesz.",
    dismiss: "Zamknij",
    playingAsGuest: "Grasz jako gość",
    noNameYet: "Jeszcze bez nazwy",
    namelessExplainer: "Wybierz nazwę, żeby grać jako gość, albo zaloguj się. Konto zachowuje nazwę, twoje punkty i historię na każdym urządzeniu.",
    createAccount: "Utwórz konto",
    logIn: "Zaloguj się",
    you: "Ty",
    displayName: "Wyświetlana nazwa",
    cancel: "Anuluj",
    change: "Zmień",
    nameColor: "Kolor nazwy",
    signingIn: "Logowanie",
    changePassword: "Zmień hasło",
    manage: "Zarządzaj",
    yourData: "Twoje dane",
    requestExport: "Poproś o eksport",
    delete: "Usuń…",
    display: "Wyświetlanie",
    theme: "Motyw",
    accessibility: "Dostępność",
    theCanvas: "Płótno",
    sound: "Dźwięk",
    volume: "Głośność",
    effects: "Efekty",
    noKeyboardThisDevice: "Brak klawiatury na tym urządzeniu",
    yourBindingsAreStillSavedStill: "Twoje przypisania klawiszy są nadal zapisane i działają. Otwórz Sketchy z podłączoną\n            klawiaturą, żeby je zmienić.",
    drawingTools: "Narzędzia rysowania",
    resetDefaults: "Przywróć domyślne",
    settings: "Ustawienia",
    closeSettings: "Zamknij ustawienia",
    settingsSections: "Sekcje ustawień",
    account: "Konto",
    appearance: "Wygląd",
    soundEffects2: "Dźwięk i efekty",
    shortcuts: "Skróty",
    red: "Czerwony",
    orange: "Pomarańczowy",
    yellow: "Żółty",
    lime: "Limonkowy",
    green: "Zielony",
    teal: "Morski",
    sky: "Błękitny",
    blue: "Niebieski",
    indigo: "Indygo",
    purple: "Fioletowy",
    magenta: "Purpurowy",
    pink: "Różowy",
    brown: "Brązowy",
    light: "Jasny",
    dark: "Ciemny",
    system: "Systemowy",
    crosshair: "Celownik",
    outline: "Obrys",
    space: "Spacja",
    hideTheFullAddress: "Ukryj pełny adres",
    showTheFullAddress: "Pokaż pełny adres",
    hide: "Ukryj",
    showInFull: "Pokaż w całości",
    confirmed: "Potwierdzony",
    notConfirmed: "Niepotwierdzony",
    saving: "Zapisywanie…",
    save: "Zapisz",
    withoutOneThereIsNo:
      "Bez niego nie da się wrócić na to konto, jeśli zapomnisz hasła.",
    addAnEmail: "Dodaj e-mail",
    changingItSignsEveryOther: "Zmiana wyloguje wszystkie inne urządzenia.",
    setThisUpAndThe:
      (p: { pendingRole: string }) => `Skonfiguruj to, a zacznie obowiązywać zaproponowana ci rola: ${p.pendingRole}.`,
    anAuthenticatorAppSCode:
      "Kod z aplikacji uwierzytelniającej, oprócz hasła. Obowiązkowe dla moderatorów i administratorów.",
    setUp: "Skonfiguruj",
    guestKeptInThisBrowser: "Twoja nazwa gościa, punkty i historia są przechowywane tylko w tej przeglądarce.",
    everyBrowserStillHoldingA:
      "Każda przeglądarka, w której trwa sesja, i możliwość zakończenia każdej z nich.",
    worksForAGuestToo: "Działa też dla gościa: rozegrane przez ciebie gry należą do ciebie.",
    everyGameListAndSetting:
      "Każda gra, lista i ustawienie, które Sketchy przechowuje na twój temat, w jednym pliku JSON.",
    deleteThisGuest: "Usuń tego gościa",
    deleteYourAccount: "Usuń konto",
    removesTheNameThePoints:
      "Usuwa nazwę, punkty i historię powiązane z tą przeglądarką.",
    gamesYouPlayedStayIn:
      "Rozegrane przez ciebie gry zostają w historii innych graczy, bez twojej nazwy.",
    clickToRebindTheSecond: "Kliknij, żeby zmienić drugi klawisz",
    clickToRebind: "Kliknij, żeby zmienić",
    pressKey: "Naciśnij klawisz…",
    key: "+ klawisz",
    none: "Brak",
  },

  stepUpDialog: {
    passkeyNotUsed: "Klucz dostępu nie został użyty. Możesz spróbować ponownie.",
    thatCodeWasNotAccepted: "Ten kod nie został zaakceptowany.",
    thatPasskeyWasNotAccepted: "Ten klucz dostępu nie został zaakceptowany.",
    confirmYou: "Potwierdź, że to ty",
    recoveryCode: "Kod odzyskiwania",
    codeFromYourAuthenticatorApp: "Kod z aplikacji uwierzytelniającej",
    cancel: "Anuluj",
    waitingForYourDevice: "Oczekiwanie na urządzenie…",
    useYourPasskey: "Użyj klucza dostępu",
    useYourAuthenticatorApp: "Użyj aplikacji uwierzytelniającej",
    useARecoveryCode: "Użyj kodu odzyskiwania",
    checking: "Sprawdzanie…",
    confirm: "Potwierdź",
  },

  suspensionNotice: {
    yourAccountSuspended: "Twoje konto jest zawieszone",
    signingOut: "Wylogowywanie…",
    signOut: "Wyloguj się",
  },

  toastProvider: {
    notifications: "Powiadomienia",
    dismissNotification: "Zamknij powiadomienie",
  },

  toolbar: {
    colorOption: (p: { color: string }) => `kolor ${p.color}`,
    adjustSize: (p: { tool: string }) => `Dostosuj rozmiar: ${p.tool}`,
    sizeSlider: (p: { tool: string }) => `${p.tool}, rozmiar`,
    chooseToolCurrent: (p: { tool: string }) => `Wybierz narzędzie, obecne: ${p.tool}`,
    chooseColorCurrent: (p: { color: string }) => `Wybierz kolor, obecny: ${p.color}`,
    sizeWithWidth: (p: { tool: string; width: number }) => `${p.tool}, rozmiar ${p.width}px`,
    sizeShortcutHint: (p: { tool: string; width: number; keys: string }) =>
      `${p.tool}, rozmiar: ${p.width}px (${p.keys})`,
    widthReadout: (p: { width: number }) => `${p.width}px`,
    defaultSize: "Domyślny",
    backToDefaultSize: (p: { width: number }) => `Domyślny rozmiar, ${p.width}px`,
    colorSwatch: (p: { color: string }) => `Kolor ${p.color}`,
    drawingTools: "Narzędzia rysowania",
    chooseTool: "Wybierz narzędzie",
    chooseColor: "Wybierz kolor",
    ctrlKey: "Ctrl",
    undo: "Cofnij",
    clearCanvas: "Wyczyść płótno",
    chooseCustomColor: "Wybierz własny kolor",
    colorPalette: "Paleta kolorów",
    canvasActions: "Działania na płótnie",
    undoWithShortcut: (p: { keys: string }) => `Cofnij ostatnie pociągnięcie (${p.keys})`,
    clear: "Wyczyść",
    brush: "Pędzel",
    fill: "Wypełnienie",
    eraser: "Gumka",
    rectangle: "Prostokąt",
    triangle: "Trójkąt",
    ellipse: "Elipsa",
    fillIsUnavailableForThe: "Wypełnienie jest niedostępne do końca tej tury",
    drawingByHandIsUnavailable: "Rysowanie odręczne jest niedostępne do końca tej tury",
  },

  turnResultsOverlay: {
    thisTurnWithHints: (p: { base: number; hintSpend: number; points: number }) =>
      `Ta tura: +${p.base} − ${p.hintSpend} za podpowiedzi = ${counted(p.points, { one: "punkt", few: "punkty", many: "punktów", other: "punktu" })}`,
    promptWas: "Hasło brzmiało",
    noOneGuessedCorrectly: "Nikt nie zgadł.",
    you: "(ty)",
    drewThisTurn: "Rysujący w tej turze",
    nextTurn: "Następna tura",
    turnResults: "Wyniki tury",
    turnComplete: "Koniec tury",
  },

  twoFactorDialog: {
    scanThisWithYourAuthenticatorApp: "Zeskanuj to aplikacją uwierzytelniającą, żeby dodać to konto",
    codeFromYourAuthenticatorApp: "Kod z aplikacji uwierzytelniającej",
    secondFactorState: (p: {
      recoveryCodesRemaining: number | null;
      confirmAuthenticator: boolean;
    }) =>
      [
        "Weryfikacja dwuetapowa jest włączona.",
        p.recoveryCodesRemaining === null
          ? null
          : `Masz jeszcze ${counted(p.recoveryCodesRemaining, {
              one: "kod odzyskiwania",
              few: "kody odzyskiwania",
              many: "kodów odzyskiwania",
              other: "kodu odzyskiwania",
            })}.`,
        p.confirmAuthenticator
          ? "Zanim to konto będzie mogło otrzymać rolę moderatora lub administratora, potwierdź hasłem i kodem z aplikacji uwierzytelniającej, że należy ona do ciebie."
          : null,
        "Każda zmiana poniżej wymaga podania hasła.",
      ]
        .filter(Boolean)
        .join(" "),
    copied: (p: { what: string }) => `Skopiowano: ${p.what}.`,
    couldNotCopy: (p: { what: string }) =>
      `Nie udało się skopiować: ${p.what}. Zaznacz i skopiuj ręcznie.`,
    roleTaken: (p: { role: "admin" | "moderator" }) =>
      `Jesteś teraz ${p.role === "admin" ? "administratorem" : "moderatorem"}. Weryfikacja dwuetapowa jest włączona, a rola, która na nią czekała, zaczęła obowiązywać. Inne urządzenia zostały wylogowane; to działa dalej, a każde logowanie od teraz będzie wymagać kodu.`,
    couldNotReadYourSecuritySettings: "Nie udało się odczytać ustawień bezpieczeństwa.",
    yourPasswordConfirmsAuthenticatorYours: "Hasło do konta potwierdza, że aplikacja uwierzytelniająca należy do ciebie.",
    yourPasswordConfirmsThisPasskeyYours: "Hasło do konta potwierdza, że ten klucz dostępu należy do ciebie.",
    passkeyAdded: "Dodano klucz dostępu.",
    thatPasskeyWasNotCreatedYou: "Klucz dostępu nie został utworzony. Możesz spróbować ponownie.",
    yourPasswordNeededRemovePasskey: "Do usunięcia klucza dostępu potrzebne jest hasło do konta.",
    confirmedThisAccountCanNowBe: "Potwierdzone. To konto może teraz otrzymać rolę moderatora lub administratora.",
    twoFactorAuthentication: "Weryfikacja dwuetapowa",
    saveTheseRecoveryCodesNow: "Zapisz teraz te kody odzyskiwania.",
    eachOneSignsYouOnceIf: "Każdy z nich pozwala zalogować się raz, jeśli stracisz aplikację uwierzytelniającą. Nie zostaną pokazane ponownie.",
    recoveryCodes: "Kody odzyskiwania",
    downloadAsFile: "Pobierz jako plik",
    copyAll: "Skopiuj wszystkie",
    iHaveSavedTheseSomewhereSafe: "Kody są zapisane w bezpiecznym miejscu",
    done: "OK",
    moderatorsAdministratorsSignWithPasskeyYour: "Moderatorzy i administratorzy logują się kluczem dostępu: twoje\n              urządzenie potwierdza, że to ty — odciskiem palca, twarzą lub\n              kodem PIN — i nie wpisujesz niczego, co można by komuś wydać.",
    yourPassword: "Hasło do konta",
    confirmsPasskeyBeingAddedByYou: "Potwierdza, że to ty dodajesz klucz dostępu.",
    useAuthenticatorAppInstead: "Użyj zamiast tego aplikacji uwierzytelniającej",
    scanCodeWithAuthenticatorAppThen: "Zeskanuj kod aplikacją uwierzytelniającą, a potem wpisz sześć cyfr,\n              które pokaże.",
    drawingCode: "Rysowanie kodu…",
    pointYourAppAtThis: "Skieruj na to aplikację.",
    setupKey: "Klucz konfiguracji",
    copySetupKey: "Skopiuj klucz konfiguracji",
    useThisIfYouCanT: "Użyj go, jeśli nie możesz zeskanować.",
    confirmsAuthenticatorYours: "Potwierdza, że aplikacja uwierzytelniająca należy do ciebie.",
    codeFromYourApp: "Kod z aplikacji",
    cancel: "Anuluj",
    passkeys: "Klucze dostępu",
    thisDeviceOnly: "· tylko na tym urządzeniu",
    remove: "Usuń",
    confirmSYours: "Potwierdź, że należy do ciebie",
    addPasskey: "Dodaj klucz dostępu",
    newRecoveryCodes: "Nowe kody odzyskiwania",
    turnOff: "Wyłącz",
    addAuthenticatorApp: "Dodaj aplikację uwierzytelniającą",
    couldNotStartSettingThis: "Nie udało się rozpocząć konfiguracji.",
    thatCodeWasNotAccepted: "Ten kod nie został zaakceptowany.",
    couldNotAddThatPasskey: "Nie udało się dodać tego klucza dostępu.",
    couldNotRemoveThatPasskey: "Nie udało się usunąć tego klucza dostępu.",
    couldNotConfirmIt: "Nie udało się tego potwierdzić.",
    couldNotReplaceYourRecovery: "Nie udało się wymienić kodów odzyskiwania.",
    couldNotTurnThisOff: "Nie udało się tego wyłączyć.",
    waitingForYourDevice: "Oczekiwanie na urządzenie…",
    setUpAPasskey: "Skonfiguruj klucz dostępu",
    noPasskeyOnThisDevice: "Nie masz klucza dostępu na tym urządzeniu? ",
    thisBrowserCannotMakeA: "Ta przeglądarka nie może utworzyć klucza dostępu. ",
    checking: "Sprawdzanie…",
    confirm: "Potwierdź",
  },

  useFriendArrivalNotices: {
    wantsToBeFriends: (p: { name: string }) => `${p.name} chce dodać cię do znajomych.`,
    accept: "Przyjmij",
    open: "Otwórz",
    manyArrived: (p: { name: string; others: number }) =>
      `${p.name} i ${counted(p.others, { one: "inna osoba", few: "inne osoby", many: "innych osób", other: "innej osoby" })} chcą dodać cię do znajomych.`,
  },

  roomVisibilityIcon: {
    publicRoom: "Pokój publiczny",
    privateRoom: "Pokój prywatny",
  },

  waitingRoomPanel: {
    finalStanding: (p: { place: number; score: number }) => `${ordinal(p.place)} · ${number(p.score)}`,
    finalStandingSpoken: (p: { place: number; score: number }) =>
      `${ordinal(p.place)} miejsce, ${counted(p.score, { one: "punkt", few: "punkty", many: "punktów", other: "punktu" })}`,
    editRoomRules: "Edytuj zasady pokoju",
    editRules: "Edytuj zasady",
    doodle: "Brudnopis",
    needMorePlayers: (p: { count: number }) =>
      `Potrzeba jeszcze ${counted(p.count, { one: "gracza", few: "graczy", many: "graczy", other: "gracza" })}`,
    waitingForHostToStart: (p: { rematch: boolean }): string =>
      p.rematch ? "Czekamy, aż {host} rozpocznie rewanż" : "Czekamy, aż {host} rozpocznie grę",
    copied: (p: { what: string }) => `Skopiowano: ${p.what}.`,
    couldNotCopy: (p: { what: string }) =>
      `Nie udało się skopiować: ${p.what}. Skopiuj z paska adresu.`,
    roomCodeLabel: (p: { code: string }) => `Kod pokoju ${p.code}`,
    rosterCount: (p: { here: number; capacity: number }) => `${p.here} z ${p.capacity}`,
    inviteYourFriends: "Zaproś znajomych",
    shareLink: "Udostępnij link",
    copyCode: "Skopiuj kod",
    copyLink: "Skopiuj link",
    inTheRoom: "W pokoju",
    you: "(ty)",
    host: "Gospodarz",
    friend: "Znajomy",
    invite: "Zaproś",
    spectatorsAfkAndDisconnectedPlayers:
      "Widzowie, gracze AFK i rozłączeni gracze nie liczą się do dwóch aktywnych graczy potrzebnych do gry.",
    joinMySketchyRoomCode: (p: { code: string }) => `Dołącz do mojego pokoju w Sketchy: ${p.code}`,
    inviteLink: "Link z zaproszeniem",
    roomCode: "Kod pokoju",
    starting: "Rozpoczynanie…",
    rematch: "Rewanż",
    startGame: "Rozpocznij grę",
    waitingForAHost: "Czekamy na gospodarza",
  },

  /** What a warning and a suspension both show about the report behind them. */
  moderationNotice: {
    yourReportedDrawing: (p: { prompt: string }) =>
      `Twój rysunek hasła „${p.prompt}”, tak jak został zgłoszony`,
    recordedAs: "Zakwalifikowano jako: {category}",
    youWereAskedDraw: "Twoje hasło do narysowania",
    theMessageThisWasAbout: "Wiadomość, której to dotyczyło:",
    theMessagesThisWasAbout: "Wiadomości, których to dotyczyło:",
    theDrawingThisWasAbout: "Rysunek, którego to dotyczyło:",
    theDrawingsThisWasAbout: "Rysunki, których to dotyczyło:",
  },
  inbox: {
    inbox: "Skrzynka",
    openInboxUnread: (p: { count: number }) => `Skrzynka, ${counted(p.count, { one: "nieprzeczytana wiadomość", few: "nieprzeczytane wiadomości", many: "nieprzeczytanych wiadomości", other: "nieprzeczytanej wiadomości" })}`,
    markAllRead: "Oznacz wszystko jako przeczytane",
    newGroup: "Nowe",
    earlierGroup: "Wcześniejsze",
    showOlder: "Pokaż starsze",
    close: "Zamknij skrzynkę",
    nothingHereYet: "Jeszcze nic tu nie ma",
    whatArrivesHere: "Tu trafiają udostępnienia twoich rysunków, zaproszenia do znajomych i wiadomości o twoim koncie.",
    sharedYourDrawing: "Twój rysunek {prompt} trafił do galerii. Udostępnienie: {sharer}.",
    yourDrawingWasShared: "Twój rysunek hasła {prompt} został udostępniony w galerii.",
    noLongerInTheGallery: "Nie ma go już w galerii",
    view: "Zobacz",
    takeItOut: "Zdejmij",
    wantsToBeFriends: "{name}: zaproszenie do znajomych.",
    accept: "Przyjmij",
    decline: "Odrzuć",
    friendsNow: "Jesteście teraz znajomymi",
    noLongerWaiting: "Już nie czeka",
    acceptedYourRequest: "Zaproszenie do znajomych przyjęte: {name}.",
    invitedYouToPlay: "{name}: zaproszenie do gry.",
    join: "Dołącz",
    expired: "Wygasło",
    reportsReviewed: (p: { count: number }) =>
      `${counted(p.count, { one: "wysłane przez ciebie zgłoszenie zostało rozpatrzone", few: "wysłane przez ciebie zgłoszenia zostały rozpatrzone", many: "wysłanych przez ciebie zgłoszeń zostało rozpatrzonych", other: "wysłanego przez ciebie zgłoszenia zostało rozpatrzone" })}. Dziękujemy.`,
    setUpTwoFactor: "Skonfiguruj logowanie dwuetapowe",
    offerEnded: "Ta propozycja wygasła",
    acknowledged: "Przeczytane",
    readTheRules: "Przeczytaj zasady",
    chooseAnotherPicture: "Wybierz inne zdjęcie",
    signedOutForRole: "Twoja rola się zmieniła, więc wylogowano cię wszędzie. Zaloguj się ponownie, aby kontynuować.",
  },

  warningNotice: {
    uploadAgainNow: "Możesz już wgrać nowe.",
    uploadAgainOn: (p: { date: string }) => `Nowe możesz wgrać ${p.date}.`,
    whatAWarningMeans:
      "Zgłoszenie dotyczące twojego zachowania zostało rozpatrzone, a to jest jego wynik. Po naciśnięciu OK nic nie jest ograniczone, ale kolejne zgłoszenie może skończyć się zawieszeniem konta.",
    yourPictureWasRemoved: "Twoje zdjęcie zostało usunięte",
    aModeratorWarning: "Ostrzeżenie od moderatora",
    aReportAboutYourPicture:
      "Zgłoszenie dotyczące twojego zdjęcia zostało rozpatrzone, a to jest jego wynik. Nic innego na twoim koncie się nie zmienia.",
    oneMoment: "Chwileczkę…",
    understood: "OK",
  },
  connectionStatusBanner: {
    youReDisconnectedCheckYour:
      "Nie masz połączenia. Sprawdź internet; Sketchy połączy się ponownie automatycznie.",
    couldNotReconnect: "Nie udało się ponownie połączyć z pokojem. Odśwież stronę, żeby spróbować jeszcze raz.",
    connectionLostReconnecting: "Utracono połączenie — ponowne łączenie…",
  },
  accountData: {
    queued: "W kolejce",
    preparing: "Przygotowywanie…",
    ready: "Gotowe",
    tooLargeToPrepareHere: "Za duże, by przygotować tutaj",
    couldNotPrepare: "Nie udało się przygotować",
    yourDataIsLargerThan:
      "Twoje dane są za duże, żeby ten serwer mógł je przygotować w jednym pliku. Poproś administratora o pomoc.",
    somethingWentWrongWhilePreparing:
      "Coś poszło nie tak podczas przygotowywania. Możesz poprosić o kolejny eksport.",
  },
  recoveryCodeFile: {
    sketchyRecoveryCodes: "Kody odzyskiwania Sketchy",
    accountUsername: (p: { username: string }) => `Konto: ${p.username}`,
    createdValue: (p: { value: string }) => `Utworzono: ${p.value}`,
    eachCodeSignsYouIn: "Każdy kod pozwala zalogować się raz, jeśli stracisz aplikację uwierzytelniającą.",
    keepThisFile:
      "Przechowuj ten plik tam, gdzie tylko ty masz dostęp. Każdy, kto ma te\nkody i twoje hasło, może zalogować się jako ty.",
  },
  avatars: {
    chooseAPngJpegWebP: "Wybierz zdjęcie PNG, JPEG, WebP lub GIF.",
    thatPictureIsTooLarge: "To zdjęcie jest za duże, żeby je odczytać: maksymalnie 10 MB.",
    thatFileCouldNotBe: "Tego pliku nie da się odczytać jako zdjęcia.",
    thatPictureIsTooSmall: "To zdjęcie jest za małe, żeby coś z niego zrobić.",
    thisBrowserCannotResizePictures: "Ta przeglądarka nie potrafi zmieniać rozmiaru zdjęć.",
    thatPictureIsTooDetailed:
      "To zdjęcie jest zbyt szczegółowe, żeby się zmieściło. Spróbuj prostszego albo przybliż jego fragment.",
  },
  settingsSync: {
    thatChangeAppliesHereBut:
      "Ta zmiana działa tutaj, ale nie udało się jej zapisać na koncie. Twoje inne urządzenia jej nie zobaczą.",
  },
  promptStats: {
    hardestFirst: "Najpierw najtrudniejsze",
    easiestFirst: "Najpierw najłatwiejsze",
    mostPicked: "Najczęściej wybierane",
    getsGuessed: "Łatwo zgadywane",
    usuallyGuessed: "Zwykle zgadywane",
    evenOdds: "Pół na pół",
    oftenMissed: "Często nieodgadnięte",
    rarelyGuessed: "Rzadko zgadywane",
    notPlayedEnough: "Za mało rozgrywek",
    allRanked: (p: { count: number }) => `Wszystkie hasła (${p.count}) padły wystarczająco często, żeby je ocenić.`,
    noneRanked: (p: { unrated: number; guessers: number }) =>
      `Żadne z tych haseł (${p.unrated}) nie miało jeszcze ${p.guessers} zgadujących, więc żadne nie ma oceny. Zagrajcie kilka gier, a ich trudność pojawi się tutaj.`,
    someRanked: (p: { rated: number; unrated: number; guessers: number }) =>
      `Z oceną: ${p.rated}. ${p.unrated} ${plural(p.unrated, { one: "kolejne hasło nie ma", few: "kolejne hasła nie mają", many: "kolejnych haseł nie ma", other: "kolejnego hasła nie ma" })} jeszcze oceny: widziało je mniej niż ${p.guessers} zgadujących.`,
    noMatch: (p: { query: string }) => `Żadne hasło nie pasuje do „${p.query}”.`,
    matching: (p: { count: number; query: string }) =>
      `${counted(p.count, { one: "hasło pasuje", few: "hasła pasują", many: "haseł pasuje", other: "hasła pasuje" })} do „${p.query}”.`,
  },
  gameHeaderStatus: {
    roundRoundNumberOfTotalRounds:
      (p: { roundNumber: number; totalRounds: number }) => `Runda ${p.roundNumber} z ${p.totalRounds}`,
    roundCompact: (p: { roundNumber: number; totalRounds: number }) =>
      `Runda ${p.roundNumber}/${p.totalRounds}`,
    roundFraction: (p: { roundNumber: number; totalRounds: number }) =>
      `${p.roundNumber}/${p.totalRounds}`,
  },
  gameRoomRegions: {
    theNextPlayer: "Następny gracz",
    drawingCanvasYouAreDrawing: "Płótno do rysowania. Rysujesz.",
    yourTurnToDraw: "Twoja kolej na rysowanie.",
    canvasSpectating: (p: { drawer: string }) => `Płótno do rysowania. Oglądasz, jak ${p.drawer} rysuje.`,
    canvasSomeoneDrawing: (p: { drawer: string }) => `Płótno do rysowania. ${p.drawer} rysuje.`,
    someoneIsDrawing: (p: { drawer: string }) => `${p.drawer} rysuje.`,
    theDrawer: "ktoś",
    aPlayer: "Ktoś",
  },
  useToolbarState: {
    fillIsUnavailableForThe: "Wypełnienie jest niedostępne do końca tej tury.",
    drawingByHandIsUnavailable:
      "Rysowanie odręczne jest niedostępne do końca tej tury. Kształty nadal działają.",
  },
  timer: {
    n10SecondsRemaining: "Zostało 10 sekund",
    timeIsUp: "Koniec czasu",
  },
  chatAnnouncements: {
    nicknameGuessedThePrompt: (p: { nickname: string }) => `${p.nickname} zna już hasło.`,
  },
  canvasSnapshot: {
    drawingOfDownloadPrompt: (p: { downloadPrompt: string }) => `Rysunek hasła „${p.downloadPrompt}”`,
    savedDrawing: "Zapisany rysunek",
  },
  roomSetup: {
    default: "Domyślna",
    fasterGuessesEarnMore100: "Szybsze odpowiedzi dają więcej punktów: 100–300.",
    pressure: "Presja",
    pointsDecayEverySecondTwice: "Punkty topnieją co sekundę — dwa razy szybciej, gdy ktoś zgadnie.",
    noScoring: "Bez punktów",
    justDrawAndGuessNo: "Po prostu rysuj i zgaduj. Bez klasyfikacji.",
    timedHints: "Podpowiedzi z czasem",
    lettersRevealToEveryoneAt: "Litery odsłaniają się wszystkim o stałych porach.",
    noHints: "Bez podpowiedzi",
    emptyTilesAllTurnLong: "Puste pola liter przez całą turę.",
    buyLetters: "Kupowanie liter",
    revealALetterSlotJust: "Odsłoń pole litery tylko dla siebie — płacisz punktami z tej tury.",
    wheelOfFortune: "Koło fortuny",
    pickALetterPayIts: "Wybierz literę i zapłać jej cenę — samogłoski kosztują więcej.",
    letterTilesHidden: "Pola liter ukryte",
    defaultScoring: "Domyślna punktacja",
    pressureScoring: "Punktacja z presją",
  },
  screenCapture: {
    thisBrowserCouldNotEncode: "Ta przeglądarka nie mogła zakodować zrzutu ekranu.",
    theCaptureWasEmpty: "Zrzut był pusty.",
    thisBrowserCouldNotRead: "Ta przeglądarka nie mogła odczytać zrzutu ekranu.",
    thatScreenshotIsTooLarge: "Ten zrzut ekranu jest za duży, żeby go wysłać.",
  },
  accountRecovery: {
    youCanRecoverThisAccount:
      (p: { address: string }) => `Możesz odzyskać to konto za pomocą adresu ${p.address}.`,
    checkPendingAddressForAConfirmation:
      (p: { pendingAddress: string }) => `Jeśli adresu ${p.pendingAddress} można użyć, link potwierdzający jest już w drodze. Dopóki go nie otworzysz, nie da się odzyskać tego konta.`,
    thisServerCannotSendEmail:
      "Ten serwer nie może wysyłać e-maili, więc zapomniane hasło musi zresetować osoba, która go prowadzi.",
    addAnEmailAddressSo: "Dodaj adres e-mail, żeby odzyskać dostęp, jeśli zapomnisz hasła.",
  },
  friends: {
    aFriend: "Znajomy",
  },
  lobbyPresence: {
    showingShownOfOnlineCount:
      (p: { shown: number; onlineCount: number }) => `Widoczni: ${p.shown} z ${p.onlineCount}`,
  },
  authStore: {
    chooseANameToPlay: "Wybierz nazwę, pod którą chcesz grać.",
  },
  passkeys: {
    noPasskeyWasCreated: "Nie utworzono klucza dostępu.",
    noPasskeyWasUsed: "Nie użyto klucza dostępu.",
  },
  useGameSocketListeners: {
    nicknameJoinedTheRoom: (p: { nickname: string }) => `${p.nickname} dołącza do pokoju`,
    gameStarted: "Gra rozpoczęta!",
    drawerNicknameIsChoosingAPrompt:
      (p: { drawerNickname: string }) => `${p.drawerNickname} wybiera hasło…`,
    thePromptWasPrompt: (p: { prompt: string }) => `Hasło brzmiało „${p.prompt}”`,
    gotIt: (p: { nickname: string; time: string; points: number | null }) =>
      `${p.nickname} trafia · ${p.time}${p.points === null ? "" : ` (+${p.points})`}`,
    playerReconnected: (p: { nickname: string }) =>
      `${p.nickname} łączy się ponownie`,
    playerDisconnected: (p: { nickname: string }) =>
      `${p.nickname} rozłącza się`,
  },
  settingsStore: {
    brushTool: "Narzędzie: pędzel",
    fillTool: "Narzędzie: wypełnienie",
    eraserTool: "Narzędzie: gumka",
    rectangleTool: "Narzędzie: prostokąt",
    triangleTool: "Narzędzie: trójkąt",
    ellipseTool: "Narzędzie: elipsa",
    decreaseBrushSize: "Zmniejsz rozmiar pędzla",
    increaseBrushSize: "Zwiększ rozmiar pędzla",
    undoStroke: "Cofnij pociągnięcie",
  },
  reactions: {
    loveIt: "Uwielbiam",
    funny: "Zabawne",
    wow: "Wow",
    fire: "Ogień",
    reaction: "Reakcja",
  },
  drawingRules: {
    brush: "Pędzel",
    theBrushAndTheEraser: "Pędzel i gumka.",
    fill: "Wypełnienie",
    theFillTool: "Narzędzie wypełniania.",
    shapes: "Kształty",
    rectangleEllipseAndTriangle: "Prostokąt, elipsa i trójkąt.",
    allColors: "Wszystkie kolory",
    thePaletteAndTheCustom: "Paleta i wybór własnego koloru.",
    paletteOnly: "Tylko paleta",
    theBuiltInSwatchesNo: "Wbudowane próbki; bez własnych kolorów.",
    colorblindSafe: "Przyjazne dla daltonistów",
    colorsThatStayApartFor: "Kolory, które daltoniści łatwo rozróżnią.",
    blackAndWhite: "Czarno-białe",
    twoSwatchesNoCustomColors: "Tylko dwie próbki; bez własnych kolorów.",
    allTools: "Wszystkie narzędzia",
    onlyTool: (p: { tool: string }) =>
      `Tylko: ${p.tool}`,
    toolList: (p: { rest: string; last: string }) =>
      `${p.rest} i ${p.last}`,
  },
  socket: {
    sketchyIsFullRightNow: "Sketchy jest teraz pełne. Spróbuj ponownie za kilka minut.",
    tooManyTabsOpen: "Sketchy jest otwarte w zbyt wielu kartach. Zamknij jedną, żeby kontynuować.",
    connectionLostWhileTryingTo:
      (p: { action: string }) => `Utracono połączenie podczas próby: ${p.action}. Spróbuj ponownie.`,
    theRequestToActionTimed:
      (p: { action: string }) => `Przekroczono czas oczekiwania: ${p.action}. Spróbuj ponownie.`,
    couldNotActionPleaseTry: (p: { action: string }) => `Nie udało się: ${p.action}. Spróbuj ponownie.`,
  },
  bugReports: {
    drawingAndCanvas: "Rysowanie i płótno",
    guessingAndChat: "Zgadywanie i czat",
    roundsScoringAndResults: "Rundy, punktacja i wyniki",
    roomsAndLobby: "Pokoje i lobby",
    promptLists: "Listy haseł",
    accountAndSettings: "Konto i ustawienia",
    connectionAndSync: "Połączenie i synchronizacja",
    performance: "Wydajność",
    accessibility: "Dostępność",
    somethingElse: "Coś innego",
    blocksPlayICouldNot: "Blokuje grę — nie dało się grać dalej",
    majorHardToPlayAround: "Poważny — trudno go obejść",
    minorWorthFixingOneDay: "Drobny — warto kiedyś poprawić",
    notInARoom: "Poza pokojem",
    codeNotInAGame: (p: { code: string }) => `${p.code} · poza grą`,
    codeRoundRoundOfTotal:
      (p: { code: string; round: number; total: number }) => `${p.code} · runda ${p.round} z ${p.total}`,
  },
  suspension: {
    thisSuspensionHasNoEnd: "To zawieszenie nie ma daty zakończenia.",
    thisSuspensionHasEndedTry: "To zawieszenie już się skończyło; spróbuj zalogować się ponownie.",
    thisSuspensionLastsUntilEnds: (p: { ends: string }) => `To zawieszenie trwa do: ${p.ends}.`,
  },
  clock: {
    unknown: "Nieznany",
  },
  protocol: {
    theServerWasUpdated: "Serwer został zaktualizowany.",
  },
  passwordPolicy: {
    tooShort: (p: { count: number }) => `Hasło do konta musi mieć co najmniej ${counted(p.count, { one: "znak", few: "znaki", many: "znaków", other: "znaku" })}.`,
    rule: (p: { count: number }) => `Co najmniej ${counted(p.count, { one: "znak", few: "znaki", many: "znaków", other: "znaku" })}.`,
  },
  operatorAccess: {
    administrator: "administrator",
    moderator: "moderator",
    pendingTitle: "Czeka na ciebie rola moderatora",
    pendingBody:
      "Administrator zaproponował ci rolę moderatora. Zacznie ona obowiązywać, gdy skonfigurujesz weryfikację dwuetapową: moderatorzy logują się kodem z aplikacji uwierzytelniającej, a rola działa od chwili, gdy to zostanie ustawione. Inne urządzenia zostaną wtedy wylogowane. Do czasu konfiguracji nic się nie zmienia, a propozycja czeka w Ustawieniach, jeśli to nie jest dobry moment.",
    grantedTitle: "Jesteś teraz moderatorem",
    grantedBody:
      "Administrator nadał ci rolę moderatora. W menu konta pojawiła się pozycja Moderacja: tam rozpatruje się zgłoszenia dotyczące graczy i haseł. Nic nie zmienia się w tym, jak grasz.",
    removedTitle: "Nie jesteś już moderatorem",
    removedBody:
      "Administrator odebrał twojemu kontu rolę moderatora. Pozycja Moderacja zniknęła z menu. Nic innego na twoim koncie ani w twoich grach się nie zmienia.",
  },
  moderationCategories: {
    harassment: "nękanie",
    offensive_drawing: "obraźliwy rysunek",
    inappropriate_name: "niestosowna nazwa",
    cheating: "oszukiwanie",
    spam: "spam",
    inappropriate_avatar: "niestosowne zdjęcie",
  },
  roomNotices: {
    kickedByVote: "Głosowanie wyrzuciło cię z pokoju.",
    roomClosed: "Administrator zamknął ten pokój.",
    roomExpired: "Ten pokój został zamknięty po 30 minutach bez gry.",
    kickedByAdmin: "Administrator wyrzucił cię z pokoju.",
    accountDeleted: "Twoje konto zostało usunięte.",
    accountSuspended: "Twoje konto zostało zawieszone.",
    signedOut: "Wylogowano cię na tym urządzeniu.",
  },
};
