#!/usr/bin/env python3
"""
Permission proxy MCP server for worker Claude sessions.

NOTE: This proxy AUTO-APPROVES all permission requests for simplicity.
Workers have unrestricted tool access. Use in trusted environments only.
"""
import json
from typing import List
from fastmcp import FastMCP
from mcp.types import TextContent, Content

mcp = FastMCP("Permission Proxy")


@mcp.tool()
async def request_permission(tool_name: str, input: dict, reason: str = "", tool_use_id: str = "") -> List[Content]:
    """Request permission for a tool - auto-approves all requests."""
    response = {
        "behavior": "allow",
        "updatedInput": input
    }
    return [TextContent(type="text", text=json.dumps(response))]


if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.run())
