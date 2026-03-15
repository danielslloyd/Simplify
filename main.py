"""
main.py — Entry point. CLI prompts, setup, and launches Flask or auto mode.
"""

import argparse
import os
import sys
import threading
import webbrowser

import nltk
from rich.console import Console

nltk.download("punkt", quiet=True)
nltk.download("punkt_tab", quiet=True)

console = Console()

PATTERNS_PATH = os.path.join(os.path.dirname(__file__), "text_tools", "patterns.json")


def prompt_input(msg: str, default: str = "") -> str:
    if default:
        val = input(f"{msg} [default: {default}]: ").strip()
        return val if val else default
    return input(f"{msg}: ").strip()


def build_session_meta(input_file, model, grade, sentences_per_chunk, output_path, total_chunks) -> dict:
    return {
        "meta": {
            "input_file": input_file,
            "model": model,
            "grade": grade,
            "sentences_per_chunk": sentences_per_chunk,
            "total_chunks": total_chunks,
        },
        "chunks": [],
    }


def run_auto(chunks: list[dict], model: str, grade: int, output_path: str) -> None:
    """Auto mode: flag + suggest + auto-approve for each chunk, no UI."""
    from llm.flagger import flag_chunk
    from llm.suggester import get_suggestion
    from output.writer import save_session, export

    session = {
        "meta": {
            "model": model,
            "grade": grade,
            "total_chunks": len(chunks),
        },
        "chunks": [],
    }

    for chunk in chunks:
        gi = chunk["global_index"]
        total = chunk["total_chunks"]
        section = chunk.get("section", "")

        try:
            flags = flag_chunk(model, chunk["original"], grade)
        except ConnectionError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

        auto_applied = 0
        for flag in flags:
            if flag.get("flag_error"):
                continue
            tier = flag.get("tier", "green")
            if tier in ("red", "yellow"):
                try:
                    flag["suggestion"] = get_suggestion(model, flag["span"], grade)
                except Exception:
                    flag["suggestion"] = flag["span"]
                flag["action"] = "approved"
                flag["final_text"] = flag["suggestion"]
                auto_applied += 1
            else:
                flag["action"] = "skipped"
                flag["final_text"] = flag["span"]

        # Build final text
        text = chunk["original"]
        for flag in flags:
            if flag.get("flag_error"):
                continue
            if flag.get("action") in ("approved", "edited") and flag.get("final_text"):
                text = text.replace(flag["span"], flag["final_text"], 1)

        chunk["flags"] = flags
        chunk["final_text"] = text
        chunk["status"] = "complete"
        session["chunks"].append(chunk)

        console.print(f"Chunk {gi + 1}/{total} [{section}] — {auto_applied} flags auto-applied")
        save_session(session, output_path)

    from output.writer import export as do_export
    do_export(session, output_path)


def run_interactive(chunks: list[dict], model: str, grade: int, output_path: str, session: dict) -> None:
    """Interactive mode: launch Flask and open browser."""
    import app as flask_app

    # Initialize session chunks if new session
    if not session.get("chunks"):
        for chunk in chunks:
            chunk["flags"] = None
            chunk["final_text"] = None
            chunk["status"] = "pending"
            session["chunks"].append(chunk)

    flask_app.init_app(session, {
        "model": model,
        "grade": grade,
        "output_path": output_path,
    })

    # Open browser after a short delay
    def open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open("http://127.0.0.1:5000")

    threading.Thread(target=open_browser, daemon=True).start()

    console.print("\n[bold green]Starting browser UI at http://127.0.0.1:5000[/bold green]")
    console.print("Press Ctrl+C to stop.\n")

    flask_app.app.run(host="127.0.0.1", port=5000, debug=False)


def main():
    parser = argparse.ArgumentParser(description="Text Simplifier")
    parser.add_argument("--auto", action="store_true", help="Auto-simplify mode, no UI")
    args = parser.parse_args()

    console.print("\n[bold]=== Text Simplifier ===[/bold]")

    # ── Gather inputs ──────────────────────────────────────────────────────────
    input_file = prompt_input("Input file path")
    if not os.path.exists(input_file):
        console.print(f"[red]File not found: {input_file}[/red]")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8", errors="replace") as f:
        raw_text = f.read()

    model = prompt_input("Ollama model name", default="llama3")

    grade_str = prompt_input("Target reading grade level (e.g. 6)")
    try:
        grade = int(grade_str)
    except ValueError:
        console.print("[red]Invalid grade level.[/red]")
        sys.exit(1)

    default_output = os.path.join(
        "./output",
        os.path.splitext(os.path.basename(input_file))[0] + "_simplified",
    )
    output_path = prompt_input("Output file path", default=default_output)

    # Check for existing output (no session) → prompt overwrite
    if os.path.exists(output_path + ".txt") and not os.path.exists(output_path + "_session.json"):
        answer = input(f"Output file '{output_path}.txt' already exists. Overwrite? (y/n): ").strip().lower()
        if answer != "y":
            new_name = prompt_input("Enter new output path")
            output_path = new_name

    spc_str = prompt_input("Sentences per chunk", default="5")
    try:
        sentences_per_chunk = int(spc_str)
    except ValueError:
        sentences_per_chunk = 5

    # ── Boilerplate detection ──────────────────────────────────────────────────
    from text_tools.boilerplate import run_interactive_boilerplate
    clean_text = run_interactive_boilerplate(raw_text)

    # ── Scan + pattern selection ───────────────────────────────────────────────
    from text_tools.scanner import scan_signals, run_interactive_pattern_builder
    signals = scan_signals(clean_text)
    pattern = run_interactive_pattern_builder(clean_text, signals, PATTERNS_PATH)

    # ── Chunk text ─────────────────────────────────────────────────────────────
    from text_tools.chunker import chunk_text
    chunks = chunk_text(clean_text, pattern, sentences_per_chunk=sentences_per_chunk, signals=signals)

    if not chunks:
        console.print("[red]No chunks produced. Exiting.[/red]")
        sys.exit(1)

    console.print(f"\n[green]Text split into {len(chunks)} chunks.[/green]")

    # ── Check for existing session ─────────────────────────────────────────────
    from output.writer import load_session, save_session
    existing_session = load_session(output_path)
    session = None

    if existing_session:
        completed = sum(1 for c in existing_session.get("chunks", []) if c.get("status") == "complete")
        total = existing_session.get("meta", {}).get("total_chunks", len(chunks))
        answer = input(f"\nExisting session found ({completed}/{total} chunks complete). Resume? (y/n): ").strip().lower()
        if answer == "y":
            session = existing_session
        else:
            session = None

    if session is None:
        session = build_session_meta(input_file, model, grade, sentences_per_chunk, output_path, len(chunks))
        save_session(session, output_path)

    # ── Run ────────────────────────────────────────────────────────────────────
    if args.auto:
        run_auto(chunks, model, grade, output_path)
    else:
        run_interactive(chunks, model, grade, output_path, session)


if __name__ == "__main__":
    main()
