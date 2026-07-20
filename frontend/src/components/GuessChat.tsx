import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { socket } from "../lib/socket";
import type { ChatMessage } from "../types";

interface GuessChatProps {
  messages: ChatMessage[];
  isDrawer: boolean;
  canGuess: boolean;
}

export function GuessChat({ messages, isDrawer, canGuess }: GuessChatProps) {
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement | null>(null);
  const mirrorRef = useRef<HTMLSpanElement | null>(null);
  const [inputWidth, setInputWidth] = useState(0);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

  // Measure the typed text's actual rendered pixel width via a hidden mirror
  // element (same font as the input) so the input can grow to fit it exactly.
  // The `size` attribute only approximates width from an average character
  // count, which drifts further off the longer/more varied the text gets.
  useEffect(() => {
    setInputWidth(mirrorRef.current?.scrollWidth ?? 0);
  }, [text]);

  // Live word-length hint for the guess currently being typed, e.g. "this is"
  // -> ["4", "2"], updating as each character is entered.
  const typedWordLengths = text
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => String(word.length));

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    socket.emit("guess", { text: trimmed });
    setText("");
  }

  return (
    <div className="guess-chat">
      <div className="chat-messages" ref={listRef}>
        {messages.map((m) => (
          <div
            key={m.id}
            className={`chat-message${m.system ? " system" : ""}${m.correct ? " correct" : ""}`}
          >
            {m.system ? (
              m.text
            ) : (
              <>
                <strong>{m.nickname}: </strong>
                {m.text}
              </>
            )}
          </div>
        ))}
      </div>
      {!isDrawer && (
        <form className="chat-input" onSubmit={handleSubmit}>
          <div className="chat-input-box">
            <span ref={mirrorRef} className="input-mirror" aria-hidden="true">
              {text}
            </span>
            <input
              type="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={canGuess ? "Type your guess..." : "Type a message..."}
              maxLength={60}
              style={
                text ? { flex: "0 0 auto", width: `${inputWidth + 2}px` } : { flex: "1 1 auto" }
              }
            />
            {canGuess && typedWordLengths.length > 0 && (
              <span className="guess-hint">
                {typedWordLengths.map((count, index) => (
                  <sup key={index}>{count}</sup>
                ))}
              </span>
            )}
          </div>
          <button type="submit">Send</button>
        </form>
      )}
    </div>
  );
}
