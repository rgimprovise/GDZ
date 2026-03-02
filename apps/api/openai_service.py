"""
OpenAI integration: Assistants API (threads / runs / messages), Whisper, Vision.

All heavy lifting is delegated to the OpenAI platform:
- Vector Store for textbook content retrieval
- Assistant for generating explanations
- Whisper for speech-to-text
- GPT-4o Vision for image-to-text (recognise homework from photos)
"""
from __future__ import annotations

import base64
import logging
import re
import time
from io import BytesIO
from typing import Optional

from openai import OpenAI

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not (settings.openai_api_key or "").strip():
            raise ValueError("OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=settings.openai_api_key.strip())
    return _client


# ── Threads ─────────────────────────────────────────

def create_thread() -> str:
    """Create a new OpenAI thread and return its id."""
    try:
        client = _get_client()
        thread = client.beta.threads.create()
        return thread.id
    except Exception as e:
        logger.exception("OpenAI create_thread failed: %s", e)
        raise


def delete_thread(thread_id: str) -> None:
    client = _get_client()
    try:
        client.beta.threads.delete(thread_id)
    except Exception:
        logger.warning("Failed to delete thread %s", thread_id, exc_info=True)


# ── Messages & Runs ─────────────────────────────────

def send_message_and_run(thread_id: str, user_text: str) -> tuple[str, int]:
    """
    Add a user message to *thread_id*, create a run with the configured
    assistant, poll until complete, and return (assistant_reply, tokens_used).
    """
    client = _get_client()

    client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_text,
    )

    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=settings.openai_assistant_id,
    )

    run = _poll_run(client, thread_id, run.id)

    if run.status != "completed":
        logger.error("Run %s finished with status %s", run.id, run.status)
        return f"[error: run {run.status}]", 0

    messages = client.beta.threads.messages.list(
        thread_id=thread_id, order="desc", limit=1,
    )

    reply_text = ""
    for msg in messages.data:
        if msg.role == "assistant":
            for block in msg.content:
                if block.type == "text":
                    reply_text += _strip_annotations(block.text)
            break

    reply_text = _clean_formatting(reply_text)
    reply_text = _remove_latex_echoes(reply_text)
    reply_text = _remove_plain_echoes(reply_text)
    reply_text = _clean_raw_latex_outside_math(reply_text)
    logger.debug("Post-processed reply (%d chars): %.200s…", len(reply_text), reply_text)

    tokens = 0
    if run.usage:
        tokens = run.usage.total_tokens

    return reply_text, tokens


def _strip_annotations(text_block) -> str:
    """
    Remove file_search citation annotations using their exact indices.
    OpenAI wraps cited content + 【...】 marker into a span defined by
    start_index / end_index.  Cutting by indices removes both the marker
    AND the duplicated character before it.
    """
    value = text_block.value
    annotations = getattr(text_block, "annotations", None)
    if not annotations:
        return value

    for ann in sorted(annotations, key=lambda a: a.start_index, reverse=True):
        start = ann.start_index
        end = ann.end_index
        if 0 <= start < end <= len(value):
            value = value[:start] + value[end:]

    return value


def _clean_formatting(text: str) -> str:
    """Normalize LaTeX delimiters, remove citation markers, trim whitespace."""
    # Remove OpenAI citation markers 【...】
    text = re.sub(r"【[^】]*】", "", text)

    # Convert \( \) → $ $ and \[ \] → $$ $$
    text = text.replace("\\(", "$").replace("\\)", "$")
    text = text.replace("\\[", "$$").replace("\\]", "$$")

    # Fix space right after opening $ or before closing $ (breaks KaTeX)
    text = re.sub(r"\$\s+", "$", text)
    text = re.sub(r"\s+\$", "$", text)

    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)
    return text.strip()


