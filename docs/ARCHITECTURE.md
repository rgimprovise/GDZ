# TutorBot (GDZ) — архитектура проекта

Детальное описание текущей архитектуры: компоненты, назначение файлов и скриптов, зависимости, библиотеки, схема данных и потоки работы.

---

## 1. Обзор

TutorBot — образовательный ассистент (решебники/учебники): пользователь присылает текст задачи, система ищет совпадения в базе задач, извлечённых из PDF, и возвращает ответ с решением и обоснованием. Доставка — через Telegram; API используется для создания запросов, аутентификации и выдачи результатов.

**Принципы:**
- **Grounded responses** — ответы опираются на найденные в базе задачи и теорию параграфа.
- **Цитирование** — указание книги, номера задачи, страницы.
- **Пошаговое объяснение** — при наличии OpenAI генерируется объяснение с опорой на `section_theory`.

**Реализовано на текущий момент:**
- Загрузка PDF (seed книг и источников), ingestion: OCR → нормализация → сегментация задач и извлечение теории параграфов (§).
- Файловый слой OCR: сырой текст в `data/ocr_raw/`, нормализованный в `data/ocr_normalized/`; в БД попадает только проверенный текст.
- Поиск по задачам (FTS), опционально — объяснение через LLM с учётом теории параграфа.
- Очереди RQ: `queries` (обработка запросов пользователя), `ingestion` (обработка PDF).

---

## 2. Структура репозитория

```
GDZ/
├── apps/
│   ├── api/              # FastAPI: REST API, auth, очереди
│   │   ├── main.py       # Точка входа, эндпоинты /health, /v1/queries, /v1/auth
│   │   ├── models.py     # SQLAlchemy-модели (users, plans, subscriptions, queries, responses, books, pdf_*, problems, section_theory)
│   │   ├── schemas.py    # Pydantic-схемы запросов/ответов
│   │   ├── config.py     # Настройки из env
│   │   ├── database.py   # Подключение к Postgres, get_db
│   │   ├── job_queue.py  # Постановка задачи в Redis (queries)
│   │   ├── auth.py       # Валидация Telegram initData, JWT
│   │   ├── routers/      # auth, debug (отладочные страницы, очередь, книги)
│   │   └── alembic/      # Миграции БД
│   │
│   ├── worker/           # RQ Worker: обработка запросов и ingestion
│   │   ├── worker.py     # Точка входа, слушает очереди ingestion + queries
│   │   ├── jobs.py       # Обработчик запросов: поиск, LLM, ответ, уведомление
│   │   ├── ingestion.py  # Пайплайн PDF: OCR → файлы → нормализация → импорт в БД, segment_problems, section_theory
│   │   ├── ocr_files.py  # Запись/чтение raw и normalized .md по страницам (data/ocr_raw, data/ocr_normalized)
│   │   ├── ocr_cleaner.py # Нормализация текста после OCR (clean_ocr_text)
│   │   ├── retrieval.py  # Поиск по задачам (FTS, part number, scoring)
│   │   ├── llm.py        # OpenAI: get_section_theory, generate_solution_explanation
│   │   ├── models.py     # Копия/зеркало моделей для БД (без async)
│   │   ├── database.py   # SessionLocal
│   │   ├── config.py     # Настройки (postgres, redis, env)
│   │   ├── notifications.py  # Отправка уведомлений в Telegram
│   │   ├── formula_processor.py  # Постобработка формул (опционально)
│   │   └── requirements.txt
│   │
│   └── bot/              # Telegram-бот
│       ├── bot.py        # Обработчики, polling (webhook — в перспективе)
│       ├── config.py     # Токен, redis
│       └── requirements.txt
│
├── packages/
│   └── shared/           # Общие константы (очереди, статусы, лимиты)
│       ├── constants.py
│       └── utils.py
│
├── scripts/              # CLI-скрипты (запуск с хоста при наличии доступа к БД/файлам)
│   ├── seed_books.py     # Классификация PDF в data/pdfs, создание books + pdf_sources
│   ├── reingest_all_books.py  # Очистка страниц/задач, pending, постановка ingestion в очередь
│   ├── apply_migrations.sh / up.sh  # Миграции и запуск стека
│   ├── process_all.py    # По книге: classify_problems, assign_sections, link_answers, link_theory
│   ├── link_answers.py   # Парсинг «Ответы» из ocr_text, проставление answer_text в problems
│   ├── link_theory.py    # Связь вопросов с блоками теории по ключевым словам
│   ├── assign_sections.py # Привязка задач к параграфам по страницам
│   ├── classify_problems.py  # Классификация тип задачи: question / exercise / unknown
│   ├── parse_problem_parts.py # Разбиение задач на подпункты (1) 2) 3)), ответы по частям
│   ├── parse_answers.py  # Парсинг ответов из PDF (альтернатива link_answers)
│   ├── fix_geometry_books.py # Исправление subject/title для геометрии
│   ├── fix_formulas.py   # Постобработка формул в ocr_text и problem_text
│   ├── validate_ocr.py   # Статистика и просмотр страниц OCR
│   ├── validate_ocr_quality.py # Проверка качества и автоочистка текста по книге
│   ├── classify_pdfs.py  # Классификация и переименование PDF по метаданным
│   ├── find_problem_in_db.py # Поиск задачи по фрагменту текста в БД
│   ├── seed_db.py        # Начальное заполнение plans и т.п.
│   └── ...
│
├── infra/
│   ├── docker-compose.yml  # postgres, redis, minio, api, worker, bot
│   ├── .env                # Секреты и URL (не в git)
│   └── env.example          # Шаблон .env
│
├── data/                  # Данные на хосте (монтируются в worker)
│   ├── pdfs/               # Исходные PDF учебников
│   ├── ocr_raw/            # Сырой OCR по источникам (book_id/source_id_model.md)
│   └── ocr_normalized/     # Нормализованный текст по страницам перед импортом в БД
│
└── docs/                   # Документация (PIPELINE_PDF, OCR_FILES, DEPLOY_VPS, ENTITIES, etc.)
```

