# TutorBot — Roadmap и инструкция по следующим шагам

> Документ описывает план развития проекта после MVP и детали реализации каждой фазы.

---

## 📊 Текущий статус (MVP Done)

### ✅ Что уже работает:

| Компонент | Статус | Описание |
|-----------|--------|----------|
| Монорепо | ✅ | `apps/api`, `apps/worker`, `apps/bot`, `packages/shared` |
| Docker Compose | ✅ | Postgres, Redis, MinIO, API, Worker, Bot |
| API `/health` | ✅ | Health check endpoint |
| API `/v1/queries` | ✅ | CRUD для запросов |
| API `/v1/auth/telegram` | ✅ | Валидация Telegram initData |
| Миграции Alembic | ✅ | Таблицы: users, plans, subscriptions, queries, responses |
| Worker (RQ) | ✅ | Обработка очереди, stub-ответы |
| Bot | ✅ | Минимальный, standby без токена |

### ✅ Что работает (Phase 2-3):

| Компонент | Статус | Описание |
|-----------|--------|----------|
| OCR | ✅ | Tesseract + постобработка формул |
| Retrieval | ✅ | FTS с бустом для задач с ответами |
| LLM генерация | ✅ | Grounded объяснения через OpenAI |
| Push уведомления | ✅ | Уведомления в Telegram |
| Ingestion | ✅ | Загрузка и обработка PDF |
| Классификация задач | ✅ | question/exercise/unknown |
| Привязка ответов | ✅ | link_answers.py |
| Привязка теории | ✅ | link_theory.py |

### ❌ Что НЕ работает (следующие шаги):

| Компонент | Статус | Описание |
|-----------|--------|----------|
| TMA | ❌ | Telegram Mini App |
| Admin TMA | ❌ | Админский интерфейс в TMA |
| Vector search | ❌ | pgvector для семантического поиска |
| OCR с фото пользователя | ❌ | Vision API для распознавания |

---

## 🗺️ Roadmap по фазам

```
Phase 1 ✅  Scaffold          → DONE
Phase 2    Telegram Integration
Phase 3    Query Pipeline (OCR + Retrieval + LLM)
Phase 4    Ingestion Pipeline
Phase 5    Admin Panel
Phase 6    Telegram Mini App
Phase 7    Production & Scaling
```

---

## Phase 2: Telegram Integration

### Цель
Полноценная интеграция с Telegram: бот принимает сообщения, отправляет уведомления, авторизует пользователей TMA.

### Задачи

#### 2.1 Настройка бота

**Файл:** `apps/bot/bot.py`

```bash
# 1. Создать бота через @BotFather
# 2. Получить токен
# 3. Добавить в infra/.env:
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_TMA_BOT_USERNAME=YourBotUsername
```

**Что должно работать:**
- `/start` — приветствие и инструкции
- `/help` — справка по боту
- Отправка текста/фото → создание query через API
- Push-уведомление когда query обработан

#### 2.2 Обработка сообщений

**Добавить в `apps/bot/bot.py`:**

```python
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений."""
    user = update.effective_user
    text = update.message.text
    
    # Создать query через API
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.base_url}/v1/queries",
            json={"text": text},
            headers={"X-Telegram-User-Id": str(user.id)}
        )
    
    if response.status_code == 201:
        query_data = response.json()
        await update.message.reply_text(
            f"✅ Запрос #{query_data['id']} принят!\n"
            f"Я пришлю уведомление когда ответ будет готов."
        )
    else:
        await update.message.reply_text("❌ Ошибка при создании запроса")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото."""
    # 1. Скачать фото
    # 2. Загрузить в MinIO
    # 3. Создать query с photo_keys
    pass
```

#### 2.3 Push-уведомления

**Файл:** `apps/worker/notifications.py` — уже создан!

**Как работает:**
1. Worker обрабатывает query
2. Вызывает `send_telegram_notification_sync(tg_uid, message)`
3. Пользователь получает сообщение в Telegram

**Проверка:**
```bash
# Добавить токен в .env
docker compose up -d bot

# Создать запрос — пользователь получит уведомление
```

#### 2.4 Deep Links

**Формат ссылки в TMA:**
```
tg://resolve?domain=YourBotUsername&startapp=query_123
```

**Обработка в боте:**
```python
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0].startswith("query_"):
        query_id = args[0].replace("query_", "")
        # Показать результат query или открыть TMA
```

---

## Phase 3: Query Pipeline

### Цель
Полный цикл обработки запроса: OCR → Retrieval → LLM → Response

### Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    Query Pipeline                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. INPUT           2. OCR              3. RETRIEVAL         │
│  ┌─────────┐       ┌─────────┐         ┌─────────────┐      │
│  │ text +  │  ───► │Tesseract│  ───►   │ FTS + pgvec│      │
│  │ photo   │       │ Vision  │         │ + rerank   │      │
│  └─────────┘       └─────────┘         └─────────────┘      │
│                                               │              │
│                                               ▼              │
│  6. NOTIFY         5. VERIFY           4. GENERATE          │
│  ┌─────────┐       ┌─────────┐         ┌─────────────┐      │
│  │Push via │  ◄─── │ Remove  │  ◄───   │  OpenAI    │      │
│  │  Bot    │       │ claims  │         │  grounded  │      │
│  └─────────┘       └─────────┘         └─────────────┘      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 OCR (Tesseract + Vision fallback)

**Установка в Dockerfile worker:**
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*
```

**Добавить в requirements.txt:**
```
pytesseract==0.3.10
Pillow==10.2.0
```

**Реализация `apps/worker/ocr.py`:**
```python
import pytesseract
from PIL import Image
from minio import Minio

def extract_text_from_image(image_key: str) -> tuple[str, int]:
    """
    OCR для изображения из MinIO.
    
    Returns:
        (extracted_text, confidence 0-100)
    """
    # 1. Скачать из MinIO
    minio_client = Minio(...)
    image_data = minio_client.get_object(bucket, image_key)
    
    # 2. OCR
    image = Image.open(image_data)
    text = pytesseract.image_to_string(image, lang='rus')
    
    # 3. Рассчитать confidence
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    confidences = [int(c) for c in data['conf'] if c != '-1']
    avg_confidence = sum(confidences) // len(confidences) if confidences else 0
    
    return text, avg_confidence
```

**Интеграция в `jobs.py`:**
```python
def process_query(query_id: int):
    # ... get query ...
    
    # OCR если есть фото
    if query.input_photo_keys:
        texts = []
        for key in query.input_photo_keys:
            text, conf = extract_text_from_image(key)
            texts.append(text)
        
        query.extracted_text = "\n".join(texts)
        query.ocr_confidence = min(confidences)
    else:
        query.extracted_text = query.input_text
        query.ocr_confidence = 100
```

### 3.2 Retrieval (FTS + pgvector)

**Установка pgvector:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

**Таблицы (новая миграция):**
```python
# alembic/versions/002_add_problems_and_vectors.py

def upgrade():
    # Таблица книг
    op.create_table('books',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(255)),
        sa.Column('subject', sa.String(50)),  # math, physics, etc.
        sa.Column('grade', sa.String(20)),    # "8" or "7-9"
        sa.Column('authors', sa.String(255)),
        sa.Column('publisher', sa.String(255)),
        sa.Column('edition_year', sa.Integer()),
        sa.Column('part', sa.String(10)),     # "1", "2", etc.
        sa.Column('is_gdz', sa.Boolean(), default=False),
    )
    
    # Таблица ожидающих классификации PDF
    op.create_table('pending_pdfs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('minio_key', sa.String(255)),
        sa.Column('original_filename', sa.String(255)),
        sa.Column('status', sa.String(50)),   # classifying, needs_confirmation, rejected
        # Предложенная классификация
        sa.Column('suggested_subject', sa.String(50)),
        sa.Column('suggested_grade', sa.String(20)),
        sa.Column('suggested_authors', sa.String(255)),
        sa.Column('suggested_title', sa.String(255)),
        sa.Column('suggested_publisher', sa.String(255)),
        sa.Column('suggested_part', sa.String(10)),
        sa.Column('is_gdz', sa.Boolean()),
        sa.Column('confidence', sa.Float()),
        sa.Column('raw_text_preview', sa.Text()),  # First pages text for debug
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )
    
    # Таблица задач
    op.create_table('problems',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('book_id', sa.Integer(), sa.ForeignKey('books.id')),
        sa.Column('number', sa.String(50)),        # "№123", "Упр. 45"
        sa.Column('problem_text', sa.Text()),
        sa.Column('solution_text', sa.Text()),
        sa.Column('answer_text', sa.Text()),
        sa.Column('page_ref', sa.String(50)),      # "стр. 45"
        sa.Column('embedding', Vector(1536)),      # OpenAI embedding
    )
    
    # Индексы
    op.execute("CREATE INDEX problems_fts ON problems USING gin(to_tsvector('russian', problem_text))")
    op.execute("CREATE INDEX problems_embedding ON problems USING ivfflat (embedding vector_cosine_ops)")
