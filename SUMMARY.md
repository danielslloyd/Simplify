# Text Simplification Tool — Build Summary

## What This Is

A Python tool that helps users interactively simplify long text files using a local Ollama LLM. It runs a Flask-based browser UI for chunk-by-chunk review, or can run in headless auto mode. The core text processing is a standalone, importable package (`text_tools/`) with no app-layer dependencies.

## How to Run

```bash
# Install dependencies (one-time)
pip install uv
uv init simplify && cd simplify
uv add flask ollama nltk rich

# Run
uv run python main.py        # interactive browser UI (default)
uv run python main.py --auto # auto mode, no UI
```

On startup, the CLI prompts for: input file path, Ollama model name (default: `llama3`), target grade level, output path, and sentences per chunk.

---

## File-by-File Reference

### `main.py`
Entry point. Handles CLI args (`--auto`), gathers user inputs, runs the full pipeline:
1. Read input file
2. Detect/strip boilerplate (`text_tools/boilerplate.py`)
3. Scan structural signals + build split pattern (`text_tools/scanner.py`)
4. Chunk text (`text_tools/chunker.py`)
5. Check for resumable session (`output/writer.py`)
6. Launch Flask UI or run auto mode

### `app.py`
Flask application. Holds server-side session state in a global `_session` dict (initialized by `main.py` via `init_app()`). Implements all API routes (see Routes section below). Handles LLM calls on demand and persists session after every significant action.

### `templates/review.html`
Single-page UI. Pure HTML + vanilla JS — no framework. On load, fetches flags from `/api/flags/<chunk_index>`. Renders:
- **Header bar**: section name, chunk counter, prev/next nav
- **Original text panel**: inline `<mark>` highlights by tier (red/yellow/green)
- **Flags table**: span, tier emoji, suggestion, action buttons per flag
- **Preview panel**: live-updated text as actions are taken
- **Action bar**: "Complete Chunk" (enabled when all flags resolved) + "Auto-complete rest"

Per-flag actions: ✓ approve, ✗ reject (fetches new suggestion), ✏️ edit (inline input), ⏭️ skip, 🚩 flag for later. All actions can be undone (↩).

### `static/style.css`
Responsive stylesheet. Key classes: `.highlight-red/yellow/green` for inline marks, `.action-approved/rejected/edited/skipped/flagged` for done states, `.spinner`/`.spinner-sm` for loading states.

---

## Module: `text_tools/` (standalone, importable)

No dependency on Flask, Ollama, or any app-layer code. Can be copied into other projects.

### `text_tools/boilerplate.py`

Detects and strips header/footer boilerplate before structure scanning.

- **Gutenberg detection**: looks for `*** START/END OF THE PROJECT GUTENBERG` markers
- **General heuristic**: scans first/last 100 lines for runs of lines with no sentence-ending punctuation that are dense with legal/publishing keywords (`copyright`, `isbn`, `www.`, etc.)
- **Interactive CLI**: shows detected regions with line numbers, prompts user to confirm stripping each

Key functions:
```python
detect_boilerplate(raw_text: str) -> dict  # {"header": (start, end)|None, "footer": ...}
strip_boilerplate(raw_text: str, regions: dict) -> str
run_interactive_boilerplate(raw_text: str) -> str  # full CLI flow, returns cleaned text
```

### `text_tools/scanner.py`

Detects three structural signals in text:

| Signal | Logic |
|---|---|
| `repeated_newlines` | regex `\n{3,}` |
| `heading_lines` | lines starting with Chapter/Part/Section/Book/Volume/Epilogue/Prologue/Introduction/Appendix |
| `allcaps_lines` | `line.isupper()`, stripped length 3–80 chars |

Manages a named pattern library in `text_tools/patterns.json`. At startup, shows known patterns with live match counts against the current file, always offering "scan fresh" as an option.

Interactive pattern builder lets users combine signals with OR/AND logic, previews split points, and optionally saves the pattern by name.

Key functions:
```python
scan_signals(text: str) -> dict[str, list[int]]  # signal_id -> list of matching line numbers
run_interactive_pattern_builder(text, signals, patterns_path) -> dict  # returns confirmed pattern
load_patterns(path: str) -> dict
save_pattern(name: str, pattern: dict, path: str) -> None
```

Pattern dict format: `{"logic": "OR"|"AND", "signals": ["heading_lines", ...], "created": "YYYY-MM-DD"}`

### `text_tools/chunker.py`

Splits cleaned text into labeled sections using the confirmed pattern, then tokenizes each section into sentence-based chunks using `nltk.sent_tokenize()`.

