# Text Simplification Tool — Claude Code Spec

## Overview

A Python tool with a Flask-based local browser UI that helps a user interactively simplify long text files using a local Ollama LLM. The core sectioning/chunking system is fully modular and importable by other projects. The simplifier supports two modes:

- **Interactive mode (default):** LLM flags difficult words/phrases with difficulty tiers; user reviews and approves, rejects, edits, skips, or flags each suggestion one chunk at a time.
- **Auto mode (optional flag):** LLM rewrites each chunk automatically without user review.

---

## Setup & Dependencies

This project uses [`uv`](https://github.com/astral-sh/uv) for environment and dependency management.

### One-time: install `uv`

```bash
pip install uv
```

### Project setup

```bash
uv init simplify
cd simplify
uv add flask ollama nltk rich
```

This creates a virtual environment automatically and generates a `uv.lock` file pinning all dependency versions.

### Running the tool

```bash
uv run python main.py
uv run python main.py --auto
```

### `nltk` data

The `punkt` sentence tokenizer must be downloaded once. Add this to `main.py` startup:

```python
import nltk
nltk.download("punkt", quiet=True)
nltk.download("punkt_tab", quiet=True)
```

`quiet=True` skips the download if already present — safe to run on every startup.

### Packages

| Package | Purpose |
|---|---|
| `flask` | Local browser UI |
| `ollama` | Ollama HTTP client |
| `nltk` | Sentence tokenizer (`sent_tokenize`) |
| `rich` | Colored CLI output during setup/scanning |

Standard library only inside `text_tools/`: `json`, `re`, `os`, `sys`, `collections`, `datetime`

---

## File Structure

```
simplify/
├── main.py                  ← entry point, CLI args, launches Flask or auto mode
├── app.py                   ← Flask app, routes, session state
├── templates/
│   └── review.html          ← single-page UI for interactive review
├── static/
│   └── style.css
│
├── text_tools/              ← MODULAR PACKAGE (importable independently)
│   ├── __init__.py
│   ├── scanner.py           ← detects structure signals in raw text
│   ├── boilerplate.py       ← detects/strips header-footer boilerplate
│   ├── chunker.py           ← splits text into labeled sections + chunks
│   └── patterns.json        ← persisted named split patterns
│
├── llm/
│   ├── client.py            ← thin Ollama wrapper
│   ├── flagger.py           ← call 1: flag difficult spans + assign tiers
│   └── suggester.py         ← call 2: generate reword suggestion per flag
│
├── output/
│   └── writer.py            ← writes session JSON + exports plain text
│
└── requirements.txt
```

The `text_tools/` package has **no dependency on Flask, Ollama, or any other app-layer code**. It can be copied into other projects and used standalone.

---

## Invocation

```
python main.py                     # interactive mode (default)
python main.py --auto              # auto-simplify mode, no UI
```

Interactive prompts at startup (CLI, before browser opens):

```
=== Text Simplifier ===
Input file path: ./my_book.txt
Ollama model name [default: llama3]:
Target reading grade level (e.g. 6):
Output file path [default: ./output/my_book_simplified]:
Sentences per chunk [default: 5]:
```

---

## Module: `text_tools/`

### `boilerplate.py`

Detects and optionally strips header/footer boilerplate before structure scanning.

**Gutenberg detection:** look for known marker strings near the top and bottom of the file:
- Start markers: `*** START OF THE PROJECT GUTENBERG`, `*** START OF THIS PROJECT GUTENBERG`
- End markers: `*** END OF THE PROJECT GUTENBERG`, `*** END OF THIS PROJECT GUTENBERG`

**General heuristic (non-Gutenberg):** scan the first and last 100 lines. Flag any run of lines that:
- Contains no sentence-ending punctuation
- Is dense with legal/publishing keywords: `copyright`, `rights reserved`, `published by`, `isbn`, `printed in`, `www.`, `http`

**Interactive confirmation:**

```
=== Boilerplate Detection ===

Possible HEADER detected (lines 1–18):
─────────────────────────────────────────
The Project Gutenberg eBook of Moby Dick
...
─────────────────────────────────────────
Strip this header? (y/n): y

Possible FOOTER detected (lines 14203–14221):
─────────────────────────────────────────
End of the Project Gutenberg EBook of Moby Dick
...
─────────────────────────────────────────
Strip this footer? (y/n): y

Stripped header (18 lines) and footer (19 lines).
```

If no boilerplate is detected, print a one-line confirmation and proceed.

**Public API:**
```python
from text_tools.boilerplate import detect_boilerplate, strip_boilerplate

regions = detect_boilerplate(raw_text: str) -> dict
# returns {"header": (start_line, end_line) | None, "footer": (start_line, end_line) | None}

clean_text = strip_boilerplate(raw_text: str, regions: dict) -> str
```

---

### `scanner.py`

Scans cleaned text for structural signals and manages the named pattern library.

**Signals detected:**

| ID | Signal | Detection Logic |
|---|---|---|
| `repeated_newlines` | 3+ consecutive `\n` | Regex `\n{3,}` |
| `heading_lines` | Keyword headings | `^(Chapter\|Part\|Section\|Book\|Volume\|Epilogue\|Prologue\|Introduction\|Appendix)[\s\.\:\-]` (case-insensitive) |
| `allcaps_lines` | ALL CAPS lines | `line.isupper()`, stripped length 3–80 chars |

**Scan report format:**
```
=== Structure Scanner ===

[1] repeated_newlines:  42 occurrences
    Sample: "...end of paragraph.\n\n\n\nThe next section..."
    Sample: "...final words here.\n\n\n\nCHAPTER TWO..."

[2] heading_lines:  18 occurrences
    Sample: "Chapter 1: The Beginning"
    Sample: "Part II: The Conflict"

[3] allcaps_lines:  5 occurrences
    Sample: "THE RETURN OF THE KING"
```

If zero signals found: inform user, offer single-section fallback, skip pattern selection.

**Pattern library (`text_tools/patterns.json`):**
```json
{
  "gutenberg": {
    "logic": "OR",
    "signals": ["heading_lines", "allcaps_lines"],
    "created": "2025-03-14"
  }
}
```

**Startup flow when `patterns.json` has entries:**
```
Known patterns:
  [1] gutenberg       — OR(heading_lines, allcaps_lines)   [23 matches in this file]
  [2] Scan this file and define a new pattern

Choose:
```

Always show match count against the current file. Always offer "scan fresh" option.

**Interactive pattern builder:**
```
Available signals: [1] repeated_newlines  [2] heading_lines  [3] allcaps_lines

Enter signal numbers to combine (e.g. "2", "1 OR 2", "2 AND 3"): 2 OR 3

Preview: 23 split points detected.
Samples:
  → "Chapter 1: The Beginning"
  → "THE RETURN OF THE KING"
  (showing 5 of 23)

Use this rule? (y/n): y
Save this pattern? (y/n): y
Pattern name: gutenberg
Saved to text_tools/patterns.json.
```

Loops if user rejects the preview.

**Public API:**
```python
from text_tools.scanner import scan_signals, run_interactive_pattern_builder, load_patterns, save_pattern

signals = scan_signals(text: str) -> dict[str, list[int]]
# returns {signal_id: [line_numbers_matched]}

pattern = run_interactive_pattern_builder(text: str, signals: dict) -> dict
# interactive CLI flow, returns confirmed pattern dict

patterns = load_patterns(path: str) -> dict
save_pattern(name: str, pattern: dict, path: str) -> None
```

---

### `chunker.py`

Splits cleaned text into labeled sections and sentence-based chunks.

- Apply confirmed split pattern to identify section boundary line numbers
- Use matched lines as section labels (stripped); if the split signal is `repeated_newlines` (no label text), auto-label as `Section 1`, `Section 2`, etc.
- If split produces only 1 section, warn and confirm with user before continuing
- Within each section: `nltk.sent_tokenize()` → group into chunks of N sentences
- Last chunk in a section may have fewer than N sentences — include as-is
- Skip empty/whitespace-only segments silently

**Chunk data structure:**
```python
{
    "section": "Chapter 1",
    "section_index": 0,
    "chunk_index": 2,       # within section
    "global_index": 14,     # across entire document
    "total_chunks": 204,
    "original": "Full original text of the chunk."
}
```

**Public API:**
```python
from text_tools.chunker import chunk_text

chunks = chunk_text(
    text: str,
    pattern: dict,
    sentences_per_chunk: int = 5
) -> list[dict]
```

---

## Module: `llm/`

### `client.py`

Thin wrapper around `ollama.chat()`.

```python
def query(model: str, prompt: str) -> str
```

Raises descriptive errors for:
- Ollama not running → caught in `main.py` / `app.py` with actionable message
- Model not found → suggest `ollama pull <model>`

---

### `flagger.py` — LLM Call 1

Sends a chunk to the LLM and returns a list of flagged spans with tiers.

**Prompt:**
```
You are a reading level expert. Analyze the following text and identify words or phrases
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
{chunk}
```

- Parse response as JSON
- If parsing fails, retry once; if still fails, mark chunk `flag_error: true`

---

### `suggester.py` — LLM Call 2

Called once per flagged span. Returns a single replacement suggestion.

**Prompt:**
```
A grade {level} student would find the phrase "{span}" difficult to understand.
Suggest a simpler replacement that preserves the original meaning.
Return only the replacement phrase, nothing else.
```

- Cache suggestions keyed by `(span, grade_level)` for the session — reuse across chunks, skip redundant API calls

---

## Flask App: `app.py` + `review.html`

### Session State

Held server-side, persisted to `<output_path>_session.json` after every chunk completion:

```json
{
  "meta": {
    "input_file": "my_book.txt",
    "model": "llama3",
    "grade": 6,
    "sentences_per_chunk": 5,
    "total_chunks": 204
  },
  "chunks": [
    {
      "global_index": 0,
      "section": "Chapter 1",
      "original": "...",
      "flags": [
        {
          "span": "melancholy",
          "tier": "red",
          "reason": "Rare emotional vocabulary",
          "suggestion": "sadness",
          "action": "approved",
          "final_text": "sadness"
        }
      ],
      "final_text": "Full chunk text with accepted edits applied.",
      "status": "complete"
    }
  ]
}
```

`action` values: `approved` | `rejected` | `edited` | `skipped` | `flagged` | `pending`

On startup, if a `_session.json` exists for the output path:
```
Existing session found (47/204 chunks complete). Resume? (y/n):
```

---

### UI Layout (`review.html`)

Single-page app. Layout per chunk:

```
┌──────────────────────────────────────────────────────────────┐
│  [Section: Chapter 3]   Chunk 12 of 204   [◀ Prev] [Next ▶] │
├──────────────────────────────────────────────────────────────┤
│  ORIGINAL TEXT (inline highlights)                           │
│                                                              │
│  "The committee reached a [melancholy] state of              │
│   [capitulation] despite the [perfunctory] review."          │
│    🔴 melancholy    🟡 capitulation    🟢 perfunctory        │
├──────────────────────────────────────────────────────────────┤
│  FLAGGED ITEMS                                               │
│  ┌─────────────┬────────┬─────────────┬───────────────────┐ │
│  │ Span        │ Tier   │ Suggestion  │ Actions           │ │
│  ├─────────────┼────────┼─────────────┼───────────────────┤ │
│  │ melancholy  │ 🔴     │ sadness     │ [✓][✗][✏️][⏭️][🚩] │ │
│  │ capitulat…  │ 🟡     │ surrender   │ [✓][✗][✏️][⏭️][🚩] │ │
│  │ perfunctory │ 🟢     │ quick       │ [✓][✗][✏️][⏭️][🚩] │ │
│  └─────────────┴────────┴─────────────┴───────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│  PREVIEW (live — updates as actions are taken)               │
│  "The committee reached a sadness state of ..."              │
├──────────────────────────────────────────────────────────────┤
│  [Complete Chunk →]              [Auto-complete rest...]     │
└──────────────────────────────────────────────────────────────┘
```

**Per-flag action buttons:**
- ✓ **Approve** — accept suggestion as-is
- ✗ **Reject** — call `/api/suggest` for a new suggestion; replace inline with spinner
- ✏️ **Edit** — open inline text input; user types replacement; confirm with Enter
- ⏭️ **Skip** — leave original unchanged
- 🚩 **Flag** — mark for later review; leave unchanged; recorded in JSON

**"Complete Chunk" button:** enabled only when all flags have a non-`pending` action. Saves session, advances to next chunk.

**"Auto-complete rest" button:** confirm dialog, then switches remaining chunks to auto mode (all red/yellow flags auto-approved, green flags skipped).

**Loading:** spinner per row during LLM calls; UI remains interactive for other rows.

**Chunk with zero flags:** auto-advance with a brief "No flags — chunk complete" notice.

---

### Flask Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Redirect to first incomplete chunk |
| `/review/<int:chunk_index>` | GET | Render chunk review page |
| `/api/flags/<int:chunk_index>` | GET | Return flags + suggestions (triggers LLM if not cached) |
| `/api/action` | POST | Record action for a flag `{chunk_index, span, action, final_text}` |
| `/api/complete/<int:chunk_index>` | POST | Mark chunk complete, persist session |
| `/api/suggest/<int:chunk_index>/<span>` | POST | Re-request suggestion for rejected span |
| `/api/export` | POST | Write final JSON + plain text output files |

---

## Output: `writer.py`

**1. Session JSON** (`<output_path>.json`) — full session state as above.

**2. Plain text** (`<output_path>.txt`) — final edited text only, sections separated by `\n\n---\n\n`.

Console summary on export:
```
Export complete.
  Chunks: 204 total | 189 complete | 12 flagged-for-review | 3 skipped
  Output: ./output/my_book_simplified.json
          ./output/my_book_simplified.txt
```

---

## Auto Mode (`--auto`)

When invoked with `--auto`, skip Flask entirely:
- For each chunk: flag → suggest for all red/yellow spans → auto-approve all
- Green flags: skip (leave unchanged)
- Print progress: `Chunk 12/204 [Chapter 3] — 4 flags auto-applied`
- Save same JSON + txt output format

---

## Edge Cases to Handle

- **Zero flags on a chunk** → mark complete immediately, carry original text forward
- **LLM returns malformed JSON for flags** → retry once; if still fails, show error state in UI with manual skip/retry option
- **Same span in multiple chunks** → reuse cached suggestion `(span, grade)`, skip API call
- **Ollama not running** → catch on first call, show error page in browser with instructions
- **Model not found** → suggest `ollama pull <model>` in error output
- **Output file exists, no session** → prompt to overwrite or rename
- **`patterns.json` malformed** → warn, offer to reset to `{}`
- **Boilerplate detection false positive** → user rejects strip confirmation, proceeds with full text
- **Split rule yields only 1 section** → warn and confirm before continuing
- **Empty/whitespace-only chunks** → skip silently, do not send to LLM
