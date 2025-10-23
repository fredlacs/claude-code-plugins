"""
Unix domain socket manager for worker IPC.

Handles Unix socket lifecycle and permission request coordination between
main session and worker subprocesses via Unix domain sockets.

Protocol: newline-delimited JSON over Unix domain socket.
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

from fastmcp.exceptions import ToolError

from .models import (
    PendingPermission,
    PermissionRequest,
    PermissionResponseMessage,
)

if TYPE_CHECKING:
    from asyncio import Queue


class UnixSocketManager:
    """
    Manages Unix socket lifecycle and permission coordination for one worker.

    Encapsulates:
    - Unix domain socket (create, bind, listen, accept, cleanup)
    - Permission request/response protocol (newline-delimited JSON)
    - Pending permission tracking
    - Approval coordination with main session

    Usage:
        async with UnixSocketManager(worker_id, timeout) as mgr:
            env_vars = mgr.get_env_vars()
            # spawn worker with env_vars
            # manager handles permission requests automatically
    """

    def __init__(self, worker_id: str, timeout: float, event_queue: Optional['Queue'] = None):
        self.worker_id = worker_id
        self.timeout = timeout
        self.event_queue = event_queue
        self.socket_path = Path(f"/tmp/claude_worker_{worker_id}.sock")
        self.io_timeout = 30.0

        # Internal state
        self._srv: Optional[asyncio.AbstractServer] = None
        self._pending: Dict[str, PendingPermission] = {}
        self._requests_handled = 0
        self._max_requests = 100  # Security: DoS prevention

    async def __aenter__(self) -> "UnixSocketManager":
        """
        Create Unix socket and start accepting connections.

        Creates a Unix domain socket at /tmp/claude_worker_{worker_id}.sock
        and begins listening for permission requests from the worker subprocess.

        Security:
            - Removes existing socket file to prevent stale sockets
            - Sets permissions to 0o600 (owner read/write only) to prevent hijacking
            - Socket path includes worker_id to prevent collisions

        Returns:
            self: The initialized UnixSocketManager instance

        Raises:
            OSError: If socket creation fails (e.g., permission denied)
        """
        # Remove existing socket file
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

        # Start Unix domain socket server
        self._srv = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(self.socket_path)
        )
        # Set restrictive permissions: owner read/write only (prevents socket hijacking)
        os.chmod(self.socket_path, 0o600)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Close server and remove socket file.

        Performs cleanup when exiting the context manager:
            - Closes the Unix socket server
            - Removes the socket file from filesystem
            - Does not suppress any exceptions from the context

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred

        Returns:
            False: Never suppresses exceptions
        """
        if self._srv:
            self._srv.close()
            await self._srv.wait_closed()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        # Don't suppress exceptions
        return False

    def get_env_vars(self) -> dict:
        """
        Returns environment variables for worker subprocess.

        The worker subprocess needs these environment variables to connect
        back to this socket manager for permission requests.

        Returns:
            dict: Environment variables containing:
                - PERM_SOCKET_PATH: Path to Unix socket for permission requests
                - WORKER_ID: Unique identifier for this worker

        Example:
            >>> async with UnixSocketManager("worker-123", 60.0) as mgr:
            ...     env_vars = mgr.get_env_vars()
            ...     # env_vars = {
            ...     #     "PERM_SOCKET_PATH": "/tmp/claude_worker_worker-123.sock",
            ...     #     "WORKER_ID": "worker-123"
            ...     # }
        """
        return {
            "PERM_SOCKET_PATH": str(self.socket_path),
            "WORKER_ID": self.worker_id,
        }

    def get_pending_requests(self) -> List[PermissionRequest]:
        """
        Returns list of pending permissions for this worker.

        Used by the main session to query what permission requests are currently
        waiting for approval. Each pending request blocks the worker until it
        receives a response via approve_request().

        Returns:
            List[PermissionRequest]: List of pending permission requests, each containing:
                - request_id: Unique identifier for the request
                - worker_id: ID of the worker making the request
                - tool: Name of the tool requiring permission
                - input: Input parameters for the tool

        Example:
            >>> pending = mgr.get_pending_requests()
            >>> for req in pending:
            ...     print(f"Worker {req.worker_id} wants to use {req.tool}")
        """
        return [
            PermissionRequest(
                request_id=request_id,
                worker_id=perm.worker_id,
                tool=perm.tool,
                input=perm.input,
            )
            for request_id, perm in self._pending.items()
        ]

    async def approve_request(
        self,
        request_id: str,
        allow: bool,
        message: Optional[str] = None
    ) -> dict:
        """
        Approve or deny a pending request.

        Args:
            request_id: Unique ID of the permission request
            allow: True to allow, False to deny
            message: Optional message to include with denial

        Returns:
            Status dict with approval details
        """
        if request_id not in self._pending:
            raise ToolError(
                f"Permission request {request_id} not found. "
                f"It may have already been processed or timed out."
            )

        perm = self._pending[request_id]

        if perm.worker_id != self.worker_id:
            raise ToolError(
                f"Worker ID mismatch: expected {perm.worker_id}, got {self.worker_id}"
            )

        # Set response using Pydantic model for type safety
        if allow:
            perm.response = PermissionResponseMessage(
                request_id=request_id,
                allow=True,
                updatedInput=perm.input
            )
        else:
            perm.response = PermissionResponseMessage(
                request_id=request_id,
                allow=False,
                message=message or "Permission denied by user"
            )

        # Unblock the permission handler
        perm.event.set()

        return {
            "status": "approved" if allow else "denied",
            "worker_id": self.worker_id,
            "request_id": request_id,
            "tool": perm.tool,
        }

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ):
        """
        Handle one connection from worker (may serve multiple permission requests).

        This coroutine is invoked for each new connection to the Unix socket.
        It implements the permission request/response protocol:

        Protocol:
            1. Read newline-delimited JSON PermissionRequest
            2. Create PendingPermission and block on asyncio.Event
            3. Wait for approve_request() to set response and unblock
            4. Send newline-delimited JSON PermissionResponseMessage
            5. Repeat for additional requests on same connection

        Security:
            - Rate limiting: max 100 requests per connection
            - Timeout protection: 30 second I/O timeouts
            - Error handling: all errors converted to denial responses

        Args:
            reader: Async stream reader for receiving requests
            writer: Async stream writer for sending responses

        Connection lifecycle:
            - Multiple requests can be served over one connection
            - Connection closes when worker closes it or on timeout/error
            - Resources cleaned up in finally block
        """
        try:
            while True:
                # Read one JSON line with timeout
                try:
                    line = await asyncio.wait_for(
                        reader.readline(),
                        timeout=self.io_timeout
                    )
                except asyncio.TimeoutError:
                    # Send error response
                    error_response = PermissionResponseMessage(
                        request_id="unknown",
                        allow=False,
                        message="read_timeout"
                    )
                    await self._send_response(writer, error_response)
                    break

                if not line:
                    break  # client closed connection

                # Parse JSON into PermissionRequest
                try:
                    request = PermissionRequest.model_validate_json(line.decode("utf-8"))
                except Exception as e:
                    # Send error response
                    error_response = PermissionResponseMessage(
                        request_id="unknown",
                        allow=False,
                        message=f"invalid_request: {str(e)}"
                    )
                    await self._send_response(writer, error_response)
                    continue

                # Rate limiting check
                if self._requests_handled >= self._max_requests:
                    error_response = PermissionResponseMessage(
                        request_id=request.request_id,
                        allow=False,
                        message=f"Rate limit exceeded (max {self._max_requests})"
                    )
                    await self._send_response(writer, error_response)
                    continue

                request_id = request.request_id

                # Create pending permission with blocking event
                event = asyncio.Event()
                pending_perm = PendingPermission(
                    request_id=request_id,
                    worker_id=self.worker_id,
                    tool=request.tool,
                    input=request.input,
                    event=event,
                    socket=None,
                    response=None
                )
                self._pending[request_id] = pending_perm

                # Push permission event to queue
                if self.event_queue:
                    from .models import PermissionEvent
                    perm_req = PermissionRequest(
                        request_id=request_id,
                        worker_id=self.worker_id,
                        tool=request.tool,
                        input=request.input
                    )
                    self.event_queue.put_nowait(PermissionEvent(worker_id=self.worker_id, permission=perm_req))

                # Block until approval (via approve_request method)
                try:
                    await event.wait()

                    # Get response and cleanup
                    response = pending_perm.response
                    del self._pending[request_id]
                    self._requests_handled += 1

                    # Send response
                    await asyncio.wait_for(
                        self._send_response(writer, response),
                        timeout=self.io_timeout
                    )
                except asyncio.TimeoutError:
                    break
                except Exception as e:
                    # Send error response on handler failure
                    error_response = PermissionResponseMessage(
                        request_id=request.request_id,
                        allow=False,
                        message=f"{type(e).__name__}: {e}"
                    )
                    await self._send_response(writer, error_response)
                    continue

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        response: PermissionResponseMessage
    ) -> None:
        """
        Serialize PermissionResponseMessage as JSON line and send to worker.

        Converts the response to newline-delimited JSON and sends it over the
        Unix socket connection. Uses Pydantic's model_dump_json() for serialization.

        Args:
            writer: Async stream writer for the socket connection
            response: Permission response to send (allow or deny)

        Protocol:
            - Format: JSON + newline (\\n)
            - Encoding: UTF-8
            - Flushed immediately with drain()

        Raises:
            OSError: If socket write fails
            asyncio.TimeoutError: If drain() times out (handled by caller)
        """
        data = (response.model_dump_json(by_alias=False) + "\n").encode("utf-8")
        writer.write(data)
        await writer.drain()
