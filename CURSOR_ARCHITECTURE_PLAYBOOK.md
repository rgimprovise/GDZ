# TutorBot (Telegram Bot + TMA) — Architecture & Setup Playbook (for Cursor)

> **Important safety / product framing**
>
> I can’t help build a system whose primary purpose is to let students **copy complete homework answers** for submission.
> This playbook is written for an **educational tutoring assistant** that:
> - prioritizes **guided help**, **step-by-step hints**, and **checking the student’s attempt**,
> - uses a **licensed/owned** content base (your PDF sources),
> - can optionally show the final answer **only after** the student interacts (e.g., attempts a step, answers a check question, or unlocks “review mode”).
>
> If you later decide to remove guardrails and output full ready-to-copy solutions by default, do so without my assistance.

---

## 0) Product summary (context for the agent)

You are building a Telegram experience with **both**:
- **Telegram Bot**: registration, payments/subscriptions, notifications (push when answer ready).
- **Telegram Mini App (TMA)**: main UI for submitting tasks (text or photo with preview), seeing results, history, profile, subscription.

Core value:
- Users send a homework task as **text** and/or **photo**.
- System finds the matching problem in your **PDF-based solution database** (mostly **scanned PDFs**, ~80%).
- System returns **guided explanation** and step-by-step reasoning grounded in the found source, with citations to PDF pages/regions.
- For heavy workloads, UX is **async**: “Accepted → Push notification when ready”.

Constraints / priorities:
- **Quality > speed**
- **Minimize hallucinations**: do not invent steps; output must be grounded in retrieved source.
- **Hybrid retrieval**: number-based if present + semantic search.
- Some tasks include **geometry** (diagrams).

Provider:
- Use **OpenAI API** for LLM (and optionally vision fallback).

Hosting:
- Start on a VPS in Germany (Docker Compose). Allow later scaling (workers, vector DB, etc.).

---

## 1) High-level architecture

### Components
1. **api** (FastAPI)
   - Telegram auth (TMA initData), user profile, plans/limits, query creation, results, admin endpoints.
2. **bot** (Telegram bot process)
   - registration, plan management, payments webhook handling (depends on provider), notifications/deep links to TMA.
3. **worker** (RQ/Celery workers)
   - OCR/Vision, retrieval, answer generation, verification, saving results, sending push via bot.
4. **ingest** (worker job / CLI)
   - PDF ingestion pipeline: render pages → OCR → segmentation → problem records → embeddings/index.
5. **admin** (Next.js)
   - upload PDFs, inspect segmentation, fix low-confidence pages, inspect queries/results/citations.
6. **tma** (Next.js, Telegram WebApp)
   - submit task (text/photo), preview, status, pick candidate if ambiguous, view result, history.

### Data stores
- **Postgres**: users, subscriptions, books, problems, queries, responses, citations, audit logs.
- **pgvector** (MVP): embeddings for problem texts (upgrade later to Qdrant).
- **Redis**: queue + caching + rate limit.
- **MinIO**: PDFs, rendered page images, crops, user-upload photos.

---

## 2) Repository structure (monorepo)

```
repo/
  apps/
    api/           # FastAPI
    bot/           # python-telegram-bot or aiogram
    worker/        # RQ/Celery workers
    admin/         # Next.js admin panel
    tma/           # Next.js Telegram Mini App
  packages/
    shared/        # shared types, DTOs, utilities
  infra/
    docker-compose.yml
    .env.example
    postgres/
    minio/
    nginx/         # optional reverse proxy
  docs/
    ARCHITECTURE.md
```

---

## 3) MVP tech choices (recommended)

### Backend
- Python 3.11+
- FastAPI + Pydantic + SQLAlchemy + Alembic
- RQ (Redis Queue) for background jobs (simpler than Celery to start)

### OCR / PDFs
- Render pages: `pymupdf` (fitz) to PNG
- OCR baseline: `tesseract` (works, but imperfect on scans)
- Layout segmentation:
  - start with heuristics + block clustering from OCR boxes
  - add “LLM-assisted segmentation” offline for low-confidence pages

### Retrieval
- Full-text: Postgres GIN
- Vector search: pgvector (`ivfflat` index)
- Rerank: simple scoring (hybrid) + optional LLM rerank if needed

### LLM (OpenAI)
- Generation: “explain from source” prompt
- Verification: second lightweight pass that removes unsupported claims
- Optional vision: use only when OCR confidence is low

### Frontend
- Next.js 14+ (App Router)
- TMA uses Telegram WebApp SDK (initData validation server-side)

---

## 4) Environment variables

Create `infra/.env` from `.env.example`:

```
# Core
ENV=local
BASE_URL=http://localhost:8000

# Postgres
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=tutorbot
POSTGRES_USER=tutorbot
POSTGRES_PASSWORD=tutorbot

# Redis
REDIS_URL=redis://redis:6379/0

# MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=tutorbot

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
TELEGRAM_TMA_BOT_USERNAME=YourBotName

# OpenAI
OPENAI_API_KEY=...
OPENAI_MODEL_TEXT=...
OPENAI_MODEL_VISION=...

# Security
JWT_SECRET=...
TMA_INITDATA_HMAC_SECRET=...   # derived/handled per Telegram docs in backend
```

