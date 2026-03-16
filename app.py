"""
app.py — Flask app, routes, and server-side session state.
"""

import json
import os
import threading
import webbrowser

from flask import Flask, jsonify, redirect, render_template, request, url_for

from llm.flagger import flag_chunk
from llm.suggester import get_suggestion
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

    return jsonify({
        "boilerplate": boilerplate,
        "signals": signals_summary,
        "patterns": patterns_info,
        "existing_session": existing_session,
        "output_path": output_path,
        "filename": filename,
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

    # Optionally save pattern
    if save_pattern_name:
        from text_tools.scanner import save_pattern
        from datetime import datetime
        save_pattern(save_pattern_name, {**pattern, "created": datetime.now().strftime("%Y-%m-%d")}, PATTERNS_PATH)

    # Chunk text
    from text_tools.chunker import chunk_text
    from text_tools.scanner import scan_signals
    signals = scan_signals(clean_text)
    chunks = chunk_text(clean_text, pattern, sentences_per_chunk=sentences_per_chunk, signals=signals)

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
    """Return flags + suggestions for a chunk. Triggers LLM if not yet cached."""
    chunk = _get_chunk(chunk_index)
    if chunk is None:
        return jsonify({"error": "Chunk not found"}), 404

    model = _config["model"]
    grade = _config["grade"]
    output_path = _config["output_path"]

    # If flags not yet fetched, call LLM
    if "flags" not in chunk or chunk.get("flags") is None:
        try:
            flags = flag_chunk(model, chunk["original"], grade)
        except ConnectionError as e:
            return jsonify({"error": str(e), "type": "connection"}), 503
        except ValueError as e:
            return jsonify({"error": str(e), "type": "model"}), 422

        chunk["flags"] = flags
        save_session(_session, output_path)

    flags = chunk.get("flags", [])

    # Check for flag_error
    if flags and flags[0].get("flag_error"):
        return jsonify({"flag_error": True, "flags": []})

    # Fill suggestions for flags that don't have one yet
    for flag in flags:
        if flag.get("suggestion") is None and flag.get("action") == "pending":
            try:
                flag["suggestion"] = get_suggestion(model, flag["span"], grade)
            except Exception:
                flag["suggestion"] = ""

    save_session(_session, output_path)
    return jsonify({"flags": flags})


@app.route("/api/action", methods=["POST"])
def api_action():
    """Record an action for a flag: {chunk_index, span, action, final_text}"""
    data = request.get_json()
    chunk_index = data.get("chunk_index")
    span = data.get("span")
    action = data.get("action")
    final_text = data.get("final_text")

    chunk = _get_chunk(chunk_index)
    if chunk is None:
        return jsonify({"error": "Chunk not found"}), 404

    for flag in chunk.get("flags", []):
        if flag.get("span") == span:
            flag["action"] = action
            flag["final_text"] = final_text
            break

    # Rebuild preview text
    chunk["final_text"] = _apply_flags(chunk)
    save_session(_session, _config["output_path"])
    return jsonify({"ok": True, "preview": chunk["final_text"]})


@app.route("/api/complete/<int:chunk_index>", methods=["POST"])
def api_complete(chunk_index: int):
    """Mark chunk complete and persist session."""
    chunk = _get_chunk(chunk_index)
    if chunk is None:
        return jsonify({"error": "Chunk not found"}), 404

    chunk["status"] = "complete"
    chunk["final_text"] = _apply_flags(chunk)
    save_session(_session, _config["output_path"])

    next_index = chunk_index + 1
    total = _session.get("meta", {}).get("total_chunks", 0)
    if next_index >= total:
        return jsonify({"ok": True, "done": True})
    return jsonify({"ok": True, "done": False, "next": next_index})


@app.route("/api/suggest/<int:chunk_index>/<path:span>", methods=["POST"])
def api_suggest(chunk_index: int, span: str):
    """Re-request suggestion for a rejected span."""
    model = _config["model"]
    grade = _config["grade"]

    # Clear cache for this span to force a new suggestion
    from llm.suggester import _cache
    key = (span.lower(), grade)
    _cache.pop(key, None)

    try:
        suggestion = get_suggestion(model, span, grade)
    except ConnectionError as e:
        return jsonify({"error": str(e)}), 503
    except ValueError as e:
        return jsonify({"error": str(e)}), 422

    # Update in session
    chunk = _get_chunk(chunk_index)
    if chunk:
        for flag in chunk.get("flags", []):
            if flag.get("span") == span:
                flag["suggestion"] = suggestion
                break
        save_session(_session, _config["output_path"])

    return jsonify({"suggestion": suggestion})


@app.route("/api/export", methods=["POST"])
def api_export():
    """Write final JSON + plain text output files."""
    output_path = _config["output_path"]
    export(_session, output_path)
    return jsonify({"ok": True, "output_path": output_path})


@app.route("/api/auto_complete_rest", methods=["POST"])
def api_auto_complete_rest():
    """Auto-complete all remaining chunks (red/yellow auto-approved, green skipped)."""
    model = _config["model"]
    grade = _config["grade"]
    output_path = _config["output_path"]

    for chunk in _session.get("chunks", []):
        if chunk.get("status") == "complete":
            continue
        if "flags" not in chunk or chunk.get("flags") is None:
            try:
                chunk["flags"] = flag_chunk(model, chunk["original"], grade)
            except Exception:
                chunk["flags"] = []

        for flag in chunk.get("flags", []):
            if flag.get("flag_error"):
                continue
            tier = flag.get("tier", "green")
            if tier in ("red", "yellow"):
                if flag.get("suggestion") is None:
                    try:
                        flag["suggestion"] = get_suggestion(model, flag["span"], grade)
                    except Exception:
                        flag["suggestion"] = flag["span"]
                flag["action"] = "approved"
                flag["final_text"] = flag["suggestion"]
            else:
                flag["action"] = "skipped"
                flag["final_text"] = flag["span"]

        chunk["final_text"] = _apply_flags(chunk)
        chunk["status"] = "complete"

    save_session(_session, output_path)
    export(_session, output_path)
    return jsonify({"ok": True})


def _apply_flags(chunk: dict) -> str:
    """Apply approved/edited flag actions to the original text to produce final_text."""
    text = chunk.get("original", "")
    for flag in chunk.get("flags", []):
        if flag.get("flag_error"):
            continue
        action = flag.get("action", "pending")
        span = flag.get("span", "")
        if action in ("approved", "edited") and flag.get("final_text"):
            text = text.replace(span, flag["final_text"], 1)
    return text