```

**Реализация `apps/worker/retrieval.py`:**
```python
from sqlalchemy import text

def hybrid_search(query_text: str, db, top_k: int = 20) -> list[dict]:
    """
    Гибридный поиск: FTS + vector + number matching.
    
    Returns:
        List of {problem_id, score, problem_text, ...}
    """
    results = []
    
    # 1. Извлечь номер задачи если есть
    number_match = extract_problem_number(query_text)  # "№123" → "123"
    
    # 2. FTS поиск
    fts_results = db.execute(text("""
        SELECT id, ts_rank(to_tsvector('russian', problem_text), 
                          plainto_tsquery('russian', :query)) as rank
        FROM problems
        WHERE to_tsvector('russian', problem_text) @@ plainto_tsquery('russian', :query)
        ORDER BY rank DESC
        LIMIT :limit
    """), {"query": query_text, "limit": top_k})
    
    # 3. Vector поиск
    embedding = get_embedding(query_text)  # OpenAI
    vector_results = db.execute(text("""
        SELECT id, 1 - (embedding <=> :embedding) as similarity
        FROM problems
        ORDER BY embedding <=> :embedding
        LIMIT :limit
    """), {"embedding": embedding, "limit": top_k})
    
    # 4. Объединить и ранжировать
    # ...
    
    return ranked_results

def extract_problem_number(text: str) -> str | None:
    """Извлечь номер задачи из текста."""
    import re
    patterns = [
        r'№\s*(\d+)',
        r'упр\.?\s*(\d+)',
        r'задача\s*(\d+)',
        r'^(\d+)\.',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None
```

### 3.3 LLM Generation (OpenAI)

**Конфиг:**
```bash
# infra/.env
OPENAI_API_KEY=sk-...
OPENAI_MODEL_TEXT=gpt-4o
```

**Реализация `apps/worker/llm.py`:**
```python
from openai import OpenAI

SYSTEM_PROMPT = """Ты — репетитор-помощник. Твоя задача — объяснить решение задачи пошагово.

ПРАВИЛА:
1. Используй ТОЛЬКО информацию из PROVIDED SOURCE
2. После каждого шага указывай источник: "Источник: стр. N"
3. Если информации недостаточно — скажи об этом
4. НЕ придумывай шаги которых нет в источнике
5. Отвечай на русском языке
6. Формат: Markdown с нумерованными шагами
"""

def generate_grounded_response(
    problem_text: str,
    solution_text: str,
    answer_text: str,
    page_ref: str,
) -> str:
    """
    Генерация grounded ответа на основе источника.
    """
    client = OpenAI()
    
    user_prompt = f"""
SOURCE:
[Задача]
{problem_text}

[Решение]
{solution_text}

[Ответ]
{answer_text}

[Страница]
{page_ref}

TASK:
Объясни это решение пошагово. После каждого шага укажи источник.
"""
    
    response = client.chat.completions.create(
        model=settings.openai_model_text,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        max_tokens=2000,
    )
    
    return response.choices[0].message.content
```

### 3.4 Verification Pass

**Реализация `apps/worker/verify.py`:**
```python
VERIFIER_PROMPT = """Ты — верификатор. Проверь черновик ответа и удали любые утверждения 
которых НЕТ в SOURCE. Сохрани цитаты и форматирование."""

def verify_response(draft: str, source_text: str) -> str:
    """
    Удаляет неподтверждённые утверждения из ответа.
    """
    client = OpenAI()
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",  # Дешевле для верификации
        messages=[
            {"role": "system", "content": VERIFIER_PROMPT},
            {"role": "user", "content": f"SOURCE:\n{source_text}\n\nDRAFT:\n{draft}"}
        ],
        temperature=0,
    )
    
    return response.choices[0].message.content
