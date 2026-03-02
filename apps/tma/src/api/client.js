const BASE = import.meta.env.VITE_API_URL || "";

let _cachedTgUserId = null;

function _getTgUserId() {
  if (_cachedTgUserId) return _cachedTgUserId;

  // 1) Telegram SDK
  const tg = window.Telegram?.WebApp;
  const sdkId = tg?.initDataUnsafe?.user?.id;
  if (sdkId != null) {
    _cachedTgUserId = String(sdkId);
    return _cachedTgUserId;
  }

  // 2) URL parameter (set by the bot: ?tg_uid=123456)
  try {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("tg_uid");
    if (fromUrl && /^\d+$/.test(fromUrl)) {
      _cachedTgUserId = fromUrl;
      return _cachedTgUserId;
    }
  } catch (_) { /* ignore */ }

  return null;
}

function _getTgInitData() {
  const tg = window.Telegram?.WebApp;
  return tg?.initData || null;
}

function headers() {
  const h = { "Content-Type": "application/json" };
  const initData = _getTgInitData();
  if (initData) {
    h["X-Telegram-Init-Data"] = initData;
  }
  const uid = _getTgUserId();
  if (uid) {
    h["X-Telegram-User-Id"] = uid;
  }
  return h;
}

function authHeaders() {
  const h = {};
  const initData = _getTgInitData();
  if (initData) {
    h["X-Telegram-Init-Data"] = initData;
  }
  const uid = _getTgUserId();
  if (uid) {
    h["X-Telegram-User-Id"] = uid;
  }
  return h;
}

function formatError(status, body) {
  if (body?.detail) return body.detail;
  if (status === 502) return "Сервер недоступен. Проверьте, что API запущен (docker-compose up api).";
  if (status === 503) return "Сервис временно недоступен. Проверьте OPENAI_API_KEY и сеть.";
  return `Ошибка ${status}`;
}

async function request(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(formatError(res.status, body));
  }
  if (res.status === 204) return null;
  return res.json();
}

const GUEST_USER = {
  user_id: 0,
  tg_uid: 0,
  username: null,
  display_name: "Гость",
  plan_type: "free",
  daily_queries_remaining: 99,
  monthly_queries_remaining: 999,
};

export async function authenticate() {
  const tg = window.Telegram?.WebApp;
  const initData = tg?.initData;
  const uid = _getTgUserId();

  // Path 1: full initData available — validate on server
  if (initData) {
    console.log("[auth] initData present, calling /v1/auth/telegram");
    try {
      const resp = await request("/v1/auth/telegram", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ init_data: initData }),
      });
      if (resp?.tg_uid) _cachedTgUserId = String(resp.tg_uid);
      console.log("[auth] Authenticated via initData, tg_uid=%s", resp?.tg_uid);
      return resp;
    } catch (err) {
      console.warn("[auth] initData auth failed:", err.message);
      // fall through to path 2
    }
  }

  // Path 2: tg_uid known (from SDK or URL param) — user already registered by bot
  if (uid && uid !== "0") {
    console.log("[auth] Using tg_uid=%s from SDK/URL", uid);
    const tgUser = tg?.initDataUnsafe?.user;
    return {
      user_id: 0,
      tg_uid: Number(uid),
      username: tgUser?.username || null,
      display_name: tgUser
        ? `${tgUser.first_name || ""} ${tgUser.last_name || ""}`.trim()
        : `User ${uid}`,
      plan_type: "free",
      daily_queries_remaining: 99,
      monthly_queries_remaining: 999,
    };
  }

  // Path 3: nothing — guest
  console.warn("[auth] No Telegram identification — guest mode");
  return GUEST_USER;
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
