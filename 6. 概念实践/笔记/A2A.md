# 6. A2A 与远程 agent

A2A 是 Agent2Agent 的简称，一个让独立部署的 agent 互相通信的协议。2025 年 4 月由 Google 发起，后来交给 Linux Foundation，规范现在是 v1.0.1。

它要解决的情况是这样：A 团队做了个查内部文档的 agent，B 团队做了个跑数据处理的 agent，两边想互相调用。各自都有 HTTP 接口，但字段命名、鉴权方式、重试策略、任务进度怎么表示全不一样，每接一对就要写一次适配。A2A 把这些约定下来——能力用 Agent Card 声明在固定路径，任务用 Task 表示并带 ID 和状态，消息用 Message 传，结果用 Artifact 交，传输走 JSON-RPC over HTTP。

一次完整调用大致是这样：客户端先 `GET` 对方的 Agent Card，知道对方有什么能力、支持哪种协议；发 `SendMessage` 派活；服务端建一个 Task，边干边推状态；干完把产物挂到 Artifact 上，任务标成 `completed`。中途需要补充信息的话，任务停在 `input-required`，客户端补一条消息、带上同一个 `task_id` 就能接着走。

这次实践要做三件事：写一个服务端，把「统计文本」发布成远程 agent；写一个客户端，从零发现它、派任务、收事件；写一个裸 HTTP 的探测脚本，绕过 SDK 看报文长什么样。

环境是 A2A 规范 v1.0.1、`a2a-sdk` 1.3.1、Python 3.14.7。下面从空目录开始，按五步搭出这条链路，每一步都能跑起来验证。完整代码在 [`a2a/`](../a2a/README.md)，每一步只贴这一步要写或要改的部分。

## 6.1 准备

```bash
mkdir -p "6. 概念实践/a2a"
cd "6. 概念实践/a2a"
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

`requirements.txt` 只有两行，pin 死版本：

```text
a2a-sdk[http-server]==1.3.1
uvicorn==0.54.0
```

`[http-server]` 这个 extra 带 starlette 和 SSE 支持。没装 FastAPI，直接用 starlette 挂路由，少一层框架。

先确认 SDK 能 import：

```bash
.venv/bin/python -c "from a2a import types; print(types.TaskState.keys())"
```

```text
['TASK_STATE_UNSPECIFIED', 'TASK_STATE_SUBMITTED', 'TASK_STATE_WORKING', 'TASK_STATE_COMPLETED',
 'TASK_STATE_FAILED', 'TASK_STATE_CANCELED', 'TASK_STATE_INPUT_REQUIRED', 'TASK_STATE_REJECTED',
 'TASK_STATE_AUTH_REQUIRED']
```

这就是任务能处的全部状态。下面五步就是把这些状态一个一个走通。

## 6.2 第一步：发布一张 Agent Card

这一步只做一件事：让 `GET /.well-known/agent-card.json` 能返回卡片。不涉及任务，也不处理消息。

建 `server.py`：

```python
import uvicorn
from starlette.applications import Starlette
from a2a.server.routes import create_agent_card_routes
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    PROTOCOL_VERSION_CURRENT,
    TransportProtocol,
)

HOST = "127.0.0.1"
PORT = 9999
BASE_URL = f"http://{HOST}:{PORT}"


def build_card() -> AgentCard:
    return AgentCard(
        name="Text Analyst",
        description="统计一段文本的字符数、行数、词元数与高频词。",
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(
                url=BASE_URL + "/",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="text_report",
                name="文本统计",
                description="输入任意文本，返回字符、行、词元与高频词统计。",
                tags=["text", "stats"],
            )
        ],
    )