```

### 3.5 Полный pipeline в jobs.py

```python
def process_query(query_id: int):
    db = SessionLocal()
    query = db.query(Query).filter(Query.id == query_id).first()
    
    # 1. OCR
    if query.input_photo_keys:
        query.extracted_text, query.ocr_confidence = ocr_images(query.input_photo_keys)
    else:
        query.extracted_text = query.input_text
        query.ocr_confidence = 100
    
    query.status = "processing"
    db.commit()
    
    # 2. Retrieval
    candidates = hybrid_search(query.extracted_text, db)
    
    if not candidates:
        query.status = "failed"
        query.error_message = "Не найдено подходящих задач в базе"
        db.commit()
        return
    
    # 3. Check confidence
    best = candidates[0]
    if best['score'] < CONFIDENCE_THRESHOLD:
        # Нужен выбор пользователя
        query.status = "needs_choice"
        # Сохранить кандидатов в отдельную таблицу
        db.commit()
        return
    
    # 4. Generate
    problem = db.query(Problem).get(best['problem_id'])
    draft = generate_grounded_response(
        problem.problem_text,
        problem.solution_text,
        problem.answer_text,
        problem.page_ref,
    )
    
    # 5. Verify
    verified = verify_response(draft, problem.solution_text)
    
    # 6. Save response
    response = Response(
        query_id=query.id,
        content_markdown=verified,
        citations=[{"page": problem.page_ref, "book_id": problem.book_id}],
        model_used=settings.openai_model_text,
        confidence_score=int(best['score'] * 100),
    )
    db.add(response)
    
    query.status = "done"
    db.commit()
    
    # 7. Notify
    send_notification(query.user_id, query.id)
