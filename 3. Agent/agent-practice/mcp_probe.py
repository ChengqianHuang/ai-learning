"""启动独立的 MCP 子进程，发现工具并读取一次真实的检索结果。"""

import argparse
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


async def probe(query: str, top_k: int) -> int:
    server_file = Path(__file__).resolve().with_name("mcp_server.py")
    launch = StdioServerParameters(command=sys.executable, args=[str(server_file)])
    async with stdio_client(launch) as (incoming, outgoing):
        async with ClientSession(incoming, outgoing, read_timeout_seconds=timedelta(seconds=10)) as session:
            info = await session.initialize()
            print(f"initialize   服务 {info.serverInfo.name}，协议 {info.protocolVersion}")

            directory = await session.list_tools()
            for tool in directory.tools:
                print(f"tools/list   {tool.name}  {json.dumps(tool.inputSchema, ensure_ascii=False)}")
            if not any(tool.name == "search_notes" for tool in directory.tools):
                print("服务端未发布 search_notes", file=sys.stderr)
                return 1

            arguments = {"query": query, "top_k": top_k}
            print(f"tools/call   search_notes  {json.dumps(arguments, ensure_ascii=False)}")
            result = await session.call_tool("search_notes", arguments)
            if result.isError:
                print("isError=true")
                for block in result.content:
                    if isinstance(block, types.TextContent):
                        print(block.text)
                return 1

            print("isError=false")
            print(json.dumps(result.structuredContent, ensure_ascii=False, indent=2))
            return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="幂等")
    parser.add_argument("--top-k", type=int, default=2)
    options = parser.parse_args()
    sys.exit(asyncio.run(probe(options.query, options.top_k)))
