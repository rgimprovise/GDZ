# TutorBot — Architecture

## Overview

TutorBot is an educational assistant that helps students with homework.
Content retrieval and answer generation are fully delegated to the
**OpenAI Assistants API** with a **Vector Store** containing textbooks.

## Components

| Component | Technology | Role |
|-----------|------------|------|
| **API** | FastAPI (Python) | Auth, conversations, media pipeline, subscription limits |
| **TMA** | React + Vite | Telegram Mini App — primary client interface |
| **Bot** | python-telegram-bot | Minimal launcher — sends WebApp button for TMA |
| **Postgres** | PostgreSQL 16 | Users, plans, subscriptions, conversations, messages |

## Data flow

```
User (TMA / Web)
    │
    ├── text  ────────────────────────────┐
    ├── audio ── Whisper API → text ──────┤
    └── image ── GPT-4o Vision → text ────┤
                                          ▼
                              POST /v1/conversations/{id}/messages
                                          │
                              API saves user message in DB
                                          │
                              OpenAI Threads API:
                                add message → create run → poll → get reply
                                          │
                              API saves assistant message in DB
                                          │
                              Returns both to client
```

## Database schema

- **users** — Telegram users (tg_uid, username, display_name)
- **plans** — Subscription plans (free / basic / premium)
- **subscriptions** — User ↔ Plan binding with usage counters
- **conversations** — Maps to an OpenAI Thread (openai_thread_id)
- **messages** — User and assistant messages within a conversation

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/v1/auth/telegram` | Authenticate via Telegram initData |
| GET | `/v1/auth/me` | Current user info |
| POST | `/v1/conversations` | Create conversation (creates OpenAI thread) |
| GET | `/v1/conversations` | List user conversations |
| GET | `/v1/conversations/{id}` | Get messages in a conversation |
| DELETE | `/v1/conversations/{id}` | Delete conversation |
| POST | `/v1/conversations/{id}/messages` | Send text message |
| POST | `/v1/conversations/{id}/audio` | Send audio (Whisper → text → assistant) |
| POST | `/v1/conversations/{id}/image` | Send image (Vision → text → assistant) |

## Infrastructure

```
docker-compose.yml:
  postgres  — database
  api       — FastAPI backend
  bot       — Telegram bot
  tma       — nginx serving built React app
```

## Environment variables

See `infra/env.example` for the full list. Key additions:
- `OPENAI_ASSISTANT_ID` — ID of the pre-configured OpenAI Assistant
- `OPENAI_MODEL_VISION` — model for image recognition (default: gpt-4o)
- `TMA_URL` — public URL of the Telegram Mini App