```

---

## Phase 4: Ingestion Pipeline

### Цель
Загрузка PDF решебников и извлечение задач для поиска.

### Архитектура

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PDF Ingestion Flow                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ┌──────────────────┐     ┌───────────────────┐   │
│  │  Admin TMA   │────►│  API: /upload    │────►│  MinIO Storage    │   │
│  │  (Upload UI) │     │                  │     │  (raw PDF)        │   │
│  └──────────────┘     └──────────────────┘     └───────────────────┘   │
│         │                                               │               │
│         │                      ┌────────────────────────┘               │
│         ▼                      ▼                                        │
│  ┌──────────────┐     ┌──────────────────┐     ┌───────────────────┐   │
│  │  Metadata    │◄────│  Worker: Auto-   │────►│  Book record      │   │
│  │  Confirmation│     │  Classification  │     │  (предмет, класс) │   │
│  └──────────────┘     └──────────────────┘     └───────────────────┘   │
│         │                                               │               │
│         │  Confirm/Edit                                 │               │
│         ▼                                               ▼               │
│  ┌──────────────┐     ┌──────────────────┐     ┌───────────────────┐   │
│  │  Start Full  │────►│  Worker: Render  │────►│  Pages → OCR →    │   │
│  │  Ingestion   │     │  + OCR + Segment │     │  Problems → Embed │   │
│  └──────────────┘     └──────────────────┘     └───────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Автоклассификация PDF

**Шаг 1: Загрузка и анализ первых страниц**

```python
# apps/api/routers/admin.py
@router.post("/v1/admin/pdfs/upload")
async def upload_pdf_for_classification(
    file: UploadFile,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    1. Сохранить PDF в MinIO (temp/)
    2. Запустить job автоклассификации
    3. Вернуть job_id для polling
    """
    # Сохранить временно
    temp_key = f"temp/{uuid4()}/{file.filename}"
    await minio_upload(temp_key, file)
    
    # Создать запись pending_pdf
    pending = PendingPdf(
        minio_key=temp_key,
        original_filename=file.filename,
        status="classifying",
    )
    db.add(pending)
    db.commit()
    
    # Запустить автоклассификацию
    enqueue_classification_job(pending.id)
    
    return {"pending_id": pending.id, "status": "classifying"}
```

**Шаг 2: Worker анализирует первые страницы**

```python
# apps/worker/classification.py
def classify_pdf_job(pending_id: int):
    """
    1. Скачать PDF
    2. Извлечь текст с первых 2-3 страниц
    3. Определить метаданные через LLM или паттерны
    4. Сохранить предложенную классификацию
    """
    db = SessionLocal()
    pending = db.query(PendingPdf).get(pending_id)
    
    # Извлечь текст
    pdf_data = minio_download(pending.minio_key)
    text = extract_first_pages_text(pdf_data, max_pages=3)
    
    # Классификация (LLM или паттерны)
    metadata = classify_with_llm(text, pending.original_filename)
    
    # Сохранить результат
    pending.suggested_subject = metadata.subject
    pending.suggested_grade = metadata.grade
    pending.suggested_authors = metadata.authors
    pending.suggested_title = metadata.title
    pending.suggested_publisher = metadata.publisher
    pending.suggested_part = metadata.part
    pending.is_gdz = metadata.is_gdz
    pending.confidence = metadata.confidence
    pending.status = "needs_confirmation"
    
    db.commit()
```

**Шаг 3: Админ подтверждает или редактирует**

```python
# apps/api/routers/admin.py
@router.get("/v1/admin/pdfs/pending/{pending_id}")
async def get_pending_pdf(pending_id: int, db: Session = Depends(get_db)):
    """Получить предложенную классификацию для подтверждения."""
    pending = db.query(PendingPdf).get(pending_id)
    return {
        "id": pending.id,
        "filename": pending.original_filename,
        "suggested": {
            "subject": pending.suggested_subject,
            "grade": pending.suggested_grade,
            "authors": pending.suggested_authors,
            "title": pending.suggested_title,
            "publisher": pending.suggested_publisher,
            "part": pending.suggested_part,
            "is_gdz": pending.is_gdz,
        },
        "confidence": pending.confidence,
        "status": pending.status,
    }


@router.post("/v1/admin/pdfs/pending/{pending_id}/confirm")
async def confirm_pdf_classification(
    pending_id: int,
    data: PdfConfirmRequest,  # subject, grade, authors, title, etc.
    db: Session = Depends(get_db),
):
    """
    1. Создать/найти Book
    2. Переместить PDF из temp/ в pdfs/{book_id}/
    3. Создать PdfSource
    4. Запустить полную ингестию
    """
    pending = db.query(PendingPdf).get(pending_id)
    
    # Найти или создать книгу
    book = find_or_create_book(db, data)
    
    # Переместить PDF
    new_key = f"pdfs/{book.id}/{pending.original_filename}"
    minio_move(pending.minio_key, new_key)
    
    # Создать PdfSource
    pdf_source = PdfSource(
        book_id=book.id,
        minio_key=new_key,
        original_filename=pending.original_filename,
        status="queued",
    )
    db.add(pdf_source)
    
    # Удалить pending
    db.delete(pending)
    db.commit()
    
    # Запустить полную ингестию
    enqueue_full_ingestion_job(pdf_source.id)
    
    return {"book_id": book.id, "pdf_source_id": pdf_source.id, "status": "ingesting"}
```

### 4.2 Render Pages (pymupdf)

### 4.2 Render Pages (pymupdf)

```python
import fitz  # pymupdf

def render_pdf_pages(pdf_key: str) -> list[str]:
    """Рендерит страницы PDF в PNG и сохраняет в MinIO."""
    # Скачать PDF из MinIO
    pdf_data = minio_client.get_object(bucket, pdf_key)
    
    doc = fitz.open(stream=pdf_data.read(), filetype="pdf")
    page_keys = []
    
    for i, page in enumerate(doc):
        # Рендерить в PNG
        pix = page.get_pixmap(dpi=150)
        img_data = pix.tobytes("png")
        
        # Сохранить в MinIO
        key = f"pages/{pdf_key}/{i:04d}.png"
        minio_client.put_object(bucket, key, io.BytesIO(img_data), len(img_data))
        page_keys.append(key)
    
    return page_keys
```

### 4.3 OCR + Segmentation

```python
def process_page(page_key: str) -> list[dict]:
    """OCR страницы и сегментация на задачи."""
    image = download_from_minio(page_key)
    
    # OCR с координатами
    data = pytesseract.image_to_data(image, lang='rus', output_type=Output.DICT)
    
    # Найти блоки задач по паттернам
    problems = []
    current_problem = None
    
    for i, text in enumerate(data['text']):
        if is_problem_start(text):  # "№123", "Задача 5"
            if current_problem:
                problems.append(current_problem)
            current_problem = {
                "number": extract_number(text),
                "text": text,
                "bbox": get_bbox(data, i),
            }
        elif current_problem:
            current_problem["text"] += " " + text
    
    return problems
```

### 4.4 Embeddings

```python
def create_embeddings(problems: list[dict]):
    """Создать embeddings для задач."""
    client = OpenAI()
    
    for problem in problems:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=problem["problem_text"],
        )
        problem["embedding"] = response.data[0].embedding
    
    # Bulk insert в БД
    db.execute(
        insert(Problem),
        problems
    )
```

---

## Phase 5: Admin Panel (TMA)

### Цель
Админский интерфейс **внутри Telegram Mini App** для управления контентом.

> 💡 Почему TMA, а не отдельный веб-интерфейс?
> - Единая точка входа (Telegram)
> - Готовая авторизация через Telegram
> - Удобно для мобильного использования
> - Не нужен отдельный домен/хостинг

### Архитектура

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Admin TMA Flow                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────┐                                                    │
│  │  Telegram Bot   │                                                    │
│  │  /admin command │───────────────────────────────────────────────┐    │
│  └─────────────────┘                                               │    │
│          │                                                         │    │
│          ▼                                                         │    │
│  ┌─────────────────┐     ┌─────────────────┐     ┌────────────────▼─┐  │
│  │   Admin TMA     │────►│  API Backend    │────►│  Check is_admin  │  │
│  │   (Next.js)     │     │  /v1/admin/*    │     │  from initData   │  │
│  └─────────────────┘     └─────────────────┘     └──────────────────┘  │
│          │                                                              │
│          ├─── 📤 Upload PDFs ─────────► Auto-classification            │
│          ├─── ✏️ Confirm/Edit ─────────► Move to books                 │
│          ├─── 📊 Dashboard ───────────► Stats & metrics                │
│          ├─── 🔍 Query Debugger ──────► Step-by-step analysis          │
│          └─── 📚 Problems Editor ─────► Manual corrections             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Экраны Admin TMA

| Экран | Описание | Функции |
|-------|----------|---------|
| **Dashboard** | Главная | Статистика, активные задачи, быстрые действия |
| **Upload** | Загрузка PDF | Drag&drop, камера, автоклассификация |
| **Pending** | Ожидают подтверждения | Список PDF с предложенной классификацией |
| **Confirm** | Подтверждение | Редактирование метаданных, confirm/reject |
| **Books** | Список книг | Фильтры по предмету/классу, статус ингестии |
| **Book Detail** | Детали книги | Страницы, задачи, проблемы OCR |
| **Queries** | Отладка запросов | Вход → OCR → retrieval → response |
| **Settings** | Настройки | Админы, лимиты, промпты |

### Структура (apps/tma с admin routes)

```
apps/tma/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                    # User home
│   ├── admin/                      # Admin-only routes
│   │   ├── layout.tsx              # Admin layout + guard
│   │   ├── page.tsx                # Dashboard
│   │   ├── upload/page.tsx         # PDF upload
│   │   ├── pending/
│   │   │   ├── page.tsx            # Pending list
│   │   │   └── [id]/page.tsx       # Confirm classification
│   │   ├── books/
│   │   │   ├── page.tsx            # Books list
│   │   │   └── [id]/page.tsx       # Book details
│   │   └── queries/
│   │       ├── page.tsx            # Queries list
│   │       └── [id]/page.tsx       # Query debugger
│   └── api/                        # Proxy to backend
├── components/
│   ├── admin/
│   │   ├── PdfUploader.tsx         # Drag&drop + camera
│   │   ├── ClassificationCard.tsx  # Show suggested metadata
│   │   ├── MetadataEditor.tsx      # Edit subject/grade/authors
│   │   ├── PageViewer.tsx          # Page image + OCR overlay
│   │   ├── QueryDebugger.tsx       # Step-by-step analysis
│   │   └── StatsCard.tsx           # Dashboard metrics
│   └── ...
└── lib/
    ├── api.ts                      # API client
    └── admin-guard.ts              # Check is_admin
```

### Проверка админских прав

```typescript
// apps/tma/lib/admin-guard.ts
import { WebApp } from '@twa-dev/sdk';

const ADMIN_TG_IDS = [
  123456789,  // Your Telegram ID
  // Add more admin IDs
];

export function isAdmin(): boolean {
  const user = WebApp.initDataUnsafe.user;
  if (!user) return false;
  return ADMIN_TG_IDS.includes(user.id);
}

// Usage in layout
export default function AdminLayout({ children }) {
  if (!isAdmin()) {
    return <AccessDenied />;
  }
  return <AdminShell>{children}</AdminShell>;
}
```

### API: Админские эндпоинты

```python
# apps/api/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException
from apps.api.auth import get_current_user

router = APIRouter(prefix="/v1/admin", tags=["Admin"])

ADMIN_TG_IDS = {123456789}  # From env in production

def require_admin(user = Depends(get_current_user)):
    if user.tg_uid not in ADMIN_TG_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

@router.get("/stats")
async def get_stats(admin = Depends(require_admin), db = Depends(get_db)):
    """Dashboard statistics."""
    return {
        "total_books": db.query(Book).count(),
        "total_problems": db.query(Problem).count(),
        "pending_pdfs": db.query(PendingPdf).count(),
        "queries_today": db.query(Query).filter(...).count(),
        "success_rate": calculate_success_rate(db),
    }

@router.get("/pending")
async def list_pending(admin = Depends(require_admin), db = Depends(get_db)):
    """List PDFs awaiting classification confirmation."""
    return db.query(PendingPdf).filter(
        PendingPdf.status == "needs_confirmation"
    ).all()

# ... other admin endpoints from Phase 4
```

### UI: Экран подтверждения классификации

```tsx
// apps/tma/app/admin/pending/[id]/page.tsx
export default function ConfirmClassification({ params }) {
  const { data: pending } = useSWR(`/api/admin/pending/${params.id}`);
  const [metadata, setMetadata] = useState(pending?.suggested);
  
  async function handleConfirm() {
    await fetch(`/api/admin/pending/${params.id}/confirm`, {
      method: 'POST',
      body: JSON.stringify(metadata),
    });
    router.push('/admin/pending');
  }
  
  return (
    <div className="p-4 space-y-4">
      <h1 className="text-xl font-bold">Подтвердите классификацию</h1>
      
      <div className="bg-gray-100 p-3 rounded">
        <p className="text-sm text-gray-600">Файл:</p>
        <p className="font-mono">{pending?.filename}</p>
      </div>
      
      <ConfidenceBadge value={pending?.confidence} />
      
      <MetadataEditor 
        value={metadata} 
        onChange={setMetadata}
        subjects={SUBJECTS}
        grades={GRADES}
      />
      
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => router.back()}>
          Отмена
        </Button>
        <Button onClick={handleConfirm}>
          ✓ Подтвердить и запустить ингестию
        </Button>
      </div>
    </div>
  );
}
```

---

## Phase 6: Telegram Mini App

### Цель
Основной UI для пользователей в Telegram.

### Технологии
- Next.js 14
- Telegram WebApp SDK
- Tailwind CSS

### Экраны

| Экран | Описание |
|-------|----------|
| **Home** | Поле ввода + кнопка фото |
| **Upload** | Превью фото, кадрирование |
| **Processing** | Анимация ожидания |
| **Result** | Пошаговый ответ с цитатами |
| **History** | Список прошлых запросов |
| **Profile** | План, лимиты, настройки |

### Валидация initData

```typescript
// apps/tma/lib/telegram.ts
import { WebApp } from '@twa-dev/sdk';

export async function authenticate() {
  const initData = WebApp.initData;
  
  const response = await fetch('/api/auth/telegram', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ init_data: initData }),
  });
  
  return response.json();
}
```

---

## Phase 7: Production & Scaling

### Инфраструктура

```
┌─────────────────────────────────────────────────────────────┐
│                     Production Setup                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────┐     ┌─────────┐     ┌─────────────────┐        │
│  │  Nginx  │────►│   API   │────►│    Postgres     │        │
│  │  (SSL)  │     │ (x2-4)  │     │   (managed)     │        │
│  └─────────┘     └─────────┘     └─────────────────┘        │
│       │                                    │                 │
│       │          ┌─────────┐     ┌─────────────────┐        │
│       └─────────►│ Workers │────►│     Redis       │        │
│                  │ (x2-8)  │     │   (managed)     │        │
│                  └─────────┘     └─────────────────┘        │
│                                                              │
│  Monitoring: Prometheus + Grafana                           │
│  Logs: Loki / ELK                                           │
│  Vectors: Qdrant (upgrade from pgvector)                    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Чеклист перед production

- [ ] SSL сертификаты (Let's Encrypt)
- [ ] Сильные пароли в .env
- [ ] Rate limiting на API
- [ ] Backup стратегия для Postgres
- [ ] Мониторинг и алерты
- [ ] Логирование с retention
- [ ] Health checks для всех сервисов

---

## 📊 Метрики успеха

| Метрика | Цель | Как измерять |
|---------|------|--------------|
| Retrieval accuracy | >90% | % запросов с confidence > threshold |
| needs_choice rate | <20% | % запросов требующих выбор пользователя |
| Response time p95 | <10s | Время от создания query до done |
| LLM cost per query | <$0.02 | Tokens used × price |
| User satisfaction | >4.5/5 | Feedback после ответа |

---

## 🚦 Порядок реализации

### Неделя 1-2: Core Pipeline
1. ✅ MVP scaffold (done)
2. ✅ Telegram бот с токеном (done)
3. ✅ Push уведомления (done)
4. ✅ Скрипт автоклассификации PDF (done - `scripts/classify_pdfs.py`)
5. ✅ OCR + ингестия (done - Tesseract в worker)
6. ✅ Таблицы books/pdf_sources/pdf_pages/problems (done)
7. ✅ FTS поиск (done - `apps/worker/retrieval.py`)
8. ✅ Классификация задач: вопросы vs упражнения (`scripts/classify_problems.py`)
9. ✅ Назначение секций (§N) задачам (`scripts/assign_sections.py`)
10. ✅ Привязка ответов к упражнениям (`scripts/link_answers.py`)
11. ✅ Привязка теории к вопросам (`scripts/link_theory.py`)

### Скрипты обработки данных

| Скрипт | Описание | Команда |
|--------|----------|---------|
| `classify_problems.py` | Классифицирует задачи: `question` / `exercise` | `python scripts/classify_problems.py --book-id 1` |
| `assign_sections.py` | Назначает секции (§N) на основе OCR | `python scripts/assign_sections.py --book-id 1` |
| `link_answers.py` | Парсит ответы из конца учебника | `python scripts/link_answers.py --book-id 1` |
| `link_theory.py` | Парсит теорию/доказательства для вопросов | `python scripts/link_theory.py --book-id 1` |
| `process_all.py` | **Мастер-скрипт** - запускает все шаги | `python scripts/process_all.py --book-id 1` |
| `validate_ocr.py` | Валидация качества OCR | `python scripts/validate_ocr.py --book-id 1 --page 10` |
| `fix_formulas.py` | Исправление формул после OCR | `python scripts/fix_formulas.py` |

### LLM-объяснения решений (✅ Done)

**Файл:** `apps/worker/llm.py`

Модуль генерирует объяснения решений используя:
1. **Текст задачи** — условие
2. **Ответ из БД** — численный ответ или решение
3. **Теорию раздела** — определения, теоремы, доказательства из параграфа

**Пример:**
```
Запрос: "Найдите смежные углы если один из них на 80 градусов больше другого"

Ответ: ✅ Ответ: 1) 105° и 75°

💡 Объяснение:
Решение этой задачи основано на свойстве смежных углов.

1. По определению, смежные углы — это два угла, у которых одна сторона общая, 
   а две другие стороны являются продолжениями одна другой.

2. Сумма смежных углов всегда равна 180°.

3. Пусть один угол = x, тогда другой = x + 80°
   x + (x + 80°) = 180°
   2x = 100°
   x = 50°

4. Ответ: 50° и 130° (но в учебнике дан другой ответ: 105° и 75°, 
   возможно условие задачи отличалось)
```

**Конфигурация:**
```bash
# infra/.env
OPENAI_API_KEY=sk-...
OPENAI_MODEL_TEXT=gpt-4o-mini  # или gpt-4o для более качественных объяснений
```

### Типы проблем

| Тип | Описание | Источник ответа |
|-----|----------|-----------------|
| `question` | Контрольный вопрос (теоретический) | Материал параграфа (определения, теоремы, доказательства) |
| `exercise` | Числовая задача | Раздел "Ответы" в конце учебника |
| `unknown` | Не классифицировано | - |

### Неделя 3-4: Admin TMA + Ingestion
8. **Admin TMA** — минимальный интерфейс:
   - [ ] /admin route в TMA
   - [ ] Проверка is_admin
   - [ ] Dashboard со статистикой
   - [ ] Upload PDF endpoint
9. **Автоклассификация через API:**
   - [ ] POST /v1/admin/pdfs/upload → temp MinIO
   - [ ] Worker job: classify_pdf (OCR + LLM)
   - [ ] GET /v1/admin/pending — список ожидающих
   - [ ] POST /v1/admin/pending/{id}/confirm
10. **Admin TMA UI:**
    - [ ] PdfUploader компонент
    - [ ] Pending list
    - [ ] Confirm/Edit metadata screen

### Неделя 5-6: LLM + Retrieval
11. Интеграция OpenAI
12. Vector search (pgvector)
13. Hybrid ranking (FTS + vector)
14. Verification pass
15. Полный pipeline в jobs.py

### Неделя 7-8: Content + User TMA
16. Полная ингестия (render pages → OCR → segment → embed)
17. Загрузить первые решебники через Admin TMA
18. User TMA (Home, Result, History, Profile)
19. Тестирование end-to-end

### Неделя 9+: Production
20. Production deploy (VPS)
21. Мониторинг и логирование
22. Итерации на основе feedback

---

## 📚 Полезные ссылки

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Telegram Mini Apps](https://core.telegram.org/bots/webapps)
- [OpenAI API](https://platform.openai.com/docs)
- [pgvector](https://github.com/pgvector/pgvector)
- [RQ Documentation](https://python-rq.org/)
- [FastAPI](https://fastapi.tiangolo.com/)
