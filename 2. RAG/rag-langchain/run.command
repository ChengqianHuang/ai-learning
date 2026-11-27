#!/bin/sh
set -eu
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "请先用 Python 3.14 创建 .venv 并安装 requirements.txt，步骤见 README.md。" >&2
    exit 1
fi

exec .venv/bin/python -u rag.py "$@"
