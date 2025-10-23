import asyncio
import json
import os
import shutil
import uuid
from asyncio import Queue
from pathlib import Path
from typing import Dict, List, Optional
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .models import (
    ActiveTask,
    ClaudeJobResult,
    CompleteTask,
    CompletionEvent,
    FailedTask,
    FailureEvent,
    PermissionEvent,
    PermissionRequest,
    Worker,
    WorkerState,
    WorkerStatus,
)
from .unix_socket_manager import UnixSocketManager


mcp = FastMCP("Async Worker Manager")
workers: Dict[str, Worker] = {}
# Legacy exports for backwards compatibility with tests
active_tasks: Dict[str, ActiveTask] = {}
complete_tasks: Dict[str, CompleteTask] = {}

# Event queue for instant notifications (created per-loop)
_event_queues: Dict[int, Queue] = {}


def get_event_queue() -> Queue:
    """Get or create event queue for current event loop."""
    loop = asyncio.get_event_loop()
    loop_id = id(loop)
    if loop_id not in _event_queues:
        _event_queues[loop_id] = Queue()
    return _event_queues[loop_id]


@mcp.tool
async def create_async_worker(prompt: str, timeout: float = 300.0) -> str:
    """Create async Claude worker. Returns worker_id or raises ToolError."""
    # Count active workers (check both workers dict and legacy active_tasks for backward compat)
    active_count = len(active_tasks)
    if active_count >= 10:
        raise ToolError("Max 10 active workers.")
    worker_id = str(uuid.uuid4())
    task = asyncio.create_task(run_claude_job(prompt, timeout, worker_id))
    # Create unified Worker entry with ACTIVE status
    workers[worker_id] = Worker(
        worker_id=worker_id,
        status=WorkerStatus.ACTIVE,
        timeout=timeout,
        task=task
    )
    # Maintain legacy dict for test compatibility
    active_tasks[worker_id] = ActiveTask(worker_id, task, timeout)
    return worker_id


@mcp.tool
async def resume_worker(worker_id: str, message: str):
    """Resume a completed worker's conversation with a new message."""
    # Try to flush if worker is still active
    if worker_id in active_tasks:
        _, _ = await _flush_completed_tasks(timeout=0.0)

    # Check complete_tasks (legacy dict for backward compat)
    if worker_id not in complete_tasks:
        raise ToolError(f"Worker {worker_id} not found in complete tasks")

    # Get the complete task info
    complete_task = complete_tasks.pop(worker_id)

    # Create new task for resumption
    new_task = asyncio.create_task(
        run_claude_job(
            message,
            complete_task.timeout,
            worker_id,
            session_id=complete_task.claude_session_id,
        )
    )

    # Transition COMPLETED -> ACTIVE in workers dict if exists
    if worker_id in workers:
        workers[worker_id].status = WorkerStatus.ACTIVE
        workers[worker_id].task = new_task
        workers[worker_id].complete_task = None

    # Maintain legacy dict for test compatibility
    active_tasks[worker_id] = ActiveTask(worker_id, new_task, complete_task.timeout)


