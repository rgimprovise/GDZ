import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";

function cleanAssistantText(raw) {
  if (!raw) return "";
  let text = raw;

  // Remove citation markers
  text = text.replace(/【[^】]*】/g, "");
  text = text.replace(/\u3010[^\u3011]*\u3011/g, "");

  // Normalize LaTeX delimiters (in case backend missed them)
  text = text.replace(/\\\(/g, "$").replace(/\\\)/g, "$");
  text = text.replace(/\\\[/g, "$$").replace(/\\\]/g, "$$");

  // Ensure $$ blocks have newlines for proper block rendering
  text = text.replace(/([^\n])\$\$/g, "$1\n$$");
  text = text.replace(/\$\$([^\n])/g, "$$\n$1");

  // Clean {,} → , outside of $...$ blocks
  text = text.replace(/(?<!\$[^$]*)\{,\}(?![^$]*\$)/g, ",");

  // Clean up excessive blank lines
  text = text.replace(/\n{4,}/g, "\n\n\n");

  return text.trim();
}

export default function MessageBubble({ message }) {
  const isUser = message.role === "user";

  const badge =
    message.input_type === "audio"
      ? "🎤 "
      : message.input_type === "image"
        ? "📷 "
        : "";

  const content = useMemo(
    () => (isUser ? message.content : cleanAssistantText(message.content)),
    [message.content, isUser]
  );

  return (
    <div className={`bubble ${isUser ? "user" : "assistant"}`}>
      {badge && <span className="bubble-badge">{badge}</span>}
      {isUser ? (
        <p>{content}</p>
      ) : (
        <ReactMarkdown
          remarkPlugins={[remarkMath, remarkGfm]}
          rehypePlugins={[rehypeKatex]}
        >
          {content}
        </ReactMarkdown>
      )}
    </div>
  );
}
