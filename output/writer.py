"""
writer.py — Write session JSON and export plain text output.
"""

import json
import os


def save_session(session: dict, output_path: str) -> None:
    """
    Persist the full session state to <output_path>_session.json.
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    session_file = output_path + "_session.json"
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)


def load_session(output_path: str) -> dict | None:
    """
    Load a persisted session from <output_path>_session.json.
    Returns None if not found.
    """
    session_file = output_path + "_session.json"
    if not os.path.exists(session_file):
        return None
    with open(session_file, "r", encoding="utf-8") as f:
        return json.load(f)


def export(session: dict, output_path: str) -> None:
    """
    Write final JSON + plain text output files and print a summary.

    Files created:
        <output_path>.json  — full session state
        <output_path>.txt   — plain text, sections separated by \\n\\n---\\n\\n
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    # Write JSON
    json_file = output_path + ".json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)

    # Build plain text
    chunks = session.get("chunks", [])
    sections: dict[str, list[str]] = {}
    for chunk in chunks:
        section = chunk.get("section", "")
        text = chunk.get("final_text") or chunk.get("original", "")
        sections.setdefault(section, []).append(text)

    parts = []
    for section_chunks in sections.values():
        parts.append(" ".join(section_chunks))

    plain_text = "\n\n---\n\n".join(parts)
    txt_file = output_path + ".txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(plain_text)

    # Summary
    total = len(chunks)
    complete = sum(1 for c in chunks if c.get("status") == "complete")
    flagged = sum(
        1 for c in chunks
        for flag in c.get("flags", [])
        if flag.get("action") == "flagged"
    )
    skipped = sum(
        1 for c in chunks
        for flag in c.get("flags", [])
        if flag.get("action") == "skipped"
    )

    print("\nExport complete.")
    print(f"  Chunks: {total} total | {complete} complete | {flagged} flagged-for-review | {skipped} skipped")
    print(f"  Output: {json_file}")
    print(f"          {txt_file}")
