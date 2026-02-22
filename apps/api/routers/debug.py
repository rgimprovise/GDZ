"""
Debug/Admin Router for testing and debugging.

Provides:
- Dashboard with statistics
- Search testing
- Books/Problems viewer
- Query debugger
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query as QueryParam, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, func

from database import get_db
from models import Book, Query, User

router = APIRouter(prefix="/debug", tags=["Debug"])


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
                <select id="book-select" class="px-4 py-2 border rounded-lg"
                        hx-get="/debug/api/problems" hx-target="#problems-list" 
                        hx-trigger="change" hx-include="this">
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
        // Load book options for select
        fetch('/debug/api/books-options')
            .then(r => r.text())
            .then(html => {
                document.getElementById('book-select').innerHTML = '<option value="">Выберите книгу...</option>' + html;
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

@router.get("/api/stats", response_class=HTMLResponse)
def get_stats(db: Session = Depends(get_db)):
    """Get statistics as HTML cards."""
    # Count books
    books_count = db.execute(text("SELECT COUNT(*) FROM books")).scalar() or 0
    
    # Count problems by type
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
    
    # Count pages
    pages_count = db.execute(text("SELECT COUNT(*) FROM pdf_pages")).scalar() or 0
    
    # Count queries
    queries_count = db.execute(text("SELECT COUNT(*) FROM queries")).scalar() or 0
    
    html = f"""
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
    return html


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
    """List all books as HTML table."""
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
    result = db.execute(text("SELECT id, title FROM books ORDER BY id"))
    
    html = ""
    for row in result:
        html += f'<option value="{row.id}">{row.title[:40]}</option>'
    
    return html


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
    
    query += " ORDER BY p.section, p.number::int NULLS LAST LIMIT :limit"
    
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


@router.get("/api/queries", response_class=HTMLResponse)
def list_recent_queries(limit: int = 10, db: Session = Depends(get_db)):
    """List recent queries."""
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
