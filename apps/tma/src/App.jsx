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
  const [error, setError] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (tg) {
      tg.ready();
      tg.expand();
    }
    authenticate()
      .then((u) => setUser(u))
      .catch((err) => {
        console.error("Auth failed:", err);
        setUser({
          user_id: 0,
          display_name: "Гость",
          plan_type: "free",
          daily_queries_remaining: 99,
        });
      });
  }, []);

  const refresh = useCallback(() => {
    listConversations()
      .then(setConversations)
      .catch((err) => console.warn("list err:", err));
  }, []);

  useEffect(() => {
    if (user) refresh();
  }, [user, refresh]);

  const handleNew = async () => {
    if (creating) return;
    setCreating(true);
    setError(null);
    try {
      const conv = await createConversation(null);
      setConversations((prev) => [conv, ...prev]);
      setActiveId(conv.id);
      setSidebarOpen(false);
    } catch (err) {
      console.error("Create conversation failed:", err);
      setError(err.message || "Не удалось создать диалог");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) setActiveId(null);
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const handleSelect = (id) => {
    setActiveId(id);
    setSidebarOpen(false);
  };

  const handleBack = () => setActiveId(null);

  if (!user) {
    return (
      <div className="loading">
        <div className="loading-spinner" />
        <p>Загрузка TutorBot...</p>
      </div>
    );
  }

  return (
    <div className="app">
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
          {activeId ? (
            <button className="topbar-menu" onClick={handleBack} aria-label="Back">
              &#8592;
            </button>
          ) : (
            <button
              className="topbar-menu"
              onClick={() => setSidebarOpen(true)}
              aria-label="Menu"
            >
              &#9776;
            </button>
          )}
          <span className="topbar-title">TutorBot</span>
          {!activeId && (
            <button className="topbar-new" onClick={handleNew} disabled={creating}>
              +
            </button>
          )}
        </header>

        {error && (
          <div className="error-banner" onClick={() => setError(null)}>
            {error} <span className="error-dismiss">&times;</span>
          </div>
        )}

        {activeId ? (
          <Chat conversationId={activeId} onRefresh={refresh} />
        ) : (
          <div className="empty-state">
            <div className="empty-icon">📚</div>
            <h2>Твой умный помощник по учебе</h2>
            <p>
              Ответы на вопросы из учебника простым языком.
              <br />
              Подсказки для ответа у доски.
            </p>
            <button className="btn-primary" onClick={handleNew} disabled={creating}>
              {creating ? "Создаю..." : "Новый диалог"}
            </button>

            {conversations.length > 0 && (
              <div className="recent-conversations">
                <h3>Недавние диалоги</h3>
                {conversations.slice(0, 5).map((c) => (
                  <button
                    key={c.id}
                    className="recent-item"
                    onClick={() => handleSelect(c.id)}
                  >
                    {c.title || c.last_message || "Без названия"}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
      {(!user?.tg_uid || user.tg_uid === 0) && (
        <div className="demo-footer">Демо-режим</div>
      )}
    </div>
  );
}
