import asyncio
from itertools import chain
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
    ClaudeJobResult,
    CompleteTask,
    CompletionEvent,
    FailedTask,
    FailureEvent,
    PermissionRequest,
    Worker,
    WorkerOptions,
    WorkerState,
    WorkerStatus,
)
from .unix_socket_manager import UnixSocketManager


mcp = FastMCP("Async Worker Manager")
workers: Dict[str, Worker] = {}

# Event queue for worker completion/failure/permission notifications
# Lazy-initialized to avoid event loop binding issues
_event_queue: Optional[Queue] = None


def get_event_queue() -> Queue:
    """Get the event queue for worker notifications.

    Lazy-initializes the queue in the current event loop to avoid
    "Queue is bound to a different event loop" errors in tests.
    """
    global _event_queue
    if _event_queue is None:
        _event_queue = Queue()
    return _event_queue



@mcp.tool
async def spawn_worker(
    description: str,
    prompt: str,
    agent_type: Optional[str] = None,
    options: Optional[WorkerOptions] = None,
) -> str:
    """
    Spawn a Claude worker (like Task but non-blocking). Returns worker_id.

    Args:
        description: Short 3-5 word description of the task
        prompt: Detailed instructions for the worker
        agent_type: Optional agent role/persona (built-in: "Explore", "general-purpose"
                    or custom: "You are a security expert...")
        options: Optional settings dict with:
            - model: Claude model (default: claude-sonnet-4-5)
            - temperature: Randomness 0.0-1.0 (default: 1.0)
            - max_tokens: Max generation tokens
            - thinking: Enable extended thinking (default: False)
            - top_p: Nucleus sampling probability
            - top_k: Top-k sampling limit

    Returns:
        worker_id (UUID string)
    """

    # Parse options
    if options is None:
        options = WorkerOptions()

    # Count active workers
    active_count = sum(1 for w in workers.values() if w.status == WorkerStatus.ACTIVE)
    if active_count >= 10:
        raise ToolError("Max 10 active workers.")

    worker_id = str(uuid.uuid4())
    task = asyncio.create_task(
        run_claude_job(
            prompt=prompt,
            worker_id=worker_id,
            agent_type=agent_type,
            options=options
        )
    )

    # Create unified Worker entry with ACTIVE status
    workers[worker_id] = Worker(
        worker_id=worker_id,
        status=WorkerStatus.ACTIVE,
        task=task,
        agent_type=agent_type,
    )

    return worker_id


@mcp.tool
async def resume_worker(
    worker_id: str, prompt: str, options: Optional[WorkerOptions] = None
):
    """Resume a completed worker with new input."""
    # Check if worker exists
    if worker_id not in workers:
        raise ToolError(f"Worker {worker_id} not found")

    worker = workers[worker_id]

    # Try to flush if worker is still active
    if worker.status == WorkerStatus.ACTIVE:
        _, _ = await _flush_completed_tasks(timeout=0.0)
        # Re-check status after flush
        if worker_id not in workers:
            raise ToolError(f"Worker {worker_id} not found")
        worker = workers[worker_id]

    # Check if worker is completed
    if worker.status != WorkerStatus.COMPLETED:
        raise ToolError(f"Worker {worker_id} is not in completed state (current: {worker.status})")

    # Get the complete task info
    if not worker.complete_task:
        raise ToolError(f"Worker {worker_id} has no completion data")

    session_id = worker.complete_task.claude_session_id

    # Create new task for resumption
    new_task = asyncio.create_task(
        run_claude_job(
            prompt=prompt,
            worker_id=worker_id,
            agent_type=worker.agent_type,
            session_id=session_id,
            options=options,
        )
    )

    # Transition COMPLETED -> ACTIVE
    worker.status = WorkerStatus.ACTIVE
    worker.task = new_task
    worker.complete_task = None


