"""
Распределение по БД на основе решений LLM (см. docs/LLM_DISTRIBUTION_DESIGN.md).

Препроцессинг: нарезка нормализованного текста на блоки с подсказками (hint).
LLM: классификация блоков и извлечение полей (theory, problem, solution, answer, section, number).
Скрипт: парсинг JSON и запись в БД (с полной перезаписью данных по источнику).
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# Границы блоков для препроцессинга (только разрез, без решения «что это»)
RE_SECTION_HEADER = re.compile(
    r"^\s*[§\$]\s*(\d+(?:\.\d+)?)[.,\s]|^\s*Параграф\s*(\d+)[.,\s]",
    re.IGNORECASE,
)
RE_SOLUTION_START = re.compile(
    r"^\s*Р\s*е\s*ш\s*е\s*н\s*и\s*е\s*\.|^\s*Решение\s*\."
    r"|^\s*О\s*т\s*в\s*е\s*т\s*\.|^\s*Ответ\s*\.",
    re.IGNORECASE,
)
# Начало задачи/упражнения (для границы блока). Не включаем сюда просто "N. " — см. _looks_like_theory_header.
RE_PROBLEM_START = re.compile(
    r"^\s*(?:Контрольное задание|Контрольные задания|Практическое задание)"
    r"\s*(?:№\s*)?(?:\(\s*)?\d+(?:\))?|"
    r"^\s*Задача\s*\(\s*\d+\s*\)|^\s*Задача\s+\d+|"
    r"^\s*Упражнение\s+\d+|^\s*Упражнение\s*\(\s*\d+\s*\)|"
    r"^\s*Вопрос\s*(?:№\s*)?(?:\(\s*)?\d+(?:\))?|"
    r"^\s*Задание\s*\(\s*\d+\s*\)|^\s*Задание\s+\d+|^\s*Задание\s*(?:№\s*)?\d+|"
    r"^\s*[§\$]\s*\d+(?:\.\d+)?|^\s*Параграф\s*\d+|"
    r"^\s*Exercise\s+\d+|^\s*№\s*\d+(?:\.\d+)?|"
    r"^\s*\d+\)\s+",
    re.IGNORECASE,
)
RE_NUMBERED_HEADING = re.compile(r"^\s*(\d+)\s*[\.\)]\s+", re.IGNORECASE)
# Ключевые слова начала формулировки задачи (рус. учебники: матем., геом., физика и т.д.).
# Используется только для эвристики «N. Заголовок» vs «N. Докажите…»; не подменяет решение LLM.
TASK_KEYWORDS = re.compile(
    r"докажите|найдите|упражнение|задача\s*\(|может ли|какая из|объясните",
    re.IGNORECASE,
)


def _looks_like_theory_header(line: str) -> bool:
    """Короткая строка вида 'N. Заголовок' без ключевых слов задачи — подпункт теории."""
    if not line or len(line) > 120:
        return False
    if TASK_KEYWORDS.search(line):
        return False
    return bool(RE_NUMBERED_HEADING.match(line.strip()))
RE_TASK_BLOCK_START = re.compile(
    r"^\s*(?:Задачи|Упражнения|Вопросы\s+к\s+параграфу|Контрольные\s+задания|Практические\s+задания)\s*[.:]?",
    re.IGNORECASE,
)
# Параграф: § N, §N, Параграф N (для разбиения по параграфам)
RE_PARAGRAPH_START = re.compile(
    r"^\s*[§\$]\s*(\d+(?:\.\d+)?)[.,\s]|^\s*Параграф\s*(\d+)[.,\s]",
    re.IGNORECASE,
)
# Запасной вариант при отсутствии § (ошибка OCR): строка вида "1. Заголовок" после пустой
RE_FALLBACK_PARAGRAPH_HEADING = re.compile(
    r"^\s*(\d+)\s*[\.\)]\s+[А-ЯA-Z].{3,120}$",
)

SYSTEM_PROMPT = """Ты — эксперт по разметке учебников. Твоя задача: по блокам текста из учебника (после OCR) определить тип каждого блока и заполнить поля. Главное — анализ контекста и содержания нормализованного текста: структура блока, характерные фразы, связность с соседними блоками. Не опирайся на номер страницы как на признак типа — опирайся на то, что именно написано и как это соотносится с окружающим текстом.

