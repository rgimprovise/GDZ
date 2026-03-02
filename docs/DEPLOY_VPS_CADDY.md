# Деплой TutorBot на VPS (Ubuntu + Caddy)

## Архитектура

- **postgres** — БД (users, subscriptions, conversations, messages)
- **api** — FastAPI, OpenAI Assistants API, Whisper, Vision
- **bot** — Telegram-бот (лаунчер TMA)
- **tma** — React-приложение (nginx), основной интерфейс

Caddy проксирует домен на TMA (порт 3010). Nginx внутри TMA проксирует `/v1/*` на API (порт 8000) внутри Docker-сети.

---

## 1. Первоначальная настройка (один раз)

### 1.1 Клонирование

```bash
cd /opt
git clone https://github.com/rgimprovise/GDZ.git tutorbot
cd tutorbot/infra
cp env.example .env
nano .env
```

Заполнить в `.env`:
- `OPENAI_API_KEY` — ключ OpenAI
- `OPENAI_ASSISTANT_ID` — ID ассистента (из скриншота: `asst_5g1hZDgTWyGjUBHWyBiHMpRH`)
- `TELEGRAM_BOT_TOKEN` — токен бота
- `TMA_URL` — `https://gdz.n8nrgimprovise.space` (URL, куда Caddy проксирует TMA)
- `POSTGRES_PASSWORD` — сменить на безопасный
- `JWT_SECRET` — сменить

### 1.2 Caddy

```bash
sudo nano /etc/caddy/Caddyfile
```

Добавить блок:

```
gdz.n8nrgimprovise.space {
    encode gzip
    reverse_proxy localhost:3010
}
```

```bash
sudo systemctl reload caddy
```

### 1.3 Запуск

```bash
cd /opt/tutorbot/infra

# Если порт 5432 занят — используйте vps-ports:
docker compose -f docker-compose.yml -f docker-compose.vps-ports.yml up -d --build

# Если порт 5432 свободен:
docker compose up -d --build

# Применить миграции
docker compose exec api alembic upgrade head
```

### 1.4 Проверка

```bash
curl -s http://localhost:8000/health
curl -s https://gdz.n8nrgimprovise.space/health
```

---

## 2. Обновление (при каждой итерации)

Перед обновлением на VPS все изменения должны быть запушены в GitHub (чтобы `git pull` их подтянул).

### Локально (перед деплоем):

```bash
git add -A && git commit -m "описание" && git push origin main
```

### На VPS (каноничная последовательность):

Остановить контейнеры, подтянуть код, пересобрать образы, поднять заново. На VPS часто стоит docker-compose v1 — команда с дефисом.

```bash
cd /opt/tutorbot && git pull origin main
cd infra
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml down
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml build --no-cache
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml up -d
```

При необходимости миграции (после изменения схемы БД):

```bash
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml exec api alembic upgrade head
```

---

## 3. Диагностика

```bash
cd /opt/tutorbot/infra

# Статус контейнеров
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml ps -a

# Логи (v1: --tail=50 перед именем сервиса)
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml logs --tail=50 api

# Проверка API
curl -s http://localhost:8000/health
curl -s http://localhost:8000/docs

# Проверка TMA
curl -s http://localhost:3010/
```

---

## 4. TMA URL — как настроить

TMA URL — это адрес, по которому доступно мини-приложение через Telegram.

1. Caddy проксирует `gdz.n8nrgimprovise.space` → `localhost:3010` (TMA)
2. В BotFather: `/newapp` или `/editapp` → указать URL: `https://gdz.n8nrgimprovise.space`
3. В `.env` на VPS: `TMA_URL=https://gdz.n8nrgimprovise.space`
4. Бот показывает кнопку "Открыть TutorBot" → открывает TMA по этому URL

---

## 5. Лимиты и выдача премиума

**Как работает лимит**

- У каждого пользователя есть подписка (subscription) на план (plan).
- План задаёт `daily_queries` и `monthly_queries`. В подписке хранятся счётчики `queries_used_today` и `queries_used_month`.
- При каждом запросе к ассистенту (текст/аудио/картинка) вызывается `_check_limits`: если `queries_used_today >= plan.daily_queries` → ответ 429 «Daily limit reached (N)».
- План по умолчанию (миграция 001) — «Free» с `daily_queries=5`. Если в БД так и осталось, все пользователи на этом плане получают лимит 5.

**Почему может не срабатывать UNLIMITED_TG_IDS**

- Лимит не проверяется только если в запросе «виден» твой Telegram ID: либо пользователь в БД с `tg_uid=430019680`, либо в заголовке приходит `X-Telegram-User-Id: 430019680`.
- Если ты заходишь как гость (без авторизации Telegram), в БД используется пользователь с `tg_uid=0`, и заголовок с твоим id может не уходить — тогда исключение по UNLIMITED_TG_IDS не срабатывает.

**Надёжный способ — выдать премиум в БД**

Вариант 1 — скрипт из контейнера API (рекомендуется):

```bash
cd /opt/tutorbot/infra
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml exec api python -m scripts.promote_premium 430019680
```

Скрипт: находит пользователя с `tg_uid=430019680`, создаёт план «Premium» с `daily_queries=99999` (если его ещё нет), переводит активную подписку пользователя на этот план и обнуляет счётчики. Пользователь должен уже существовать в БД (хотя бы один раз зайти из Telegram с этим id или быть созданным иначе).

Вариант 2 — вручную SQL (если пользователя с таким tg_uid ещё нет, сначала открой приложение из Telegram один раз):

```bash
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml exec postgres psql -U tutorbot -d tutorbot -c "
-- посмотреть планы и пользователя
SELECT id, name, type, daily_queries FROM plans;
SELECT id, tg_uid, display_name FROM users WHERE tg_uid = 430019680;

-- создать план «Премиум» (если ещё нет)
INSERT INTO plans (name, type, daily_queries, monthly_queries, price_monthly, price_yearly, features, is_active)
VALUES ('Premium', 'premium', 99999, 999999, 0, 0, '{}', true)
ON CONFLICT (name) DO NOTHING;

-- привязать подписку пользователя к премиум-плану (подставь user_id и plan id из SELECT выше)
UPDATE subscriptions SET plan_id = (SELECT id FROM plans WHERE name = 'Premium'), queries_used_today = 0, queries_used_month = 0
WHERE user_id = (SELECT id FROM users WHERE tg_uid = 430019680) AND status = 'active';
"
```

Если пользователя с `tg_uid=430019680` нет — открой TMA из Telegram (не из браузера), отправь один запрос, чтобы создался пользователь, затем выполни скрипт или SQL.
