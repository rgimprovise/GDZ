# Аудит проекта TutorBot (GDZ)

Дата: февраль 2025. Текущее состояние: что реализовано, что нет, проблемные зоны, пайплайны и дальнейшие шаги.

---

## 1. Реализовано

### 1.1 Инфраструктура и API

| Компонент | Статус | Детали |
|-----------|--------|--------|
| Монорепо | ✅ | `apps/api`, `apps/worker`, `apps/bot`, `infra`, `scripts` |
| Docker Compose | ✅ | Postgres 16, Redis 7, MinIO, API, Worker, Bot |
| FastAPI | ✅ | Health, POST/GET /v1/queries, лимиты подписок |
| Auth | ✅ | Telegram initData (TMA), X-Telegram-User-Id (бот), fallback user_id=1 |
| Миграции | ✅ | Alembic, таблицы users, plans, subscriptions, queries, responses, books, pdf_sources, pdf_pages, problems, problem_parts |
| RQ (Redis Queue) | ✅ | Очереди `queries` и `ingestion`; воркер слушает обе |

### 1.2 Пайплайн PDF → БД (Ingestion)

| Шаг | Статус | Где |
|-----|--------|-----|
| Открытие PDF | ✅ | PyMuPDF, путь с хоста (`DATA_DIR`/`minio_key`), том `../data:/app/data` в worker |
| OCR | ✅ | **Всегда** Tesseract (rus+eng), рендер 150 DPI → PNG → `pytesseract.image_to_string` |
| Нормализация | ✅ | `clean_ocr_text()` (ocr_cleaner) до сегментации; результат в `pdf_pages.ocr_text` |
| Сегментация | ✅ | `segment_problems()`: паттерны (задача, упражнение, задание, вопрос, §, №, N. / N), границы «Решение.» / «Ответ.» → `solution_text` |
| Сохранение | ✅ | `pdf_pages` (ocr_text, ocr_confidence), `problems` (problem_text, solution_text, number, page_ref), **`section_theory`** (теория параграфа по § для LLM) |
| Теория параграфа | ✅ | `extract_and_save_section_theory()` — по разметке § N и границам «Задачи»/«Упражнения» сохраняется текст параграфа; используется для ответов на контрольные вопросы и обоснования решений |
| Reanalyze | ✅ | `reanalyze_pdf_source()` — повторный разбор по уже сохранённому ocr_text (задачи + теория параграфов) без перечитывания PDF |
| Постановка в очередь | ✅ | `enqueue_ingestion()`, `enqueue_reanalyze()` |

**Зависимости воркера:** pymupdf, pytesseract, Pillow; в Dockerfile — tesseract-ocr, tesseract-ocr-rus, tesseract-ocr-eng.

### 1.3 Пайплайн запроса (Query)

| Шаг | Статус | Детали |
|-----|--------|--------|
| Создание запроса | ✅ | POST /v1/queries → Query (queued) → RQ job в очередь `queries` |
| Поиск задач | ✅ | FTS по `problems` (ts_rank, plainto_tsquery ru), бусты за answer/solution, порог 0.15 |
| Подпункты/варианты | ✅ | `extract_part_number()`, `part_answer` из problem_parts |
| LLM-объяснение | ✅ | OpenAI (gpt-4o-mini): теория раздела + условие + ответ → пошаговое объяснение |
| Ответ и цитаты | ✅ | `format_response()`: книга, номер, страница, ответ, решение/объяснение |
| Сохранение | ✅ | Response (content_markdown, citations, confidence_score), Query.status = done |
| Уведомление | ✅ | `send_telegram_notification_sync(tg_uid, message)` при готовности (если задан TELEGRAM_BOT_TOKEN) |

### 1.4 Дебаг и администрирование

| Функция | Статус | Где |
|---------|--------|-----|
| Debug-панель | ✅ | /debug: статистика, поиск задач, создание тестового запроса, опрос результата (HTMX), список книг и задач |
| Скрипты seed | ✅ | `seed_books.py`, `seed_db.py` — книги, pdf_sources из data/pdfs |
| Перезапуск ingestion | ✅ | `reingest_all_books.py` — очистка problems/pdf_pages, pending, постановка в очередь (или --no-queue) |
| Исправление геометрии | ✅ | `fix_geometry_books.py` — subject/title для книг геометрии |
| Поиск задачи в БД | ✅ | `find_problem_in_db.py` — по ключевым словам/номеру в problems и pdf_pages |

