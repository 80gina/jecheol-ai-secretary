"""
[보너스 ①-2] MCP Server.

같은 도구(get_data_summary / query_data / find_extreme / list_past_conversations)를
MCP 프로토콜로도 노출한다. 이렇게 하면 Claude Desktop 같은 외부 MCP 클라이언트에서도
내 제철밥상 데이터를 조회할 수 있다 — 즉 '멀티채널 연동'이 검증된다.

도구 정의(TOOL_SPECS)는 app/services/tools.py 한 곳에만 두고 여기서 재사용한다.
정의가 두 벌이 되면 반드시 어긋나기 때문이다.

실행:
    pip install "mcp[cli]"
    python mcp_server/server.py           # stdio 로 대기

Claude Desktop 등록 예 (claude_desktop_config.json):
{
  "mcpServers": {
    "seasonal-table": {
      "command": "python",
      "args": ["/절대경로/backend/mcp_server/server.py"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/절대경로/serviceAccountKey.json"
      }
    }
  }
}
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp.server.stdio  # noqa: E402
import mcp.types as types  # noqa: E402
from mcp.server import Server  # noqa: E402
from mcp.server.models import InitializationOptions  # noqa: E402
from mcp.server import NotificationOptions  # noqa: E402

from app.db import init_db  # noqa: E402
from app.services.tools import TOOL_SPECS, run_tool  # noqa: E402

server = Server("seasonal-table-planner")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """FastAPI 가 GPT 에 넘기는 것과 완전히 같은 도구 목록을 MCP 형식으로 변환."""
    return [
        types.Tool(
            name=spec["name"],
            description=spec["description"],
            inputSchema=spec["parameters"],
        )
        for spec in TOOL_SPECS
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """도구 실행기도 FastAPI 와 동일한 run_tool 을 그대로 쓴다."""
    result = run_tool(name, arguments or {})
    return [
        types.TextContent(
            type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
        )
    ]


async def main() -> None:
    init_db()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="seasonal-table-planner",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