- Matched split lines become section labels (stripped). If signal is `repeated_newlines` (no label text), auto-labels as `Section 1`, `Section 2`, etc.
- Warns and confirms with user if split produces only 1 section
- Skips empty/whitespace-only segments silently
- Last chunk in a section may have fewer than N sentences — included as-is

Key function:
```python
chunk_text(text, pattern, sentences_per_chunk=5, signals=None) -> list[dict]
```

Chunk dict:
```python
{
    "section": "Chapter 1",
    "section_index": 0,
    "chunk_index": 2,      # within section
    "global_index": 14,    # across full document
    "total_chunks": 204,
    "original": "Full original text of the chunk."
}
```

---

## Module: `llm/`

### `llm/client.py`
Thin wrapper around `ollama.chat()`. Single function `query(model, prompt) -> str`. Raises `ConnectionError` if Ollama isn't running (with a helpful message), `ValueError` if model not found (suggests `ollama pull <model>`).

### `llm/flagger.py`
LLM Call 1. Sends a chunk + grade level to the LLM; returns a list of flagged spans with tiers (`red`/`yellow`/`green`) and reasons. Parses the JSON array response defensively (finds `[...]` within any surrounding text). Retries once on parse failure; marks chunk `flag_error: True` if both attempts fail.

Flag dict returned: `{"span": ..., "tier": ..., "reason": ..., "suggestion": None, "action": "pending", "final_text": None}`

### `llm/suggester.py`
LLM Call 2. Generates a simpler replacement for a single span at a target grade level. Caches results in a module-level dict keyed by `(span.lower(), grade_level)` — reuses across chunks, skips redundant API calls. Cache can be cleared with `clear_cache()`.

---

## Module: `output/`

### `output/writer.py`

- `save_session(session, output_path)` → writes `<output_path>_session.json`
- `load_session(output_path)` → reads session or returns `None`
- `export(session, output_path)` → writes `<output_path>.json` (full session) + `<output_path>.txt` (plain text, sections joined by `\n\n---\n\n`), prints summary

---

## Flask Routes (`app.py`)

| Route | Method | Description |
|---|---|---|
| `/` | GET | Redirect to first incomplete chunk |
| `/review/<chunk_index>` | GET | Render review page |
| `/api/flags/<chunk_index>` | GET | Return flags + suggestions; triggers LLM if not yet cached |
| `/api/action` | POST | Record flag action `{chunk_index, span, action, final_text}` |
| `/api/complete/<chunk_index>` | POST | Mark chunk complete, persist session |
| `/api/suggest/<chunk_index>/<span>` | POST | Re-request suggestion (clears cache for span first) |
| `/api/export` | POST | Write final JSON + plain text output |
| `/api/auto_complete_rest` | POST | Auto-complete all remaining chunks, export |

---

## Session State

Persisted to `<output_path>_session.json` after every chunk completion. On startup, if a session file exists, the user is prompted to resume.

```json
{
  "meta": { "input_file": "...", "model": "llama3", "grade": 6, "sentences_per_chunk": 5, "total_chunks": 204 },
  "chunks": [
    {
      "global_index": 0,
      "section": "Chapter 1",
      "original": "...",
      "flags": [
        { "span": "melancholy", "tier": "red", "reason": "...", "suggestion": "sadness", "action": "approved", "final_text": "sadness" }
      ],
      "final_text": "...",
      "status": "complete"
    }
  ]
}
```

`action` values: `approved` | `rejected` | `edited` | `skipped` | `flagged` | `pending`

---

## Auto Mode (`--auto`)

When run with `--auto`, skips Flask entirely. For each chunk: flags → suggests for red/yellow spans (auto-approves) → skips green flags. Prints progress line per chunk, saves same JSON + txt output.

---

## Edge Cases Handled

- Zero flags on a chunk → auto-advance in UI; mark complete immediately
- LLM returns malformed JSON → retry once; show error state in UI with manual skip/retry option
- Same span in multiple chunks → suggestion cache reuse, no extra API call
- Ollama not running → `ConnectionError` caught in routes, shown in browser with link to ollama.ai
- Model not found → `ValueError` with `ollama pull <model>` hint
- Output file exists but no session → prompt to overwrite or rename
- `patterns.json` malformed → warns, treats as `{}`
- Boilerplate false positive → user rejects strip confirmation, proceeds with full text
- Split rule yields only 1 section → warn and confirm before continuing
- Empty/whitespace-only chunks → skipped silently, never sent to LLM