Как различать по контексту и содержанию:
- Оглавление: список заголовков («1. Название», «§ N. Название») без основного текста параграфа — каждая строка короткая, нет определений и доказательств, нет связного изложения. Отмечай как other.
- Титул, выходные данные: характерные фразы (издательство, тираж, ©, «Учебник для …»). Отмечай как other.
- Теоретический материал параграфа: связный текст с определениями, формулировками, доказательствами. Важно: строка вида «N. Заголовок» или «N. ЗАГОЛОВОК» (нумерованный подпункт внутри параграфа) — это подпункт теории, не задача. Отмечай как section_theory или theory; никогда не помещай в type: problem.
- Задачи: только блоки с явным условием задачи — пометка «Задача (N)», «Упражнение N», императив («Докажите», «Найдите», …), вопрос к ученику. Блок, который начинается с «N. Заголовок» и далее идёт связное изложение (определения, свойства, отсылки к рисункам) — это теория, type: theory или section_theory.
- Блок «Решение.» / «Ответ.» и далее текст — решение к предыдущей задаче. type: "solution_only", только solution_text (или answer_text) не null.
- В конце учебника: предметный указатель (список «термин — стр. N»); блок ответов к задачам — перечень номеров и кратких ответов. Блок ответов размечай как type: "answers_block" и заполняй поле "answers": [{"number": "N", "answer_text": "…"}, …]. Предметный указатель — other.

Типы блоков:
- section_theory: заголовок параграфа с началом теории (§ N. Название... или первый содержательный блок теории).
- theory: продолжение теоретического текста (включая пункты «N. Подзаголовок» и связный текст).
- problem: только явные задачи (условие; при необходимости solution_text, answer_text, parts в том же блоке).
- solution_only: блок «Решение.» / «Ответ.» и текст — привязывается к предыдущей задаче.
- answers_block: блок ответов к задачам в конце книги; заполни только "answers": [{"number": "N", "answer_text": "…"}, …]. Остальные поля null.
- other: оглавление, титул, выходные данные, предметный указатель, пустые/неразборчивые блоки.

Формат ответа — только валидный JSON, без комментариев и markdown-обёртки:
{"blocks": [{"block_id": 1, "type": "section_theory"|"theory"|"problem"|"solution_only"|"answers_block"|"other", "section": "§12" или null, "number": "315" или null, "theory_text": "..." или null, "problem_text": "..." или null, "solution_text": "..." или null, "answer_text": "..." или null, "parts": null или [...], "answers": null или [{"number": "315", "answer_text": "…"}, …]}]}

Правила:
- block_id — номер блока из запроса.
- Оглавление vs теория: по структуре и содержанию (список коротких заголовков без связного текста = оглавление).
- number — только для явных задач; не для пунктов параграфа.
- solution_only: только solution_text или answer_text не null.
- answers_block: только "answers" не null; number в каждом элементе — номер задачи для сопоставления с БД.
- Не придумывай текст; неразборчиво — type: "other", остальное null.
- Для каждого блока в запросе указан контекст соседних блоков (предыдущий и следующий). Используй его: блок между двумя теоретическими — скорее всего теория; блок после «Задача (N)» — условие задачи; не помещай теорию в problem_text.
- Критично: нумерованный подзаголовок параграфа («N. Заголовок») без формулировки задания — это теория; type: theory или section_theory, не problem."""

PARAGRAPH_SYSTEM_PROMPT = """Ты — эксперт по разметке учебников. Твоя задача: разбить полный текст одного параграфа на смысловые блоки и для каждого блока указать тип и поля.

Ниже приведён полный текст параграфа (section указан в запросе). Внутри параграфа могут быть: заголовок/начало теории, продолжение теории, задачи («Задача (N)», «Упражнение N» и т.п.), блоки «Решение.» / «Ответ.» (решение к предыдущей задаче), оглавление параграфа, прочее. Разбей текст на блоки по смыслу и для каждого блока верни тип и поля.

Учитывай возможность ошибки OCR: знак параграфа (§) в тексте может отсутствовать или быть искажён. Если в тексте нет явного «§ N», используй для section номер параграфа из запроса или заголовок/нумерацию в самом тексте.

