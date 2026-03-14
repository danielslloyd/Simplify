"""
flagger.py — LLM Call 1: flag difficult spans in a chunk and assign difficulty tiers.
"""

import json
from .client import query

FLAG_PROMPT = """You are a reading level expert. Analyze the following text and identify words or phrases
that would be difficult for a grade {level} student to understand.

For each difficult word or phrase, assign a difficulty tier:
- "red": very difficult — rare, technical, or domain-specific; must be simplified
- "yellow": moderately difficult — complex or uncommon; should be simplified
- "green": mildly difficult — slightly above grade level; consider simplifying

Return ONLY a valid JSON array with no preamble. Each item must have:
  - "span": the exact word or phrase as it appears in the text
  - "tier": "red", "yellow", or "green"
  - "reason": one short sentence explaining why it is difficult

Text:
{chunk}"""


def flag_chunk(model: str, chunk_text: str, grade_level: int) -> list[dict]:
    """
    Flag difficult spans in a chunk.

    Returns:
        List of flag dicts: [{"span": ..., "tier": ..., "reason": ...}]
        Returns [] on persistent failure (chunk marked with flag_error).

    Raises:
        Sets "flag_error": True on the returned list marker instead of raising.
    """
    prompt = FLAG_PROMPT.format(level=grade_level, chunk=chunk_text)

    for attempt in range(2):
        raw = query(model, prompt)
        # Try to extract JSON array from response
        raw = raw.strip()
        # Find first '[' and last ']' in case there's any stray text
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            try:
                flags = json.loads(raw[start:end + 1])
                if isinstance(flags, list):
                    # Validate structure
                    valid = []
                    for item in flags:
                        if isinstance(item, dict) and "span" in item and "tier" in item:
                            valid.append({
                                "span": item["span"],
                                "tier": item.get("tier", "green"),
                                "reason": item.get("reason", ""),
                                "suggestion": None,
                                "action": "pending",
                                "final_text": None,
                            })
                    return valid
            except json.JSONDecodeError:
                continue

    # Both attempts failed
    return [{"flag_error": True}]
