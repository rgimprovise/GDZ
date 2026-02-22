"""
Shared utility functions.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."
