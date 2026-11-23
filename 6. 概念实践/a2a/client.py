"""A2A 客户端：发现 Agent Card，发一条消息，按到达顺序打印事件流。

用法：
    python client.py "统计这段文字"
    python client.py "echo hello"
    python client.py "ask"                 # 服务端停在 input-required
    python client.py "要统计的正文" --task <task_id>   # 用同一个任务继续
"""
import argparse
import asyncio
import uuid

import httpx

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState

BASE_URL = "http://127.0.0.1:9999"


def text_of(parts) -> str:
    return " ".join(part.text for part in parts if part.text)


def describe(event) -> str:
    if event.HasField("task"):
        task = event.task
        return f"Task      id={task.id} state={TaskState.Name(task.status.state)}"
    if event.HasField("status_update"):
        update = event.status_update
        note = ""
        if update.status.HasField("message"):
            note = text_of(update.status.message.parts)
        return f"状态更新   state={TaskState.Name(update.status.state)} {note}".rstrip()
    if event.HasField("artifact_update"):
        artifact = event.artifact_update.artifact
        body = text_of(artifact.parts)
        body = "\n" + "\n".join("           " + line for line in body.splitlines())
        return f"产物       name={artifact.name}{body}"
    if event.HasField("message"):
        message = event.message
        return f"消息       role={Role.Name(message.role)}: {text_of(message.parts)}"
    return f"未知事件   {event}"


async def main(prompt: str, task_id: str | None = None) -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()
        print(f"发现 agent：{card.name} v{card.version}")
        print(f"  描述：{card.description}")
        for interface in card.supported_interfaces:
            print(f"  接口：{interface.url} [{interface.protocol_binding} {interface.protocol_version}]")
        for skill in card.skills:
            print(f"  技能：{skill.id} — {skill.name}")
        print(f"  能力：streaming={card.capabilities.streaming}")
        print()

        client = await create_client(
            card,
            client_config=ClientConfig(streaming=True, httpx_client=http),
        )
        request = SendMessageRequest(
            message=Message(
                message_id=str(uuid.uuid4()),
                role=Role.ROLE_USER,
                task_id=task_id or "",
                parts=[Part(text=prompt)],
            )
        )

        print(f"发送：{prompt}" + (f"（task_id={task_id}）" if task_id else ""))
        print("-" * 60)
        async for event in client.send_message(request):
            print(describe(event))
            if event.HasField("task"):
                print(f"          → 复用该任务：--task {event.task.id}")

        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt")
    parser.add_argument("--task", help="继续一个已存在的任务")
    args = parser.parse_args()
    asyncio.run(main(args.prompt, args.task))