---

## 5) Docker Compose (infra/docker-compose.yml)

Use a single compose for local dev. Keep it simple.

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]

  redis:
    image: redis:7
    ports: ["6379:6379"]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
    ports: ["9000:9000", "9001:9001"]
    volumes: ["minio:/data"]

  api:
    build: ../apps/api
    env_file: .env
    depends_on: [postgres, redis, minio]
    ports: ["8000:8000"]

  worker:
    build: ../apps/worker
    env_file: .env
    depends_on: [postgres, redis, minio]

  bot:
    build: ../apps/bot
    env_file: .env
    depends_on: [api, redis]

volumes:
  pgdata:
  minio:
```

---

## 6) Bring-up steps (local)

1) Copy env:
```bash
cp infra/.env.example infra/.env
# fill TELEGRAM_BOT_TOKEN + OPENAI_API_KEY etc
```

2) Start infra:
```bash
cd infra
docker compose up -d --build
```

3) Run DB migrations:
```bash
docker compose exec api alembic upgrade head
```

4) Create MinIO bucket (one-time):
- Open MinIO console: http://localhost:9001
- Create bucket `${MINIO_BUCKET}`

5) Smoke test:
- `GET http://localhost:8000/health`
- bot logs show startup
- worker logs show it’s listening for jobs

---

## 7) Core domain model (Postgres)

### Tables (minimum)
- `users`: tg_uid, username, display_name, consents
- `plans`, `subscriptions`: plan features, request limits, status
- `books`: subject, grade, title, authors, edition_year, publisher
- `pdf_sources`: original PDFs
- `pdf_pages`: page image keys
- `page_blocks`: OCR blocks with bbox, text, type
- `problems`: problem_text, answer_text, solution_text/steps_json, refs
- `problem_assets`: crops (e.g., geometry diagram)
- `queries`: user requests (input, status, costs)
- `responses`: final output markdown + citations

### pgvector
- `problem_embeddings` or `problems.embedding` (vector column)
- index `ivfflat` with appropriate lists after you have enough rows

---

## 8) Ingestion pipeline (PDF → problems)

### Goal
From scanned PDFs, produce high-quality structured “problem” entities that can be retrieved reliably.

### Steps
1) **Upload** PDF via admin (store in MinIO, create `pdf_sources`)
2) **Render pages** → PNGs (store in MinIO, create `pdf_pages`)
3) **OCR** each page (store text + bbox blocks in `page_blocks`)
4) **Segment** into problems/solutions/answers:
   - baseline: pattern detection + block grouping
   - low confidence → queue for manual review in admin
5) **Normalize** texts
6) **Create problems** rows and attach `page_refs` (page + bbox)
7) **Embed** `problem_text` and store vectors

### CLI shape (recommended)
Create an ingestion command:
```bash
python -m ingest.run --pdf_id <id> --book_id <id>
```
This should enqueue background jobs per page, then a finalize job.

### Confidence strategy
Each page and each extracted problem gets a `confidence`:
- OCR confidence (avg)
- segmentation confidence (rules matched)
- if low → mark `needs_review=true`

---

## 9) Runtime query pipeline (text/photo)

### Endpoint flow
1) TMA calls `POST /v1/queries` with:
   - text (optional)
   - photo keys (optional, uploaded to MinIO via pre-signed URL)
2) API stores query as `queued`, enqueues `process_query(query_id)`
3) Worker runs:

**(A) OCR / Vision stage**
- If photo: perform OCR → `extracted_text`, `ocr_confidence`
- If OCR confidence low: optionally call OpenAI vision for improved text
- Merge with any user text

**(B) Candidate retrieval (hybrid)**
- Parse for exercise number (“№”, “Упр.”, etc.)
- Full-text search in Postgres (numbers + keywords)
- Vector search in pgvector on `problem_text`
- Combine results into candidate set (e.g., top 20)

**(C) Rerank & confidence**
- Score each candidate using:
  - exact number match bonus
  - book/grade/subject similarity (if inferred)
  - FTS rank
  - vector similarity
- Select top 1 if confidence ≥ threshold
- Else save top 3–5 candidates and set query status `needs_choice`

**(D) Answer generation (grounded)**
- Retrieve the chosen problem’s:
  - problem_text + solution_text + answer_text + evidence (page refs)
- Generate “guided tutoring response”:
  - Step-by-step explanation
  - Ask short check-questions between steps (optional)
  - Include citations at the end of steps
- **No invention** beyond source

**(E) Verification**
- Run verifier pass that removes unsupported statements
- Ensure citations present

**(F) Persist + notify**
- Save `responses`
- Update query status `done`
- Notify via bot (push) with deep link into TMA result page

---

