"""
app.py — Flask app, routes, and server-side session state.
"""

import json
import os
import threading
import webbrowser

from flask import Flask, jsonify, redirect, render_template, request, url_for

from output.writer import save_session, export

app = Flask(__name__)

PATTERNS_PATH = os.path.join(os.path.dirname(__file__), "text_tools", "patterns.json")

# Global state
_session: dict = {}
_config: dict = {}
_pending: dict = {}  # Temporary state between /api/setup and /api/start


def init_app(session: dict, config: dict) -> None:
    """Initialize the app with session data and config. Called from main.py."""
    global _session, _config
    _session = session
    _config = config


def _get_chunk(chunk_index: int) -> dict | None:
    chunks = _session.get("chunks", [])
    if 0 <= chunk_index < len(chunks):
        return chunks[chunk_index]
    return None


def _first_incomplete() -> int:
    """Return the index of the first incomplete chunk."""
    for chunk in _session.get("chunks", []):
        if chunk.get("status") != "complete":
            return chunk["global_index"]
    return 0


@app.route("/")
def index():
    if not _session.get("chunks"):
        return redirect(url_for("setup"))
    return redirect(url_for("review", chunk_index=_first_incomplete()))


@app.route("/api/models")
def api_models():
    """Return the list of models installed in Ollama."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        return jsonify({"models": models})
    except Exception:
        return jsonify({"models": []})


@app.route("/setup")
def setup():
    return render_template("setup.html")


@app.route("/api/setup", methods=["POST"])
def api_setup():
    global _pending

    # Accept multipart (file upload) or JSON (file path)
    if request.content_type and "multipart" in request.content_type:
        file = request.files.get("file")
        model = request.form.get("model", "llama3")
        grade_str = request.form.get("grade", "6")
        output_path = request.form.get("output_path", "").strip()
        spc_str = request.form.get("sentences_per_chunk", "5")
        if not file or not file.filename:
            return jsonify({"error": "No file provided."}), 400
        filename = file.filename
        raw_text = file.read().decode("utf-8", errors="replace")
    else:
        data = request.get_json() or {}
        file_path = data.get("file_path", "").strip()
        model = data.get("model", "llama3")
        grade_str = str(data.get("grade", "6"))
        output_path = data.get("output_path", "").strip()
        spc_str = str(data.get("sentences_per_chunk", "5"))
        if not file_path or not os.path.exists(file_path):
            return jsonify({"error": f"File not found: {file_path}"}), 400
        filename = os.path.basename(file_path)
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()

    if not raw_text.strip():
        return jsonify({"error": "File is empty."}), 400

    try:
        grade = int(grade_str)
        sentences_per_chunk = int(spc_str)
    except ValueError:
        return jsonify({"error": "Grade and sentences per chunk must be numbers."}), 400

    if not output_path:
        basename = os.path.splitext(filename)[0]
        output_path = f"./output/{basename}_simplified"

    # Boilerplate detection
    from text_tools.boilerplate import detect_boilerplate
    regions = detect_boilerplate(raw_text)
    lines = raw_text.splitlines()

    boilerplate = {}
    if regions.get("header"):
        h = regions["header"]
        boilerplate["header"] = {"start": h[0], "end": h[1], "preview": lines[h[0]:h[1]+1][:20]}
    if regions.get("footer"):
        ft = regions["footer"]
        boilerplate["footer"] = {"start": ft[0], "end": ft[1], "preview": lines[ft[0]:ft[1]+1][:20]}

    # Signals
    from text_tools.scanner import scan_signals, load_patterns, SIGNALS, _get_split_lines
    signals = scan_signals(raw_text)

    signals_summary = {}
    for sig_id, line_nums in signals.items():
        desc = SIGNALS[sig_id].get("description", sig_id)
        samples = [lines[ln].strip() for ln in line_nums[:2] if 0 <= ln < len(lines)]
        signals_summary[sig_id] = {"count": len(line_nums), "description": desc, "samples": samples}

    # Known patterns with match counts
    patterns_raw = load_patterns(PATTERNS_PATH)
    patterns_info = {}
    for name, pat in patterns_raw.items():
        n = len(_get_split_lines(raw_text, signals, pat))
        patterns_info[name] = {"logic": pat.get("logic", "OR"), "signals": pat.get("signals", []), "match_count": n}

    # Existing session check
    from output.writer import load_session
    existing_session = None
    sess = load_session(output_path)
    if sess:
        completed = sum(1 for c in sess.get("chunks", []) if c.get("status") == "complete")
        total = sess.get("meta", {}).get("total_chunks", 0)
        existing_session = {"completed": completed, "total": total}

    _pending = {
        "raw_text": raw_text,
        "filename": filename,
        "signals": signals,
        "model": model,
        "grade": grade,
        "output_path": output_path,
        "sentences_per_chunk": sentences_per_chunk,
    }

    # Whitespace analysis
    whitespace = {}
    if "\r\n" in raw_text:
        whitespace["crlf"] = raw_text.count("\r\n")
    bare_cr = raw_text.replace("\r\n", "").count("\r")
    if bare_cr:
        whitespace["cr"] = bare_cr
    if "\t" in raw_text:
        whitespace["tabs"] = raw_text.count("\t")
    if "\u00a0" in raw_text:
        whitespace["nbsp"] = raw_text.count("\u00a0")
    zw = sum(raw_text.count(c) for c in "\u200b\u200c\u200d\ufeff")
    if zw:
        whitespace["zero_width"] = zw

    return jsonify({
        "boilerplate": boilerplate,
        "signals": signals_summary,
        "patterns": patterns_info,
        "existing_session": existing_session,
        "output_path": output_path,
        "filename": filename,
        "whitespace": whitespace,
    })


@app.route("/api/pattern_preview", methods=["POST"])
def api_pattern_preview():
    if not _pending.get("raw_text"):
        return jsonify({"error": "No file loaded."}), 400

    data = request.get_json() or {}
    pattern = data.get("pattern", {"logic": "OR", "signals": []})

    from text_tools.scanner import _get_split_lines
    raw_text = _pending["raw_text"]
    signals = _pending["signals"]
    lines = raw_text.splitlines()

    split_lines = _get_split_lines(raw_text, signals, pattern)
    samples = [lines[ln].strip() for ln in split_lines[:5] if 0 <= ln < len(lines)]

    return jsonify({"split_count": len(split_lines), "samples": samples})


@app.route("/api/start", methods=["POST"])
def api_start():
    global _session, _config

    if not _pending.get("raw_text"):
        return jsonify({"error": "No file loaded. Please go back to setup."}), 400

    data = request.get_json() or {}

    model = data.get("model") or _pending.get("model", "llama3")
    grade = int(data.get("grade") or _pending.get("grade", 6))
    output_path = data.get("output_path") or _pending.get("output_path", "./output/simplified")
    sentences_per_chunk = int(data.get("sentences_per_chunk") or _pending.get("sentences_per_chunk", 5))
    strip_header = data.get("strip_header", False)
    strip_footer = data.get("strip_footer", False)
    pattern = data.get("pattern", {"logic": "OR", "signals": []})
    save_pattern_name = (data.get("save_pattern_name") or "").strip()
    resume = data.get("resume", False)

    # Resume existing session
    if resume:
        from output.writer import load_session
        existing = load_session(output_path)
        if existing:
            _session = existing
            _config = {"model": model, "grade": grade, "output_path": output_path}
            return jsonify({"ok": True})

    # Use pre-processed text from chapter editor if available, else process from raw
    if "clean_text" in _pending:
        clean_text = _pending["clean_text"]
        override_splits = _pending.get("current_splits")
    else:
        raw_text = _pending["raw_text"]
        normalizations = data.get("normalizations", [])

        from text_tools.boilerplate import detect_boilerplate, strip_boilerplate
        if strip_header or strip_footer:
            regions = detect_boilerplate(raw_text)
            confirmed = {
                "header": regions.get("header") if strip_header else None,
                "footer": regions.get("footer") if strip_footer else None,
            }
            clean_text = strip_boilerplate(raw_text, confirmed)
        else:
            clean_text = raw_text

        clean_text = _apply_normalizations(clean_text, normalizations)
        override_splits = None

    # Optionally save pattern
    if save_pattern_name:
        from text_tools.scanner import save_pattern
        from datetime import datetime
        save_pattern(save_pattern_name, {**pattern, "created": datetime.now().strftime("%Y-%m-%d")}, PATTERNS_PATH)

    # Chunk text
    from text_tools.chunker import chunk_text
    from text_tools.scanner import scan_signals
    signals = scan_signals(clean_text)
    chunks = chunk_text(clean_text, pattern, signals=signals, override_splits=override_splits)

    if not chunks:
        return jsonify({"error": "No chunks produced from this text."}), 400

    filename = _pending.get("filename", "")
    _session = {
        "meta": {
            "input_file": filename,
            "model": model,
            "grade": grade,
            "sentences_per_chunk": sentences_per_chunk,
            "total_chunks": len(chunks),
        },
        "chunks": [],
    }
    for chunk in chunks:
        chunk["flags"] = None
        chunk["final_text"] = None
        chunk["status"] = "pending"
        _session["chunks"].append(chunk)

    _config = {"model": model, "grade": grade, "output_path": output_path}
    save_session(_session, output_path)

    return jsonify({"ok": True})


@app.route("/review/<int:chunk_index>")
def review(chunk_index: int):
    chunk = _get_chunk(chunk_index)
    if chunk is None:
        return "Chunk not found", 404
    total = _session.get("meta", {}).get("total_chunks", 0)
    return render_template(
        "review.html",
        chunk=chunk,
        chunk_index=chunk_index,
        total=total,
        section=chunk.get("section", ""),
    )


@app.route("/api/flags/<int:chunk_index>")
def api_flags(chunk_index: int):
    """Analyze sentence with LLM if not yet cached; return tier + suggestion + prompt."""
    chunk = _get_chunk(chunk_index)
    if chunk is None:
        return jsonify({"error": "Chunk not found"}), 404

    model = _config["model"]
    grade = _config["grade"]
    output_path = _config["output_path"]

    if chunk.get("tier") is None:
        from llm.analyzer import analyze_sentence
        try:
            result = analyze_sentence(model, chunk["original"], grade)
        except ConnectionError as e:
            return jsonify({"error": str(e), "type": "connection"}), 503
        except ValueError as e:
            return jsonify({"error": str(e), "type": "model"}), 422

        chunk["tier"] = result["tier"]
        chunk["reason"] = result["reason"]
        chunk["suggestion"] = result["suggestion"]
        chunk["prompt"] = result["prompt"]
        chunk["action"] = "pending"
        chunk["final_text"] = None
        save_session(_session, output_path)

    return jsonify({
        "tier": chunk.get("tier"),
        "reason": chunk.get("reason", ""),
        "suggestion": chunk.get("suggestion"),
        "prompt": chunk.get("prompt", ""),
        "action": chunk.get("action", "pending"),
    })


@app.route("/api/action", methods=["POST"])
def api_action():
    """Record sentence-level action: {chunk_index, action, final_text}"""
    data = request.get_json()
    chunk_index = data.get("chunk_index")
    action = data.get("action")       # "approved" | "kept" | "edited"
    final_text = data.get("final_text")

    chunk = _get_chunk(chunk_index)
    if chunk is None:
        return jsonify({"error": "Chunk not found"}), 404

    chunk["action"] = action
    chunk["final_text"] = final_text
    save_session(_session, _config["output_path"])
    return jsonify({"ok": True})


@app.route("/api/complete/<int:chunk_index>", methods=["POST"])
def api_complete(chunk_index: int):
    """Mark sentence complete and persist session."""
    chunk = _get_chunk(chunk_index)
    if chunk is None:
        return jsonify({"error": "Chunk not found"}), 404

    if chunk.get("final_text") is None:
        chunk["final_text"] = chunk.get("original", "")

    chunk["status"] = "complete"
    save_session(_session, _config["output_path"])

    next_index = chunk_index + 1
    total = _session.get("meta", {}).get("total_chunks", 0)
    if next_index >= total:
        return jsonify({"ok": True, "done": True})
    return jsonify({"ok": True, "done": False, "next": next_index})


@app.route("/api/reanalyze/<int:chunk_index>", methods=["POST"])
def api_reanalyze(chunk_index: int):
    """Force a fresh LLM analysis for this sentence."""
    chunk = _get_chunk(chunk_index)
    if chunk is None:
        return jsonify({"error": "Chunk not found"}), 404

    # Clear cached result
    for key in ("tier", "reason", "suggestion", "prompt", "action", "final_text"):
        chunk.pop(key, None)

    return api_flags(chunk_index)


@app.route("/api/export", methods=["POST"])
def api_export():
    """Write final JSON + plain text output files."""
    output_path = _config["output_path"]
    export(_session, output_path)
    return jsonify({"ok": True, "output_path": output_path})


@app.route("/api/auto_complete_rest", methods=["POST"])
def api_auto_complete_rest():
    """Auto-complete all remaining sentences (red/yellow → accept suggestion, green → keep)."""
    from llm.analyzer import analyze_sentence
    model = _config["model"]
    grade = _config["grade"]
    output_path = _config["output_path"]

    for chunk in _session.get("chunks", []):
        if chunk.get("status") == "complete":
            continue
        if chunk.get("tier") is None:
            try:
                result = analyze_sentence(model, chunk["original"], grade)
                chunk.update(result)
            except Exception:
                chunk["tier"] = "green"
                chunk["reason"] = ""
                chunk["suggestion"] = None
                chunk["prompt"] = ""

        tier = chunk.get("tier", "green")
        if tier in ("red", "yellow") and chunk.get("suggestion"):
            chunk["action"] = "approved"
            chunk["final_text"] = chunk["suggestion"]
        else:
            chunk["action"] = "kept"
            chunk["final_text"] = chunk["original"]

        chunk["status"] = "complete"

    save_session(_session, output_path)
    export(_session, output_path)
    return jsonify({"ok": True})


# ── Chapter editor ─────────────────────────────────────────────────────────────

def _chapter_list_from_pending() -> list[dict]:
    """Compute chapter list from _pending state (clean_text + current_splits)."""
    import nltk
    text = _pending.get("clean_text") or _pending.get("raw_text", "")
    splits = _pending.get("current_splits", [])
    lines = text.splitlines()

    boundaries = sorted(set(splits)) + [len(lines)]
    chapters = []
    prev = 0

    for boundary in boundaries:
        chunk_lines = lines[prev:boundary]
        content = "\n".join(chunk_lines).strip()
        if not content:
            prev = boundary
            continue

        title = next((l.strip() for l in chunk_lines if l.strip()), f"Section {len(chapters) + 1}")
        sentences = nltk.sent_tokenize(content)
        preview_start = content[:200]
        preview_end = content[-100:] if len(content) > 300 else ""

        chapters.append({
            "index": len(chapters),
            "title": title,
            "start_line": prev,
            "end_line": boundary - 1,
            "sentence_count": len(sentences),
            "preview_start": preview_start,
            "preview_end": preview_end,
        })
        prev = boundary

    return chapters


def _apply_normalizations(text: str, normalizations: list[str]) -> str:
    if "crlf" in normalizations:
        text = text.replace("\r\n", "\n")
    if "cr" in normalizations:
        text = text.replace("\r", "\n")
    if "tabs" in normalizations:
        text = text.replace("\t", " ")
    if "nbsp" in normalizations:
        text = text.replace("\u00a0", " ")
    if "zero_width" in normalizations:
        for ch in "\u200b\u200c\u200d\ufeff":
            text = text.replace(ch, "")
    return text


@app.route("/api/setup_chapters", methods=["POST"])
def api_setup_chapters():
    """Store setup choices and compute initial chapter splits. Called before /chapters."""
    global _pending
    if not _pending.get("raw_text"):
        return jsonify({"error": "No file loaded."}), 400

    data = request.get_json() or {}
    strip_header = data.get("strip_header", False)
    strip_footer = data.get("strip_footer", False)
    normalizations = data.get("normalizations", [])
    pattern = data.get("pattern", {"logic": "OR", "signals": []})
    model = data.get("model") or _pending.get("model", "llama3")
    grade = int(data.get("grade") or _pending.get("grade", 6))
    output_path = data.get("output_path") or _pending.get("output_path", "./output/simplified")
    spc = int(data.get("sentences_per_chunk") or _pending.get("sentences_per_chunk", 1))

    raw_text = _pending["raw_text"]

    # Strip boilerplate
    from text_tools.boilerplate import detect_boilerplate, strip_boilerplate
    if strip_header or strip_footer:
        regions = detect_boilerplate(raw_text)
        confirmed = {
            "header": regions.get("header") if strip_header else None,
            "footer": regions.get("footer") if strip_footer else None,
        }
        clean_text = strip_boilerplate(raw_text, confirmed)
    else:
        clean_text = raw_text

    clean_text = _apply_normalizations(clean_text, normalizations)

    # Compute initial splits from pattern
    from text_tools.scanner import scan_signals, _get_split_lines
    signals = scan_signals(clean_text)
    splits = _get_split_lines(clean_text, signals, pattern)

    _pending.update({
        "clean_text": clean_text,
        "current_splits": splits,
        "model": model,
        "grade": grade,
        "output_path": output_path,
        "sentences_per_chunk": spc,
        "pattern": pattern,
    })

    return jsonify({"chapters": _chapter_list_from_pending()})


@app.route("/chapters")
def chapters_page():
    if not _pending.get("raw_text"):
        return redirect(url_for("setup"))
    return render_template("chapters.html")


@app.route("/api/chapters")
def api_chapters():
    if not _pending.get("raw_text"):
        return jsonify({"error": "No file loaded."}), 400
    return jsonify({"chapters": _chapter_list_from_pending()})


@app.route("/api/chapters/add", methods=["POST"])
def api_chapters_add():
    data = request.get_json() or {}
    line = data.get("line")
    if line is None:
        return jsonify({"error": "line required"}), 400
    splits = list(_pending.get("current_splits", []))
    if line not in splits:
        splits.append(line)
        splits.sort()
    _pending["current_splits"] = splits
    return jsonify({"chapters": _chapter_list_from_pending()})


@app.route("/api/chapters/remove", methods=["POST"])
def api_chapters_remove():
    data = request.get_json() or {}
    line = data.get("line")
    if line is None:
        return jsonify({"error": "line required"}), 400
    splits = [s for s in _pending.get("current_splits", []) if s != line]
    _pending["current_splits"] = splits
    return jsonify({"chapters": _chapter_list_from_pending()})


@app.route("/api/chapters/search", methods=["POST"])
def api_chapters_search():
    data = request.get_json() or {}
    query_text = (data.get("search") or "").strip().lower()
    if not query_text:
        return jsonify({"error": "search text required"}), 400

    text = _pending.get("clean_text") or _pending.get("raw_text", "")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if query_text in line.lower():
            start = max(0, i - 1)
            context_lines = lines[start:i + 2]
            return jsonify({"line": i, "context": "\n".join(context_lines)})

    return jsonify({"line": None, "context": ""})
