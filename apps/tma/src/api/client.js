const BASE = import.meta.env.VITE_API_URL || "";

function headers() {
  const h = { "Content-Type": "application/json" };
  const tg = window.Telegram?.WebApp;
  if (tg?.initData) {
    h["X-Telegram-Init-Data"] = tg.initData;
  }
  return h;
}

function authHeaders() {
  const h = {};
  const tg = window.Telegram?.WebApp;
  if (tg?.initData) {
    h["X-Telegram-Init-Data"] = tg.initData;
  }
  return h;
}

async function request(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function authenticate() {
  const tg = window.Telegram?.WebApp;
  const initData =
    tg?.initData || 'user=%7B%22id%22%3A1%2C%22first_name%22%3A%22Dev%22%7D';
  return request("/v1/auth/telegram", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ init_data: initData }),
  });
}

export async function createConversation(title) {
  return request("/v1/conversations", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ title: title || null }),
  });
}

export async function listConversations() {
  return request("/v1/conversations", { headers: headers() });
}

export async function getMessages(conversationId) {
  return request(`/v1/conversations/${conversationId}`, {
    headers: headers(),
  });
}

export async function deleteConversation(conversationId) {
  return request(`/v1/conversations/${conversationId}`, {
    method: "DELETE",
    headers: headers(),
  });
}

export async function sendTextMessage(conversationId, text) {
  return request(`/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ text }),
  });
}

export async function sendAudio(conversationId, blob) {
  const fd = new FormData();
  fd.append("file", blob, "audio.webm");
  return request(`/v1/conversations/${conversationId}/audio`, {
    method: "POST",
    headers: authHeaders(),
    body: fd,
  });
}

export async function sendImage(conversationId, file) {
  const fd = new FormData();
  fd.append("file", file);
  return request(`/v1/conversations/${conversationId}/image`, {
    method: "POST",
    headers: authHeaders(),
    body: fd,
  });
}
