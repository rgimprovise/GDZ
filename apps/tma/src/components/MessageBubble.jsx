import React from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

export default function MessageBubble({ message }) {
  const isUser = message.role === "user";

  const badge =
    message.input_type === "audio"
      ? "🎤 "
      : message.input_type === "image"
        ? "📷 "
        : "";

  return (
    <div className={`bubble ${isUser ? "user" : "assistant"}`}>
      {badge && <span className="bubble-badge">{badge}</span>}
      {isUser ? (
        <p>{message.content}</p>
      ) : (
        <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
          {message.content}
        </ReactMarkdown>
      )}
    </div>
  );
}
