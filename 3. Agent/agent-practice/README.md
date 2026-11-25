# 第三章 Agent 代码实践

三个实验共用只读工具 `search_notes(query, top_k)`，直接搜索仓库第三章的 Markdown 笔记。每条命中都带文件名、所在标题和原文。工具按关键词与中文相邻双字匹配段落，方便换问题、改笔记后立即观察结果。 [工具定义与实现](notes_tool.py)

## 一次跑完

使用 Python 3.10 或以上版本（本项目在 Python 3.14.7 上验证）。从仓库根目录运行下面一行，macOS 也可以双击 `run.command`。

```sh
"./3. Agent/agent-practice/run.command"
```

脚本使用本章的 `.venv`，首次运行会创建虚拟环境并安装 MCP SDK。模型消息默认在本地回放，检索、SQLite 事务和 MCP 子进程均实际执行。每次演示使用独立数据库，终端会打印路径。下面的单项命令在 `3. Agent/agent-practice` 目录运行。

## 实验一 工具调用与纠错

```sh
python3 agent.py --replay-invalid '写入超时后，怎样判断能否重试？'
```

第一轮回放请求 `top_k=6`，超过工具上限 5。Host 给原调用回填带 `is_error=true` 的 `tool_result`。第二轮回放读取错误，改用 `top_k=2` 并生成新调用 ID。第三轮读取实际命中的段落，以 `[S1]`、`[S2]` 引用来源。对照终端中的两组 ID，可以看出修正参数发生在哪一轮、哪个结果属于哪个调用。

从 `run()` 看 Host 怎样保留模型消息、分派工具及回填结果，从 `execute()` 看参数校验和重复查询检查。去掉 `--replay-invalid` 会走两轮成功路径。加上 `--max-turns 1` 可以触发预算耗尽，进程以非零状态退出。 [工具调用循环](agent.py) · [模型消息来源](model_adapter.py)

已在终端配置 `MINIMAX_API_KEY` 时，可以让 MiniMax 决定工具参数和下一步。此模式将问题及命中片段发给模型 API，默认模型为 `MiniMax-M3.1-Flash`，可通过 `MINIMAX_MODEL` 配置。Host 会检查最终引用编号是否出现在本次工具结果中。 [MiniMax 的 Anthropic 兼容接口](https://platform.minimax.cn/docs/api-reference/text-anthropic-api)

```sh
python3 agent.py --live '为什么写操作超时后要先核对远端状态？'
```

## 实验二 状态恢复与跨任务记忆

在同一用户下，让两个任务查同一个问题。第一个任务取得三条证据后暂停，第二个任务在偏好变更后开始。

```sh
python3 state_memory.py start first '跨任务记忆' --pause-after-search
python3 state_memory.py remember --top-k 1
python3 state_memory.py resume first
python3 state_memory.py start second '跨任务记忆'
```

| 观察时点 | SQLite 中的记录 | 可验证的行为 |
|---|---|---|
| `first` 暂停 | `tasks.state='searched'` 和 `tasks.evidence` 在同一事务提交 | 此时退出进程，证据已经落盘 |
| 更新偏好 | `preferences` 中该用户的 `top_k` 变为 1 | 已创建任务保存的参数快照仍为 3 |
| 新进程恢复 `first` | 从检查点读取证据，生成结果并提交 `done` | 输出出现「恢复检查点」。再执行一次 `resume first` 会复用已完成结果 |
| 创建 `second` | 创建时读取该用户当前偏好，写入新任务的参数快照 | 输出显示实际以 `top_k=1` 重新检索 |

手动运行默认写入 `.local/state.sqlite3`。全局选项 `--db 路径` 可以选择独立实验库，`--user 用户名` 可以切换偏好所属用户，均放在子命令前。代码在短时本地检索期间持有 SQLite 写锁，保证并发恢复者读取已提交的检查点。检索事务提交前进程中断时，恢复会重新执行这次只读查询。 [检查点与偏好实现](state_memory.py)

## 实验三 跨进程 MCP 工具调用

完整脚本已准备好本章虚拟环境。单独运行探针时，它会启动一个独立的 Server 子进程。

```sh
.venv/bin/python mcp_probe.py '跨任务记忆' --top-k 1
.venv/bin/python mcp_probe.py '跨任务记忆' --top-k 0
```

看第一条命令输出的三个协议步骤。Client 用 `initialize` 确定协议版本，`tools/list` 读回 Server 实际发布的参数 Schema，再用 `tools/call` 请求检索。`structuredContent.matches` 包含来源、标题和原文。第二条命令故意传入越界参数，服务端返回错误，探针打印 `isError=true` 并以状态码 1 退出。 [Client 实现](mcp_probe.py) · [Server 实现](mcp_server.py)

实验固定官方 Python SDK `mcp==1.27.0`，两端使用 `2025-11-25` 版初始化握手。协议笔记第 4 节也介绍了 `2026-07-28` 版的按请求协商流程。 [实验依赖](requirements-mcp.txt) · [MCP 协议笔记](../笔记/4.%20MCP%20接入与执行机制.md)
