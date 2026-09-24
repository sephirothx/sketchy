import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { MAX_PROMPT_LENGTH } from "../lib/customPrompts";
import { chatAnnouncement } from "../lib/chatAnnouncements";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { recordRender } from "../lib/renderDiagnostics";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { sendGuess } from "../lib/guessSender";
import { inputPurposeFor } from "../lib/chatPurpose";
import type { AckResponse, ChatMessage, PlayerInfo } from "../types";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { ChevronDownIcon, ChevronRightIcon } from "./icons";
import { refusalText } from "../lib/refusals.ts";
import { chatLineText } from "../lib/announcements.ts";
import { ui } from "../content/ui/index.ts";
import { useLocaleRerender } from "../hooks/useLocaleRerender";
import "../styles/lazy/toolbar.css";

interface RoomChatPanelProps {
  messages: ChatMessage[];
  players: PlayerInfo[];
  mode: "waiting" | "playing" | "game-end";
  isDrawer: boolean;
  canGuess: boolean;
  myPlayerId?: string | null;
  targetPromptLengths: string[];
  hideMaskedPrompt?: boolean;
  onFocusChange?: (focused: boolean) => void;
  /** Set once this player has the word; drives the dock's success state. */
  guessedPrompt?: string | null;
  /** Points and hint spend for the guess that landed, for the same. */
  guessBreakdown?: { points: number; hintSpend: number } | null;
  /** 1-based finishing place among this turn's correct guesses. */
  guessPlace?: number | null;
}

type GuessFlash = {
  id: string;
  text: string;
  kind: "close" | "miss" | "info" | "error";
};

function letterRunLengths(text: string): number[] {
  const runs: number[] = [];
  let current = 0;
  for (const ch of text) {
    if (/[\p{L}\p{N}]/u.test(ch)) {
      current++;
    } else if (current > 0) {
      runs.push(current);
      current = 0;
    }
  }
  if (current > 0) runs.push(current);
  return runs;
}

