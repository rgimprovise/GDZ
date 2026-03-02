import React, { useEffect, useRef, useState } from "react";
import MessageBubble from "./MessageBubble";
import AudioRecorder from "./AudioRecorder";
import {
  getMessages,
  sendTextMessage,
  sendAudio,
  sendImage,
} from "../api/client";

export default function Chat({ conversationId, onRefresh }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);
  const fileRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    setMessages([]);
    setError(null);
    getMessages(conversationId)
      .then((msgs) => setMessages(Array.isArray(msgs) ? msgs : []))
      .catch((err) => {
        console.error("Load messages failed:", err);
        setError(err.message);
      });
  }, [conversationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSendText = async () => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    const userText = trimmed;
    setText("");
    setLoading(true);
    setError(null);

    const optimisticMsg = {
      id: `tmp-${Date.now()}`,
      role: "user",
      content: userText,
      input_type: "text",
      tokens_used: 0,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticMsg]);

    try {
      const reply = await sendTextMessage(conversationId, userText);
      setMessages((prev) => {
        const filtered = prev.filter((m) => m.id !== optimisticMsg.id);
        return [...filtered, reply.user_message, reply.assistant_message];
      });
      onRefresh?.();
    } catch (err) {
      setError(err.message || "Ошибка отправки");
      setMessages((prev) => prev.filter((m) => m.id !== optimisticMsg.id));
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendText();
    }
  };

  const handleAudio = async (blob) => {
    setLoading(true);
    setError(null);
    try {
      const reply = await sendAudio(conversationId, blob);
      setMessages((prev) => [...prev, reply.user_message, reply.assistant_message]);
      onRefresh?.();
    } catch (err) {
      setError(err.message || "Ошибка записи");
    } finally {
      setLoading(false);
    }
  };

  const handleImage = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const reply = await sendImage(conversationId, file);
      setMessages((prev) => [...prev, reply.user_message, reply.assistant_message]);
      onRefresh?.();
    } catch (err) {
      setError(err.message || "Ошибка распознавания");
    } finally {
      setLoading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="chat">
      <div className="chat-messages">
        {messages.length === 0 && !loading && !error && (
          <div className="chat-empty">
            <div className="chat-empty-icon">💬</div>
            <p>Спроси что-нибудь по учебе</p>
            <span className="chat-empty-hint">Текст, голос или фото задания</span>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {loading && (
          <div className="bubble assistant">
            <div className="typing-indicator">
              <span /><span /><span />
            </div>
          </div>
        )}
        {error && (
          <div className="chat-error" onClick={() => setError(null)}>
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input">
        <button
          className="chat-input-btn"
          onClick={() => fileRef.current?.click()}
          disabled={loading}
          aria-label="Attach photo"
        >
          📷
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={handleImage}
        />

        <textarea
          ref={inputRef}
          className="chat-input-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Спроси что-нибудь по учебе..."
          rows={1}
          disabled={loading}
          autoFocus
        />

        <AudioRecorder onRecorded={handleAudio} disabled={loading} />

        <button
          className="chat-input-btn send"
          onClick={handleSendText}
          disabled={loading || !text.trim()}
          aria-label="Send"
        >
          &#10148;
        </button>
      </div>
    </div>
  );
}