### 1.5 Постобработка по книге (process_all)

Каноничный пайплайн: `pipeline.run.run_ingestion(pdf_source_id)` или `scripts/dev/smoke_ingest.py`. Секции/ответы/теория из doc_map при ингестии (PR4–PR5).

| Шаг | Статус | Скрипт / модуль | Назначение |
|-----|--------|-----------------|------------|
| Классификация | ✅ | `classify_problems.py` | question / exercise / unknown по ключевым словам |
| Секции | ✅ | doc_map/ingestion или `legacy/assign_sections.py` | § N, Параграф N → problems.section |
| Ответы | ✅ | segmentation/answers или `legacy/link_answers.py` | Парсинг ответов по § + номер → problems.answer_text |
| Теория | ✅ | segmentation/theory или `legacy/link_theory.py` | Блоки теории по параграфам (для LLM) |

Legacy мастер-скрипт: `scripts/legacy/process_all.py --book-id N`. Доп. скрипты: `parse_problem_parts.py`, `validate_ocr_quality.py`, `validate_ocr.py`, `fix_formulas.py`, `parse_answers.py`, `classify_pdfs.py`.

---

## 2. Не реализовано / частично

### 2.1 Загрузка PDF из MinIO

- **Сейчас:** PDF берётся только с хоста: `DATA_DIR`/`minio_key`, том `../data:/app/data`.
- **В коде:** `# TODO: Download from MinIO` в `ingestion.py`.
- **Итог:** Для облачного/продакшн-сценария нужна выгрузка файла из MinIO в временный путь и передача в `process_pdf_source` (или `local_pdf_path`).

### 2.2 OCR для фото пользователя

- **Сейчас:** В запросе есть `input_photo_keys`, но в jobs используется только `input_text`; `extracted_text` просто копирует текст. OCR по фото не вызывается.
- **Итог:** Для сценария «фото задачи» нужен шаг: MinIO → изображение → Tesseract → текст → подстановка в поиск.

### 2.3 Векторный поиск (embeddings)

- **Сейчас:** Только FTS (PostgreSQL). В retrieval есть комментарий: `# TODO: Add vector search and merge results`.
- **Модели/миграции:** В models упомянут тип embedding (Vector), колонка закомментирована; в ROADMAP — pgvector, позже Qdrant.
- **Итог:** Семантический поиск не реализован; гибрид FTS+vector не делался.

### 2.4 Telegram Mini App и бот

- Бот: минимальный, standby без токена; уведомления уходят из воркера при наличии TELEGRAM_BOT_TOKEN.
- TMA (Mini App): в аудите не разбирался; в README указан как следующий шаг.

### 2.5 Admin-панель

- Отдельного приложения admin нет; роль админ-функций выполняет debug-панель API.

---

## 3. Проблемные зоны

### 3.1 Качество и объём данных после ingestion

- **Пустой ocr_text у части книг:** Если раньше (до перехода на «всегда Tesseract») ingestion уже гоняли без Tesseract, у книг 1–4 могли сохраниться пустые или короткие ocr_text. Нужен полный перезапуск ingestion с текущим пайплайном (всегда Tesseract) по всем книгам.
- **Мало задач на книгу:** Сегментация даёт 0–2 задачи на книгу, если разметка учебника не совпадает с паттернами. Нужна выборочная проверка ocr_text страниц с задачами и при необходимости расширение паттернов в `segment_problems`.
- **Секции и ответы:** assign_sections и link_answers зависят от качества OCR и сегментации; при сбитых номерах/параграфах ответы привязываются не к тем задачам.

### 3.2 Корректность ссылки на задачу

- Ссылка (книга, номер, страница) берётся из лучшего результата FTS. Она будет неверной, если:
  - лучше всего подошла другая задача (FTS/порог/формулировки);
  - у нужной задачи неверно заполнены number/section/page_ref из-за сегментации или постобработки.
- Улучшения: качество OCR и сегментации, при необходимости — семантический поиск и двухшаговый LLM.

### 3.3 Поиск (FTS)

- Один язык (russian); нет гибрида с vector; порог 0.15 может давать ложные срабатывания или пропуски в зависимости от формулировок.
- Нет явного реранжирования по релевантности к «что просят найти» (сейчас это частично компенсируется промптом LLM).

### 3.4 LLM

- Модель по умолчанию — gpt-4o-mini; при сложных/многовариантных задачах возможны подмены искомой величины. В промпте добавлен блок «В УСЛОВИИ ПРОСЯТ НАЙТИ» и правило не подменять задачу.
- Теория раздела: берётся по section из БД; если section пустой или неверный, контекст для LLM скудный.