---

## 3. Компоненты приложений

### 3.1 API (`apps/api`)

**Назначение:** REST API для создания запросов, получения ответов, аутентификации (Telegram Mini App), отладочные страницы.

**Ключевые файлы:**

| Файл | Назначение |
|------|------------|
| `main.py` | FastAPI app, CORS, роутеры; эндпоинты: `GET /health`, `POST /v1/queries`, `GET /v1/queries/{id}`, `POST /v1/auth/telegram` |
| `models.py` | SQLAlchemy-модели: User, Plan, Subscription, Query, Response, Book, PdfSource, PdfPage, Problem, SectionTheory; enum'ы статусов |
| `schemas.py` | Pydantic: HealthResponse, QueryCreate, QueryResponse, QueryDetailResponse |
| `job_queue.py` | Постановка задачи обработки запроса в очередь `queries` (RQ) |
| `database.py` | Подключение к Postgres, `get_db()` для зависимостей |
| `auth.py` | Валидация Telegram initData, получение user_id, JWT (опционально) |
| `routers/auth.py` | POST /v1/auth/telegram |
| `routers/debug.py` | Отладочные HTML-страницы: очередь, статусы, книги, PDF-источники |

**Зависимости:** FastAPI, uvicorn, SQLAlchemy, alembic, redis, rq, minio, pydantic, python-dotenv. БД — Postgres; очереди — Redis.

---

### 3.2 Worker (`apps/worker`)

**Назначение:** Обработка двух очередей — **ingestion** (PDF → страницы, задачи, теория) и **queries** (поиск по задаче, LLM, ответ пользователю).

**Очереди:** слушает `ingestion` и `queries` (см. `worker.py`).

**Ключевые файлы:**

