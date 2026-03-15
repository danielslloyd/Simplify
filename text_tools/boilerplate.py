"""
boilerplate.py — Detect and strip header/footer boilerplate from raw text.
No external dependencies.
"""

import re

GUTENBERG_START_MARKERS = [
    "*** START OF THE PROJECT GUTENBERG",
    "*** START OF THIS PROJECT GUTENBERG",
]
GUTENBERG_END_MARKERS = [
    "*** END OF THE PROJECT GUTENBERG",
    "*** END OF THIS PROJECT GUTENBERG",
]

BOILERPLATE_KEYWORDS = re.compile(
    r"copyright|rights reserved|published by|isbn|printed in|www\.|http",
    re.IGNORECASE,
)

SENTENCE_END = re.compile(r"[.!?]")


def _detect_gutenberg(lines: list[str]) -> dict:
    """Return header/footer line ranges if Gutenberg markers found."""
    header_end = None
    footer_start = None

    for i, line in enumerate(lines):
        for marker in GUTENBERG_START_MARKERS:
            if marker.lower() in line.lower():
                header_end = i
                break

    for i in range(len(lines) - 1, -1, -1):
        for marker in GUTENBERG_END_MARKERS:
            if marker.lower() in lines[i].lower():
                footer_start = i
                break
        if footer_start is not None:
            break

    result = {"header": None, "footer": None}
    if header_end is not None:
        result["header"] = (0, header_end)
    if footer_start is not None:
        result["footer"] = (footer_start, len(lines) - 1)
    return result


def _detect_heuristic(lines: list[str]) -> dict:
    """General heuristic: scan first/last 100 lines for boilerplate runs."""
    def is_boilerplate_line(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if SENTENCE_END.search(stripped):
            return False
        if BOILERPLATE_KEYWORDS.search(stripped):
            return True
        return False

    def find_run(line_slice, offset=0):
        run_start = None
        run_end = None
        for i, line in enumerate(line_slice):
            if is_boilerplate_line(line):
                if run_start is None:
                    run_start = i + offset
                run_end = i + offset
            elif run_start is not None:
                break
        if run_start is not None and run_end is not None:
            return (run_start, run_end)
        return None

    header = find_run(lines[:100])
    last_100_offset = max(0, len(lines) - 100)
    footer = find_run(lines[last_100_offset:], offset=last_100_offset)

    return {"header": header, "footer": footer}


def detect_boilerplate(raw_text: str) -> dict:
    """
    Detect header/footer boilerplate regions.

    Returns:
        {"header": (start_line, end_line) | None, "footer": (start_line, end_line) | None}
    """
    lines = raw_text.splitlines()

    # Try Gutenberg first
    result = _detect_gutenberg(lines)
    if result["header"] is not None or result["footer"] is not None:
        return result

    # Fall back to general heuristic
    return _detect_heuristic(lines)


def strip_boilerplate(raw_text: str, regions: dict) -> str:
    """
    Strip detected boilerplate regions from raw text.

    Args:
        raw_text: original full text
        regions: dict from detect_boilerplate()

    Returns:
        Cleaned text with boilerplate removed.
    """
    lines = raw_text.splitlines()
    header = regions.get("header")
    footer = regions.get("footer")

    start = 0
    end = len(lines)

    if header is not None:
        start = header[1] + 1

    if footer is not None:
        end = footer[0]

    return "\n".join(lines[start:end])


def run_interactive_boilerplate(raw_text: str) -> str:
    """
    Interactive CLI flow: detect boilerplate, show previews, prompt user to strip.

    Returns:
        Cleaned text (may be same as input if user rejects strips).
    """
    from rich.console import Console
    from rich.rule import Rule

    console = Console()
    lines = raw_text.splitlines()
    regions = detect_boilerplate(raw_text)

    console.print("\n[bold]=== Boilerplate Detection ===[/bold]\n")

    header = regions.get("header")
    footer = regions.get("footer")

    stripped_header = False
    stripped_footer = False

    if header is None and footer is None:
        console.print("[green]No boilerplate detected.[/green]")
        return raw_text

    def show_region(label, start, end):
        console.print(f"\nPossible [bold]{label}[/bold] detected (lines {start + 1}–{end + 1}):")
        console.print("─" * 41)
        for line in lines[start:end + 1]:
            console.print(line)
        console.print("─" * 41)

    confirmed_regions = {"header": None, "footer": None}

    if header is not None:
        show_region("HEADER", header[0], header[1])
        answer = input("Strip this header? (y/n): ").strip().lower()
        if answer == "y":
            confirmed_regions["header"] = header
            stripped_header = True

    if footer is not None:
        show_region("FOOTER", footer[0], footer[1])
        answer = input("Strip this footer? (y/n): ").strip().lower()
        if answer == "y":
            confirmed_regions["footer"] = footer
            stripped_footer = True

    if stripped_header or stripped_footer:
        parts = []
        if stripped_header:
            h = confirmed_regions["header"]
            parts.append(f"header ({h[1] - h[0] + 1} lines)")
        if stripped_footer:
            f = confirmed_regions["footer"]
            parts.append(f"footer ({f[1] - f[0] + 1} lines)")
        console.print(f"\n[green]Stripped {' and '.join(parts)}.[/green]")
        return strip_boilerplate(raw_text, confirmed_regions)

    return raw_text
