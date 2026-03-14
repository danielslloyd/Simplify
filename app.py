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

# Global session state (set by main.py before starting Flask)
_session: dict = {}
_config: dict = {}


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
    return redirect(url_for("review", chunk_index=_first_incomplete()))


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