| Файл | Назначение |
|------|------------|
| `worker.py` | Точка входа RQ Worker, подключение к Redis, прослушивание очередей `ingestion` и `queries` |
| `jobs.py` | `process_query(query_id)`: поиск задач (retrieval), форматирование ответа, вызов LLM для объяснения, сохранение Response, уведомление в Telegram |
| `ingestion.py` | `process_pdf_source(pdf_source_id)`: OCR (Tesseract) по страницам → запись raw в `data/ocr_raw/`, нормализация → `data/ocr_normalized/`, импорт в `pdf_pages` + сегментация задач + извлечение теории в `section_theory`. Функции: `segment_problems`, `extract_and_save_section_theory`, `reanalyze_pdf_source`, `import_from_normalized_file`, `enqueue_ingestion`, `enqueue_reanalyze`, `enqueue_import_from_normalized_file` |
| `ocr_files.py` | Пути и работа с файлами: `data/ocr_raw/{book_id}/{source_id}_{model}.md`, `data/ocr_normalized/{book_id}/{source_id}.md`; функции записи/парсинга по блокам «## Страница N» |
| `ocr_cleaner.py` | `clean_ocr_text(text)` — нормализация артефактов OCR (латиница/кириллица, переносы и т.д.) |
| `retrieval.py` | `search_problems(query_text, ...)` — полнотекстовый поиск по `problems`, извлечение номера части из запроса, подсчёт score, возврат SearchResult |
| `llm.py` | `get_section_theory(db, book_id, section)` — теория из `section_theory` или эвристика по `pdf_pages.ocr_text`; `generate_solution_explanation(...)` — вызов OpenAI для объяснения решения с учётом условия, ответа и теории |
| `models.py` | Модели БД (аналоги API) для синхронного доступа в worker |
| `database.py` | SessionLocal (sync) |
| `config.py` | Настройки из env (postgres, redis_url) |
| `notifications.py` | Отправка сообщений в Telegram (уведомление о готовности ответа) |
| `formula_processor.py` | Постобработка формул в тексте (опционально, используется скриптами) |

**Зависимости:** sqlalchemy, psycopg2-binary, redis, rq, minio, pymupdf, pytesseract, Pillow, openai, requests, httpx, pydantic-settings, python-dotenv. В контейнере дополнительно: tesseract-ocr, tesseract-ocr-rus, tesseract-ocr-eng.

---

### 3.3 Bot (`apps/bot`)

**Назначение:** Telegram-бот — регистрация пользователей, приём сообщений, уведомления. Сейчас работает в режиме polling; в продакшене возможен webhook.

**Ключевые файлы:** `bot.py` (обработчики команд и сообщений), `config.py` (токен, redis). Зависимости: python-telegram-bot, redis, pydantic-settings, python-dotenv.

---

## 4. Потоки данных

### 4.1 Запрос пользователя (query)

```
Пользователь (Telegram / TMA)
    → POST /v1/queries { "text": "..." }
    → API: создаётся Query (status=queued), задача ставится в очередь "queries"
    → Redis (RQ)
    → Worker: process_query(query_id)
        → retrieval.search_problems() — FTS по problems
        → при наличии результата: llm.get_section_theory(), llm.generate_solution_explanation()
        → сохранение Response, обновление Query (status=done)
        → notifications: отправка в Telegram
    → Пользователь получает ответ (polling GET /v1/queries/{id} или уведомление от бота)
```

### 4.2 Ingestion (PDF → БД)

```
PDF в data/pdfs/ + запись в pdf_sources (seed_books)
    → Очередь "ingestion" (enqueue_ingestion(pdf_source_id))
    → Worker: process_pdf_source(pdf_source_id)
        → Открытие PDF (PyMuPDF), рендер страниц (150 DPI)
        → OCR по каждой странице (Tesseract) → список raw текстов
        → Запись в data/ocr_raw/{book_id}/{source_id}_{model}.md
        → Нормализация по страницам (clean_ocr_text) → data/ocr_normalized/{book_id}/{source_id}.md
        → Удаление старых pdf_pages и problems по этому источнику
        → Создание pdf_pages (ocr_text = нормализованный текст), segment_problems() → запись в problems
        → extract_and_save_section_theory() → запись в section_theory
        → pdf_sources.status = done
```

Импорт без повторного OCR: `import_from_normalized_file(pdf_source_id)` читает `data/ocr_normalized/...` и заполняет страницы/задачи/теорию.

---

## 5. База данных (схема)

