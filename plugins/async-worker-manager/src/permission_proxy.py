#!/usr/bin/env python3
"""
Permission proxy MCP server for worker Claude sessions.

This is an MCP server that workers connect to via stdio.
It communicates with the parent MCP server through a Unix domain socket
to bubble permission requests up to the main session.

Uses newline-delimited JSON protocol over Unix domain sockets.
"""
import asyncio
import os
import json
import sys
import uuid
from typing import List
from fastmcp import FastMCP
from mcp.types import TextContent, Content

from .models import PermissionResponse, PermissionRequest, PermissionResponseMessage

mcp = FastMCP("Permission Proxy")
socket_path = os.environ.get("PERM_SOCKET_PATH")
worker_id = os.environ.get("WORKER_ID")

if None in (socket_path, worker_id):
    raise Exception(" missing env vars PERM_SOCKET_PATH WORKER_ID")

@mcp.tool()
async def request_permission(tool_name: str, input: dict, reason: str = "", tool_use_id: str = "") -> List[Content]:
    """Request permission for a tool from the parent session via Unix socket."""

    # Connect to the parent's Unix socket (async client)
    try:
        # Open async Unix connection with timeout
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(socket_path),
            timeout=600.0
        )
    except (OSError, asyncio.TimeoutError) as e:
        sys.stderr.write(f"ERROR: Failed to connect to socket {socket_path}: {e}\n")
        sys.stderr.flush()
        return [TextContent(type="text", text='{"behavior": "deny", "message": "Socket connection error"}')]

    # Prepare permission request using Pydantic model
    request = PermissionRequest(
        request_id=str(uuid.uuid4()),
        worker_id=worker_id,
        tool=tool_name,
        input=input,
    )

    try:
        # Send request as newline-delimited JSON
        request_json = request.model_dump_json() + "\n"
        writer.write(request_json.encode('utf-8'))
        await asyncio.wait_for(writer.drain(), timeout=600.0)

        # Read response line (newline-delimited JSON)
        response_line = await asyncio.wait_for(reader.readline(), timeout=600.0)

        if not response_line:
            sys.stderr.write("ERROR: Socket closed by parent\n")
            sys.stderr.flush()
            return [TextContent(type="text", text='{"behavior": "deny", "message": "Connection closed"}')]

        # Parse response using Pydantic model for type safety
        response = PermissionResponseMessage.model_validate_json(response_line.decode('utf-8'))

    except (OSError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as e:
        sys.stderr.write(f"ERROR: Communication error: {e}\n")
        sys.stderr.flush()
        return [TextContent(type="text", text=json.dumps({"behavior": "deny", "message": str(e)}))]
    finally:
        writer.close()
        await writer.wait_closed()

    # Return decision to Claude as TextContent with JSON
    # Permission prompt tools require explicit List[TextContent] format
    if response.allow:
        result = PermissionResponse.allow(updated_input=response.updatedInput)
        result_json = result.model_dump_json()
        return [TextContent(type="text", text=result_json)]
    else:
        result = PermissionResponse.deny(
            message=response.message or "Permission denied by user"
        )
        result_json = result.model_dump_json()
        return [TextContent(type="text", text=result_json)]


if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.run())
