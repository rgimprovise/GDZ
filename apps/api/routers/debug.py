"""
Debug/Admin Router for testing and debugging.

Provides:
- Dashboard with statistics
- Search testing
- Books/Problems viewer
- Query debugger
- Upload PDF, Start OCR
"""
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

import os
from fastapi import APIRouter, Depends, Query as QueryParam, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from sqlalchemy.exc import ProgrammingError

from database import get_db
from models import Book, PdfSource, PdfPage, Query, User
from config import get_settings
from job_queue import enqueue_ingestion, enqueue_llm_normalize, enqueue_import_from_normalized

router = APIRouter(prefix="/debug", tags=["Debug"])
settings = get_settings()

# Ключевые слова для классификации по имени файла (без чтения PDF)
SUBJECT_KEYWORDS = [
    ("physics", ["физика", "физик"]),
    ("chemistry", ["химия", "хими"]),
    ("biology", ["биология", "биолог"]),
    ("russian", ["русский язык", "русск. яз", "русск"]),
    ("english", ["английский язык", "английск", "english", "англ яз"]),
    ("history", ["история", "истори"]),
    ("geography", ["география", "географ"]),
    ("informatics", ["информатика", "информатик"]),
    ("geometry", ["геометрия", "геометри"]),
    ("math", ["математика", "алгебра", "матем", "алгебр"]),
]


def _normalize_unicode(t: str) -> str:
    return unicodedata.normalize("NFC", t) if t else ""


def classify_from_filename(filename: str) -> dict:
    """Классификация по имени файла (без PyMuPDF)."""
    low = _normalize_unicode(filename.lower())
    out = {
        "subject": "other",
        "grade": None,
        "authors": None,
        "title": Path(filename).stem.replace("_", " ").replace("-", " "),
        "publisher": None,
        "part": None,
        "is_gdz": False,
    }
    for subject, keywords in SUBJECT_KEYWORDS:
        for kw in keywords:
            if kw in low:
                out["subject"] = subject
                break
        if out["subject"] != "other":
            break
    grade_m = re.search(r"(\d{1,2})\s*[-–]?\s*класс", low) or re.search(r"(\d{1,2})\s*класс", low)
    if grade_m:
        out["grade"] = grade_m.group(1)
    part_m = re.search(r"часть\s*(\d+)", low)
    if part_m:
        out["part"] = part_m.group(1)
    if any(x in low for x in ["гдз", "решебник", "ответы"]):
        out["is_gdz"] = True
    subject_names = {
        "math": "Математика", "geometry": "Геометрия", "physics": "Физика",
        "chemistry": "Химия", "biology": "Биология", "russian": "Русский язык",
        "english": "Английский язык", "history": "История", "geography": "География",
        "informatics": "Информатика",
    }
    if out["subject"] in subject_names:
        parts = [subject_names[out["subject"]]]
        if out["grade"]:
            parts.append(f"{out['grade']} класс")
        if out["authors"]:
            parts.append(out["authors"])
        if out["part"]:
            parts.append(f"часть {out['part']}")
        out["title"] = " ".join(parts)
    return out


