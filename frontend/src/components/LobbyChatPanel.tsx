import { useClock } from "../hooks/useClock";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { chatTimeLabel } from "../lib/lobbyChat";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { needsIdentity, useAuthStore } from "../store/authStore";
import { useLobbyChatStore } from "../store/lobbyChatStore";
import type { AckResponse } from "../types";
import { ChevronRightIcon } from "./icons";

/** How often the labels beside the lines are re-read. "now" becomes "1m"
without a new line arriving, which is the point of the label. */
const CLOCK_TICK_MS = 30_000;
const MAX_LINE_LENGTH = 500;

function identityMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "Could not save that name. Please try again.";
}

/** The lobby's chat: the recent lines, and a way to add one.

Anyone with a name may speak - the same boundary as the online list beside
it. A visitor who has not chosen one yet is offered that instead of a box
that would refuse them, and choosing it reconnects the socket, which is what
makes the next line theirs. */
export function LobbyChatPanel() {
  const { timeFormat, dateTime } = useClock();
  const lines = useLobbyChatStore((state) => state.chat.lines);
  const awaitingName = useAuthStore((state) => needsIdentity(state.user));
  const ensureIdentity = useAuthStore((state) => state.ensureIdentity);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [isScrolledUp, setIsScrolledUp] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), CLOCK_TICK_MS);
    return () => window.clearInterval(tick);
  }, []);

  useEffect(() => {
    if (!isScrolledUp) {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
    }
  }, [lines, isScrolledUp]);

  function handleScroll() {
    const element = listRef.current;
    if (!element) return;
    const distanceToBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    setIsScrolledUp(distanceToBottom > 30);
  }

  async function chooseName() {
    setError(null);
    try {
      await ensureIdentity();
    } catch (identityError) {
      setError(identityMessage(identityError));
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setSending(true);
    setError(null);
    try {
      const response = await emitWithAck<AckResponse>("send_lobby_chat", { text: trimmed });
      if (response.ok) {
        setText("");
        setIsScrolledUp(false);
      } else {
        setError(response.error || "Could not send that.");
      }
    } catch (sendError) {
      setError(socketRequestErrorMessage(sendError, "send the message"));
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  return (
    <section className="panel lobby-chat-panel" aria-labelledby="lobby-chat-heading">
      <div className="lobby-rooms-heading">
        <h2 id="lobby-chat-heading">Chat</h2>
      </div>
      <div className="chat-messages-container">
        {/* Focusable because it scrolls: a keyboard user has to be able to
            reach the lines that scrolled out of view. */}
        <div
          ref={listRef}
          className="chat-messages lobby-chat-list"
          onScroll={handleScroll}
          tabIndex={0}
          role="log"
          aria-label="Lobby chat"
          data-testid="lobby-chat-list"
        >
          {lines.length === 0 ? (
            <p className="lobby-chat-empty">Nobody has said anything yet.</p>
          ) : (
            lines.map((line) => {
              const at = new Date(line.sentAt);
              return (
                <div key={line.seq} className="chat-message lobby-chat-line">
                  <span className="lobby-chat-body">
                    <strong
                      className={playerNameClass(line.isAnonymous)}
                      style={playerNameStyle(line.nameColor ?? undefined, line.isAnonymous)}
                    >
                      {line.displayName}:{" "}
                    </strong>
                    {line.text}
                  </span>
                  {/* Fresh or stale at a glance; the whole instant on hover. */}
                  <time className="lobby-chat-time" dateTime={at.toISOString()} title={dateTime(at)}>
                    {chatTimeLabel(line.sentAt, now, timeFormat)}
                  </time>
                </div>
              );
            })
          )}
        </div>
      </div>
      {error && (
        <p className="waiting-chat-error" role="alert">
          {error}
        </p>
      )}
      {awaitingName ? (
        <button type="button" className="btn btn-secondary lobby-chat-name-prompt" onClick={() => void chooseName()}>
          Choose a name to chat
        </button>
      ) : (
        <form className="chat-input lobby-chat-form" onSubmit={(event) => void handleSubmit(event)}>
          <div className="chat-input-row">
            <div className="chat-input-box">
              {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
              <input
                ref={inputRef}
                type="search"
                inputMode="text"
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="Say something to the lobby..."
                aria-label="Lobby chat message"
                maxLength={MAX_LINE_LENGTH}
                autoComplete="off"
                autoCapitalize="sentences"
                spellCheck
                enterKeyHint="send"
              />
            </div>
            <button type="submit" className="chat-send-button" disabled={sending} aria-label="Send">
              <ChevronRightIcon size={17} />
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
