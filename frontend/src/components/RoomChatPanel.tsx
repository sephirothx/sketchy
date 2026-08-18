import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { MAX_WORD_LENGTH } from "../lib/customWords";
import { chatAnnouncement } from "../lib/chatAnnouncements";
import { recordRender } from "../lib/renderDiagnostics";
import { emitWithAck, socket, socketRequestErrorMessage } from "../lib/socket";
import type { AckResponse, ChatMessage, PlayerInfo } from "../types";

interface RoomChatPanelProps {
  messages: ChatMessage[];
  players: PlayerInfo[];
  mode: "waiting" | "playing" | "game-end";
  isDrawer: boolean;
  canGuess: boolean;
  myPlayerId?: string | null;
  targetWordLengths: string[];
  hideMaskedPrompt?: boolean;
  onFocusChange?: (focused: boolean) => void;
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
  targetWordLengths,
  hideMaskedPrompt = false,
  onFocusChange,
}: RoomChatPanelProps) {
  recordRender("chat");
  const inputPurpose = mode === "playing" ? "guess" : "chat";
  const [previousInputPurpose, setPreviousInputPurpose] = useState(inputPurpose);
  const [text, setText] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
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

  useEffect(() => {
    if (!canGuess || isDrawer) {
      if (blurTimeoutRef.current != null) {
        window.clearTimeout(blurTimeoutRef.current);
        blurTimeoutRef.current = null;
      }
      inputRef.current?.blur();
      onFocusChange?.(false);
    }
  }, [canGuess, isDrawer, onFocusChange]);

  useEffect(() => {
    if (!guessFlash) return;
    const flashId = guessFlash.id;
    const timeout = window.setTimeout(() => {
      setGuessFlash((current) => (current?.id === flashId ? null : current));
    }, 3200);
    return () => window.clearTimeout(timeout);
  }, [guessFlash]);

  if (previousInputPurpose !== inputPurpose) {
    setPreviousInputPurpose(inputPurpose);
    setText("");
    setHistoryIndex(null);
    setError(null);
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
        flash = { id: newestMessage.id, text: newestMessage.text, kind: "close" };
      } else if (newestMessage.restricted && (!newestMessage.playerId || newestMessage.playerId === myPlayerId)) {
        flash = { id: newestMessage.id, text: newestMessage.text, kind: "miss" };
      } else if (
        newestMessage.playerId === myPlayerId
        && !newestMessage.system
        && !newestMessage.correct
        && !newestMessage.close
      ) {
        flash = { id: newestMessage.id, text: newestMessage.text, kind: "miss" };
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
    if (inputPurpose !== "guess") return;
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
      socket.emit("guess", { text: trimmed });
      setHistory((current) =>
        current.length === 0 || current[current.length - 1] !== trimmed
          ? [...current, trimmed]
          : current,
      );
      setHistoryIndex(null);
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
        setError(response.error || "Could not send message");
      }
    } catch (sendError) {
      setError(socketRequestErrorMessage(sendError, "send the message"));
    } finally {
      setSending(false);
    }
  }

  const typedWordLengths = letterRunLengths(text);
  const showLiveLetterCounts = text.trim().length <= MAX_WORD_LENGTH;
  const activeIndex =
    text.length > 0 && /[\p{L}\p{N}]/u.test(text[text.length - 1])
      ? typedWordLengths.length - 1
      : -1;

  function hintClass(index: number) {
    const target = Number(targetWordLengths[index]);
    const typed = typedWordLengths[index];
    if (index === activeIndex && (!Number.isFinite(target) || typed < target)) {
      return "guess-hint-typing";
    }
    return typed === target ? "guess-hint-correct" : "guess-hint-wrong";
  }

  const inputVisible = mode !== "playing" || !isDrawer;

  return (
    <section
      className={`room-chat-panel guess-chat${mode === "waiting" ? " waiting-chat" : ""}`}
      aria-labelledby="room-chat-title"
    >
      <div className="room-panel-heading room-chat-heading">
        <div>
          <p className="room-panel-kicker">Room chat</p>
          <h2 id="room-chat-title">
            {mode === "waiting"
              ? "Chat while you wait"
              : mode === "game-end"
                ? "Game chat"
                : "Guess and chat"}
          </h2>
        </div>
      </div>

      <div className="chat-messages-container">
        <div className="chat-messages" ref={listRef} onScroll={handleScroll}>
          {messages.length === 0 ? (
            <p className="waiting-chat-empty">
              {mode === "waiting" ? "Say hello before the game starts." : "No messages yet."}
            </p>
          ) : (
            messages.map((message) => (
              <div
                key={message.id}
                className={`chat-message${message.system ? " system" : ""}${message.correct ? " correct" : ""}${message.close ? " close-hint" : ""}${message.restricted ? " restricted" : ""}`}
              >
                {message.system || message.close ? (
                  message.text
                ) : (
                  <>
                    <strong
                      className={
                        players.find((player) => player.playerId === message.playerId)
                          ?.isAnonymous
                          ? "colored-player-name is-guest"
                          : "colored-player-name"
                      }
                      style={{
                        color: message.nameColor
                          ?? players.find((player) => player.playerId === message.playerId)
                            ?.nameColor,
                      }}
                    >
                      {message.nickname}:{" "}
                    </strong>
                    {message.text}
                  </>
                )}
              </div>
            ))
          )}
        </div>
        {isScrolledUp && unreadCount > 0 && (
          <button type="button" className="chat-scroll-bottom-button" onClick={scrollToBottom}>
            ↓ {unreadCount} new {unreadCount === 1 ? "message" : "messages"}
          </button>
        )}
      </div>
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true" data-testid="chat-announcer">
        {liveAnnouncement}
      </div>

      {error && <p className="waiting-chat-error" role="alert">{error}</p>}
      {inputVisible && (
        <form
          className={`chat-input${mode === "waiting" ? " waiting-chat-form" : ""}`}
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
                  <span className="guess-focus-flash-label">Sent:</span> {guessFlash.text}
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
              && typedWordLengths.map((count, index) => (
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
                onChange={(event) => setText(event.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={() => {
                  if (blurTimeoutRef.current != null) {
                    window.clearTimeout(blurTimeoutRef.current);
                    blurTimeoutRef.current = null;
                  }
                  onFocusChange?.(true);
                }}
                onBlur={() => {
                  if (blurTimeoutRef.current != null) {
                    window.clearTimeout(blurTimeoutRef.current);
                  }
                  blurTimeoutRef.current = window.setTimeout(() => {
                    blurTimeoutRef.current = null;
                    onFocusChange?.(false);
                  }, 150);
                }}
                placeholder={
                  mode === "playing" && canGuess ? "Type your guess..." : "Type a message..."
                }
                maxLength={500}
                autoComplete="off"
                autoCapitalize={inputPurpose === "chat" ? "sentences" : "none"}
                spellCheck={inputPurpose === "chat"}
                autoCorrect={inputPurpose === "guess" ? "off" : undefined}
                enterKeyHint="send"
              />
            </div>
            <button type="submit" disabled={sending}>
              {sending ? "Sending…" : "Send"}
            </button>
          </div>
        </form>
      )}
      {mode === "playing" && isDrawer && (
        <p className="room-chat-drawer-note">You’re drawing—watch the guesses come in.</p>
      )}
    </section>
  );
}
