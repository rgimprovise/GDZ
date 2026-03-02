import React from "react";

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  open,
  onClose,
  user,
}) {
  return (
    <>
      {open && <div className="sidebar-overlay" onClick={onClose} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-header">
          <span className="sidebar-user">
            {user.display_name || user.username || "User"}
          </span>
          <button className="sidebar-close" onClick={onClose}>
            &times;
          </button>
        </div>

        <button className="sidebar-new" onClick={onNew}>
          + Новый диалог
        </button>

        <div className="sidebar-list">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`sidebar-item ${c.id === activeId ? "active" : ""}`}
              onClick={() => onSelect(c.id)}
            >
              <span className="sidebar-item-title">
                {c.title || "Без названия"}
              </span>
              <button
                className="sidebar-item-del"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(c.id);
                }}
                aria-label="Delete"
              >
                &times;
              </button>
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <span className="sidebar-plan">
            {user.plan_type} &middot;{" "}
            {user.daily_queries_remaining} запросов
          </span>
        </div>
      </aside>
    </>
  );
}
