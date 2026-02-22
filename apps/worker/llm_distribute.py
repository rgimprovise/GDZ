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
# Начало задачи/упражнения (для границы блока)
RE_PROBLEM_START = re.compile(
    r"^\s*(?:Контрольное задание|Контрольные задания|Практическое задание)"
    r"\s*(?:№\s*)?(?:\(\s*)?\d+(?:\))?|"
    r"^\s*Задача\s*\(\s*\d+\s*\)|^\s*Задача\s+\d+|"
    r"^\s*Упражнение\s+\d+|^\s*Упражнение\s*\(\s*\d+\s*\)|"
    r"^\s*Вопрос\s*(?:№\s*)?(?:\(\s*)?\d+(?:\))?|"
    r"^\s*Задание\s*\(\s*\d+\s*\)|^\s*Задание\s+\d+|^\s*Задание\s*(?:№\s*)?\d+|"
    r"^\s*[§\$]\s*\d+(?:\.\d+)?|^\s*Параграф\s*\d+|"
    r"^\s*Exercise\s+\d+|^\s*№\s*\d+(?:\.\d+)?|"
    r"^\s*\d+\.\s+|^\s*\d+\)\s+",
    re.IGNORECASE,
)
RE_TASK_BLOCK_START = re.compile(
    r"^\s*(?:Задачи|Упражнения|Вопросы\s+к\s+параграфу|Контрольные\s+задания|Практические\s+задания)\s*[.:]?",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """Ты — эксперт по разметке учебников. Твоя задача: по блокам текста из учебника (после OCR) определить тип каждого блока и заполнить поля.

Типы блоков:
- section_theory: заголовок параграфа с началом теории (§ N. Название... или первый блок теории параграфа).
- theory: продолжение теоретического текста параграфа.
- problem: условие задачи/упражнения (и при необходимости решение/ответ в полях solution_text, answer_text). Если в задаче есть подпункты (1), 2), а), б) и т.д.) — заполни массив "parts".
- other: всё остальное (вводные фразы, «Задачи к параграфу», оглавление и т.п.) — можно не включать в ответ или type: "other".

Формат ответа — только валидный JSON, без комментариев и markdown-обёртки:
{"blocks": [{"block_id": 1, "type": "section_theory"|"theory"|"problem"|"other", "section": "§12" или null, "number": "315" или null, "theory_text": "..." или null, "problem_text": "..." или null, "solution_text": "..." или null, "answer_text": "..." или null, "parts": null или [{"part_number": "1", "part_text": "...", "answer_text": null, "solution_text": null}, ...]}]}

Правила:
- block_id — номер блока из запроса (1, 2, 3, ...).
- section — номер параграфа в формате §N (например §12). Для theory и section_theory заполняй. Для problem — если задание из параграфа.
- number — номер задачи (только число или "123.1"). Только для type: "problem".
- theory_text — для type section_theory или theory: текст блока теории (можно подчистить только явный мусор).
- problem_text — условие задачи (общая формулировка или весь текст, если подпунктов нет). solution_text — решение, answer_text — краткий ответ, если есть в блоке.
- parts — только для type "problem": массив подпунктов, если в задаче есть пункты 1), 2), а), б) и т.д. Каждый элемент: part_number ("1", "2", "а", "б"), part_text (текст подпункта), answer_text, solution_text (если есть). Если подпунктов нет — parts: null.
- Если блок не относится к теории и не к задаче — type: "other", остальные поля null.
- Не придумывай текст; если блок пустой или неразборчив, type: "other" и остальное null."""


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
            if RE_PROBLEM_START.search(stripped):
                flush()
                current_lines = [stripped]
                current_hint = "problem_start"
                continue
            current_lines.append(line.rstrip() if stripped else line)

        flush()

    return blocks


def build_user_prompt(blocks: list[PreprocessBlock], subject: str) -> str:
    parts = [f"Предмет: {subject}. Ниже блоки текста из учебника. Для каждого блока верни JSON с полями (block_id, type, section, number, theory_text, problem_text, solution_text, answer_text).\n"]
    for b in blocks:
        parts.append(f"--- BLOCK {b.block_id} ---\npage: {b.page_num}\nhint: {b.hint}\n\n{b.text}\n")
    return "\n".join(parts)


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


def distribute_batches(
    pages_data: list[tuple[int, str]],
    subject: str,
    batch_size: int = 18,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> list[dict[str, Any]]:
    """
    Препроцессинг → батчи → вызовы LLM → объединённый список разметанных блоков.
    progress_callback(batch_index, total_batches) опционально.
    """
    blocks = preprocess_blocks(pages_data)
    if not blocks:
        return []

    all_parsed: list[dict[str, Any]] = []
    total_batches = (len(blocks) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        batch = blocks[start : start + batch_size]
        parsed = call_llm_batch(batch, subject)
        for p in parsed:
            # Привязываем page_num из препроцессинга по block_id
            bid = p.get("block_id")
            if bid is not None and 1 <= bid <= len(blocks):
                # block_id в ответе может совпадать с порядком в батче; у нас block_id глобальный
                for b in batch:
                    if b.block_id == bid:
                        p["_page_num"] = b.page_num
                        break
            all_parsed.append(p)
        if progress_callback:
            progress_callback(batch_idx + 1, total_batches)

    return all_parsed
