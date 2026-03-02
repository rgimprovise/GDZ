# Local Development

## Prerequisites

- Docker & Docker Compose
- Node.js 20+ (for TMA development)
- OpenAI API key with an Assistant configured + Vector Store

## Quick start

```bash
# 1. Copy and edit env
cd infra
cp env.example .env
# Edit .env — set OPENAI_API_KEY, OPENAI_ASSISTANT_ID, TELEGRAM_BOT_TOKEN

# 2. Start everything
docker compose up -d --build

# 3. Run migrations
docker compose exec api alembic upgrade head
```

Services:
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- TMA: http://localhost:3010
- Health: http://localhost:8000/health

## Developing TMA locally

```bash
cd apps/tma
npm install
npm run dev
```

Vite dev server runs on port 3000 and proxies `/v1/*` to the API at port 8000.

## Expose Postgres for local tools

```bash
docker compose -f docker-compose.yml -f docker-compose.local-ports.yml up -d
```

Postgres will be available at `localhost:5432`.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full overview.