app = Starlette(
    routes=create_agent_card_routes(build_card(), card_url=AGENT_CARD_WELL_KNOWN_PATH)
)
```

几个字段值得注意：

- `supported_interfaces` 是数组。v1.0 改成数组以后，一个 agent 可以同时挂 JSON-RPC、gRPC、HTTP+JSON，各自声明协议版本。这里只填一个 JSON-RPC。
- `capabilities` 先留空。第三步要开流式时再改成 `AgentCapabilities(streaming=True)`，不然客户端会以为服务端支持流式。
- `url` 写的是服务端自己的地址。换成部署环境要跟着改。

启动：

```bash
uvicorn server:app --host 127.0.0.1 --port 9999
```

验证：

```bash
curl -s http://127.0.0.1:9999/.well-known/agent-card.json | python3 -m json.tool
```

```json
{
  "name": "Text Analyst",
  "supportedInterfaces": [
    {"url": "http://127.0.0.1:9999/", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
  ],
  "version": "0.1.0",
  "capabilities": {},
  "defaultInputModes": ["text/plain"],
  "skills": [{"id": "text_report", "name": "文本统计"}]
}
```

上面是节选，`skills` 里还有 `description` 和 `tags`。`json.tool` 默认把中文转成 `\u` 转义，要看原文直接 `curl` 不接管道。

路径是协议定死的，客户端不需要先约定什么就能发现。JSON 字段是 camelCase，写 proto 时的 `supported_interfaces` 在这里变成 `supportedInterfaces`。

## 6.3 第二步：让 agent 能回消息

卡片只是声明，还没有处理能力。这一步加 JSON-RPC 接口，让它能回一条消息。

SDK 里承载业务逻辑的是 `AgentExecutor`，要实现两个方法：`execute()` 干活，`cancel()` 处理取消。先只做 `execute()`，取消留空。

```python
import uuid
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role


class TextAnalyst(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input().strip()
        context_id = context.context_id or str(uuid.uuid4())

        if text.lower().startswith("echo"):
            await event_queue.enqueue_event(
                Message(
                    message_id=str(uuid.uuid4()),
                    role=Role.ROLE_AGENT,
                    context_id=context_id,
                    parts=[Part(text="echo: " + text[4:].strip())],
                )
            )
            return

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass
```

`execute()` 不返回结果，往 `event_queue` 里塞事件。这里塞的是 `Message`，代表「一句话答完，不建任务」。这是 A2A 里最轻的一种响应。

把它挂到路由上，替换掉第一步末尾的 `app`：

```python
card = build_card()
handler = DefaultRequestHandler(
    agent_executor=TextAnalyst(),
    task_store=InMemoryTaskStore(),
    agent_card=card,
)
app = Starlette(routes=[
    *create_agent_card_routes(card, card_url=AGENT_CARD_WELL_KNOWN_PATH),
    *create_jsonrpc_routes(handler, rpc_url="/"),
])
```

`DefaultRequestHandler` 负责解析请求、管任务、跑 executor、把事件发回客户端。`InMemoryTaskStore` 先把任务放内存里，够用。

重启服务，用 curl 直接发一条 JSON-RPC：

```bash
curl -s -X POST http://127.0.0.1:9999/ \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"11111111-2222-3333-4444-555555555555","role":"ROLE_USER","parts":[{"text":"echo hello"}]}}}'
```

`A2A-Version` 这个头不能省。不带它服务端按 0.3 处理，直接返回 `VERSION_NOT_SUPPORTED`：

```json
{"error":{"code":-32009,"message":"A2A version '0.3' is not supported by this handler. Expected version '1.0'."}}
```

返回：

```json
{
  "result": {
    "message": {
      "messageId": "280a0ff8-cd7b-4cad-b3b5-aaac346cb3a1",
      "contextId": "8f88494c-d76f-4e81-a96b-b458707f6e71",
      "role": "ROLE_AGENT",
      "parts": [{"text": "echo: hello"}]
    }
  },
  "id": "1",
  "jsonrpc": "2.0"
}
```

注意方法名是 `SendMessage`，不是 `message/send`。v1.0 的操作名全部改成了 PascalCase，v0.3 的小写带斜杠那套已经失效。role 是 `ROLE_USER`，state 也一样用大写枚举。

到这里，一个能被调用、能回话的远程 agent 就有了。还没有任务的概念。

## 6.4 第三步：把耗时的事做成 Task

echo 一问一答就够了。但统计要 500 毫秒，中间还得告诉对方在干活，最后要交一份结果。这时候再用 Message 就不合适：结果和过程挤在一起，客户端断线就没了。

先写个统计函数：

```python
def analyse(text: str) -> str:
    lines = text.splitlines() or [text]
    chars_no_space = len(re.sub(r"\s", "", text))
    words = re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]", text)
    top = Counter(word.lower() for word in words).most_common(5)
    top_text = "、".join(f"{word}×{count}" for word, count in top) or "无"
    return (
        f"字符数：{len(text)}（去空白 {chars_no_space}）\n"
        f"行数：{len(lines)}\n"
        f"词元数：{len(words)}\n"
        f"高频：{top_text}"
    )
```

然后在 `execute()` 里加任务分支。自然想法是直接上 `TaskUpdater`：

```python
updater = TaskUpdater(event_queue, task_id, context_id)
await updater.submit()
await updater.start_work()
await updater.complete()
```

这样写客户端会直接报错：

```text
InvalidAgentResponseError: Agent should enqueue Task before TaskStatusUpdateEvent event
```

原因是 `TaskUpdater` 只发 `TaskStatusUpdateEvent`，不发 Task 本身。首次请求时任务还不存在，状态事件没有挂靠的对象。所以得自己先入队一个空的 Task：

```python
task_id = context.task_id or str(uuid.uuid4())

await event_queue.enqueue_event(
    Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
    )
)

