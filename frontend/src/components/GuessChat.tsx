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

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

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
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={canGuess ? "Type your guess..." : "Type a message..."}
            maxLength={60}
          />
          <button type="submit">Send</button>
        </form>
      )}
    </div>
  );
}
