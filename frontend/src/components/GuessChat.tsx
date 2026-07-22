import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { socket } from "../lib/socket";
import type { ChatMessage } from "../types";

interface GuessChatProps {
  messages: ChatMessage[];
  isDrawer: boolean;
  canGuess: boolean;
  targetWordLengths: string[];
}

// Mirrors the backend's masked_word() grouping: runs of letters/digits are
// counted, while spaces and other symbols (hyphens, apostrophes, etc.) act
// only as separators between them, e.g. "wall-e" -> [4, 1], not 6.
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

export function GuessChat({ messages, isDrawer, canGuess, targetWordLengths }: GuessChatProps) {
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

  // Live letter-run-length hint for the guess currently being typed, e.g.
  // "this is" -> [4, 2], updating as each character is entered.
  const typedWordLengths = letterRunLengths(text);

  // Only the last run is still "active" (growing) - that's the case as long
  // as the text doesn't end with a separator (space, hyphen, etc.), meaning
  // the cursor could still add more letters to it. Every earlier run is
  // already locked in and can never change again.
  const activeIndex =
    text.length > 0 && /[\p{L}\p{N}]/u.test(text[text.length - 1]) ? typedWordLengths.length - 1 : -1;

  // The active word is gray while still short of its target length, turning
  // green/red the instant it matches/exceeds it. A locked-in word is never
  // gray - it's immediately green if it matches the target, red otherwise.
  function hintClass(index: number) {
    const target = Number(targetWordLengths[index]);
    const typed = typedWordLengths[index];
    if (index === activeIndex && (!Number.isFinite(target) || typed < target)) {
      return "guess-hint-typing";
    }
    return typed === target ? "guess-hint-correct" : "guess-hint-wrong";
  }

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
            className={`chat-message${m.system ? " system" : ""}${m.correct ? " correct" : ""}${m.close ? " close-hint" : ""}`}
          >
            {m.system || m.close ? (
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
          <div className="guess-hint">
            {canGuess &&
              typedWordLengths.map((count, index) => (
                <sup key={index} className={hintClass(index)}>
                  {count}
                </sup>
              ))}
          </div>
          <div className="chat-input-row">
            <div className="chat-input-box">
              <input
                type="text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={canGuess ? "Type your guess..." : "Type a message..."}
                maxLength={60}
              />
            </div>
            <button type="submit">Send</button>
          </div>
        </form>
      )}
    </div>
  );
}
