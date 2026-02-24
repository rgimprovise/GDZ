#!/usr/bin/env python3
"""
PR8: Smoke test for LLM gating — when all pages have quality_scores >= threshold,
correct_normalized_pages returns input unchanged without calling OpenAI.
Run without OPENAI_API_KEY to avoid any API call; gate logic is tested via need_llm_set.
"""
import os
import sys
from pathlib import Path

# Ensure worker is on path
_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_root / "apps" / "worker"))

# Unset key so correct_normalized_pages returns early (no API)
orig_key = os.environ.pop("OPENAI_API_KEY", None)
try:
    from llm_ocr_correct import correct_normalized_pages

    page_texts = ["Страница 1 текст.", "Страница 2 текст."]
    # All scores above threshold -> no pages sent to LLM; result should equal input
    quality_scores = [85.0, 90.0]
    result = correct_normalized_pages(
        page_texts,
        subject="geometry",
        quality_scores=quality_scores,
        llm_gate_threshold=70.0,
    )
    assert result == page_texts, f"Expected unchanged: {result!r}"
    print("OK: LLM gate — all pages above threshold, result unchanged (no API call).")
finally:
    if orig_key is not None:
        os.environ["OPENAI_API_KEY"] = orig_key
