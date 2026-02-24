"""
PR1 — Structured LLM I/O: strict parsing, retries, persist raw on failure (no silent drops).

Single entry point: llm_call(messages, parse_fn, ...) -> parsed object.
- Initial parse; on JSON error try repair_json(raw); then parse again.
- If still failing: write raw to data/llm_audit/... and raise LLMStructuredError.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

# Default audit root
def _audit_base() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "llm_audit"


class LLMStructuredError(Exception):
    """Raised when JSON parse fails after repair; raw response persisted to path."""
    def __init__(self, message: str, raw: str, persisted_path: Optional[Path] = None):
        super().__init__(message)
        self.raw = raw
        self.persisted_path = persisted_path


def repair_json(raw: str) -> str:
    """Try to extract/fix JSON from raw LLM output (markdown fence, truncation)."""
    if not (raw or "").strip():
        return raw or ""
    s = raw.strip()
    # Strip ```json ... ``` or ``` ... ```
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    s = s.strip()
    # If truncated, try to close unclosed brackets
    open_braces = s.count("{") - s.count("}")
    open_brackets = s.count("[") - s.count("]")
    if open_braces > 0 or open_brackets > 0:
        s += "]" * open_brackets + "}" * open_braces
    return s


def _persist_raw(raw: str, audit_dir: Path, audit_key: str) -> Path:
    """Write raw response to audit_dir/audit_key. Creates parent dirs. Returns path."""
    audit_dir = Path(audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / audit_key
    path.write_text(raw, encoding="utf-8")
    return path


def llm_call(
    messages: list[dict[str, Any]],
    parse_fn: Callable[[str], Any],
    *,
    model: Optional[str] = None,
    temperature: float = 0.1,
    audit_dir: Optional[Path] = None,
    audit_key: Optional[str] = None,
    dry_run: bool = False,
) -> Any:
    """
    Call OpenAI chat completion, parse response with parse_fn. No silent drops.

    - parse_fn(raw_str) must return parsed object or raise (e.g. json.JSONDecodeError).
    - Retry: 1) parse_fn(raw), 2) parse_fn(repair_json(raw)), 3) persist raw and raise LLMStructuredError.
    - If audit_dir and audit_key are set, raw is written to audit_dir/audit_key on parse failure.
    - dry_run: if True, do not call API; return None (for testing without key).
    """
    if dry_run:
        return None
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise LLMStructuredError("OPENAI_API_KEY not set", "")
    try:
        from openai import OpenAI
    except ImportError:
        raise LLMStructuredError("openai package not installed", "")

    client = OpenAI(api_key=api_key)
    model = model or os.environ.get("OPENAI_MODEL_TEXT", "gpt-4o")
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    raw = (resp.choices[0].message.content or "").strip()
    if not raw:
        raise LLMStructuredError("Empty LLM response", raw)

    # 1) Initial parse
    try:
        return parse_fn(raw)
    except Exception:
        pass

    # 2) Repair and parse again
    repaired = repair_json(raw)
    if repaired != raw:
        try:
            return parse_fn(repaired)
        except Exception:
            pass

    # 3) Persist and raise
    path = None
    if audit_dir is not None and audit_key is not None:
        path = _persist_raw(raw, Path(audit_dir), audit_key)
    raise LLMStructuredError(
        "LLM response failed JSON parse after repair; raw persisted",
        raw,
        path,
    )


def parse_blocks_response(raw: str) -> list[dict[str, Any]]:
    """Parse raw string as JSON with top-level 'blocks' array. For use as parse_fn."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    blocks = data.get("blocks")
    if blocks is None:
        blocks = []
    if not isinstance(blocks, list):
        raise ValueError("'blocks' must be a list")
    return blocks


def make_audit_key(mode: str) -> str:
    """Timestamped key for audit file: {timestamp}_{mode}.json"""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{mode}.json"


def audit_dir_for_source(book_id: int, pdf_source_id: int) -> Path:
    """data/llm_audit/{book_id}/{pdf_source_id}"""
    return _audit_base() / str(book_id) / str(pdf_source_id)
