#!/usr/bin/env bash
# foamagent.sh — Foam-Agent zero-install MCP launcher for Linux/WSL/macOS
set -euo pipefail

MODE="${1:-mcp}"
PORT="${2:-${FOAMAGENT_PORT:-}}"
HOST="${3:-0.0.0.0}"

# Port resolution: parameter > env var > mode default
if [ -z "$PORT" ]; then
    if [ "$MODE" = "mcp" ]; then PORT=7860; else PORT=5174; fi
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"

# --- Step 1: Create venv if missing ---
if [ ! -f "$PYTHON" ]; then
    echo "[Foam-Agent] Creating virtual environment..."
    uv venv "$VENV_DIR" --python 3.12
    echo "[Foam-Agent] Installing dependencies..."
    uv pip install -e "$SCRIPT_DIR"
    echo "[Foam-Agent] Environment ready."
fi

# --- Step 2: Check API keys ---
if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "[Foam-Agent] WARNING: No OPENAI_API_KEY or ANTHROPIC_API_KEY set. LLM calls will fail." >&2
fi

# --- Step 3: Check OpenFOAM ---
if [ -z "${WM_PROJECT_DIR:-}" ]; then
    echo "[Foam-Agent] WARNING: WM_PROJECT_DIR not set. Source OpenFOAM env first:" >&2
    echo "  source /opt/openfoam10/etc/bashrc" >&2
fi

# --- Step 4: Launch ---
export PYTHONPATH="$SCRIPT_DIR"
echo "[Foam-Agent] Starting $MODE server on ${HOST}:${PORT}..."

case "$MODE" in
    mcp)
        exec "$PYTHON" "$SCRIPT_DIR/src/mcp/cli.py"
        ;;
    ws)
        exec "$PYTHON" "$SCRIPT_DIR/app.py" --mode ws --host "$HOST" --port "$PORT"
        ;;
    health)
        exec "$PYTHON" "$SCRIPT_DIR/app.py" --mode health --host "$HOST" --port "$PORT"
        ;;
    *)
        echo "[Foam-Agent] Unknown mode: $MODE (use mcp, ws, or health)" >&2
        exit 1
        ;;
esac
