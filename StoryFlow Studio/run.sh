#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "StoryFlow Studio: không tìm thấy Python tại $PYTHON_BIN" >&2
    echo "Hãy cài đặt lần đầu bằng các lệnh:" >&2
    echo "  python3 -m venv \"$SCRIPT_DIR/.venv\"" >&2
    echo "  \"$SCRIPT_DIR/.venv/bin/python\" -m pip install -e \"$SCRIPT_DIR\"" >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c "import PySide6, storyflow_studio" >/dev/null 2>&1; then
    echo "StoryFlow Studio: môi trường chưa được cài dependencies." >&2
    echo "Chạy: \"$PYTHON_BIN\" -m pip install -e \"$SCRIPT_DIR\"" >&2
    exit 1
fi

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" -m storyflow_studio "$@"
