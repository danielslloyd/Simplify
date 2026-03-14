# text_tools: modular text processing package
# No dependency on Flask, Ollama, or any app-layer code.

from .boilerplate import detect_boilerplate, strip_boilerplate
from .scanner import scan_signals, run_interactive_pattern_builder, load_patterns, save_pattern
from .chunker import chunk_text

__all__ = [
    "detect_boilerplate",
    "strip_boilerplate",
    "scan_signals",
    "run_interactive_pattern_builder",
    "load_patterns",
    "save_pattern",
    "chunk_text",
]