**СУБД:** PostgreSQL. Миграции: Alembic (`apps/api/alembic`). Версии: 001_initial_schema, 002_add_ingestion_tables, 003_add_problem_type, 004_add_problem_parts, 005_add_section_theory.

### Основные таблицы

| Таблица | Назначение |
|---------|------------|
| **users** | Пользователи (tg_uid, username, display_name, is_active) |
| **plans** | Тарифные планы (type: free/basic/premium, лимиты запросов) |
| **subscriptions** | Подписки пользователей (user_id, plan_id, status, queries_used_today/month) |
| **queries** | Запросы пользователей (user_id, input_text, status, extracted_text, ocr_confidence) |
| **responses** | Сгенерированные ответы (query_id, content_markdown, citations, confidence_score) |
| **books** | Книги/учебники (subject, grade, title, authors, is_gdz) |
| **pdf_sources** | Источники PDF (book_id, minio_key, original_filename, page_count, status: pending/ocr/done/failed) |
| **pdf_pages** | Страницы PDF (pdf_source_id, page_num, ocr_text, ocr_confidence) |
| **problems** | Задачи/упражнения (book_id, source_page_id, number, section, problem_text, solution_text, answer_text, page_ref, problem_type, has_parts) |
| **section_theory** | Теория параграфа (book_id, section, theory_text, page_ref) — для LLM |

Полнотекстовый поиск: по полям `problems` (problem_text, solution_text и т.д.) через PostgreSQL FTS (см. retrieval.py).

---

## 6. Скрипты (назначение и зависимости)

Скрипты запускаются с хоста (или из контейнера с доступом к БД и каталогу `data/`). Для подключения к БД используют переменные окружения (POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB) или явный DATABASE_URL.

| Скрипт | Назначение | Зависимости |
|--------|------------|-------------|
| **seed_books.py** | Классификация PDF в `data/pdfs/`, создание записей в `books` и `pdf_sources` | PyMuPDF (извлечение текста для классификации), БД |
| **reingest_all_books.py** | Очистка pdf_pages и problems по всем источникам, установка status=pending, постановка ingestion в очередь | БД, Redis, импорт ingestion (enqueue_ingestion) |
| **process_all.py** | Последовательный запуск по книге: classify_problems, assign_sections, link_answers, link_theory | БД, модули assign_sections, link_answers, link_theory, classify_problems |
| **link_answers.py** | Поиск страниц с «Ответы», парсинг номеров и ответов, обновление problems.answer_text | БД |
| **link_theory.py** | Извлечение блоков теории из ocr_text, сопоставление с вопросами, обновление связей | БД |
| **assign_sections.py** | Определение параграфа по странице (§ на странице), проставление problems.section | БД |
| **classify_problems.py** | Классификация типа задачи (question / exercise / unknown) по тексту | БД |
| **parse_problem_parts.py** | Разбиение задач на подпункты (1) 2) 3)), разбор ответов по частям, опционально clean_ocr_text | БД, ocr_cleaner |
| **parse_answers.py** | Парсинг ответов из PDF (альтернативный способ заполнения answer_text) | БД, PyMuPDF |
| **fix_geometry_books.py** | Исправление subject/title для книг геометрии (math → geometry) | БД |
| **fix_formulas.py** | Постобработка формул в pdf_pages.ocr_text и problems.problem_text | БД, formula_processor |
| **validate_ocr.py** | Статистика по страницам (длина текста, пустые), просмотр случайной/конкретной страницы | БД, опционально PyMuPDF для рендера |
| **validate_ocr_quality.py** | Анализ качества текста задач, автоочистка (clean_ocr_text) по книге | БД, ocr_cleaner |
| **classify_pdfs.py** | Классификация и переименование/перемещение PDF по метаданным (паттерны + опционально LLM) | Файловая система, опционально OpenAI |
| **find_problem_in_db.py** | Поиск задачи по фрагменту текста в БД (для отладки) | БД |
| **seed_db.py** | Начальное заполнение (plans и т.п.) | БД |

Общее: для работы с БД скрипты добавляют в `sys.path` корень проекта и `apps/worker` или `apps/api`, подключаются к Postgres по env.

