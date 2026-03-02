import React, { useEffect, useState, useCallback } from "react";
import Sidebar from "./components/Sidebar";
import Chat from "./components/Chat";
import {
  authenticate,
  createConversation,
  listConversations,
  deleteConversation,
} from "./api/client";

export default function App() {
  const [user, setUser] = useState(null);
  const [authError, setAuthError] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (tg) {
      tg.ready();
      tg.expand();
    }
    authenticate()
      .then((u) => {
        setUser(u);
        setAuthError(null);
      })
      .catch((err) => {
        console.error("Auth failed:", err);
        setAuthError(err.message || "Ошибка входа");
        setUser({
          user_id: 0,
          tg_uid: 0,
          username: null,
          display_name: "Гость",
          plan_type: "free",
          daily_queries_remaining: 0,
          monthly_queries_remaining: 0,
        });
      });
  }, []);

  const refresh = useCallback(() => {
    listConversations().then(setConversations).catch(console.error);
  }, []);

  useEffect(() => {
    if (user) refresh();
  }, [user, refresh]);

  const handleNew = async () => {
    const conv = await createConversation(null);
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.id);
    setSidebarOpen(false);
  };

  const handleDelete = async (id) => {
    await deleteConversation(id);
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeId === id) setActiveId(null);
  };

  const handleSelect = (id) => {
    setActiveId(id);
    setSidebarOpen(false);
  };

  if (!user) {
    return <div className="loading">Loading...</div>;
  }

  const isGuest = user && (user.user_id === 0 || user.display_name === "Гость");

  return (
    <div className={`app ${isGuest ? "is-guest" : ""}`}>
      {authError && (
        <div className="auth-banner">
          {authError}
        </div>
      )}
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={handleSelect}
        onNew={handleNew}
        onDelete={handleDelete}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        user={user}
      />
      <main className="main">
        <header className="topbar">
          <button
            className="topbar-menu"
            onClick={() => setSidebarOpen(true)}
            aria-label="Menu"
          >
            &#9776;
          </button>
          <span className="topbar-title">TutorBot</span>
        </header>
        {activeId ? (
          <Chat conversationId={activeId} onRefresh={refresh} />
        ) : (
          <div className="empty-state">
            <h2>Твой умный помощник по учебе</h2>
            <p>Ответы на вопросы из учебника простым языком. Подсказки для ответа у доски.</p>
            <button className="btn-primary" onClick={handleNew}>
              Новый диалог
            </button>
          </div>
        )}
      </main>
      {isGuest && (
        <div className="demo-footer">
          Демо-режим. Авторизацию подключим через бота позже.
        </div>
      )}
    </div>
  );
}