updater = TaskUpdater(event_queue, task_id, context_id)
await updater.start_work(
    message=updater.new_agent_message([Part(text="收到文本，开始统计")])
)
await asyncio.sleep(0.5)
await updater.add_artifact(
    parts=[Part(text=analyse(text), media_type="text/plain")],
    name="report",
)
await updater.complete()
```

一次任务产生四类事件：入队的 `Task` 给 ID 和初始状态，`start_work()` 推 working 并捎一句 agent 的话，`add_artifact()` 交产物，`complete()` 收尾。产物用 `append` / `last_chunk` 控制分片追加，示例只有一片。

客户端改用 SDK，不再手拼 JSON。新建 `client.py`：

```python
async with httpx.AsyncClient(timeout=30) as http:
    card = await A2ACardResolver(http, BASE_URL).get_agent_card()

    client = await create_client(
        card,
        client_config=ClientConfig(streaming=True, httpx_client=http),
    )
    request = SendMessageRequest(
        message=Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text=prompt)],
        )
    )
    async for event in client.send_message(request):
        print(describe(event))
```

这里有两个点：

- `create_client` 是 `async def`，签名打出来是 `-> Client`，看不出要 await。不 await 会拿到 coroutine 对象，报 `AttributeError: 'coroutine' object has no attribute 'send_message'`。
- `streaming=True` 要求服务端卡片里声明了 `capabilities.streaming`。所以这一步要把 `build_card()` 里的 `AgentCapabilities()` 改成 `AgentCapabilities(streaming=True)`，客户端才知道可以走 `SendStreamingMessage`。

`describe()` 按 `HasField` 逐个判断事件类型（[完整实现](../a2a/client.py#L25)）。跑：

```bash
python client.py "统计：回归测试"
```

```text
发现 agent：Text Analyst v0.1.0
  接口：http://127.0.0.1:9999/ [JSONRPC 1.0]
  技能：text_report — 文本统计

Task      id=2fa7eae3-d59f-4051-9f56-17c0c0f7ccf7 state=TASK_STATE_SUBMITTED
状态更新   state=TASK_STATE_WORKING 收到文本，开始统计
产物       name=report
           字符数：7（去空白 7）
           行数：1
           词元数：6
状态更新   state=TASK_STATE_COMPLETED
```

四条事件按序到达，客户端全程不需要关心任务 ID 从哪来——服务端生成，客户端只是看到。

## 6.5 第四步：任务能中断，也能接回来

统计需要正文。对方没给正文时，与其报错，不如把任务挂起等补充。

在 `execute()` 的任务分支里加：

```python
if text.lower().startswith("ask"):
    await updater.start_work()
    await updater.requires_input(
        updater.new_agent_message(
            [Part(text="请补发一条消息给出要统计的正文，task_id 保持不变。")]
        )
    )
    return
```

`requires_input()` 把状态推到 `TASK_STATE_INPUT_REQUIRED`，`execute()` 返回，任务留在存储里，不结束。

恢复时客户端只要在消息里带 `task_id`。服务端从存储读回任务，看到状态是 `INPUT_REQUIRED`，走另一条分支。这段要放在 `execute()` 最前面，在 echo 判断之前：

```python
current = context.current_task
if (
    current is not None
    and current.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
):
    updater = TaskUpdater(event_queue, task_id, context_id)
    await updater.start_work()
    await updater.add_artifact(
        parts=[Part(text=analyse(text), media_type="text/plain")],
        name="report",
    )
    await updater.complete()
    return
```

`client.py` 加 `--task` 参数透传到 `Message(task_id=...)`（[完整实现](../a2a/client.py#L46)）。

跑两次，中间换进程：

```bash
python client.py "ask"
```

```text
Task      id=3864adfa-caf3-4b02-82e6-04908b43b348 state=TASK_STATE_SUBMITTED
          → 复用该任务：--task 3864adfa-caf3-4b02-82e6-04908b43b348
状态更新   state=TASK_STATE_WORKING
状态更新   state=TASK_STATE_INPUT_REQUIRED 请补发一条消息给出要统计的正文，task_id 保持不变。
```

第一个进程到这里就退出了。另开一个：

```bash
python client.py "任务可以跨进程恢复，只要带着 task_id 回来。" \
  --task 3864adfa-caf3-4b02-82e6-04908b43b348
```

```text
状态更新   state=TASK_STATE_WORKING
产物       name=report
           字符数：26（去空白 24）
           行数：1
           词元数：17