### 3.5 Зависимость от локального пути

- Worker жёстко завязан на наличие PDF в `/app/data` (том с хоста). Для продакшна нужен сценарий с MinIO (или другим хранилищем) и скачиванием файла перед обработкой.

---

## 4. Пайплайны (сводка)

### 4.1 PDF → БД (ingestion)

```
PDF (файл с хоста) → process_pdf_source(pdf_source_id)
  → для каждой страницы:
      рендер → Tesseract OCR (rus+eng) → clean_ocr_text() → pdf_pages.ocr_text
      → segment_problems() → problems (problem_text, solution_text, number, page_ref)
  → pdf_source.status = done
```

Опционально: `reanalyze_pdf_source(pdf_source_id)` — только перезапуск сегментации по уже сохранённому ocr_text.

### 4.2 Запрос пользователя → ответ

```
POST /v1/queries → Query (queued) → RQ queue "queries"
  → process_query(query_id):
      search_problems(text) [FTS] → best match (score ≥ 0.15)
      → get_section_theory(book_id, section)
      → generate_solution_explanation(problem, answer, theory) [OpenAI]
      → format_response() → Response
      → send_telegram_notification_sync(tg_uid, message)
```

### 4.3 Постобработка по книге (ручной запуск)

```
run_ingestion(pdf_source_id) или legacy/process_all.py --book-id N
  → classify_problems → (doc_map) assign_sections / link_answers / link_theory (или legacy-скрипты)
```

---

## 5. Дальнейшие шаги (приоритизировано)

### Высокий приоритет

1. **Полный перезапуск ingestion с Tesseract по всем книгам**  
   Убедиться, что воркер собран с pytesseract/Pillow и tesseract-ocr (rus+eng), затем `reingest_all_books.py` (или очистка + enqueue) и дождаться завершения. Проверить, что у всех pdf_sources появился непустой ocr_text и выросло число problems.

2. **Проверка сегментации по 1–2 учебникам**  
   Выгрузить образцы ocr_text со страниц, где есть задачи; при необходимости добавить/уточнить паттерны в `segment_problems` и повторно запустить reanalyze по этим книгам.

3. **Загрузка PDF из MinIO в ingestion**  
   Реализовать скачивание по minio_key в временный файл и вызов process_pdf_source с этим путём (или передача bytes/stream), чтобы не зависеть от тома с хоста.

### Средний приоритет

4. **Семантический поиск (pgvector)**  
   Миграция: колонка embedding в problems (или отдельная таблица); джоба/скрипт заполнения эмбеддингов (OpenAI text-embedding-3-small); гибрид FTS + vector в retrieval и реранжирование.

5. **OCR по фото пользователя**  
   При наличии input_photo_keys: загрузка изображений из MinIO → Tesseract → извлечённый текст в поиск (и в query.extracted_text).

6. **Доработка постобработки**  
   Проверить assign_sections/link_answers на 1–2 книгах после стабильного ingestion; при необходимости поправить форматы парсинга ответов и секций.

### Низкий приоритет

7. **Обновить README**  
   Отметить реализованные пункты: FTS, LLM, уведомления, полный пайплайн ingestion (Tesseract → нормализация → сегментация), reanalyze.

8. **Расширение дебаг-панели**  
   Просмотр образцов ocr_text по странице, ручной запуск reanalyze по книге, просмотр ответов link_answers по задаче.

9. **Telegram Mini App и платёжная интеграция**  
   По дорожной карте продукта.

---

## 6. Файлы и места для правок

| Задача | Файлы |
|--------|--------|
| MinIO в ingestion | `apps/worker/ingestion.py` (заменить локальный путь на загрузку по minio_key) |
| Паттерны сегментации | `apps/worker/ingestion.py` → `segment_problems`, список `patterns` |
| FTS/порог/бусты | `apps/worker/retrieval.py` → `search_problems`, CONFIDENCE_THRESHOLD в jobs.py |
| Vector search | Миграция (embedding), `apps/worker/retrieval.py`, скрипт/джоба эмбеддингов |
| OCR по фото | `apps/worker/jobs.py` → process_query (шаг до search_problems), MinIO client |
| Теория для LLM | `apps/worker/llm.py` → get_section_theory; при необходимости link_theory/assign_sections |

---

*Документ можно обновлять по мере изменений в коде и инфраструктуре.*