# ===========================================
# Dashboard HTML
# ===========================================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TutorBot Debug Panel</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <style>
        .loading { opacity: 0.5; }
        pre { white-space: pre-wrap; word-wrap: break-word; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8 max-w-6xl">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-gray-800">TutorBot Debug Panel</h1>
            <p class="text-gray-600">Тестирование и отладка</p>
        </header>

        <!-- Stats Cards -->
        <div id="stats" hx-get="/debug/api/stats" hx-trigger="load" hx-swap="innerHTML"
             class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div class="bg-white p-4 rounded-lg shadow animate-pulse">
                <div class="h-8 bg-gray-200 rounded w-20 mb-2"></div>
                <div class="h-4 bg-gray-200 rounded w-16"></div>
            </div>
            <div class="bg-white p-4 rounded-lg shadow animate-pulse">
                <div class="h-8 bg-gray-200 rounded w-20 mb-2"></div>
                <div class="h-4 bg-gray-200 rounded w-16"></div>
            </div>
            <div class="bg-white p-4 rounded-lg shadow animate-pulse">
                <div class="h-8 bg-gray-200 rounded w-20 mb-2"></div>
                <div class="h-4 bg-gray-200 rounded w-16"></div>
            </div>
            <div class="bg-white p-4 rounded-lg shadow animate-pulse">
                <div class="h-8 bg-gray-200 rounded w-20 mb-2"></div>
                <div class="h-4 bg-gray-200 rounded w-16"></div>
            </div>
        </div>

        <!-- Search Test -->
        <div class="bg-white rounded-lg shadow mb-8 p-6">
            <h2 class="text-xl font-semibold mb-4">🔍 Тест поиска</h2>
            <form hx-get="/debug/api/search" hx-target="#search-results" hx-indicator="#search-loading">
                <div class="flex gap-2 mb-4">
                    <input type="text" name="q" placeholder="Введите запрос..." 
                           class="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                           value="Докажите что сумма смежных углов равна 180">
                    <button type="submit" 
                            class="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                        Искать
                    </button>
                </div>
            </form>
            <div id="search-loading" class="htmx-indicator text-center py-4">
                <span class="text-gray-500">Поиск...</span>
            </div>
            <div id="search-results"></div>
        </div>

        <!-- Create Query Test -->
        <div class="bg-white rounded-lg shadow mb-8 p-6">
            <h2 class="text-xl font-semibold mb-4">📝 Создать запрос</h2>
            <form hx-post="/debug/api/create-query" hx-target="#query-result" hx-indicator="#query-loading">
                <div class="flex gap-2 mb-4">
                    <input type="text" name="text" placeholder="Текст запроса..." 
                           class="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                           value="Найдите смежные углы если один из них на 80 градусов больше другого">
                    <button type="submit" 
                            class="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700">
                        Отправить
                    </button>
                </div>
            </form>
            <div id="query-loading" class="htmx-indicator text-center py-4">
                <span class="text-gray-500">Обработка...</span>
            </div>
            <div id="query-result"></div>
        </div>

        <!-- Upload PDF -->
        <div class="bg-white rounded-lg shadow mb-8 p-6">
            <h2 class="text-xl font-semibold mb-4">📤 Загрузить новый учебник</h2>
            <form hx-post="/debug/api/upload-pdf" hx-target="#upload-result" hx-indicator="#upload-indicator"
                  hx-encoding="multipart/form-data" class="space-y-4">
                <div class="flex flex-wrap gap-4 items-end">
                    <div>
                        <label class="block text-sm text-gray-600 mb-1">PDF файл</label>
                        <input type="file" name="file" accept=".pdf,.PDF" required
                               class="px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                    </div>
                    <div>
                        <label class="block text-sm text-gray-600 mb-1">Предмет (опционально)</label>
                        <select name="subject" class="px-3 py-2 border rounded-lg">
                            <option value="">по имени файла</option>
                            <option value="math">Математика</option>
                            <option value="geometry">Геометрия</option>
                            <option value="physics">Физика</option>
                            <option value="chemistry">Химия</option>
                            <option value="russian">Русский язык</option>
                            <option value="english">Английский язык</option>
                            <option value="other">Другое</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm text-gray-600 mb-1">Класс (опционально)</label>
                        <input type="text" name="grade" placeholder="7" class="px-3 py-2 border rounded-lg w-20">
                    </div>
                    <div>
                        <label class="block text-sm text-gray-600 mb-1">Название (опционально)</label>
                        <input type="text" name="title" placeholder="по имени файла" class="px-3 py-2 border rounded-lg w-64">
                    </div>
                    <button type="submit" class="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">
                        Загрузить
                    </button>
                </div>
                <div id="upload-indicator" class="htmx-indicator text-gray-500">Загрузка...</div>
                <div id="upload-result"></div>
            </form>
        </div>

        <!-- PDF sources: Start OCR -->
        <div class="bg-white rounded-lg shadow mb-8 p-6">
            <h2 class="text-xl font-semibold mb-4">📄 Источники PDF — начать OCR</h2>
            <p class="text-sm text-gray-500 mb-4">Пайплайн: Tesseract → md/txt → нормализация (OpenAI) → распределение в БД (OpenAI).</p>
            <p class="text-xs text-gray-400 mb-4">Результат LLM-нормализации записывается в <code>data/ocr_normalized/{book_id}/{pdf_source_id}.md</code>, затем импортируется в БД. При сбое прогресс сохраняется в чекпоинт — повторный запуск «LLM нормализация» продолжит с места остановки (без повторной оплаты API).</p>
            <div id="pdf-sources-list" hx-get="/debug/api/pdf-sources" hx-trigger="load, refreshPdfSources from:body" hx-swap="innerHTML">
                <div class="animate-pulse">
                    <div class="h-10 bg-gray-200 rounded mb-2"></div>
                    <div class="h-10 bg-gray-200 rounded mb-2"></div>
                </div>
            </div>
        </div>

        <!-- Books List -->
        <div class="bg-white rounded-lg shadow mb-8 p-6">
            <h2 class="text-xl font-semibold mb-4">📚 Книги в базе</h2>
            <div id="books-list" hx-get="/debug/api/books" hx-trigger="load" hx-swap="innerHTML">
                <div class="animate-pulse">
                    <div class="h-10 bg-gray-200 rounded mb-2"></div>
                    <div class="h-10 bg-gray-200 rounded mb-2"></div>
                </div>
            </div>
        </div>

        <!-- Problems Viewer -->
        <div class="bg-white rounded-lg shadow mb-8 p-6">
            <h2 class="text-xl font-semibold mb-4">📋 Просмотр задач</h2>
            <div class="flex gap-2 mb-4">
                <select id="book-select" name="book_id" class="px-4 py-2 border rounded-lg"
                        hx-get="/debug/api/problems" hx-target="#problems-list" 
                        hx-trigger="change" hx-include="#book-select, select[name='problem_type']">
                    <option value="">Выберите книгу...</option>
                </select>
                <select name="problem_type" class="px-4 py-2 border rounded-lg"
                        hx-get="/debug/api/problems" hx-target="#problems-list" 
                        hx-trigger="change" hx-include="#book-select">
                    <option value="">Все типы</option>
                    <option value="question">Вопросы</option>
                    <option value="exercise">Упражнения</option>
                    <option value="unknown">Неизвестные</option>
                </select>
            </div>
            <div id="problems-list"></div>
        </div>

        <!-- DB Debug Window -->
        <div class="bg-white rounded-lg shadow mb-8 p-6">
            <h2 class="text-xl font-semibold mb-4">🔧 Окно отладки по БД</h2>
            <p class="text-sm text-gray-500 mb-4">Просмотр того, что реально записано в БД: теория по параграфам, задачи/вопросы/ответы. Фильтры по книге, типу, параграфу, странице.</p>
            <div class="flex flex-wrap gap-4 mb-4 items-end">
                <div>
                    <label class="block text-xs text-gray-500 mb-1">Книга</label>
                    <select id="db-debug-book" name="book_id" class="px-3 py-2 border rounded-lg"
                            hx-get="/debug/api/db-preview" hx-target="#db-preview-result" hx-trigger="change"
                            hx-include="#db-debug-book, #db-debug-content, #db-debug-ptype, #db-debug-section, #db-debug-page, #db-debug-with-answer">
                        <option value="">Выберите книгу...</option>
                    </select>
                </div>
                <div>
                    <label class="block text-xs text-gray-500 mb-1">Что смотреть</label>
                    <select id="db-debug-content" name="content" class="px-3 py-2 border rounded-lg"
                            hx-get="/debug/api/db-preview" hx-target="#db-preview-result" hx-trigger="change"
                            hx-include="#db-debug-book, #db-debug-content, #db-debug-ptype, #db-debug-section, #db-debug-page, #db-debug-with-answer">
                        <option value="all">Теория и задачи</option>
                        <option value="theory">Только теория (параграфы)</option>
                        <option value="problems">Только задачи</option>
                    </select>
                </div>
                <div>
                    <label class="block text-xs text-gray-500 mb-1">Тип задачи</label>
                    <select id="db-debug-ptype" name="problem_type" class="px-3 py-2 border rounded-lg"
                            hx-get="/debug/api/db-preview" hx-target="#db-preview-result" hx-trigger="change"
                            hx-include="#db-debug-book, #db-debug-content, #db-debug-ptype, #db-debug-section, #db-debug-page, #db-debug-with-answer">
                        <option value="">Все</option>
                        <option value="question">Вопрос</option>
                        <option value="exercise">Упражнение</option>
                        <option value="unknown">Неизвестный</option>
                    </select>
                </div>
                <div>
                    <label class="block text-xs text-gray-500 mb-1">Параграф (§)</label>
                    <input type="text" id="db-debug-section" name="section" placeholder="§12 или 12" class="px-3 py-2 border rounded-lg w-24"
                           hx-get="/debug/api/db-preview" hx-target="#db-preview-result" hx-trigger="keyup changed delay:300ms"
                           hx-include="#db-debug-book, #db-debug-content, #db-debug-ptype, #db-debug-section, #db-debug-page, #db-debug-with-answer">
                </div>
                <div>
                    <label class="block text-xs text-gray-500 mb-1">Страница</label>
                    <input type="number" id="db-debug-page" name="page" placeholder="—" min="0" class="px-3 py-2 border rounded-lg w-20"
                           hx-get="/debug/api/db-preview" hx-target="#db-preview-result" hx-trigger="change"
                           hx-include="#db-debug-book, #db-debug-content, #db-debug-ptype, #db-debug-section, #db-debug-page, #db-debug-with-answer">
                </div>
                <div class="flex items-center gap-2">
                    <input type="checkbox" id="db-debug-with-answer" name="with_answer" value="1" class="rounded"
                           hx-get="/debug/api/db-preview" hx-target="#db-preview-result" hx-trigger="change"
                           hx-include="#db-debug-book, #db-debug-content, #db-debug-ptype, #db-debug-section, #db-debug-page, #db-debug-with-answer">
                    <label for="db-debug-with-answer" class="text-sm text-gray-600">Только с ответом</label>
                </div>
            </div>
            <div id="db-preview-result" class="min-h-[120px] rounded border border-gray-200 bg-gray-50 p-4">
                <p class="text-gray-500 text-sm">Выберите книгу</p>
            </div>
        </div>

        <!-- Recent Queries -->
        <div class="bg-white rounded-lg shadow p-6">
            <h2 class="text-xl font-semibold mb-4">📬 Последние запросы</h2>
            <div id="recent-queries" hx-get="/debug/api/queries" hx-trigger="load, every 10s" hx-swap="innerHTML">
                <div class="animate-pulse">
                    <div class="h-16 bg-gray-200 rounded mb-2"></div>
                    <div class="h-16 bg-gray-200 rounded mb-2"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Load book options for both selects
        fetch('/debug/api/books-options')
            .then(r => r.text())
            .then(html => {
                const opt = '<option value="">Выберите книгу...</option>' + html;
                document.getElementById('book-select').innerHTML = opt;
                const dbBook = document.getElementById('db-debug-book');
                if (dbBook) dbBook.innerHTML = opt;
            });
    </script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def debug_dashboard():
    """Debug dashboard HTML page."""
    return DASHBOARD_HTML


# ===========================================
# API Endpoints for Dashboard
# ===========================================

def _stats_html(books_count: int, total: int, questions: int, exercises: int,
                with_answer: int, with_solution: int, pages_count: int, queries_count: int) -> str:
    return f"""
    <div class="bg-white p-4 rounded-lg shadow">
        <div class="text-3xl font-bold text-blue-600">{books_count}</div>
        <div class="text-gray-600">Книг</div>
    </div>
    <div class="bg-white p-4 rounded-lg shadow">
        <div class="text-3xl font-bold text-green-600">{total}</div>
        <div class="text-gray-600">Задач</div>
        <div class="text-xs text-gray-400 mt-1">
            📝 {questions} вопр. | 🔢 {exercises} упр.
        </div>
    </div>
    <div class="bg-white p-4 rounded-lg shadow">
        <div class="text-3xl font-bold text-purple-600">{with_answer}</div>
        <div class="text-gray-600">С ответами</div>
        <div class="text-xs text-gray-400 mt-1">
            💡 {with_solution} с решением
        </div>
    </div>
    <div class="bg-white p-4 rounded-lg shadow">
        <div class="text-3xl font-bold text-orange-600">{pages_count}</div>
        <div class="text-gray-600">Страниц OCR</div>
        <div class="text-xs text-gray-400 mt-1">
            📬 {queries_count} запросов
        </div>
    </div>
    """


@router.get("/api/stats", response_class=HTMLResponse)
def get_stats(db: Session = Depends(get_db)):
    """Get statistics as HTML cards. Returns zeros if tables are missing (run alembic upgrade head)."""
    try:
        books_count = db.execute(text("SELECT COUNT(*) FROM books")).scalar() or 0
        problems_result = db.execute(text("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE problem_type = 'question') as questions,
                COUNT(*) FILTER (WHERE problem_type = 'exercise') as exercises,
                COUNT(*) FILTER (WHERE answer_text IS NOT NULL) as with_answer,
                COUNT(*) FILTER (WHERE solution_text IS NOT NULL) as with_solution
            FROM problems
        """)).first()
        total = problems_result.total if problems_result else 0
        questions = problems_result.questions if problems_result else 0
        exercises = problems_result.exercises if problems_result else 0
        with_answer = problems_result.with_answer if problems_result else 0
        with_solution = problems_result.with_solution if problems_result else 0
        pages_count = db.execute(text("SELECT COUNT(*) FROM pdf_pages")).scalar() or 0
        queries_count = db.execute(text("SELECT COUNT(*) FROM queries")).scalar() or 0
    except ProgrammingError:
        books_count = total = questions = exercises = with_answer = with_solution = pages_count = queries_count = 0
    return _stats_html(books_count, total, questions, exercises, with_answer, with_solution, pages_count, queries_count)


@router.get("/api/search", response_class=HTMLResponse)
def search_problems(
    q: str = QueryParam(..., description="Search query"),
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Search problems and return HTML results."""
    if not q or len(q) < 2:
        return "<p class='text-gray-500'>Введите запрос (минимум 2 символа)</p>"
    
    # Preprocess query
    import re
    query = re.sub(r'градусов|градуса|градус', '°', q, flags=re.IGNORECASE)
    query = re.sub(r'°', ' ', query)
    query = re.sub(r'[^\w\s\dа-яА-ЯёЁ]', ' ', query)
    query = ' '.join(query.split()).lower()
    
    like_pattern = '%' + '%'.join(query.split()[:4]) + '%'
    
    # Search
    result = db.execute(text("""
        SELECT 
            p.id,
            p.number,
            p.section,
            p.problem_type,
            LEFT(p.problem_text, 300) as problem_text,
            LEFT(p.answer_text, 200) as answer_text,
            LEFT(p.solution_text, 200) as solution_text,
            b.title as book_title,
            ts_rank(
                to_tsvector('russian', p.problem_text),
                plainto_tsquery('russian', :query)
            ) as score
        FROM problems p
        JOIN books b ON b.id = p.book_id
        WHERE 
            to_tsvector('russian', p.problem_text) @@ plainto_tsquery('russian', :query)
            OR LOWER(p.problem_text) LIKE :like_query
        ORDER BY score DESC
        LIMIT :limit
    """), {"query": query, "like_query": like_pattern, "limit": limit})
    
    rows = list(result)
    
    if not rows:
        return f"<p class='text-gray-500'>По запросу «{q}» ничего не найдено</p>"
    
    html = f"<p class='text-sm text-gray-500 mb-4'>Найдено: {len(rows)} результатов</p>"
    
    for row in rows:
        type_badge = {
            'question': '<span class="px-2 py-0.5 bg-blue-100 text-blue-800 rounded text-xs">вопрос</span>',
            'exercise': '<span class="px-2 py-0.5 bg-green-100 text-green-800 rounded text-xs">упражнение</span>',
            'unknown': '<span class="px-2 py-0.5 bg-gray-100 text-gray-800 rounded text-xs">?</span>',
        }.get(row.problem_type or 'unknown', '')
        
        answer_html = ""
        if row.answer_text:
            answer_html = f'<div class="mt-2 p-2 bg-green-50 rounded text-sm"><strong>Ответ:</strong> {row.answer_text}</div>'
        elif row.solution_text:
            answer_html = f'<div class="mt-2 p-2 bg-blue-50 rounded text-sm"><strong>Решение:</strong> {row.solution_text[:150]}...</div>'
        
        html += f"""
        <div class="border-b py-3">
            <div class="flex items-center gap-2 mb-1">
                <span class="font-semibold">№{row.number or '?'}</span>
                <span class="text-gray-400">{row.section or ''}</span>
                {type_badge}
                <span class="text-xs text-gray-400 ml-auto">score: {row.score:.4f}</span>
            </div>
            <div class="text-sm text-gray-700">{row.problem_text}...</div>
            <div class="text-xs text-gray-500 mt-1">{row.book_title}</div>
            {answer_html}
        </div>
        """
    
    return html


@router.post("/api/create-query", response_class=HTMLResponse)
def create_test_query(
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    """Create a test query and process it."""
    import httpx
    
    # Call the actual API endpoint
    try:
        response = httpx.post(
            "http://localhost:8000/v1/queries",
            json={"text": text},
            timeout=30.0
        )
        
        if response.status_code == 201:
            data = response.json()
            return f"""
            <div class="p-4 bg-green-50 rounded-lg">
                <div class="font-semibold text-green-800">✅ Запрос создан</div>
                <div class="text-sm text-gray-600 mt-1">ID: {data['id']}</div>
                <div class="text-sm text-gray-600">Статус: {data['status']}</div>
                <div class="mt-2">
                    <a href="/debug/api/query/{data['id']}" 
                       hx-get="/debug/api/query/{data['id']}" 
                       hx-target="#query-result"
                       class="text-blue-600 hover:underline">
                       Проверить результат →
                    </a>
                </div>
            </div>
            """
        else:
            return f"""
            <div class="p-4 bg-red-50 rounded-lg">
                <div class="font-semibold text-red-800">❌ Ошибка</div>
                <div class="text-sm text-gray-600">{response.text}</div>
            </div>
            """
    except Exception as e:
        return f"""
        <div class="p-4 bg-red-50 rounded-lg">
            <div class="font-semibold text-red-800">❌ Ошибка подключения</div>
            <div class="text-sm text-gray-600">{str(e)}</div>
        </div>
        """


@router.get("/api/query/{query_id}", response_class=HTMLResponse)
def get_query_result(query_id: int, db: Session = Depends(get_db)):
    """Get query result as HTML."""
    result = db.execute(text("""
        SELECT 
            q.id,
            q.input_text,
            q.status,
            q.processing_time_ms,
            q.created_at,
            r.content_markdown,
            r.confidence_score
        FROM queries q
        LEFT JOIN responses r ON r.query_id = q.id
        WHERE q.id = :id
    """), {"id": query_id}).first()
    
    if not result:
        return "<p class='text-red-500'>Запрос не найден</p>"
    
    status_badge = {
        'queued': '<span class="px-2 py-0.5 bg-yellow-100 text-yellow-800 rounded">в очереди</span>',
        'processing': '<span class="px-2 py-0.5 bg-blue-100 text-blue-800 rounded">обработка...</span>',
        'done': '<span class="px-2 py-0.5 bg-green-100 text-green-800 rounded">готово</span>',
        'failed': '<span class="px-2 py-0.5 bg-red-100 text-red-800 rounded">ошибка</span>',
    }.get(result.status, result.status)
    
    content_html = ""
    if result.content_markdown:
        content_html = f"""
        <div class="mt-4 p-4 bg-gray-50 rounded">
            <div class="text-sm font-semibold mb-2">Ответ (confidence: {result.confidence_score}%):</div>
            <pre class="text-sm whitespace-pre-wrap">{result.content_markdown[:2000]}</pre>
        </div>
        """
    elif result.status in ('queued', 'processing'):
        content_html = f"""
        <div class="mt-4 p-4 bg-yellow-50 rounded text-center"
             hx-get="/debug/api/query/{query_id}" hx-trigger="every 2s" hx-target="#query-result" hx-swap="innerHTML">
            <span class="text-yellow-700">⏳ Ожидание результата...</span>
        </div>
        """
    
    # When polling (queued/processing), HTMX replaces #query-result with this card;
    # we must return the full card so one card is shown (no nesting).
    return f"""
    <div class="p-4 bg-white border rounded-lg" id="query-result-card">
        <div class="flex items-center gap-2 mb-2">
            <span class="font-semibold">Query #{result.id}</span>
            {status_badge}
            <span class="text-xs text-gray-400 ml-auto">
                {result.processing_time_ms or '?'}ms
            </span>
        </div>
        <div class="text-sm text-gray-600">{result.input_text}</div>
        {content_html}
    </div>
    """


@router.get("/api/books", response_class=HTMLResponse)
def list_books(db: Session = Depends(get_db)):
    """List all books as HTML table. Returns message if tables missing (run alembic upgrade head)."""
    try:
        result = db.execute(text("""
            SELECT 
                b.id,
                b.subject,
                b.grade,
                b.title,
                b.authors,
                b.is_gdz,
                (SELECT COUNT(*) FROM problems WHERE book_id = b.id) as problem_count,
                (SELECT COUNT(*) FROM problems WHERE book_id = b.id AND answer_text IS NOT NULL) as with_answer,
                (SELECT COUNT(*) FROM pdf_sources WHERE book_id = b.id) as pdf_count
            FROM books b
            ORDER BY b.id
        """))
        rows = list(result)
    except ProgrammingError:
        return "<p class='text-gray-500'>Таблицы не найдены. Выполните: <code>alembic upgrade head</code></p>"
    
    if not rows:
        return "<p class='text-gray-500'>Книги не найдены. Запустите скрипт seed_books.py</p>"
    
    html = """
    <table class="w-full text-sm">
        <thead class="bg-gray-50">
            <tr>
                <th class="px-3 py-2 text-left">ID</th>
                <th class="px-3 py-2 text-left">Предмет</th>
                <th class="px-3 py-2 text-left">Класс</th>
                <th class="px-3 py-2 text-left">Название</th>
                <th class="px-3 py-2 text-right">Задач</th>
                <th class="px-3 py-2 text-right">С ответом</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for row in rows:
        gdz_badge = '<span class="text-xs text-purple-600">ГДЗ</span>' if row.is_gdz else ''
        html += f"""
        <tr class="border-b hover:bg-gray-50">
            <td class="px-3 py-2">{row.id}</td>
            <td class="px-3 py-2">{row.subject}</td>
            <td class="px-3 py-2">{row.grade or '-'}</td>
            <td class="px-3 py-2">{row.title[:50]} {gdz_badge}</td>
            <td class="px-3 py-2 text-right">{row.problem_count}</td>
            <td class="px-3 py-2 text-right">{row.with_answer}</td>
        </tr>
        """
    
    html += "</tbody></table>"
    return html


@router.get("/api/books-options", response_class=HTMLResponse)
def books_options(db: Session = Depends(get_db)):
    """Get books as HTML options for select."""
    try:
        result = db.execute(text("SELECT id, title FROM books ORDER BY id"))
        html = ""
        for row in result:
            html += f'<option value="{row.id}">{row.title[:40]}</option>'
        return html
    except ProgrammingError:
        return ""


@router.get("/api/pdf-sources", response_class=HTMLResponse)
def list_pdf_sources(db: Session = Depends(get_db)):
    """List PDF sources with book title, filename, status, and Start OCR button."""
    try:
        result = db.execute(text("""
            SELECT ps.id, ps.original_filename, ps.minio_key, ps.status, ps.page_count,
                   b.id as book_id, b.title as book_title
            FROM pdf_sources ps
            JOIN books b ON b.id = ps.book_id
            ORDER BY ps.id DESC
        """))
        rows = list(result)
    except ProgrammingError:
        return "<p class='text-gray-500'>Таблицы не найдены. Выполните: <code>alembic upgrade head</code></p>"
    if not rows:
        return "<p class='text-gray-500'>Нет загруженных PDF. Загрузите учебник выше.</p>"
    html = """
    <table class="w-full text-sm">
        <thead class="bg-gray-50">
            <tr>
                <th class="px-3 py-2 text-left">ID</th>
                <th class="px-3 py-2 text-left">Книга</th>
                <th class="px-3 py-2 text-left">Файл</th>
                <th class="px-3 py-2 text-left">Статус</th>
                <th class="px-3 py-2 text-right">Действие</th>
            </tr>
        </thead>
        <tbody>
    """
    for row in rows:
        status_cls = {"pending": "text-yellow-600", "ocr": "text-blue-600", "done": "text-green-600", "failed": "text-red-600"}.get(row.status, "text-gray-600")
        can_start = row.status in ("pending", "failed", "ocr")
        start_ocr_btn = f"""<button type="button" hx-post="/debug/api/start-ocr/{row.id}" hx-target="#start-ocr-result-{row.id}" hx-swap="innerHTML" hx-indicator="#ocr-indicator-{row.id}"
                class="px-3 py-1 bg-amber-500 text-white rounded text-xs hover:bg-amber-600">Начать OCR</button>
                <span id="ocr-indicator-{row.id}" class="htmx-indicator ml-1">...</span>
                <span id="start-ocr-result-{row.id}"></span>""" if can_start else ""
        llm_btn = f"""<button type="button" hx-post="/debug/api/run-llm-normalize/{row.id}" hx-target="#llm-result-{row.id}" hx-swap="innerHTML" hx-indicator="#llm-indicator-{row.id}"
                class="px-3 py-1 bg-violet-500 text-white rounded text-xs hover:bg-violet-600 ml-1">LLM нормализация</button>
                <button type="button" hx-post="/debug/api/cancel-llm-normalize/{row.id}" hx-target="#llm-result-{row.id}" hx-swap="innerHTML"
                class="px-3 py-1 bg-gray-400 text-white rounded text-xs hover:bg-gray-500 ml-1">Отмена</button>
                <span id="llm-indicator-{row.id}" class="htmx-indicator ml-1">...</span>
                <span id="llm-result-{row.id}"></span>
                <span id="llm-progress-{row.id}" hx-get="/debug/api/llm-normalize-progress/{row.id}" hx-trigger="every 5s" hx-swap="innerHTML" class="ml-1"></span>"""
        import_db_btn = f"""<button type="button" hx-post="/debug/api/run-import-db/{row.id}" hx-target="#import-db-result-{row.id}" hx-swap="innerHTML" hx-indicator="#import-db-indicator-{row.id}"
                class="px-3 py-1 bg-emerald-500 text-white rounded text-xs hover:bg-emerald-600 ml-1">Распределение в БД</button>
                <button type="button" hx-post="/debug/api/cancel-import-db/{row.id}" hx-target="#import-db-result-{row.id}" hx-swap="innerHTML"
                class="px-3 py-1 bg-gray-400 text-white rounded text-xs hover:bg-gray-500 ml-1">Остановить</button>
                <span id="import-db-indicator-{row.id}" class="htmx-indicator ml-1">...</span>
                <span id="import-db-result-{row.id}"></span>"""
        btn = (start_ocr_btn + " " + llm_btn + " " + import_db_btn).strip() if (start_ocr_btn or llm_btn or import_db_btn) else "<span class='text-gray-400'>—</span>"
        html += f"""
        <tr class="border-b hover:bg-gray-50">
            <td class="px-3 py-2">{row.id}</td>
            <td class="px-3 py-2">{row.book_title[:40] if row.book_title else '-'}</td>
            <td class="px-3 py-2">{row.original_filename or row.minio_key or '-'}</td>
            <td class="px-3 py-2 {status_cls}">{row.status}</td>
            <td class="px-3 py-2 text-right">{btn}</td>
        </tr>
        """
    html += "</tbody></table>"
    return html


@router.post("/api/upload-pdf", response_class=HTMLResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    subject: Optional[str] = Form(None),
    grade: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Save uploaded PDF to data/pdfs, create Book and PdfSource, return success + refresh pdf-sources list."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return "<p class='text-red-500'>Выберите файл .pdf</p>"
    safe_name = re.sub(r"[^\w\s\-\.]", "_", file.filename)[:200].strip() or "upload.pdf"
    data_dir = Path(settings.data_dir)
    pdfs_dir = data_dir / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    dest = pdfs_dir / safe_name
    try:
        content = await file.read()
        dest.write_bytes(content)
    except Exception as e:
        return f"<p class='text-red-500'>Ошибка записи файла: {e}</p>"
    minio_key = f"pdfs/{safe_name}"
    try:
        meta = classify_from_filename(file.filename)
        if subject:
            meta["subject"] = subject
        if grade:
            meta["grade"] = grade
        if title:
            meta["title"] = title
        existing = db.query(Book).filter(
            Book.subject == meta["subject"],
            Book.grade == meta.get("grade"),
            Book.authors == meta.get("authors"),
            Book.part == meta.get("part"),
        ).first()
        if existing:
            book = existing
        else:
            book = Book(
                subject=meta["subject"],
                grade=meta.get("grade"),
                title=meta["title"],
                authors=meta.get("authors"),
                publisher=meta.get("publisher"),
                part=meta.get("part"),
                is_gdz=meta.get("is_gdz", False),
            )
            db.add(book)
            db.commit()
            db.refresh(book)
        existing_ps = db.query(PdfSource).filter(PdfSource.minio_key == minio_key).first()
        if existing_ps:
            existing_ps.original_filename = file.filename
            existing_ps.file_size_bytes = dest.stat().st_size
            existing_ps.status = "pending"
            existing_ps.error_message = None
            existing_ps.page_count = None
            db.commit()
            db.refresh(existing_ps)
            pdf_source = existing_ps
            msg = f"<p class='text-green-600'>Файл обновлён, источник id={pdf_source.id}. Нажмите «Начать OCR».</p>"
            return HTMLResponse(content=msg, headers={"HX-Trigger": "refreshPdfSources"})
        pdf_source = PdfSource(
            book_id=book.id,
            minio_key=minio_key,
            original_filename=file.filename,
            file_size_bytes=dest.stat().st_size,
            page_count=None,
            status="pending",
        )
        db.add(pdf_source)
        db.commit()
        db.refresh(pdf_source)
    except Exception as e:
        db.rollback()
        err = str(e)
        if "does not exist" in err or "relation" in err.lower():
            return """<p class='text-red-500'>Таблицы БД не созданы. На VPS выполните миграции:</p>
<pre class='mt-2 p-3 bg-gray-100 rounded text-sm'>docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml exec api alembic upgrade head</pre>
<p class='text-gray-600 mt-2'>После этого снова загрузите файл.</p>"""
        return f"<p class='text-red-500'>Ошибка БД: {e}</p>"
    msg = f"<p class='text-green-600'>Загружен: книга id={book.id}, источник PDF id={pdf_source.id}. Ниже нажмите «Начать OCR».</p>"
    return HTMLResponse(content=msg, headers={"HX-Trigger": "refreshPdfSources"})


@router.post("/api/start-ocr/{pdf_source_id}", response_class=HTMLResponse)
def start_ocr(pdf_source_id: int, db: Session = Depends(get_db)):
    """Put PDF ingestion job in queue (OCR → normalization → DB)."""
    try:
        ps = db.query(PdfSource).filter(PdfSource.id == pdf_source_id).first()
        if not ps:
            return "<span class='text-red-500'>Источник не найден</span>"
        job_id = enqueue_ingestion(pdf_source_id)
        return f"<span class='text-green-600'>В очереди (job {job_id[:8]}…)</span>"
    except Exception as e:
        return f"<span class='text-red-500'>{e}</span>"


@router.post("/api/run-llm-normalize/{pdf_source_id}", response_class=HTMLResponse)
def run_llm_normalize(pdf_source_id: int, db: Session = Depends(get_db)):
    """Поставить в очередь только LLM-нормализацию (без перезапуска OCR)."""
    try:
        ps = db.query(PdfSource).filter(PdfSource.id == pdf_source_id).first()
        if not ps:
            return "<span class='text-red-500'>Источник не найден</span>"
        job_id = enqueue_llm_normalize(pdf_source_id)
        return f"<span class='text-green-600'>В очереди (job {job_id[:8]}…)</span>"
    except Exception as e:
        return f"<span class='text-red-500'>{e}</span>"


@router.post("/api/cancel-llm-normalize/{pdf_source_id}", response_class=HTMLResponse)
def cancel_llm_normalize(pdf_source_id: int):
    """Отменить LLM-нормализацию: убрать из очереди или запросить остановку выполняющейся задачи."""
    try:
        from redis import Redis
        from rq import Job
        r = Redis.from_url(settings.redis_url)
        key = f"llm_norm_job_id:{pdf_source_id}"
        job_id = r.get(key)
        if not job_id:
            return "<span class='text-gray-500'>Нет запущенной задачи LLM-нормализации</span>"
        job_id = job_id.decode("utf-8") if isinstance(job_id, bytes) else job_id
        job = Job.fetch(job_id, connection=r)
        status = job.get_status()
        if status == "queued":
            job.cancel()
            r.delete(key)
            return "<span class='text-green-600'>Задача снята с очереди</span>"
        if status == "started":
            r.setex(f"cancel_llm:{pdf_source_id}", 300, "1")
            return "<span class='text-amber-600'>Запрошена остановка (текущий батч доработает)</span>"
        r.delete(key)
        return "<span class='text-gray-500'>Задача уже завершена</span>"
    except Exception as e:
        return f"<span class='text-red-500'>{e}</span>"


@router.post("/api/run-import-db/{pdf_source_id}", response_class=HTMLResponse)
def run_import_db(pdf_source_id: int, db: Session = Depends(get_db)):
    """Поставить в очередь распределение в БД: чтение нормализованного .md → сегментация задач и теория → БД."""
    try:
        ps = db.query(PdfSource).filter(PdfSource.id == pdf_source_id).first()
        if not ps:
            return "<span class='text-red-500'>Источник не найден</span>"
        job_id = enqueue_import_from_normalized(pdf_source_id)
        return f"<span class='text-green-600'>В очереди (job {job_id[:8]}…)</span>"
    except Exception as e:
        return f"<span class='text-red-500'>{e}</span>"


@router.post("/api/cancel-import-db/{pdf_source_id}", response_class=HTMLResponse)
def cancel_import_db(pdf_source_id: int):
    """Остановить распределение по БД: снять с очереди или запросить остановку выполняющейся задачи."""
    try:
        from redis import Redis
        from rq import Job
        r = Redis.from_url(settings.redis_url)
        key = f"import_db_job_id:{pdf_source_id}"
        job_id = r.get(key)
        if not job_id:
            return "<span class='text-gray-500'>Нет запущенной задачи распределения по БД</span>"
        job_id = job_id.decode("utf-8") if isinstance(job_id, bytes) else job_id
        job = Job.fetch(job_id, connection=r)
        status = job.get_status()
        if status == "queued":
            job.cancel()
            r.delete(key)
            return "<span class='text-green-600'>Задача снята с очереди</span>"
        if status == "started":
            r.setex(f"cancel_import_db:{pdf_source_id}", 300, "1")
            return "<span class='text-amber-600'>Запрошена остановка (текущий батч доработает)</span>"
        r.delete(key)
        return "<span class='text-gray-500'>Задача уже завершена</span>"
    except Exception as e:
        return f"<span class='text-red-500'>{e}</span>"


@router.get("/api/llm-normalize-progress/{pdf_source_id}", response_class=HTMLResponse)
def llm_normalize_progress(pdf_source_id: int):
    """Текущий прогресс LLM-нормализации по источнику (из Redis). Для опроса из UI."""
    try:
        from redis import Redis
        r = Redis.from_url(settings.redis_url)
        key = f"llm_norm_progress:{pdf_source_id}"
        val = r.get(key)
        r.close()
        if val:
            s = val.decode("utf-8") if isinstance(val, bytes) else str(val)
            return f"<span class='text-violet-600 text-xs'>LLM: {s}</span>"
    except Exception:
        pass
    return ""


@router.get("/api/problems", response_class=HTMLResponse)
def list_problems(
    book_id: Optional[int] = None,
    problem_type: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """List problems for a book."""
    if not book_id:
        return "<p class='text-gray-500'>Выберите книгу</p>"
    
    query = """
        SELECT 
            p.id,
            p.number,
            p.section,
            p.problem_type,
            LEFT(p.problem_text, 200) as problem_text,
            LEFT(p.answer_text, 100) as answer_text,
            p.solution_text IS NOT NULL as has_solution
        FROM problems p
        WHERE p.book_id = :book_id
    """
    params = {"book_id": book_id, "limit": limit}
    
    if problem_type:
        query += " AND p.problem_type = :ptype"
        params["ptype"] = problem_type
    
    query += " ORDER BY p.section, p.number LIMIT :limit"
    
    result = db.execute(text(query), params)
    rows = list(result)
    
    if not rows:
        return "<p class='text-gray-500'>Задачи не найдены</p>"
    
    html = f"<p class='text-sm text-gray-500 mb-3'>Показано: {len(rows)} задач</p>"
    
    for row in rows:
        type_class = {
            'question': 'border-l-blue-400',
            'exercise': 'border-l-green-400',
            'unknown': 'border-l-gray-300',
        }.get(row.problem_type or 'unknown', 'border-l-gray-300')
        
        answer_badge = ""
        if row.answer_text:
            answer_badge = f'<span class="text-xs bg-green-100 px-1 rounded">✓ ответ</span>'
        elif row.has_solution:
            answer_badge = f'<span class="text-xs bg-blue-100 px-1 rounded">✓ решение</span>'
        
        html += f"""
        <div class="border-l-4 {type_class} pl-3 py-2 mb-2 bg-white rounded-r">
            <div class="flex items-center gap-2">
                <span class="font-semibold">№{row.number or '?'}</span>
                <span class="text-gray-400 text-sm">{row.section or ''}</span>
                {answer_badge}
            </div>
            <div class="text-sm text-gray-700 mt-1">{row.problem_text}...</div>
            {f'<div class="text-xs text-green-700 mt-1">Ответ: {row.answer_text}</div>' if row.answer_text else ''}
        </div>
        """
    
    return html


@router.get("/api/db-preview", response_class=HTMLResponse)
def db_preview(
    book_id: Optional[int] = None,
    content: str = "all",
    problem_type: Optional[str] = None,
    section: Optional[str] = None,
    page: Optional[int] = None,
    with_answer: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Окно отладки по БД: теория и/или задачи по фильтрам."""
    if not book_id:
        return "<p class='text-gray-500'>Выберите книгу</p>"
    parts: list[str] = []
    # Теория по параграфам
    if content in ("all", "theory"):
        q_theory = "SELECT id, section, page_ref, LEFT(theory_text, 500) as theory_text FROM section_theory WHERE book_id = :book_id"
        params: dict = {"book_id": book_id, "limit": limit}
        if section and section.strip():
            params["section_pattern"] = f"%{section.strip()}%" if "%" not in section else section.strip()
            q_theory += " AND section ILIKE :section_pattern"
        q_theory += " ORDER BY section LIMIT :limit"
        try:
            rows = list(db.execute(text(q_theory), params))
        except Exception:
            rows = []
        if rows:
            parts.append("<div class='mb-4'><h3 class='font-semibold text-gray-700 mb-2'>Теория (параграфы)</h3>")
            for r in rows:
                ref = f" <span class='text-gray-400 text-xs'>{r.page_ref or ''}</span>" if r.page_ref else ""
                parts.append(
                    f"<div class='border-l-2 border-amber-400 pl-3 py-2 mb-2 bg-amber-50/50 rounded-r'><span class='font-medium'>{r.section}</span>{ref}<pre class='text-sm text-gray-700 mt-1 whitespace-pre-wrap'>{_h(r.theory_text or '')}...</pre></div>"
                )
            parts.append("</div>")
        elif content == "theory":
            parts.append("<p class='text-gray-500'>Теория не найдена</p>")
    # Задачи
    if content in ("all", "problems"):
        q_prob = """
            SELECT p.id, p.number, p.section, p.problem_type,
                   LEFT(p.problem_text, 300) as problem_text,
                   LEFT(p.answer_text, 150) as answer_text,
                   p.solution_text IS NOT NULL as has_solution,
                   pp.page_num, pp.id as source_page_id
            FROM problems p
            LEFT JOIN pdf_pages pp ON p.source_page_id = pp.id
            WHERE p.book_id = :book_id
        """
        params = {"book_id": book_id, "limit": limit}
        if problem_type:
            q_prob += " AND p.problem_type = :ptype"
            params["ptype"] = problem_type
        if section and section.strip():
            params["section_pattern"] = f"%{section.strip()}%" if "%" not in section else section.strip()
            q_prob += " AND p.section ILIKE :section_pattern"
        if page is not None:
            pnum = page - 1 if page >= 1 else page
            q_prob += " AND pp.page_num = :pnum"
            params["pnum"] = pnum
        if with_answer == "1":
            q_prob += " AND p.answer_text IS NOT NULL"
        q_prob += " ORDER BY p.section, p.number LIMIT :limit"
        try:
            rows = list(db.execute(text(q_prob), params))
        except Exception:
            rows = []
        if rows:
            parts.append("<div><h3 class='font-semibold text-gray-700 mb-2'>Задачи</h3>")
            for r in rows:
                type_cls = {"question": "border-l-blue-400", "exercise": "border-l-green-400"}.get(r.problem_type or "unknown", "border-l-gray-300")
                pg = f" <span class='text-gray-400 text-xs'>стр.{r.page_num + 1 if r.page_num is not None else '?'}</span>" if r.page_num is not None else ""
                page_img = ""
                if getattr(r, "source_page_id", None):
                    page_img = f" <a href='/debug/api/page-image/{r.source_page_id}' target='_blank' class='text-xs text-blue-600'>картинка</a>"
                ans = ""
                if r.answer_text:
                    ans = f"<div class='text-xs text-green-700 mt-1'>Ответ: {_h(r.answer_text)}</div>"
                elif getattr(r, "has_solution", False):
                    ans = "<span class='text-xs bg-blue-100 px-1 rounded'>решение</span>"
                parts.append(
                    f"<div class='border-l-4 {type_cls} pl-3 py-2 mb-2 bg-white rounded-r'><span class='font-semibold'>№{r.number or '?'}</span> <span class='text-gray-500 text-sm'>{r.section or ''}</span>{pg}{page_img}<div class='text-sm text-gray-700 mt-1'>{_h(r.problem_text or '')}...</div>{ans}</div>"
                )
            parts.append("</div>")
        elif content == "problems":
            parts.append("<p class='text-gray-500'>Задачи не найдены</p>")
    if not parts:
        return "<p class='text-gray-500'>Нет данных по выбранным фильтрам</p>"
    return "\n".join(parts)


def _h(s: str) -> str:
    """Escape HTML for preview."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@router.get("/api/page-image/{pdf_page_id}", response_class=FileResponse)
def get_page_image(pdf_page_id: int, db: Session = Depends(get_db)):
    """
    PR9: Вернуть изображение страницы PDF по id pdf_pages.
    Используется в debug: по source_page_id задачи можно получить картинку страницы.
    """
    page = db.query(PdfPage).filter(PdfPage.id == pdf_page_id).first()
    if not page or not page.image_minio_key:
        raise HTTPException(status_code=404, detail="Page or image not found")
    base = Path(os.environ.get("DATA_DIR", "data"))
    path = base / page.image_minio_key.strip()
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(path, media_type="image/png")


@router.get("/api/queries", response_class=HTMLResponse)
def list_recent_queries(limit: int = 10, db: Session = Depends(get_db)):
    """List recent queries."""
    try:
        result = db.execute(text("""
            SELECT 
                q.id,
                LEFT(q.input_text, 100) as input_text,
                q.status,
                q.processing_time_ms,
                q.created_at,
                r.confidence_score
            FROM queries q
            LEFT JOIN responses r ON r.query_id = q.id
            ORDER BY q.created_at DESC
            LIMIT :limit
        """), {"limit": limit})
        rows = list(result)
    except ProgrammingError:
        return "<p class='text-gray-500'>Запросов пока нет</p>"
    
    if not rows:
        return "<p class='text-gray-500'>Запросов пока нет</p>"
    
    html = ""
    for row in rows:
        status_class = {
            'queued': 'bg-yellow-100 text-yellow-800',
            'processing': 'bg-blue-100 text-blue-800',
            'done': 'bg-green-100 text-green-800',
            'failed': 'bg-red-100 text-red-800',
        }.get(row.status, 'bg-gray-100')
        
        html += f"""
        <div class="border-b py-3 hover:bg-gray-50 cursor-pointer"
             hx-get="/debug/api/query/{row.id}" hx-target="#query-result">
            <div class="flex items-center gap-2">
                <span class="font-semibold">#{row.id}</span>
                <span class="px-2 py-0.5 rounded text-xs {status_class}">{row.status}</span>
                <span class="text-xs text-gray-400 ml-auto">
                    {row.processing_time_ms or '?'}ms | conf: {row.confidence_score or '?'}%
                </span>
            </div>
            <div class="text-sm text-gray-600 mt-1">{row.input_text or 'фото'}...</div>
        </div>
        """
    
    return html