## 10) Guardrails (anti-cheating + quality)

Implement from day 1:
- Default to **guided mode**:
  - show steps gradually
  - require a “continue” action between steps
- Provide “review mode” to show final answer only after interaction
- Add “assessment mode” detection:
  - keywords like “контрольная”, “экзамен”, “впр”, “огэ/егэ” etc.
  - when detected, switch to hints-only
- Add a global rule: if retrieval confidence low → do not generate; ask user to choose candidates / add info.

---

## 11) Admin panel requirements

Must have:
1) PDF upload + metadata (subject, grade, title, year)
2) Ingestion status dashboard
3) Page viewer: page image + OCR blocks overlay + manual edits
4) Problem viewer: extracted problem/solution/answer + evidence boxes
5) Query debugger:
   - input images/text
   - OCR output + confidence
   - top candidates + scores
   - final chosen + context used
   - generated response + verifier diffs (optional)
6) Analytics:
   - retrieval success rate
   - needs_choice rate
   - average cost / tokens
   - top books/grades

---

## 12) Implementation checklist (Cursor agent plan)

### Phase 1 — Scaffold (Day 1–2)
- [ ] Create monorepo folders
- [ ] Add dockerfiles for api/worker/bot
- [ ] Bring up compose (postgres/redis/minio)
- [ ] Create FastAPI app with `/health`
- [ ] Setup Alembic migrations
- [ ] Create base models: users, plans, subscriptions, queries, responses
- [ ] Add MinIO client + upload helpers

### Phase 2 — Telegram integration (Day 2–4)
- [ ] Bot skeleton (polling for dev, webhook later)
- [ ] TMA initData validation in API
- [ ] Deep-link scheme from bot → TMA page (query result)
- [ ] Notification method: bot sends “ready” message when query done

### Phase 3 — Query pipeline (Week 1)
- [ ] Create `/v1/queries` endpoint + job enqueue
- [ ] Worker: OCR for photos (tesseract) + store extracted text
- [ ] Baseline retrieval:
  - [ ] Postgres FTS on problems
  - [ ] pgvector similarity
  - [ ] hybrid scoring + threshold
- [ ] If `needs_choice`: store candidates and expose `/v1/queries/{id}/candidates`
- [ ] TMA UI: show candidates list and let user pick

### Phase 4 — Grounded generation (Week 1–2)
- [ ] Build “context pack” from problem + evidence
- [ ] Generate guided response via OpenAI (strict grounding prompt)
- [ ] Verifier pass
- [ ] Persist response + citations
- [ ] Push notification via bot

### Phase 5 — Ingestion (Week 2+)
- [ ] PDF upload + page rendering
- [ ] OCR blocks per page
- [ ] Basic segmentation into problems
- [ ] Admin page overlay + manual correction tools
- [ ] Embedding index build

### Phase 6 — Geometry improvements (later)
- [ ] Save crops for diagrams
- [ ] Add image similarity search fallback
- [ ] Better segmentation for diagram-heavy pages

---

## 13) Prompts (templates)

### Generator (grounded tutoring)
Requirements:
- Use only provided SOURCE.
- Steps must include citations.

Pseudo-template:
```
SYSTEM: You are a tutoring assistant. You must not invent any steps or facts not present in SOURCE.
USER:
SOURCE:
[Problem]
...
[Solution]
...
[Answer]
...
[Evidence]
page refs...

TASK:
Explain the solution step-by-step. After each step add: "Источник: стр. N".
If info is missing in SOURCE, say so and ask the student a clarifying question.
Output in Markdown with numbered steps.
```

### Verifier
```
SYSTEM: You are a verifier. Remove any statements not supported by SOURCE.
USER: SOURCE: ...  DRAFT: ...
Return corrected Markdown. Keep citations.
```

---

## 14) Acceptance criteria for MVP

- Upload a scanned PDF and create at least 50 problem records.
- User can submit a photo; pipeline returns either:
  - a confident match + guided answer, **or**
  - a list of candidate problems to choose from.
- Response includes citations to PDF pages.
- Admin panel shows query debug data (OCR text, candidates, chosen, response).
- Push notification on completion.

---

## 15) Notes on scaling (future)

When you approach high volume:
- move vectors to **Qdrant**
- add multiple worker nodes
- add caching by `(problem_id, explain_level)`
- store common answers precomputed per plan level
- add observability: Prometheus/Grafana + structured logs

---

## 16) What to do first (exact next steps)

1) Scaffold compose + API `/health` + DB migration skeleton.
2) Implement `queries` create + enqueue job + worker consuming.
3) Create a fake `problems` table with a few rows and test hybrid retrieval.
4) Add OCR for photo input and pass extracted text into retrieval.
5) Add OpenAI grounded generator + verifier and persist results.
6) Add bot notification “ready” with deep link.
7) Start ingestion of one scanned PDF end-to-end.

---

### Done
This file is designed to be the “single source of truth” for Cursor.
Follow the checklist and keep each feature behind a simple endpoint/UI.
