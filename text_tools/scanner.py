"""
scanner.py — Detect structural signals in text and build split patterns.
No external dependencies beyond standard library.
"""

import re
import json
import os
from datetime import datetime

SIGNALS = {
    "repeated_newlines": {
        "description": "3+ consecutive newlines",
        "regex": re.compile(r"\n{3,}"),
    },
    "heading_lines": {
        "description": "Keyword headings (Chapter, Part, etc.)",
        "regex": re.compile(
            r"^(Chapter|Part|Section|Book|Volume|Epilogue|Prologue|Introduction|Appendix)[\s\.\:\-]",
            re.IGNORECASE | re.MULTILINE,
        ),
    },
    "allcaps_lines": {
        "description": "ALL CAPS lines (3–80 chars)",
        "check": None,  # handled manually
    },
}


def _is_allcaps(line: str) -> bool:
    stripped = line.strip()
    return stripped.isupper() and 3 <= len(stripped) <= 80


def scan_signals(text: str) -> dict[str, list[int]]:
    """
    Scan text for structural signals.

    Returns:
        {signal_id: [line_numbers_matched]}  (0-indexed line numbers)
    """
    lines = text.splitlines()
    result: dict[str, list[int]] = {k: [] for k in SIGNALS}

    # repeated_newlines — work on full text, map to line numbers
    for match in SIGNALS["repeated_newlines"]["regex"].finditer(text):
        # Find which line number this position falls on
        line_num = text[:match.start()].count("\n")
        result["repeated_newlines"].append(line_num)

    # Remove duplicates (multiple matches at same line)
    result["repeated_newlines"] = sorted(set(result["repeated_newlines"]))

    # heading_lines
    for i, line in enumerate(lines):
        if SIGNALS["heading_lines"]["regex"].match(line):
            result["heading_lines"].append(i)

    # allcaps_lines
    for i, line in enumerate(lines):
        if _is_allcaps(line):
            result["allcaps_lines"].append(i)

    return result


def _get_split_lines(text: str, signals: dict[str, list[int]], pattern: dict) -> list[int]:
    """
    Given a pattern (logic + signals), return sorted list of split line numbers.
    """
    logic = pattern.get("logic", "OR")
    signal_ids = pattern.get("signals", [])

    if not signal_ids:
        return []

    sets = [set(signals.get(sid, [])) for sid in signal_ids]

    if logic == "OR":
        combined = set()
        for s in sets:
            combined |= s
    elif logic == "AND":
        if sets:
            combined = sets[0]
            for s in sets[1:]:
                combined &= s
        else:
            combined = set()
    else:
        combined = set()

    return sorted(combined)


def _sample_lines(lines: list[str], line_numbers: list[int], n: int = 5) -> list[str]:
    samples = []
    for ln in line_numbers[:n]:
        if 0 <= ln < len(lines):
            samples.append(lines[ln].strip())
    return samples


def print_scan_report(text: str, signals: dict[str, list[int]]) -> None:
    """Print a human-readable structure scan report."""
    from rich.console import Console
    console = Console()

    lines = text.splitlines()
    console.print("\n[bold]=== Structure Scanner ===[/bold]\n")

    found_any = False
    for i, (sig_id, line_nums) in enumerate(signals.items(), 1):
        if line_nums:
            found_any = True
            desc = SIGNALS[sig_id]["description"]
            console.print(f"[bold][{i}] {sig_id}:[/bold]  {len(line_nums)} occurrences")
            for sample_ln in line_nums[:2]:
                if 0 <= sample_ln < len(lines):
                    sample = lines[sample_ln].strip()
                    console.print(f'    Sample: "{sample}"')

    if not found_any:
        console.print("[yellow]No structural signals found in this file.[/yellow]")


