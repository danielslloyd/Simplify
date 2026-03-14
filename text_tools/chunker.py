"""
chunker.py — Split text into labeled sections and sentence-based chunks.
Requires: nltk
"""

import re
import nltk


def _get_split_line_numbers(text: str, signals: dict, pattern: dict) -> list[int]:
    """Resolve split line numbers from a pattern."""
    from .scanner import _get_split_lines, scan_signals
    if not signals:
        signals = scan_signals(text)
    return _get_split_lines(text, signals, pattern)


def chunk_text(
    text: str,
    pattern: dict,
    sentences_per_chunk: int = 5,
    signals: dict = None,
) -> list[dict]:
    """
    Split text into labeled sections and sentence-based chunks.

    Args:
        text: cleaned input text
        pattern: dict with "logic" and "signals" keys
        sentences_per_chunk: how many sentences per chunk
        signals: pre-computed signals dict (optional, will be computed if None)

    Returns:
        List of chunk dicts.
    """
    from .scanner import scan_signals, _get_split_lines

    if signals is None:
        signals = scan_signals(text)

    lines = text.splitlines()
    split_line_numbers = _get_split_lines(text, signals, pattern)

    # Build sections: list of (label, text_content)
    sections = []

    if not split_line_numbers:
        # Single section
        sections.append(("Section 1", text))
    else:
        use_line_as_label = "repeated_newlines" not in pattern.get("signals", [])

        boundaries = split_line_numbers + [len(lines)]
        prev = 0
        section_idx = 0

        for boundary in boundaries:
            chunk_lines = lines[prev:boundary]
            content = "\n".join(chunk_lines).strip()

            if content:
                if use_line_as_label and prev < len(lines):
                    label = lines[prev].strip() if lines[prev].strip() else f"Section {section_idx + 1}"
                else:
                    label = f"Section {section_idx + 1}"
                sections.append((label, content))
                section_idx += 1

            prev = boundary

        # Handle the last section after final boundary
        remaining_lines = lines[boundaries[-1]:] if boundaries else lines
        remaining_content = "\n".join(remaining_lines).strip()
        if remaining_content:
            sections.append((f"Section {section_idx + 1}", remaining_content))

    if len(sections) == 1:
        from rich.console import Console
        console = Console()
        console.print("[yellow]Warning: split rule produced only 1 section.[/yellow]")
        confirm = input("Continue with entire text as one section? (y/n): ").strip().lower()
        if confirm != "y":
            raise SystemExit("Aborted by user.")

    # Build chunks
    chunks = []
    global_index = 0

    # First pass: build all chunks to get total count
    raw_chunks = []
    for section_idx, (section_label, section_text) in enumerate(sections):
        sentences = nltk.sent_tokenize(section_text)
        # Group into chunks of N sentences
        for i in range(0, len(sentences), sentences_per_chunk):
            group = sentences[i:i + sentences_per_chunk]
            chunk_text_str = " ".join(group).strip()
            if not chunk_text_str:
                continue
            raw_chunks.append({
                "section": section_label,
                "section_index": section_idx,
                "chunk_index": i // sentences_per_chunk,
                "original": chunk_text_str,
            })

    total = len(raw_chunks)
    for gi, rc in enumerate(raw_chunks):
        rc["global_index"] = gi
        rc["total_chunks"] = total
        chunks.append(rc)

    return chunks
