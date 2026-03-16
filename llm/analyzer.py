"""
analyzer.py — Single LLM call per sentence: grade reading difficulty + suggest simplification.
Replaces the separate flagger + suggester two-call flow.
"""

import json
from .client import query

ANALYZE_PROMPT = """You are a reading level expert helping make text accessible for grade {level} readers.

Analyze the following sentence and respond with ONLY a JSON object — no preamble, no markdown.

Fields:
  "tier":       "red"    = difficult (rare/technical vocabulary or complex structure — needs rewriting)
                "yellow" = moderate  (could be simplified for better accessibility)
                "green"  = fine      (already appropriate for grade {level}, no change needed)
  "reason":     a single short sentence explaining your rating
  "suggestion": if tier is "red" or "yellow" — a plain-language rewrite at grade {level} that
                preserves the full meaning; if tier is "green" — null

Sentence: {sentence}"""


def analyze_sentence(model: str, sentence: str, grade_level: int) -> dict:
    """
    Analyze a single sentence for reading difficulty.

    Returns:
        {
            "tier":       "red" | "yellow" | "green" | "error",
            "reason":     str,
            "suggestion": str | None,
            "prompt":     str,   # exact prompt (for UI preview)
        }
    """
    prompt = ANALYZE_PROMPT.format(level=grade_level, sentence=sentence)

    for _ in range(2):
        raw = query(model, prompt).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            try:
                data = json.loads(raw[start:end + 1])
                if isinstance(data, dict) and "tier" in data:
                    return {
                        "tier": data.get("tier", "green"),
                        "reason": data.get("reason", ""),
                        "suggestion": data.get("suggestion"),
                        "prompt": prompt,
                    }
            except json.JSONDecodeError:
                continue

    return {
        "tier": "error",
        "reason": "Could not parse LLM response.",
        "suggestion": None,
        "prompt": prompt,
    }