@mcp.tool
async def wait(
    timeout: float = 30.0, worker_id: Optional[str] = None
) -> WorkerState:
    """
    Wait for workers to complete or request permissions. Returns unified WorkerState.

    Uses event-driven notifications for instant response (<100ms latency).

    Returns WorkerState when:
    - One or more workers complete, OR
    - One or more pending permissions exist, OR
    - Timeout expires (returns empty/current state)

    Args:
        timeout: Maximum time to wait in seconds
        worker_id: Optional worker ID to wait for specifically

    Returns:
        WorkerState with completed tasks and pending permission requests
    """
    start_time = asyncio.get_event_loop().time()

    if worker_id is None:
        # Wait for any worker
        if not active_tasks and not complete_tasks:
            raise ToolError("No active workers to wait for")

        # Check if we already have completed/failed workers
        completed, failed = await _flush_completed_tasks(timeout=0.0)
        pending_perms = _get_pending_permissions()

        if completed or failed or pending_perms:
            return WorkerState(completed=completed, failed=failed, pending_permissions=pending_perms)

        # Hybrid event + periodic polling loop
        # This combines instant event-driven response with periodic completion checks
        # for long-running subprocesses that complete after wait() is called
        POLL_INTERVAL = 5.0  # Check for completions every 5 seconds

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            remaining = max(0, timeout - elapsed)

            if remaining <= 0:
                return WorkerState(completed=[], failed=[], pending_permissions=[])

            try:
                # Wait for event OR poll interval (whichever comes first)
                # This ensures we get instant response for quick tasks,
                # while still checking for slow subprocess completions
                wait_time = min(remaining, POLL_INTERVAL)
                event = await asyncio.wait_for(get_event_queue().get(), timeout=wait_time)

                # Process event
                if isinstance(event, CompletionEvent):
                    return WorkerState(
                        completed=[event.task],
                        failed=[],
                        pending_permissions=_get_pending_permissions()
                    )
                elif isinstance(event, FailureEvent):
                    return WorkerState(
                        completed=[],
                        failed=[event.task],
                        pending_permissions=_get_pending_permissions()
                    )
                elif isinstance(event, PermissionEvent):
                    # Flush any completed tasks too
                    completed, failed = await _flush_completed_tasks(timeout=0.0)
                    return WorkerState(
                        completed=completed,
                        failed=failed,
                        pending_permissions=[event.permission] + _get_pending_permissions()
                    )
            except asyncio.TimeoutError:
                # No event received in POLL_INTERVAL - check for completions manually
                # This catches long-running subprocesses that complete between polls
                completed, failed = await _flush_completed_tasks(timeout=0.0)
                pending_perms = _get_pending_permissions()

                if completed or failed or pending_perms:
                    return WorkerState(
                        completed=completed,
                        failed=failed,
                        pending_permissions=pending_perms
                    )
                # Nothing yet, loop continues to wait for more events

    else:
        # Wait for specific worker - keep polling approach for simplicity
        # (Event filtering by worker_id would add complexity)
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            remaining_timeout = timeout - elapsed
            if remaining_timeout <= 0:
                raise ToolError(f"Timeout after {timeout}s waiting for worker {worker_id}")

            # Check if worker already complete
            if worker_id in complete_tasks:
                return WorkerState(
                    completed=[complete_tasks[worker_id]],
                    failed=[],
                    pending_permissions=_get_pending_permissions(worker_id)
                )

            # Check if worker exists
            if worker_id not in active_tasks:
                raise ToolError(f"Worker {worker_id} not found in active tasks")

            # Quick check for completions
            completed, failed = await _flush_completed_tasks(timeout=0.0)

            # Check again if worker completed
            if worker_id in complete_tasks:
                return WorkerState(
                    completed=[complete_tasks[worker_id]],
                    failed=[],
                    pending_permissions=_get_pending_permissions(worker_id)
                )

            # Check if this specific worker failed
            worker_failed = [f for f in failed if f.worker_id == worker_id]
            if worker_failed:
                return WorkerState(
                    completed=[],
                    failed=worker_failed,
                    pending_permissions=_get_pending_permissions(worker_id)
                )

            # Check for pending permissions for this worker
            pending_perms = _get_pending_permissions(worker_id)
            if pending_perms:
                return WorkerState(
                    completed=[],
                    failed=[],
                    pending_permissions=pending_perms
                )

            # Sleep briefly before next poll (keep for specific worker case)
            await asyncio.sleep(0.5)


