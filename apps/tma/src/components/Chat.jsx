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
  const bottomRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    getMessages(conversationId).then(setMessages).catch(console.error);
  }, [conversationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSendText = async () => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setText("");
    setLoading(true);
    try {
      const reply = await sendTextMessage(conversationId, trimmed);
      setMessages((prev) => [
        ...prev,
        reply.user_message,
        reply.assistant_message,
      ]);
      onRefresh?.();
    } catch (err) {
      alert(err.message);
    } finally {
      setLoading(false);
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
    try {
      const reply = await sendAudio(conversationId, blob);
      setMessages((prev) => [
        ...prev,
        reply.user_message,
        reply.assistant_message,
      ]);
      onRefresh?.();
    } catch (err) {
      alert(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleImage = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      const reply = await sendImage(conversationId, file);
      setMessages((prev) => [
        ...prev,
        reply.user_message,
        reply.assistant_message,
      ]);
      onRefresh?.();
    } catch (err) {
      alert(err.message);
    } finally {
      setLoading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="chat">
      <div className="chat-messages">
        {messages.length === 0 && !loading && (
          <div className="chat-empty">
            Отправь вопрос, фото задания или голосовое сообщение
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
          className="chat-input-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Введи вопрос..."
          rows={1}
          disabled={loading}
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