状态更新   state=TASK_STATE_COMPLETED
```

任务没有重建，状态从 `WORKING` 接着走。这就是 Task 相对普通请求的价值：状态在服务端，不在客户端连接上。

前提是 `InMemoryTaskStore` 没丢。它把任务放在服务端进程内存里，重启服务端，`GetTask` 就查不到了。真正的跨进程恢复要换 `DatabaseTaskStore`（`a2a-sdk[sql]`）。

## 6.6 第五步：绕过 SDK 看协议

SDK 把传输细节包掉了。要看清协议，直接用 httpx 发 JSON-RPC。新建 `probe.py`：

```python
def rpc(http: httpx.Client, method: str, params: dict, call_id: str = "1") -> dict:
    body = {"jsonrpc": "2.0", "id": call_id, "method": method, "params": params}
    response = http.post(BASE_URL + "/", json=body, headers={"A2A-Version": "1.0"})
    response.raise_for_status()
    return response.json()
```

拿任务：非流式的 `SendMessage` 会等任务进入终态才返回，所以 `result.task.id` 已经拿到了。换进程后用它查：

```python
fetched = rpc(http, "GetTask", {"id": task_id}, call_id="2")
```

原始响应长这样（节选）：

```json
{
  "result": {
    "id": "94cad023-50ac-4e5e-9fec-6c671e5c059c",
    "contextId": "233c8f66-8dda-4c1b-b84b-0c3cd6f55535",
    "status": {"state": "TASK_STATE_COMPLETED"},
    "artifacts": [{"name": "report"}],
    "history": [{"role": "ROLE_AGENT", "parts": [{"text": "收到文本，开始统计"}]}]
  },
  "id": "2",
  "jsonrpc": "2.0"
}
```

注意 `state` 在 `status` 里，不在顶层。`history` 保留了过程中的 agent 消息。

参数不对时报错：

```python
rpc(http, "SendMessage", {"message": {"role": "ROLE_USER"}}, call_id="3")
```

```json
{
  "error": {
    "code": -32602,
    "message": "Validation failed",
    "data": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "INVALID_PARAMS",
              "domain": "a2a-protocol.org",
              "metadata": {"errors": [{"field": "message.message_id", "message": "Field is required."}]}}]
  },
  "id": "3",
  "jsonrpc": "2.0"
}
```

`data` 里是 `google.rpc.ErrorInfo` 和 `google.rpc.BadRequest`，逐字段列违规项。这就是 v1.0 的错误模型。

用 v0.3 的方法名打过去：

```json
{"error": {"code": -32601, "message": "Method not found"}, "id": "4", "jsonrpc": "2.0"}
```

要兼容老客户端，得在服务端 `create_jsonrpc_routes(handler, "/", enable_v0_3_compat=True)` 显式打开，默认关。

这里要把两件事分开：HTTP 200 只说明 JSON-RPC 收到了，任务成功与否得看 `status.state`。协议错误走 error，业务失败走 `TASK_STATE_FAILED`。

## 6.7 完成后的文件

| 文件 | 行数 | 关键位置 |
|---|---|---|
| `server.py` | 184 | [`build_card()`](../a2a/server.py#L134)、[`build_app()`](../a2a/server.py#L161)、[`execute()`](../a2a/server.py#L62) |
| `client.py` | 86 | [`describe()`](../a2a/client.py#L25)、[`main()`](../a2a/client.py#L46) |
| `probe.py` | 80 | [`rpc()`](../a2a/probe.py#L21) |
| `requirements.txt` | 2 | 依赖版本 |

五步加起来的最终代码就是这些，没有为教程单独简化过的第二份实现。

## 6.8 没做的部分

- gRPC 和 HTTP+JSON 绑定，只跑了 JSON-RPC
- Push notification，需要客户端有公网可达的 webhook，本地没有
- 流式的背压和断线续传
- 多 agent 链路（A 调 B、B 调 C）
- 鉴权和 TLS

## 6.9 调试时碰到的坑

`TaskUpdater` 不建 Task（见 6.4），`create_client` 要 await（见 6.4），这两个是挡路的。还有两个不会挡路但容易误导：

`create_agent_card_routes()` 的默认路径就是 `/.well-known/agent-card.json`，SDK 里对应的常量是 `AGENT_CARD_WELL_KNOWN_PATH`。要改路径用 `card_url` 参数，不要在客户端写死。

protobuf 7 删掉了 `FieldDescriptor.label`。反射字段时用 `is_repeated`，老的示例代码会在这里报 `AttributeError`。

## 参考

- [A2A 规范](https://a2a-protocol.org/latest/specification/)
- [A2A 项目仓库](https://github.com/a2aproject/A2A)
- [a2a-python SDK](https://github.com/a2aproject/a2a-python)
- [v1.0 变更说明](https://a2a-protocol.org/latest/whats-new-v1/)
