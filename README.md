# TutorBot — Educational Tutoring Assistant

Telegram Mini App + API для помощи с домашними заданиями. Ответы генерируются через OpenAI Assistant с Vector Store на основе учебников.

## Архитектура

```
apps/
  api/     → FastAPI (auth, conversations, OpenAI Assistants API)
  bot/     → Telegram Bot (лаунчер TMA)
  tma/     → React + Vite (Telegram Mini App, основной клиент)

infra/
  docker-compose.yml → Postgres, API, Bot, TMA
```

## Быстрый старт

```bash
cd infra
cp env.example .env
# Заполнить: OPENAI_API_KEY, OPENAI_ASSISTANT_ID, TELEGRAM_BOT_TOKEN, TMA_URL

docker compose up -d --build
docker compose exec api alembic upgrade head
```

Сервисы:
- **API**: http://localhost:8000 (docs: /docs)
- **TMA**: http://localhost:3010

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/v1/auth/telegram` | Auth через Telegram initData |
| GET | `/v1/auth/me` | Текущий пользователь |
| POST | `/v1/conversations` | Создать диалог |
| GET | `/v1/conversations` | Список диалогов |
| GET | `/v1/conversations/{id}` | Сообщения диалога |
| POST | `/v1/conversations/{id}/messages` | Отправить текст |
| POST | `/v1/conversations/{id}/audio` | Отправить аудио (Whisper) |
| POST | `/v1/conversations/{id}/image` | Отправить фото (Vision) |
| DELETE | `/v1/conversations/{id}` | Удалить диалог |

## Деплой

См. [docs/DEPLOY_VPS_CADDY.md](docs/DEPLOY_VPS_CADDY.md)

## Разработка TMA

```bash
cd apps/tma
npm install
npm run dev    # http://localhost:3000 (Vite), в Docker TMA на :3010
```

## Лицензия

Private / Internal Use Only