@mcp.tool
async def wait() -> WorkerState:
    """
    Wait for ALL active workers to complete or fail.

    Blocks until all pending workers finish. Returns all results.
    Primary pattern: spawn multiple workers, then wait for all results.

    Returns:
        WorkerState with lists of:
        - completed: Successfully completed workers with conversation_history_file_path
        - failed: Failed workers with error hints
        - pending_permissions: Workers awaiting permission approval (if any)

    Usage:
        # Batch mode (recommended)
        spawn_worker("Task 1", "...")
        spawn_worker("Task 2", "...")
        spawn_worker("Task 3", "...")
        result = wait()  # Blocks until ALL complete

        # Access conversation histories
        for worker in result.completed:
            # Read: cat {worker.conversation_history_file_path}
            pass
    """
    # Check if there are any active workers
    active_workers = [w for w in workers.values() if w.status == WorkerStatus.ACTIVE]
    if not active_workers:
        raise ToolError("No active workers to wait for")

    # Wait until ALL workers complete or permissions needed
    POLL_INTERVAL = 5.0

    while True:
        # Check for active workers
        active_workers = [w for w in workers.values() if w.status == WorkerStatus.ACTIVE]
        if not active_workers:
            break

        # Check for immediate completions
        completed, failed = await _flush_completed_tasks(timeout=0.0)
        pending_perms = _get_pending_permissions()

        # Return if any permissions are pending (to avoid deadlock)
        if pending_perms:
            return WorkerState(
                completed=completed,
                failed=failed,
                pending_permissions=pending_perms
            )

        # Check again if all workers done
        active_workers = [w for w in workers.values() if w.status == WorkerStatus.ACTIVE]
        if not active_workers:
            return WorkerState(
                completed=completed,
                failed=failed,
                pending_permissions=pending_perms
            )

        # Wait for next event or poll interval
        try:
            event = await asyncio.wait_for(get_event_queue().get(), timeout=POLL_INTERVAL)
            # Event received, loop continues to check if all done
        except asyncio.TimeoutError:
            # Timeout, loop continues to poll
            pass

    # All workers complete
    completed, failed = await _flush_completed_tasks(timeout=0.0)
    pending_perms = _get_pending_permissions()
    return WorkerState(
        completed=completed,
        failed=failed,
        pending_permissions=pending_perms
    )


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
    prompt: str,
    worker_id: str,
    agent_type: Optional[str] = None,
    session_id: Optional[str] = None,
    options: Optional[WorkerOptions] = None,
) -> ClaudeJobResult:
    """Spawn Claude subprocess with Unix domain socket for permission requests."""
    if options is None:
        options = WorkerOptions()

    if not shutil.which("claude"):
        raise ToolError("Claude not in PATH")

    # Create logs directory
    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    output_file = logs_dir / f"worker-{worker_id}.json"


    # Use UnixSocketManager context manager for socket lifecycle
    async with UnixSocketManager(worker_id, get_event_queue()) as socket_mgr:
        # Register manager in unified worker registry
        if worker_id in workers:
            workers[worker_id].socket_mgr = socket_mgr

        try:
            # Get plugin root for uv run --directory
            plugin_root = os.environ.get('CLAUDE_PLUGIN_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

            # Create MCP config JSON for permission proxy server
            # Use uv run with python -m to properly handle package imports
            mcp_config = {
                "mcpServers": {
                    "permission_proxy": {
                        "command": "uv",
                        "args": [
                            "run",
                            "--directory", plugin_root,
                            "python", "-m", "src.permission_proxy"
                        ]
                    }
                }
            }
            mcp_config_json = json.dumps(mcp_config)

            cmd = ["claude"]
            if session_id:
                cmd += ["--resume", session_id]

            if options.model:
                cmd += ["--model", options.model]

            if agent_type:
                cmd += [
                    "--system-prompt",
                    f"You are an agent. this is your description:\n{agent_type}",
                ]


            settings = {}
            if options.temperature is not None:
                settings["temperature"] = options.temperature
            if options.max_tokens is not None:
                settings["maxTokens"] = options.max_tokens
            if options.thinking:
                settings["thinking"] = {"type": "enabled", "budget_tokens": 10000}
            if options.top_p is not None:
                settings["topP"] = options.top_p
            if options.top_k is not None:
                settings["topK"] = options.top_k

            if settings:
                settings_json = json.dumps(settings)
                cmd += ["--settings", settings_json]

            # Add core arguments
            cmd += [
                "-p", prompt,
                "--output-format", "json",
                "--mcp-config", mcp_config_json,
                "--permission-prompt-tool", "mcp__permission_proxy__request_permission",
            ]

            env_vars = socket_mgr.get_env_vars()
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
                # No timeout - wait indefinitely for completion
                out_bytes, err_bytes = await proc.communicate()

                # Write stdout to file
                output_file.write_text(out_bytes.decode("utf-8"))

                return ClaudeJobResult(
                    worker_id=worker_id,
                    returncode=proc.returncode,
                    stdout=out_bytes.decode("utf-8"),
                    stderr=err_bytes.decode("utf-8"),
                    output_file=str(output_file.absolute()),
                )
            except asyncio.CancelledError:
                proc.kill()
                await proc.wait()
                raise  # Re-raise CancelledError
        finally:
            # Clean up manager from registry
            if worker_id in workers:
                workers[worker_id].socket_mgr = None
    # UnixSocketManager.__aexit__ handles all socket cleanup automatically


def _get_pending_permissions() -> List[PermissionRequest]:
    """Query pending permissions from socket managers."""
    return list(chain.from_iterable(
        w.socket_mgr.get_pending_requests()
        for w in workers.values()
        if w.socket_mgr is not None
    ))


@mcp.tool
async def approve_permission(
    request_id: str,
    worker_id: str,
    allow: bool,
    reason: Optional[str] = None
) -> dict:
    """
    Approve or deny a worker's permission request.

    Unblocks the worker waiting for permission decision.
    Call wait() again after this to get next event.

    Args:
        request_id: Unique ID of the permission request (from PermissionNeeded)
        worker_id: ID of the worker making the request (from PermissionRequest.worker_id)
        allow: True to allow, False to deny
        reason: Optional reason for denial

    Returns:
        Status of the approval including tool details
    """
    if worker_id not in workers:
        raise ToolError(
            f"Worker {worker_id} not found. "
            f"Worker may have already completed or been removed."
        )

    worker = workers[worker_id]

    if not worker.socket_mgr:
        raise ToolError(
            f"Worker {worker_id} has no active socket manager. "
            f"Worker may have already completed."
        )

    return await worker.socket_mgr.approve_request(request_id, allow, reason)


async def _flush_completed_tasks(timeout: float) -> tuple[List[CompleteTask], List[FailedTask]]:
    # Get all active workers
    active_workers = {wid: w for wid, w in workers.items() if w.status == WorkerStatus.ACTIVE and w.task}
    if not active_workers:
        return [], []

    done, _ = await asyncio.wait(
        (w.task for w in active_workers.values()),
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
            # Check if output file exists (partial output)
            output_file_path = Path(result.output_file)
            output_file_str = str(output_file_path.absolute()) if output_file_path.exists() else None

            # Create FailedTask with error hint
            failed_task = FailedTask(
                worker_id=result.worker_id,
                returncode=result.returncode,
                conversation_history_file_path=output_file_str,
                error_hint=_generate_error_hint(result.stderr, result.returncode),
            )
            failed.append(failed_task)

            # Push failure event to queue
            get_event_queue().put_nowait(FailureEvent(worker_id=result.worker_id, task=failed_task))

            # Transition ACTIVE -> FAILED in workers dict
            if result.worker_id in workers:
                workers[result.worker_id].status = WorkerStatus.FAILED
                workers[result.worker_id].task = None
        else:
            # Materialize successful completion
            data = json.loads(result.stdout)
            session_id = data.get("session_id")
            if not isinstance(session_id, str):
                raise ToolError(f"Invalid or missing session_id: {session_id}")

            # Create CompleteTask with conversation history file path
            complete = CompleteTask(
                worker_id=result.worker_id,
                claude_session_id=session_id,
                conversation_history_file_path=result.output_file,
            )

            # Push completion event to queue
            get_event_queue().put_nowait(CompletionEvent(worker_id=result.worker_id, task=complete))

            # Transition ACTIVE -> COMPLETED in workers dict
            if result.worker_id in workers:
                workers[result.worker_id].status = WorkerStatus.COMPLETED
                workers[result.worker_id].task = None
                workers[result.worker_id].complete_task = complete

            completed.append(complete)

    return completed, failed


if __name__ == "__main__":
    mcp.run()