export function RoomChatPanel({
  messages,
  players,
  mode,
  isDrawer,
  canGuess,
  myPlayerId = null,
  targetPromptLengths,
  hideMaskedPrompt = false,
  onFocusChange,
  guessedPrompt = null,
  guessBreakdown = null,
  guessPlace = null,
}: RoomChatPanelProps) {
  const locale = useLocaleRerender();
  recordRender("chat");
  const inputPurpose = inputPurposeFor(mode, canGuess);
  // A draft outlives the purpose flipping under it: a correct guess, or a
  // turn's results giving way to the next drawing, is not a reason to lose a
  // half-typed line. Only entering or leaving a game clears the input.
  const [previousMode, setPreviousMode] = useState(mode);
  const [text, setText] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [isScrolledUp, setIsScrolledUp] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [prevMessagesCount, setPrevMessagesCount] = useState(messages.length);
  const [guessFlash, setGuessFlash] = useState<GuessFlash | null>(null);
  const [flashSourceId, setFlashSourceId] = useState<string | null>(null);
  const [liveAnnouncement, setLiveAnnouncement] = useState("");
  const draftTextRef = useRef("");
  const listRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const blurTimeoutRef = useRef<number | null>(null);
  const wasFocusedRef = useRef(false);
  // Matches the mobile block in game-room.css so JS and CSS agree on the breakpoint.
  const isMobile = useMediaQuery("(max-width: 900px)");
  const inputVisible = mode !== "playing" || !isDrawer;
  useEffect(() => {
    return () => {
      if (blurTimeoutRef.current != null) {
        window.clearTimeout(blurTimeoutRef.current);
      }
      // Input may unmount when becoming drawer — clear stale focus so guess-focused
      // does not stick across turns with a closed keyboard.
      onFocusChange?.(false);
    };
  }, [onFocusChange]);

  // The form unmounts while drawing; report focus lost without touching the DOM
  // so guess-focused cannot stick to a node that no longer exists.
  useEffect(() => {
    if (inputVisible) return;
    if (blurTimeoutRef.current != null) {
      window.clearTimeout(blurTimeoutRef.current);
      blurTimeoutRef.current = null;
    }
    onFocusChange?.(false);
  }, [inputVisible, onFocusChange]);

  // Mobile only: dismiss the soft keyboard once guessing stops, so it does not
  // cover the canvas or the turn-results overlay. On desktop there is no keyboard
  // and guess-focused is already mobile-gated, so blurring would only cost the
  // caret between turns.
  useEffect(() => {
    if (!isMobile) return;
    if (!canGuess || isDrawer) {
      if (blurTimeoutRef.current != null) {
        window.clearTimeout(blurTimeoutRef.current);
        blurTimeoutRef.current = null;
      }
      inputRef.current?.blur();
      onFocusChange?.(false);
    }
  }, [isMobile, canGuess, isDrawer, onFocusChange]);

  // Desktop only: put the caret back when a guessable turn starts, but only if
  // the input held focus when it was taken away and nothing else claimed it —
  // never steal focus from an open dialog. Deliberately not done on mobile,
  // where it would pop the keyboard open every turn.
  useEffect(() => {
    if (isMobile || !canGuess || isDrawer) return;
    if (!wasFocusedRef.current) return;
    const active = document.activeElement;
    if (active && active !== document.body) return;
    inputRef.current?.focus();
  }, [isMobile, canGuess, isDrawer]);

  // Long enough to read and act on, short enough that it cannot still be on
  // screen for a turn the player has since stopped guessing in.
  useEffect(() => {
    if (!deliveryError) return;
    const timeout = window.setTimeout(() => setDeliveryError(null), 8000);
    return () => window.clearTimeout(timeout);
  }, [deliveryError]);

  if (previousMode !== mode) {
    setPreviousMode(mode);
    setText("");
    setHistoryIndex(null);
    setError(null);
    setDeliveryError(null);
  }

  if ((!canGuess || isDrawer) && guessFlash) {
    setGuessFlash(null);
  }

  if (messages.length !== prevMessagesCount) {
    setPrevMessagesCount(messages.length);
    if (isScrolledUp) {
      setUnreadCount((count) => count + Math.max(0, messages.length - prevMessagesCount));
    }
  }

  const newestMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  if (newestMessage && newestMessage.id !== flashSourceId) {
    setFlashSourceId(newestMessage.id);
    const announcement = chatAnnouncement(newestMessage);
    if (announcement) setLiveAnnouncement(announcement);
    if (mode === "playing" && canGuess) {
      let flash: GuessFlash | null = null;
      if (newestMessage.close) {
        flash = { id: newestMessage.id, text: chatLineText(newestMessage), kind: "close" };
      } else if (newestMessage.restricted && (!newestMessage.playerId || newestMessage.playerId === myPlayerId)) {
        flash = { id: newestMessage.id, text: chatLineText(newestMessage), kind: "miss" };
      } else if (
        newestMessage.playerId === myPlayerId
        && !newestMessage.system
        && !newestMessage.correct
        && !newestMessage.close
      ) {
        flash = { id: newestMessage.id, text: chatLineText(newestMessage), kind: "miss" };
      }
      if (flash) {
        setGuessFlash(flash);
      }
    }
  }

  useEffect(() => {
    if (!isScrolledUp) {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
    }
  }, [messages, isScrolledUp]);

  function handleScroll() {
    const element = listRef.current;
    if (!element) return;
    const distanceToBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    if (distanceToBottom <= 30) {
      setIsScrolledUp(false);
      setUnreadCount(0);
    } else {
      setIsScrolledUp(true);
    }
  }

  function scrollToBottom() {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
    setIsScrolledUp(false);
    setUnreadCount(0);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowUp") {
      if (history.length === 0) return;
      const targetInput = event.currentTarget;
      if (historyIndex === null && targetInput.selectionStart !== 0 && text.length > 0) return;
      event.preventDefault();
      if (historyIndex === null) {
        draftTextRef.current = text;
        const newIndex = history.length - 1;
        setHistoryIndex(newIndex);
        setText(history[newIndex]);
      } else if (historyIndex > 0) {
        const newIndex = historyIndex - 1;
        setHistoryIndex(newIndex);
        setText(history[newIndex]);
      }
    } else if (event.key === "ArrowDown" && historyIndex !== null) {
      event.preventDefault();
      if (historyIndex < history.length - 1) {
        const newIndex = historyIndex + 1;
        setHistoryIndex(newIndex);
        setText(history[newIndex]);
      } else {
        setHistoryIndex(null);
        setText(draftTextRef.current);
      }
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    setError(null);
    if (inputPurpose === "guess") {
      // A guess is volatile: a momentarily unwritable transport drops it. The
      // sender resends once on its own; this only has to report the guess that
      // never made it, which otherwise vanishes with nothing said.
      setDeliveryError(null);
      sendGuess(trimmed, {
        onUndelivered: () =>
          setDeliveryError(ui.roomChatPanel.yourGuessTrimmedDidNot({ trimmed })),
      });
      setHistory((current) =>
        current.length === 0 || current[current.length - 1] !== trimmed
          ? [...current, trimmed]
          : current,
      );
      setHistoryIndex(null);
      // Always: a guess you got right is not a draft worth keeping.
      draftTextRef.current = "";
      setText("");
      scrollToBottom();
      return;
    }

    setSending(true);
    try {
      const response = await emitWithAck<AckResponse>("send_chat", { text: trimmed });
      if (response.ok) {
        setText("");
        scrollToBottom();
      } else {
        setError(refusalText(response, ui.roomChatPanel.couldNotSendMessage));
      }
    } catch (sendError) {
      setError(socketRequestErrorMessage(sendError, ui.roomChatPanel.sendTheMessage));
    } finally {
      setSending(false);
    }
  }

  const typedPromptLengths = letterRunLengths(text);
  const showLiveLetterCounts = text.trim().length <= MAX_PROMPT_LENGTH;
  const activeIndex =
    text.length > 0 && /[\p{L}\p{N}]/u.test(text[text.length - 1])
      ? typedPromptLengths.length - 1
      : -1;

  function hintClass(index: number) {
    const target = Number(targetPromptLengths[index]);
    const typed = typedPromptLengths[index];
    if (index === activeIndex && (!Number.isFinite(target) || typed < target)) {
      return "guess-hint-typing";
    }
    return typed === target ? "guess-hint-correct" : "guess-hint-wrong";
  }

  return (
    <section
      className={`room-chat-panel guess-chat${mode === "waiting" ? " waiting-chat" : ""}`}
      aria-labelledby="room-chat-title"
    >
      <div className="room-panel-heading room-chat-heading">
        <h2 id="room-chat-title">
          {mode === "waiting"
            ? ui.roomChatPanel.chatWhileYouWait
            : mode === "game-end"
              ? ui.roomChatPanel.gameChat
              : ui.roomChatPanel.guessAndChat}
        </h2>
      </div>

      <div className="chat-messages-container">
        {/* Focusable because it scrolls: a scroll region a keyboard cannot
            reach is content a keyboard cannot read. It only became genuinely
            scrollable once the feed stopped overflowing out of its own top,
            which is why axe had nothing to say about it before. */}
        <div
          className="chat-messages"
          ref={listRef}
          onScroll={handleScroll}
          tabIndex={0}
          role="log"
          aria-label={mode === "playing" ? ui.roomChatPanel.guessesAndChat : ui.roomChatPanel.roomChat}
        >
          {messages.length === 0 ? (
            <p className="waiting-chat-empty">
              {mode === "waiting" ? ui.roomChatPanel.sayHelloBeforeTheGame : ui.roomChatPanel.noMessagesYet}
            </p>
          ) : (
            <ChatMessageList messages={messages} players={players} locale={locale} />
          )}
        </div>
        {isScrolledUp && unreadCount > 0 && (
          <button type="button" className="chat-scroll-bottom-button" onClick={scrollToBottom}>
            <ChevronDownIcon size={13} /> {ui.roomChatPanel.unreadMessages({ count: unreadCount })}
          </button>
        )}
      </div>
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true" data-testid="chat-announcer">
        {liveAnnouncement}
      </div>

      {(error ?? deliveryError) && (
        <p className="waiting-chat-error" role="alert">{error ?? deliveryError}</p>
      )}
      {mode === "playing" && guessedPrompt && (
        <p className="guess-verdict-hit" data-testid="guess-verdict-hit">
          <span className="guess-verdict-hit-head">
            {ui.roomChatPanel.correctWithPlace({
              place: guessPlace ? ui.format.ordinal({ value: guessPlace }) : null,
            })}
          </span>
          <span className="guess-verdict-hit-word">{guessedPrompt}</span>
          {guessBreakdown && guessBreakdown.points > 0 && (
            <span className="guess-verdict-hit-points">+{guessBreakdown.points}</span>
          )}
        </p>
      )}
      {inputVisible && (
        <form
          className={`chat-input${mode === "waiting" ? " waiting-chat-form" : ""}${guessedPrompt && mode === "playing" ? " has-guessed" : ""}`}
          onSubmit={(event) => void handleSubmit(event)}
        >
          {guessFlash && (
            <p
              className={`guess-focus-flash guess-focus-flash-${guessFlash.kind}`}
              role="status"
              aria-live="polite"
              data-testid="guess-focus-flash"
            >
              {guessFlash.kind === "close" ? guessFlash.text : guessFlash.kind === "miss" ? (
                <>
                  <span className="guess-focus-flash-label">{ui.roomChatPanel.sent}</span> {guessFlash.text}
                </>
              ) : (
                guessFlash.text
              )}
            </p>
          )}
          <div className="guess-hint">
            {mode === "playing"
              && canGuess
              && !hideMaskedPrompt
              && showLiveLetterCounts
              && typedPromptLengths.map((count, index) => (
                <sup key={index} className={hintClass(index)}>
                  {count}
                </sup>
              ))}
          </div>
          <div className="chat-input-row">
            <div className="chat-input-box">
              {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
              <input
                ref={inputRef}
                type="search"
                inputMode="text"
                value={text}
                onChange={(event) => {
                  setText(event.target.value);
                  if (guessFlash) setGuessFlash(null);
                }}
                onKeyDown={handleKeyDown}
                onFocus={() => {
                  wasFocusedRef.current = true;
                  if (blurTimeoutRef.current != null) {
                    window.clearTimeout(blurTimeoutRef.current);
                    blurTimeoutRef.current = null;
                  }
                  onFocusChange?.(true);
                }}
                onBlur={() => {
                  wasFocusedRef.current = false;
                  if (blurTimeoutRef.current != null) {
                    window.clearTimeout(blurTimeoutRef.current);
                  }
                  blurTimeoutRef.current = window.setTimeout(() => {
                    blurTimeoutRef.current = null;
                    onFocusChange?.(false);
                  }, 150);
                }}
                placeholder={
                  mode === "playing" && canGuess ? ui.roomChatPanel.typeYourGuess : ui.roomChatPanel.typeAMessage
                }
                maxLength={500}
                autoComplete="off"
                autoCapitalize={inputPurpose === "chat" ? "sentences" : "none"}
                spellCheck={inputPurpose === "chat"}
                autoCorrect={inputPurpose === "guess" ? "off" : undefined}
                enterKeyHint="send"
              />
            </div>
            <button type="submit" className="chat-send-button" disabled={sending} aria-label={ui.roomChatPanel.send}>
              <ChevronRightIcon size={17} />
            </button>
          </div>
        </form>
      )}
      {mode === "playing" && isDrawer && (
        <p className="room-chat-drawer-note">{ui.roomChatPanel.youReDrawingWatchGuessesCome}</p>
      )}
    </section>
  );
}

/** The lines themselves, apart from the panel that owns the input (#988).

The guess box's text is state on the panel, so every keystroke re-rendered
every line - up to the hundred the store keeps, three `players.find` scans
each - and a new message rendered them all twice, through the panel's
render-phase bookkeeping. Memoised on the messages and the roster, and each
line on its own message, a keystroke renders no line and a message renders
one. */
const ChatMessageList = memo(function ChatMessageList({
  messages,
  players,
  locale,
}: {
  messages: ChatMessage[];
  players: PlayerInfo[];
  /** Compared by memo so a language switch re-renders the lines: an
      announcement's words are read from `ui` at render. */
  locale: string;
}) {
  const byId = useMemo(() => new Map(players.map((player) => [player.playerId, player])), [players]);
  return messages.map((message) => {
    const player = message.playerId ? byId.get(message.playerId) : undefined;
    return (
      <ChatLine
        key={message.id}
        message={message}
        isAnonymous={player?.isAnonymous}
        nameColor={message.nameColor ?? player?.nameColor ?? undefined}
        locale={locale}
      />
    );
  });
});

const ChatLine = memo(function ChatLine({
  message,
  isAnonymous,
  nameColor,
}: {
  message: ChatMessage;
  isAnonymous: boolean | undefined;
  nameColor: string | undefined;
  /** Unused in the body; there so memo sees a language switch (R-I18N-03). */
  locale: string;
}) {
  recordRender("chatLine");
  return (
    <div
      className={`chat-message${message.system ? " system" : ""}${message.correct ? " correct" : ""}${message.close ? " close-hint" : ""}${message.restricted ? " restricted" : ""}`}
    >
      {message.system || message.close ? (
        chatLineText(message)
      ) : (
        <>
          <strong
            className={playerNameClass(isAnonymous)}
            style={playerNameStyle(nameColor, isAnonymous)}
          >
            {message.nickname}:{" "}
          </strong>
          {message.text}
        </>
      )}
    </div>
  );
});