def _latex_to_plain(latex: str) -> str:
    """Approximate how an inline LaTeX expression looks as plain text."""
    s = latex
    s = re.sub(r"\\text\s*\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\s*\{([^}]*)\}\{([^}]*)\}", r"\1/\2", s)
    s = re.sub(r"\\sqrt\s*\{([^}]*)\}", r"√\1", s)
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    s = re.sub(r"[{}_\\^]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _remove_latex_echoes(text: str) -> str:
    """
    Remove plain-text duplicates that follow inline $...$.

    The model often writes  $CD = 6{,}0$CD = 6,0  — the expression in LaTeX
    followed by its plain-text echo.  This strips the echo.
    """
    if "$" not in text:
        return text

    out: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        if text[i] == "$":
            if i + 1 < n and text[i + 1] == "$":
                end = text.find("$$", i + 2)
                if end == -1:
                    out.append(text[i:])
                    break
                out.append(text[i : end + 2])
                i = end + 2
                continue

            close = text.find("$", i + 1)
            if close == -1:
                out.append(text[i:])
                break

            inner = text[i + 1 : close]
            plain = _latex_to_plain(inner)
            after = close + 1

            if (
                plain
                and 1 <= len(plain) <= 60
                and after + len(plain) <= n
                and text[after : after + len(plain)] == plain
                and (after + len(plain) >= n or not text[after + len(plain)].isalnum())
            ):
                out.append(f"${inner}$")
                i = after + len(plain)
            else:
                out.append(text[i : close + 1])
                i = close + 1
        else:
            out.append(text[i])
            i += 1

    return "".join(out)


def _remove_plain_echoes(text: str) -> str:
    """
    Catch plain-text duplications the model produces OUTSIDE of $...$ blocks.

    Patterns like:
        CD = 6,0CD = 6,0 см   →  CD = 6,0 см
        3)CM = 12,3м, м,MD = 5,8$ м:  →  cleaned up
    """
    # Pattern: (LETTERS = DIGITS,DIGITS)(same thing again)
    text = re.sub(
        r"([A-ZА-ЯЁa-zа-яё]{1,5}\s*=\s*[\d]+[,.][\d]+)"
        r"\s*\1",
        r"\1",
        text,
    )
    # Pattern: single/few uppercase letters immediately doubled: MM → M, CDCD → CD
    text = re.sub(r"\b([A-ZА-ЯЁ]{1,4})\1\b", r"\1", text)
    return text


def _clean_raw_latex_outside_math(text: str) -> str:
    """
    Clean up LaTeX syntax that ended up outside of $...$ blocks:
      {,}  →  ,
      \text{ см}  →  см
    """
    parts: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "$":
            if i + 1 < n and text[i + 1] == "$":
                end = text.find("$$", i + 2)
                if end == -1:
                    parts.append(text[i:])
                    break
                parts.append(text[i : end + 2])
                i = end + 2
            else:
                close = text.find("$", i + 1)
                if close == -1:
                    parts.append(text[i:])
                    break
                parts.append(text[i : close + 1])
                i = close + 1
        else:
            parts.append(text[i])
            i += 1

    result: list[str] = []
    for p in parts:
        if p.startswith("$"):
            result.append(p)
        else:
            chunk = p
            chunk = chunk.replace("{,}", ",")
            chunk = re.sub(r"\\text\s*\{([^}]*)\}", r"\1", chunk)
            chunk = re.sub(r"\\[a-zA-Z]+", "", chunk)
            chunk = chunk.replace("{", "").replace("}", "")
            result.append(chunk)
    return "".join(result)


def _poll_run(client: OpenAI, thread_id: str, run_id: str):
    """Poll a run until it reaches a terminal state."""
    terminal = {"completed", "failed", "cancelled", "expired"}
    delay = 0.5
    while True:
        run = client.beta.threads.runs.retrieve(
            thread_id=thread_id, run_id=run_id,
        )
        if run.status in terminal:
            return run
        time.sleep(delay)
        delay = min(delay * 1.5, 4.0)


# ── Whisper (audio → text) ──────────────────────────

def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """Transcribe audio bytes via Whisper API and return text."""
    client = _get_client()
    buf = BytesIO(audio_bytes)
    buf.name = filename
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=buf,
        language="ru",
    )
    return transcript.text


# ── Vision (image → text) ───────────────────────────

VISION_SYSTEM_PROMPT = (
    "Ты распознаёшь учебные задания с фотографий. "
    "Верни ТОЛЬКО текст задания, включая номер, условие и все данные. "
    "Если на фото несколько заданий — перечисли каждое. "
    "Используй LaTeX ($...$) для формул. Ответ на русском языке."
)


def recognise_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """Extract homework text from an image using GPT-4o Vision."""
    client = _get_client()
    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:{mime_type};base64,{b64}"

    response = client.chat.completions.create(
        model=settings.openai_model_vision,
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "high"},
                    },
                ],
            },
        ],
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""