---

## 7. Библиотеки и окружение

### 7.1 По приложениям

| Приложение | Ключевые библиотеки |
|------------|----------------------|
| **API** | fastapi, uvicorn, sqlalchemy, psycopg2-binary, alembic, redis, rq, minio, pydantic, pydantic-settings, python-dotenv, httpx |
| **Worker** | sqlalchemy, psycopg2-binary, redis, rq, minio, pymupdf, pytesseract, Pillow, openai, requests, httpx, pydantic-settings, python-dotenv |
| **Bot** | python-telegram-bot, redis, pydantic-settings, python-dotenv |

### 7.2 Внешние сервисы

- **PostgreSQL** — основное хранилище (пользователи, запросы, ответы, книги, страницы, задачи, теория).
- **Redis** — очереди RQ (queries, ingestion).
- **MinIO** — S3-совместимое хранилище (ключи в pdf_sources.minio_key; файлы PDF при локальном запуске читаются из `data/` по пути minio_key).
- **OpenAI API** — генерация объяснений (LLM) при обработке запроса; ключ в OPENAI_API_KEY.

### 7.3 Переменные окружения (основные)

- **API/Worker:** POSTGRES_HOST, POSTGRES_*, REDIS_URL, MINIO_*, BASE_URL, JWT_SECRET, OPENAI_API_KEY, OPENAI_MODEL_TEXT.
- **Worker:** DATA_DIR (каталог данных: pdfs, ocr_raw, ocr_normalized).
- **Bot:** TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, REDIS_URL.
- **Infra:** POSTGRES_PASSWORD, MINIO_ACCESS_KEY, MINIO_SECRET_KEY (и др. в env.example).

---

## 8. Инфраструктура (Docker)

**Файл:** `infra/docker-compose.yml`.

| Сервис | Образ/сборка | Назначение |
|--------|--------------|------------|
| **postgres** | postgres:16-alpine | БД, volume pgdata |
| **redis** | redis:7-alpine | Очереди RQ, volume redisdata |
| **minio** | minio/minio | S3-хранилище, порты 9000/9001, volume miniodata |
| **api** | Сборка из apps/api | FastAPI на порту 8000, зависит от postgres, redis, minio |
| **worker** | Сборка из apps/worker | RQ worker, очереди ingestion и queries; volume `../data:/app/data`, env DATA_DIR=/app/data |
| **bot** | Сборка из apps/bot | Telegram-бот, зависит от redis, api |

Миграции применяются после старта: `docker compose exec api alembic upgrade head` (или скрипт `scripts/apply_migrations.sh`).

---

## 9. Связи между компонентами

- **API** создаёт Query и ставит задачу в Redis (очередь `queries`). Worker обрабатывает задачу и пишет в Query/Response; бот/клиент получают результат по GET или через уведомление.
- **Ingestion** ставится в очередь `ingestion` (из скрипта reingest_all_books или вручную). Worker читает PDF из `data/` (minio_key как путь относительно DATA_DIR), пишет raw/normalized в `data/ocr_raw` и `data/ocr_normalized`, обновляет pdf_pages, problems, section_theory.
- **retrieval** и **llm** в worker используют одни и те же модели БД (Problem, Book, SectionTheory, PdfPage); llm запрашивает теорию параграфа для улучшения объяснения.
- **Скрипты** не входят в образы API/Worker; для их работы нужен доступ к БД (и при необходимости к Redis, каталогу data/, модулям apps/worker типа ocr_cleaner).

---

## 10. Дополнительная документация

- **Пайплайн PDF, сегментация, теория:** `docs/PIPELINE_PDF.md`
- **Файловый слой OCR, нормализация по файлам:** `docs/OCR_FILES_AND_NORMALIZATION.md`
- **Будущий пайплайн (два прохода OCR, изображения):** `docs/PIPELINE_FUTURE.md`
- **Сущности и детекция (теория, задачи):** `docs/ENTITIES_AND_DETECTION.md`
- **Развёртывание на VPS:** `docs/DEPLOY_VPS.md`