Критично — не путай теорию и задачи:
- Строка вида «N. Заголовок» или «N. ЗАГОЛОВОК» (нумерованный подпункт внутри параграфа) — это подпункт теории. Тип таких блоков: section_theory или theory. Никогда не помещай их в type: problem.
- type: problem — только для блоков с явным условием задачи: пометка «Задача (N)», «Упражнение N», императив (Докажите, Найдите, …), вопрос к ученику. Если блок начинается с «N. Заголовок» и далее идёт связное изложение (определения, отсылки к рисункам, свойства) — это теория, не задача.

Типы блоков: section_theory, theory, problem, solution_only, answers_block, other. Формат ответа — только валидный JSON:
{"blocks": [{"block_id": 1, "type": "...", "section": "§N", "number": "315" или null, "theory_text": "..." или null, "problem_text": "..." или null, "solution_text": "..." или null, "answer_text": "..." или null, "parts": null или [...], "answers": null или [...]}]}

Правила: block_id — порядковый номер блока (1, 2, 3, ...). section — номер параграфа из запроса (например §1). theory_text — для теории, problem_text — только для явных задач. solution_only — блок «Решение.» привязать к предыдущей задаче. Не помещай теоретический текст в problem_text."""


@dataclass
class PreprocessBlock:
    block_id: int
    page_num: int  # 1-based
    hint: str
    text: str


def preprocess_blocks(pages_data: list[tuple[int, str]]) -> list[PreprocessBlock]:
    """
    Режет текст по страницам и по границам (§, Задача, Решение.), выдаёт блоки с hint.
    Не решает «это задача или теория» — только подсказки для LLM.
    """
    blocks: list[PreprocessBlock] = []
    block_id = 0

    for page_num_1based, text in pages_data:
        if not (text or "").strip():
            continue
        lines = (text or "").split("\n")
        current_lines: list[str] = []
        current_hint = "theory"

        def flush() -> None:
            nonlocal block_id
            if not current_lines:
                return
            block_id += 1
            blocks.append(
                PreprocessBlock(
                    block_id=block_id,
                    page_num=page_num_1based,
                    hint=current_hint,
                    text="\n".join(current_lines).strip(),
                )
            )

        for line in lines:
            stripped = line.strip()
            if RE_SECTION_HEADER.search(stripped):
                flush()
                current_lines = [stripped]
                current_hint = "section_header"
                continue
            if RE_TASK_BLOCK_START.search(stripped):
                flush()
                current_lines = [stripped]
                current_hint = "other"
                continue
            if RE_SOLUTION_START.search(stripped):
                flush()
                current_lines = [stripped]
                current_hint = "solution"
                continue
            # "N. Заголовок" без ключевых слов задачи — подпункт теории; "N. Докажите..." и т.п. — задача
            if RE_NUMBERED_HEADING.search(stripped):
                if _looks_like_theory_header(stripped):
                    current_lines.append(line.rstrip() if stripped else line)
                    continue
                flush()
                current_lines = [stripped]
                current_hint = "problem_start"
                continue
            if RE_PROBLEM_START.search(stripped):
                flush()
                current_lines = [stripped]
                current_hint = "problem_start"
                continue
            current_lines.append(line.rstrip() if stripped else line)

        flush()

    return blocks


def merge_short_theory_blocks(blocks: list[PreprocessBlock], max_merge_len: int = 400) -> list[PreprocessBlock]:
    """
    Объединяет подряд идущие короткие блоки теории/параграфа в один, чтобы модель
    получала больший контекст и не резала теорию на мелкие куски.
    """
    if len(blocks) <= 1:
        return blocks
    result: list[PreprocessBlock] = []
    i = 0
    block_id = 0
    while i < len(blocks):
        b = blocks[i]
        if b.hint in ("theory", "section_header") and len(b.text) < max_merge_len and i + 1 < len(blocks):
            next_b = blocks[i + 1]
            if next_b.hint in ("theory", "section_header"):
                # Объединяем с последующими короткими теориями
                combined_text = b.text
                j = i + 1
                while j < len(blocks) and blocks[j].hint in ("theory", "section_header") and len(blocks[j].text) < max_merge_len:
                    combined_text += "\n\n" + blocks[j].text
                    j += 1
                block_id += 1
                result.append(PreprocessBlock(block_id=block_id, page_num=b.page_num, hint=b.hint, text=combined_text.strip()))
                i = j
                continue
        block_id += 1
        result.append(PreprocessBlock(block_id=block_id, page_num=b.page_num, hint=b.hint, text=b.text))
        i += 1
    return result


def split_by_paragraphs(pages_data: list[tuple[int, str]]) -> list[tuple[str, str, int]]:
    """
    Разбивает текст по параграфам (§ N, Параграф N).
    Возвращает список (section_label, paragraph_text, start_page), например ("§1", "текст...", 5).
    Учитывает отсутствие § из-за OCR: запасной вариант — нумерованный заголовок после пустой строки.
    """
    if not pages_data:
        return []
    lines_with_pages: list[tuple[str, int]] = []
    for page_num, text in pages_data:
        for line in (text or "").split("\n"):
            lines_with_pages.append((line, page_num))

    # Первый проход: границы по § N или Параграф N
    paragraphs_primary: list[tuple[str, list[str], int]] = []
    current_section: Optional[str] = None
    current_lines: list[str] = []
    current_start_page: int = pages_data[0][0]

    for line, page_num in lines_with_pages:
        stripped = line.strip()
        m = RE_PARAGRAPH_START.match(stripped) if stripped else None
        if m:
            if current_section is not None and current_lines:
                paragraphs_primary.append((current_section, current_lines[:], current_start_page))
            elif current_section is None and current_lines and "\n".join(current_lines).strip():
                paragraphs_primary.append(("§0", current_lines[:], current_start_page))
            num = (m.group(1) or m.group(2) or "").strip()
            current_section = f"§{num}" if num else "§?"
            current_lines = [line]
            current_start_page = page_num
        else:
            if current_section is None:
                if not current_lines and not stripped:
                    current_start_page = page_num
                current_lines.append(line)
            else:
                current_lines.append(line)

    if current_section is not None and current_lines:
        paragraphs_primary.append((current_section, current_lines[:], current_start_page))

    if paragraphs_primary:
        return [
            (sec, "\n".join(lines).strip(), start_page)
            for sec, lines, start_page in paragraphs_primary
            if "\n".join(lines).strip()
        ]

    # Запасной вариант: § не найден (ошибка OCR). Разбиваем по нумерованному заголовку после пустой строки.
    prev_blank = True
    fallback_paras: list[tuple[str, list[str], int]] = []
    current_num = "1"
    current_lines = []
    current_start_page = pages_data[0][0]

    for line, page_num in lines_with_pages:
        stripped = line.strip()
        if not stripped:
            prev_blank = True
            current_lines.append(line)
            continue
        m = RE_FALLBACK_PARAGRAPH_HEADING.match(stripped)
        if m and prev_blank and current_lines:
            fallback_paras.append((f"§{current_num}", current_lines[:], current_start_page))
            current_num = m.group(1)
            current_lines = [line]
            current_start_page = page_num
        else:
            if not current_lines:
                current_start_page = page_num
            current_lines.append(line)
        prev_blank = False

    if current_lines and "\n".join(current_lines).strip():
        fallback_paras.append((f"§{current_num}", current_lines[:], current_start_page))

    return [
        (sec, "\n".join(lines).strip(), start_page)
        for sec, lines, start_page in fallback_paras
        if "\n".join(lines).strip()
    ]


CONTEXT_SNIPPET_LEN = 450


def build_user_prompt(blocks: list[PreprocessBlock], subject: str) -> str:
    parts = [f"Предмет: {subject}. Ниже блоки текста из учебника. Для каждого блока указан контекст соседних блоков (предыдущий и следующий) — используй его для классификации. Определи тип по содержанию и контексту: структура текста, характерные фразы, что идёт до и после — так отличить оглавление от теории, теорию от задачи, блок ответов от условия. Верни JSON с полями (block_id, type, section, number, theory_text, problem_text, solution_text, answer_text, parts, answers).\n"]
    for idx, b in enumerate(blocks):
        prev_snippet = "—"
        if idx > 0:
            prev_snippet = (blocks[idx - 1].text or "")[-CONTEXT_SNIPPET_LEN:] or "—"
        next_snippet = "—"
        if idx + 1 < len(blocks):
            next_snippet = (blocks[idx + 1].text or "")[:CONTEXT_SNIPPET_LEN] or "—"
        parts.append(f"--- BLOCK {b.block_id} ---\npage: {b.page_num}\nhint: {b.hint}\nконтекст предыдущий блок:\n{prev_snippet}\nконтекст следующий блок:\n{next_snippet}\n\nТЕКСТ БЛОКА:\n{b.text}\n")
    return "\n".join(parts)


def build_paragraph_user_prompt(section_label: str, paragraph_text: str, subject: str) -> str:
    return (
        f"Предмет: {subject}. Параграф: {section_label}.\n\n"
        "Ниже полный текст одного параграфа. Разбей его на смысловые блоки (теория, задачи, решение, ответы и т.д.) и для каждого блока верни тип и поля. "
        f"Если в тексте нет знака параграфа (§) из-за ошибки OCR — используй для section номер из запроса ({section_label}).\n\n"
        f"ТЕКСТ ПАРАГРАФА:\n{paragraph_text}"
    )


def call_llm_paragraph(
    section_label: str, paragraph_text: str, subject: str, start_page: int
) -> list[dict[str, Any]]:
    """Один вызов LLM: один параграф → список блоков. Каждому блоку добавляется _page_num = start_page."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return []
    try:
        from openai import OpenAI
    except ImportError:
        return []
    client = OpenAI(api_key=api_key)
    model = os.environ.get("OPENAI_MODEL_TEXT", "gpt-4o")
    user_content = build_paragraph_user_prompt(section_label, paragraph_text, subject)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": PARAGRAPH_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
    )
    raw = (resp.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    blocks = data.get("blocks") or []
    for b in blocks:
        b["_page_num"] = start_page
    return blocks


def call_llm_batch(blocks: list[PreprocessBlock], subject: str) -> list[dict[str, Any]]:
    """Один вызов OpenAI: батч блоков → JSON с разметкой."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return []
    try:
        from openai import OpenAI
    except ImportError:
        return []

    client = OpenAI(api_key=api_key)
    model = os.environ.get("OPENAI_MODEL_TEXT", "gpt-4o")
    user_content = build_user_prompt(blocks, subject)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
    )
    raw = (resp.choices[0].message.content or "").strip()
    # Убрать markdown-обёртку если есть
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data.get("blocks") or []


class ImportDBCancelRequested(Exception):
    """Запрошена остановка распределения по БД пользователем."""
    pass


# Максимальная длина одного параграфа для режима «по параграфам»; иначе fallback на блоки
MAX_PARAGRAPH_LEN_FOR_PARAGRAPH_MODE = 35000


def distribute_batches(
    pages_data: list[tuple[int, str]],
    subject: str,
    batch_size: int = 18,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> list[dict[str, Any]]:
    """
    Сначала пробуем разбить по параграфам (§ N). Если параграфы есть и не один гигантский —
    скармливаем нейросети по одному параграфу. Иначе fallback: препроцессинг по блокам → батчи → LLM.
    cancel_check: между параграфами/батчами проверяется; если True — raise ImportDBCancelRequested.
    """
    paragraphs = split_by_paragraphs(pages_data)
    use_paragraph_mode = bool(paragraphs) and (
        len(paragraphs) > 1
        or (len(paragraphs) == 1 and len(paragraphs[0][1]) <= MAX_PARAGRAPH_LEN_FOR_PARAGRAPH_MODE)
    )

    if use_paragraph_mode:
        all_parsed: list[dict[str, Any]] = []
        total = len(paragraphs)
        for idx, (section_label, paragraph_text, start_page) in enumerate(paragraphs):
            if cancel_check and cancel_check():
                raise ImportDBCancelRequested()
            parsed = call_llm_paragraph(section_label, paragraph_text, subject, start_page)
            all_parsed.extend(parsed)
            if progress_callback:
                progress_callback(idx + 1, total)
        return all_parsed

    # Fallback: по блокам
    blocks = preprocess_blocks(pages_data)
    if not blocks:
        return []
    blocks = merge_short_theory_blocks(blocks)
    all_parsed = []
    total_batches = (len(blocks) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        if cancel_check and cancel_check():
            raise ImportDBCancelRequested()
        start = batch_idx * batch_size
        batch = blocks[start : start + batch_size]
        parsed = call_llm_batch(batch, subject)
        for p in parsed:
            bid = p.get("block_id")
            if bid is not None and 1 <= bid <= len(batch):
                for b in batch:
                    if b.block_id == bid:
                        p["_page_num"] = b.page_num
                        break
            all_parsed.append(p)
        if progress_callback:
            progress_callback(batch_idx + 1, total_batches)

    return all_parsed
