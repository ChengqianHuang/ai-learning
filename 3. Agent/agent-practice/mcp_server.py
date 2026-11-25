"""通过 MCP stdio 发布本章的笔记检索工具。"""

import asyncio
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from notes_tool import TOOL, search_notes


server = Server("agent-notes")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=TOOL["name"],
            description=TOOL["description"],
            inputSchema=TOOL["input_schema"],
            annotations=types.ToolAnnotations(readOnlyHint=True),
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != TOOL["name"]:
        raise ValueError(f"未知工具 {name}")
    # SDK 按工具目录中的 inputSchema 校验参数，并将返回的字典放入 structuredContent。
    return {"matches": search_notes(**arguments)}


async def main() -> None:
    async with stdio_server() as (incoming, outgoing):
        await server.run(incoming, outgoing, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
