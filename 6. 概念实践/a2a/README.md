# A2A 最小实践

A2A 是 Agent2Agent 协议的简称，让独立部署的 agent 互相派活。能力用 Agent Card 声明在固定路径，任务用 Task 表示并带 ID 和状态，结果用 Artifact 交，传输走 JSON-RPC over HTTP。协议和背景见[笔记](../笔记/A2A.md)。

这里三个文件跑一条完整链路：服务端发布能力，客户端从零发现它、派任务、收事件，中断后凭 `task_id` 接着走。服务端 184 行，客户端 86 行，裸协议探测 80 行。环境是 A2A 规范 v1.0.1、`a2a-sdk` 1.3.1、Python 3.14.7。

## 运行

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 终端 1
.venv/bin/python server.py

# 终端 2
.venv/bin/python client.py "统计这段文字：先发现能力，再交换任务。"
```

三个脚本分工：

| 文件 | 看什么 |
|---|---|
| `server.py` | 能力怎么发布、任务状态怎么流转、产物怎么挂载 |
| `client.py` | 通过 SDK 走完整流程：拉卡片、发消息、逐条接收事件 |
| `probe.py` | 不经过 SDK，直接看 HTTP + JSON-RPC 报文和错误形状 |

## 四个可运行的场景

```bash
# 1. 立即消息：不建任务，直接回一条 Message
python client.py "echo hello"

# 2. 任务模式：submitted → working → completed，结果在 artifact 里
python client.py "统计这段文字：Agent 之间要先发现能力。"

# 3. 中断：任务停在 input-required
python client.py "ask"
# → 输出里带 task_id

# 4. 恢复：换一个进程，带同一个 task_id 继续
python client.py "补发的正文" --task <上一步的 task_id>
```

第 4 步验证客户端跨进程恢复。服务端保存任务状态，新客户端凭任务 ID 继续提交输入。

## 协议细节

实现步骤、事件序列、错误形状和踩到的坑都在[笔记](../笔记/A2A.md)，这里只记怎么跑。

## 任务其实存在内存里

当前用 `InMemoryTaskStore`，服务端进程重启后 `GetTask` 查不到旧任务。生产场景要换 `DatabaseTaskStore`（`a2a-sdk[sql]`），否则中断恢复只是同一进程内的假象。

另外这版没有鉴权。Agent Card 的 `securitySchemes` / `securityRequirements` 字段留空，意味着任何能访问 9999 端口的进程都能派任务。上线要补 HTTPS 和声明式鉴权，v1.0 支持 API key、Bearer、OAuth 2.0（授权码 + PKCE、客户端凭证、设备码）、OIDC、mTLS。

## 没做的部分

- gRPC 和 REST 绑定：只跑了 JSON-RPC。
- Push notification：需要客户端提供可访问的 webhook，本地环境没有公网入口。
- 流式：`capabilities.streaming=True` 走的是 SSE，但没做背压和断线续传。
- 多 agent 编排：客户端只调一个远程 agent，没有演示 A 调 B、B 再调 C 的链路。

## 和第 2 章 RAG 的关系

`TextAnalyst` 现在是纯本地计算。换检索只要替掉 `execute()` 里的 `analyse()`，把 `rag-practice` 的检索结果当 artifact 返回，其他地方不动。

多出来的东西是任务状态。函数调用不留痕迹，谁调都一样；包成远程 agent 之后要维护 ID、中断、取消。单次检索用不上这些，但「检索 → 生成 → 人核对引用」这条链上，中间停下来等人确认是常态。
