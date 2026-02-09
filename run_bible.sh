#!/bin/bash
# Bible Animation Generator - Entry Point
# Usage:
#   ./run_bible.sh "창세기 1-3장"               # Full run (generates script + TTS, then pauses)
#   ./run_bible.sh --script-only "출애굽기 14장"  # Script only
#   ./run_bible.sh --resume <run_id>             # Resume after placing scene videos

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if it exists
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Set Python path
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Run orchestrator
if [ "$1" == "--resume" ] && [ -n "$2" ]; then
    echo "🔄 Resuming run: $2"
    python -m api.production.orchestrator --resume "$2"
elif [ "$1" == "--script-only" ] && [ -n "$2" ]; then
    echo "📝 Script-only mode: $2"
    python -m api.production.orchestrator --script-only "$2"
elif [ -n "$1" ]; then
    echo "🎬 Starting Bible Animation: $1"
    python -m api.production.orchestrator "$@"
else
    echo ""
    echo "📖 Bible Animation Generator"
    echo "─────────────────────────────────────"
    echo ""
    echo "Usage:"
    echo "  ./run_bible.sh \"창세기 1-3장\"               # Full run"
    echo "  ./run_bible.sh --script-only \"출애굽기 14장\"  # Script only"
    echo "  ./run_bible.sh --resume <run_id>             # Resume after adding videos"
    echo ""
fi
