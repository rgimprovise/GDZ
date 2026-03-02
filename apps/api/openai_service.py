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
                    reply_text += block.text.value
            break

    tokens = 0
    if run.usage:
        tokens = run.usage.total_tokens

    return reply_text, tokens


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