def _generate_error_hint(stderr: str, returncode: int) -> str:
    """Generate brief actionable hint from stderr."""
    stderr_lower = stderr.lower()

    if "timeout" in stderr_lower:
        return "Timed out. Increase timeout parameter."
    elif "permission" in stderr_lower:
        return "Permission denied. Check pending_permissions and approve."
    elif "command not found" in stderr_lower:
        return "Tool not found. Check MCP server config."
    elif "connection" in stderr_lower or "failed to connect" in stderr_lower:
        return "Connection failed. Check MCP server is running."
    elif stderr:
        # Return first 150 chars of stderr
        return stderr[:150].replace('\n', ' ')
    else:
        return f"Exit code {returncode}"


async def run_claude_job(
    prompt: str, timeout: float, worker_id: str, session_id: Optional[str] = None
) -> ClaudeJobResult:
    """Spawn Claude subprocess with Unix domain socket for permission requests."""
    if not shutil.which("claude"):
        raise ToolError("Claude not in PATH")

    # Create logs directory
    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    output_file = logs_dir / f"worker-{worker_id}.json"

    # Use UnixSocketManager context manager for socket lifecycle
    async with UnixSocketManager(worker_id, timeout, get_event_queue()) as socket_mgr:
        # Register manager in unified worker registry
        if worker_id in workers:
            workers[worker_id].socket_mgr = socket_mgr

        try:
            # Get paths for permission_proxy.py
            plugin_root = os.environ.get('CLAUDE_PLUGIN_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            permission_proxy_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'permission_proxy.py')

            # Create MCP config JSON for permission proxy server
            # Use uv run to ensure we're in the right venv with fastmcp
            mcp_config = {
                "mcpServers": {
                    "permission_proxy": {
                        "command": "uv",
                        "args": [
                            "run",
                            "--directory", plugin_root,
                            "python", permission_proxy_path
                        ]
                    }
                }
            }
            mcp_config_json = json.dumps(mcp_config)

            cmd = ["claude"]
            if session_id:
                cmd += ["--resume", session_id]
            cmd += [
                "-p", prompt,
                "--output-format", "json",
                "--mcp-config", mcp_config_json,
                "--permission-prompt-tool", "mcp__permission_proxy__request_permission",
            ]

            # Debug logging
            import sys
            env_vars = socket_mgr.get_env_vars()
            print(f"\n=== WORKER COMMAND ===", file=sys.stderr)
            print(f"worker_id: {worker_id}", file=sys.stderr)
            print(f"cmd: {cmd}", file=sys.stderr)
            print(f"env vars: {env_vars}", file=sys.stderr)
            print(f"mcp_config: {mcp_config_json}", file=sys.stderr)
            print(f"======================\n", file=sys.stderr)
            sys.stderr.flush()

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,  # Changed from DEVNULL - MCP servers need stdin
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    **env_vars,  # Use manager's environment variables
                }
            )

            # Close stdin since we're in non-interactive mode
            # But keep the pipe open so MCP servers can still function
            if proc.stdin:
                proc.stdin.close()

            try:
                out_bytes, err_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )

                # Write stdout to file
                output_file.write_text(out_bytes.decode("utf-8"))

                return ClaudeJobResult(
                    worker_id=worker_id,
                    returncode=proc.returncode,
                    stdout=out_bytes.decode("utf-8"),
                    stderr=err_bytes.decode("utf-8"),
                    output_file=str(output_file.absolute()),
                )
            except (asyncio.TimeoutError, asyncio.CancelledError) as e:
                proc.kill()
                await proc.wait()
                if isinstance(e, asyncio.TimeoutError):
                    raise ToolError(f"Claude process timed out after {timeout} seconds")
                raise  # Re-raise CancelledError
        finally:
            # Clean up manager from registry
            if worker_id in workers:
                workers[worker_id].socket_mgr = None
    # UnixSocketManager.__aexit__ handles all socket cleanup automatically


