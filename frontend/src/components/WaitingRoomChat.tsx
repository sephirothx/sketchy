import { useEffect, useRef, useState } from "react";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import type { AckResponse, ChatMessage } from "../types";

interface WaitingRoomChatProps { messages: ChatMessage[]; }

export function WaitingRoomChat({ messages }: WaitingRoomChatProps) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }); }, [messages]);

  async function send() {
    const message = text.trim();
    if (!message || sending) return;
    setSending(true);
    setError(null);
    try {
      const response = await emitWithAck<AckResponse>("send_chat", { text: message });
      if (response.ok) setText("");
      else setError(response.error || "Could not send message");
    } catch (sendError) {
      setError(socketRequestErrorMessage(sendError, "send the message"));
    } finally {
      setSending(false);
    }
  }

  return <section className="waiting-card waiting-chat" aria-labelledby="waiting-chat-title">
    <p className="waiting-card-kicker">Room chat</p><h2 id="waiting-chat-title">Chat while you wait</h2>
    <div className="chat-messages-container">
    <div className="chat-messages" ref={listRef}>
      {messages.length === 0 ? <p className="waiting-chat-empty">Say hello before the game starts.</p> : messages.map((message) =>
        <div key={message.id} className={`chat-message${message.system ? " system" : ""}`}>{message.system ? message.text : <><strong>{message.nickname}:</strong> {message.text}</>}</div>
      )}
    </div></div>
    {error && <p className="waiting-chat-error" role="alert">{error}</p>}
    <form className="chat-input waiting-chat-form" onSubmit={(event) => { event.preventDefault(); void send(); }}>
      <div className="chat-input-row"><div className="chat-input-box"><input value={text} onChange={(event) => setText(event.target.value)} placeholder="Type a message..." maxLength={60} autoComplete="off" /></div>
      <button type="submit" disabled={sending}>{sending ? "Sending…" : "Send"}</button>
      </div>
    </form>
  </section>;
}
