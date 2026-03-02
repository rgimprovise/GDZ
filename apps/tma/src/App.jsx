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
      .then((u) => setUser(u))
      .catch(console.error);
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
            <h2>TutorBot</h2>
            <p>Задай вопрос по домашнему заданию</p>
            <button className="btn-primary" onClick={handleNew}>
              Новый диалог
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
