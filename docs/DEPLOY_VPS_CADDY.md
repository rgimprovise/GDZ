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