def load_patterns(path: str) -> dict:
    """Load patterns from JSON file. Returns {} if missing or malformed."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Not a dict")
        return data
    except (json.JSONDecodeError, ValueError) as e:
        from rich.console import Console
        Console().print(f"[yellow]Warning: patterns.json malformed ({e}). Treating as empty.[/yellow]")
        return {}


def save_pattern(name: str, pattern: dict, path: str) -> None:
    """Save a named pattern to patterns.json."""
    patterns = load_patterns(path)
    patterns[name] = pattern
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(patterns, f, indent=2)


def run_interactive_pattern_builder(text: str, signals: dict[str, list[int]], patterns_path: str) -> dict:
    """
    Interactive CLI flow to select or build a split pattern.

    Returns:
        Confirmed pattern dict: {"logic": "OR"|"AND", "signals": [...]}
    """
    from rich.console import Console
    console = Console()

    lines = text.splitlines()
    known_patterns = load_patterns(patterns_path)

    # Show known patterns with match counts
    if known_patterns:
        console.print("\n[bold]Known patterns:[/bold]")
        for idx, (name, pat) in enumerate(known_patterns.items(), 1):
            logic = pat.get("logic", "OR")
            sigs = pat.get("signals", [])
            split_lines = _get_split_lines(text, signals, pat)
            console.print(f"  [{idx}] {name:<20} — {logic}({', '.join(sigs)})   [{len(split_lines)} matches in this file]")
        next_idx = len(known_patterns) + 1
        console.print(f"  [{next_idx}] Scan this file and define a new pattern")
        console.print()
        choice = input("Choose: ").strip()
        try:
            choice_num = int(choice)
            if 1 <= choice_num <= len(known_patterns):
                pat_name = list(known_patterns.keys())[choice_num - 1]
                return known_patterns[pat_name]
        except ValueError:
            pass

    # Print scan report
    print_scan_report(text, signals)

    signal_ids = list(signals.keys())
    active_signals = [sid for sid in signal_ids if signals[sid]]

    if not active_signals:
        console.print("\n[yellow]No signals found. Using entire text as one section.[/yellow]")
        return {"logic": "OR", "signals": []}

    # Show available signals
    console.print("\n[bold]Available signals:[/bold] " + "  ".join(
        f"[{i+1}] {sid}" for i, sid in enumerate(active_signals)
    ))

    while True:
        raw = input('\nEnter signal numbers to combine (e.g. "2", "1 OR 2", "2 AND 3"): ').strip()

        # Parse input like "2", "1 OR 2", "2 AND 3"
        logic = "OR"
        if " AND " in raw.upper():
            logic = "AND"
            parts = re.split(r"\s+AND\s+", raw, flags=re.IGNORECASE)
        elif " OR " in raw.upper():
            parts = re.split(r"\s+OR\s+", raw, flags=re.IGNORECASE)
        else:
            parts = [raw]

        try:
            chosen_signals = []
            for p in parts:
                idx = int(p.strip()) - 1
                chosen_signals.append(active_signals[idx])
        except (ValueError, IndexError):
            console.print("[red]Invalid input. Try again.[/red]")
            continue

        pattern = {"logic": logic, "signals": chosen_signals}
        split_lines = _get_split_lines(text, signals, pattern)
        console.print(f"\n[bold]Preview:[/bold] {len(split_lines)} split points detected.")
        console.print("Samples:")
        for ln in split_lines[:5]:
            console.print(f'  → "{lines[ln].strip()}"')
        if len(split_lines) > 5:
            console.print(f"  (showing 5 of {len(split_lines)})")

        use_it = input("\nUse this rule? (y/n): ").strip().lower()
        if use_it != "y":
            continue

        save_it = input("Save this pattern? (y/n): ").strip().lower()
        if save_it == "y":
            name = input("Pattern name: ").strip()
            pattern["created"] = datetime.now().strftime("%Y-%m-%d")
            save_pattern(name, pattern, patterns_path)
            console.print(f"[green]Saved to {patterns_path}.[/green]")

        return pattern