def _get_pending_permissions(worker_id: Optional[str] = None) -> List[PermissionRequest]:
    """
    Internal helper: Query pending permissions from socket managers.

    Args:
        worker_id: Optional worker ID to filter by. If not provided, returns all pending permissions.

    Returns:
        List of pending permission requests with details
    """
    results = []
    if worker_id is not None:
        # Get permissions for specific worker
        if worker_id in workers and workers[worker_id].socket_mgr:
            mgr = workers[worker_id].socket_mgr
            results.extend(mgr.get_pending_requests())
    else:
        # Get permissions for all workers
        for worker in workers.values():
            if worker.socket_mgr:
                results.extend(worker.socket_mgr.get_pending_requests())
    return results


@mcp.tool
async def approve_worker_permission(
    worker_id: str,
    request_id: str,
    allow: bool,
    message: Optional[str] = None
) -> dict:
    """
    Approve or deny a worker's pending permission request.

    This tool is called by the main Claude session when a worker requests permission.
    The worker will block until this approval is given.

    Args:
        worker_id: ID of the worker requesting permission
        request_id: Unique ID of the permission request
        allow: True to allow, False to deny
        message: Optional message to include with denial

    Returns:
        Status of the approval including tool details
    """
    # Get worker and its socket manager
    if worker_id not in workers or not workers[worker_id].socket_mgr:
        raise ToolError(
            f"Worker {worker_id} not found or already completed. "
            f"Cannot approve permission request."
        )

    mgr = workers[worker_id].socket_mgr
    return await mgr.approve_request(request_id, allow, message)


async def _flush_completed_tasks(timeout: float) -> tuple[List[CompleteTask], List[FailedTask]]:
    # Use legacy active_tasks dict for backward compat
    if not active_tasks:
        return [], []

    done, _ = await asyncio.wait(
        (task.task for task in active_tasks.values()),
        timeout=timeout,
        return_when=asyncio.FIRST_COMPLETED,
    )
    if not done:
        return [], []

    results = [task.result() for task in done]

    completed = []
    failed = []

    for result in results:
        if result.returncode != 0:
            # Get the active task
            active = active_tasks.pop(result.worker_id)

            # Check if output file exists (partial output)
            output_file_path = Path(result.output_file)
            output_file_str = str(output_file_path.absolute()) if output_file_path.exists() else None

            # Create FailedTask with error hint
            failed_task = FailedTask(
                worker_id=result.worker_id,
                returncode=result.returncode,
                output_file=output_file_str,
                error_hint=_generate_error_hint(result.stderr, result.returncode),
                timeout=active.timeout
            )
            failed.append(failed_task)

            # Push failure event to queue
            get_event_queue().put_nowait(FailureEvent(worker_id=result.worker_id, task=failed_task))

            # Transition ACTIVE -> FAILED in workers dict if exists
            if result.worker_id in workers:
                workers[result.worker_id].status = WorkerStatus.FAILED
                workers[result.worker_id].task = None
        else:
            # Materialize successful completion
            data = json.loads(result.stdout)
            session_id = data.get("session_id")
            if not isinstance(session_id, str):
                raise ToolError(f"Invalid or missing session_id: {session_id}")

            # Get the active task
            active = active_tasks.pop(result.worker_id)

            # Create CompleteTask with output file path
            complete = CompleteTask(
                worker_id=result.worker_id,
                claude_session_id=session_id,
                output_file=result.output_file,
                timeout=active.timeout
            )

            # Push completion event to queue
            get_event_queue().put_nowait(CompletionEvent(worker_id=result.worker_id, task=complete))

            # Transition ACTIVE -> COMPLETED in workers dict if exists
            if result.worker_id in workers:
                workers[result.worker_id].status = WorkerStatus.COMPLETED
                workers[result.worker_id].task = None
                workers[result.worker_id].complete_task = complete

            # Maintain legacy dict for test compatibility
            complete_tasks[result.worker_id] = complete

            completed.append(complete)

    return completed, failed


if __name__ == "__main__":
    mcp.run()
