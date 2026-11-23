"""A2A 服务端：把「文本统计」发布成一个可被其他 agent 调用的远程 agent。

协议版本 1.0（A2A v1.0.1），JSON-RPC 2.0 over HTTP。

两种响应形态：
- 消息以 echo 开头：直接回一条 Message，不创建 Task。
- 其他输入：创建 Task，经历 submitted → working → completed，
  中间推一条 Artifact 承载统计报告。
"""
import asyncio
import re
import uuid
from collections import Counter

import uvicorn
from starlette.applications import Starlette

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    PROTOCOL_VERSION_CURRENT,
    TransportProtocol,
)

HOST = "127.0.0.1"
PORT = 9999
BASE_URL = f"http://{HOST}:{PORT}"


def analyse(text: str) -> str:
    lines = text.splitlines() or [text]
    chars = len(text)
    chars_no_space = len(re.sub(r"\s", "", text))
    words = re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]", text)
    top = Counter(word.lower() for word in words).most_common(5)
    top_text = "、".join(f"{word}×{count}" for word, count in top) or "无"
    return (
        f"字符数：{chars}（去空白 {chars_no_space}）\n"
        f"行数：{len(lines)}\n"
        f"词元数：{len(words)}\n"
        f"高频：{top_text}"
    )


class TextAnalyst(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input().strip()
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or str(uuid.uuid4())

        # 恢复分支：上一条消息被标为 input-required，这条是对它的补充。
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

        # A2A 要求先入队 Task 本身，后续的 TaskStatusUpdateEvent 才有挂靠对象。
        await event_queue.enqueue_event(
            Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            )
        )

        updater = TaskUpdater(event_queue, task_id, context_id)

        # 中断分支：任务停在需要补充信息的状态，客户端可换连接、换进程再来。
        if text.lower().startswith("ask"):
            await updater.start_work()
            await updater.requires_input(
                updater.new_agent_message(
                    [Part(text="请补发一条消息给出要统计的正文，task_id 保持不变。")]
                )
            )
            return

        await updater.start_work(
            message=updater.new_agent_message(
                [Part(text="收到文本，开始统计")]
            )
        )

        # 模拟真实工作耗时，让流式事件在客户端按顺序到达。
        await asyncio.sleep(0.5)

        await updater.add_artifact(
            parts=[Part(text=analyse(text), media_type="text/plain")],
            name="report",
        )
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()


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
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="text_report",
                name="文本统计",
                description="输入任意文本，返回字符、行、词元与高频词统计。",
                tags=["text", "stats"],
                examples=["统计这段文字", "echo hello"],
            )
        ],
    )


def build_app() -> Starlette:
    card = build_card()
    handler = DefaultRequestHandler(
        agent_executor=TextAnalyst(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = [
        *create_agent_card_routes(card, card_url=AGENT_CARD_WELL_KNOWN_PATH),
        *create_jsonrpc_routes(handler, rpc_url="/"),
    ]
    return Starlette(routes=routes)


def main() -> None:
    card = build_card()
    print(f"Agent Card：{BASE_URL}{AGENT_CARD_WELL_KNOWN_PATH}")
    print(f"JSON-RPC：{BASE_URL}/")
    print(f"skill：{card.skills[0].id} — {card.skills[0].name}")
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
