#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}!${RESET} $*"; }
die()  { echo -e "${RED}✗${RESET} $*" >&2; exit 1; }

echo ""
echo "=== Simplify — startup ==="
echo ""

# ── 1. git pull ───────────────────────────────────────────────────────────────
echo "→ Pulling latest changes..."
if git pull --ff-only 2>&1 | grep -q "Already up to date"; then
    ok "Already up to date."
else
    ok "Pulled latest changes."
fi

# ── 2. Python 3.11+ ──────────────────────────────────────────────────────────
echo "→ Checking Python..."
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null)
        if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
            PYTHON="$cmd"
            ok "Python $($cmd --version 2>&1 | cut -d' ' -f2) found at $(command -v "$cmd")"
            break
        fi
    fi
done
if [[ -z "$PYTHON" ]]; then
    die "Python 3.11+ is required but was not found. Install it from https://python.org"
fi

# ── 3. uv ─────────────────────────────────────────────────────────────────────
echo "→ Checking uv..."
if ! command -v uv &>/dev/null; then
    warn "uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # add to PATH for this session
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        die "uv install failed. Try manually: https://docs.astral.sh/uv/"
    fi
    ok "uv installed: $(uv --version)"
else
    ok "uv $(uv --version | awk '{print $2}') found."
fi

# ── 4. Ollama ─────────────────────────────────────────────────────────────────
echo "→ Checking Ollama..."
if ! command -v ollama &>/dev/null; then
    warn "Ollama not found. Install it from https://ollama.ai and run 'ollama serve'."
    warn "The tool will still start, but LLM calls will fail until Ollama is running."
else
    ok "Ollama $(ollama --version 2>/dev/null | head -1) found."
    if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
        warn "Ollama is installed but not running. Start it with: ollama serve"
        warn "LLM calls will fail until the server is up."
    else
        ok "Ollama server is reachable."
    fi
fi

# ── 5. Python dependencies via uv ─────────────────────────────────────────────
echo "→ Syncing Python dependencies..."
uv sync --no-install-project --quiet
ok "Dependencies ready."

# ── 6. Launch ────────────────────────────────────────────────────────────────
echo ""
echo "=== Starting Simplify ==="
echo ""

# pass any arguments through (e.g. --auto)
uv run --no-project python main.py "$@"
