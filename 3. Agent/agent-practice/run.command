#!/bin/sh
set -eu
cd "$(dirname "$0")"

python=python3
if [ -x .venv/bin/python ]; then
    python=.venv/bin/python
fi
"$python" -c 'import sys
if sys.version_info < (3, 10):
    sys.exit(f"第三章实验需要 Python 3.10 或以上版本，当前解释器为 {sys.executable}（{sys.version.split()[0]}）")'
if [ ! -x .venv/bin/python ]; then
    "$python" -m venv .venv
    python=.venv/bin/python
fi
"$python" -m pip --disable-pip-version-check install --quiet -r requirements-mcp.txt

printf '\n1. 工具调用与参数纠错\n'
"$python" agent.py --replay-invalid '写入超时后，怎样判断能否重试？'

printf '\n2. 提交检查点，更新偏好，跨进程恢复\n'
mkdir -p .local
run_dir=$(mktemp -d .local/run.XXXXXX)
database="$run_dir/state.sqlite3"
"$python" state_memory.py --db "$database" start first '跨任务记忆' --pause-after-search
"$python" state_memory.py --db "$database" remember --top-k 1
"$python" state_memory.py --db "$database" resume first
"$python" state_memory.py --db "$database" start second '跨任务记忆'
printf '本次 SQLite 数据库保存在 %s\n' "$database"

printf '\n3. 通过 MCP stdio 发现并调用同一个检索工具\n'
"$python" mcp_probe.py '跨任务记忆' --top-k 1
