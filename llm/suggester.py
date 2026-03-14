"""
suggester.py — LLM Call 2: generate a simpler replacement for a flagged span.
Caches suggestions keyed by (span, grade_level) for the session.
"""

from .client import query

SUGGEST_PROMPT = """A grade {level} student would find the phrase "{span}" difficult to understand.
Suggest a simpler replacement that preserves the original meaning.
Return only the replacement phrase, nothing else."""

# Session-level cache: (span_lower, grade_level) -> suggestion
_cache: dict[tuple[str, int], str] = {}


def get_suggestion(model: str, span: str, grade_level: int) -> str:
    """
    Get a simpler replacement for span at the given grade level.
    Reuses cached result if available.
    """
    key = (span.lower(), grade_level)
    if key in _cache:
        return _cache[key]

    prompt = SUGGEST_PROMPT.format(level=grade_level, span=span)
    result = query(model, prompt).strip()
    _cache[key] = result
    return result


def clear_cache() -> None:
    """Clear the suggestion cache (useful for testing)."""
    _cache.clear()
