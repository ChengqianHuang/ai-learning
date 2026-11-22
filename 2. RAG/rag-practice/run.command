#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "找不到虚拟环境：$PYTHON" >&2
  exit 1
fi

exec "$PYTHON" -u "$PROJECT_DIR/pipeline.py" "$@"
