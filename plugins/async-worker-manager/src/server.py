from dataclasses import dataclass
import asyncio
import json
import shutil
import uuid
from typing import Dict, List, Optional
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError


@dataclass
class ClaudeJobResult:
    worker_id: str
    returncode: int
    stdout: str
    stderr: str


@dataclass
class ActiveTask:
    worker_id: str
    task: asyncio.Task[ClaudeJobResult]
    timeout: float


@dataclass
class CompleteTask:
    worker_id: str
    claude_session_id: str
    std_out: str
    std_err: str
    timeout: float


mcp = FastMCP("Async Worker Manager")
active_tasks: Dict[str, ActiveTask] = {}
complete_tasks: Dict[str, CompleteTask] = {}


@mcp.tool
async def create_async_worker(prompt: str, timeout: float = 300.0) -> str:
    """Create async Claude worker. Returns worker_id or raises ToolError."""
    if len(active_tasks) >= 10:
        raise ToolError("Max 10 active workers.")
    worker_id = str(uuid.uuid4())
    task = asyncio.create_task(run_claude_job(prompt, timeout, worker_id))
    active_tasks[worker_id] = ActiveTask(worker_id, task, timeout)
    return worker_id


@mcp.tool
async def peek(worker_id: str) -> CompleteTask:
    """Peek at stdout/stderr of a worker."""
    if worker_id in active_tasks:
        _ = await _flush_completed_tasks(timeout=0.0)
    if worker_id not in complete_tasks:
        raise ToolError(f"Worker {worker_id} not found or not complete. try wait")
    return complete_tasks[worker_id]


@mcp.tool
async def write_to_worker(worker_id: str, message: str):
    """Send message to worker and resume conversation."""
    if worker_id in active_tasks:
        _ = await _flush_completed_tasks(timeout=0.0)
    if worker_id not in complete_tasks:
        raise ToolError(f"Worker {worker_id} not found in complete tasks")

    complete_task = complete_tasks.pop(worker_id)
    new_task = asyncio.create_task(
        run_claude_job(
            message,
            complete_task.timeout,
            worker_id,
            session_id=complete_task.claude_session_id,
        )
    )
    active_tasks[worker_id] = ActiveTask(worker_id, new_task, complete_task.timeout)


@mcp.tool
async def wait(
    timeout: float = 30.0, worker_id: Optional[str] = None
) -> List[CompleteTask]:
    """Wait for first workers to complete. Returns list of CompleteTasks."""
    start_time = asyncio.get_event_loop().time()
    if worker_id is None:
        return await _flush_completed_tasks(timeout)

    if worker_id in complete_tasks:
        return [complete_tasks[worker_id]]
    if worker_id not in active_tasks:
        raise ToolError(f"Worker {worker_id} not found in active tasks")

    while worker_id not in complete_tasks:
        elapsed = asyncio.get_event_loop().time() - start_time
        remaining_timeout = timeout - elapsed
        if remaining_timeout <= 0:
            raise ToolError(f"Timeout after {timeout}s waiting for worker {worker_id}")
        await _flush_completed_tasks(min(remaining_timeout, 0.5))
        await asyncio.sleep(0.5)
    return [complete_tasks[worker_id]]


async def run_claude_job(
    prompt: str, timeout: float, worker_id: str, session_id: Optional[str] = None
) -> ClaudeJobResult:
    """Spawn Claude."""
    if not shutil.which("claude"):
        raise ToolError("Claude not in PATH")
    cmd = ["claude"]
    if session_id:
        cmd += ["--resume", session_id]
    cmd += ["-p", prompt, "--output-format", "json"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        out_bytes, err_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return ClaudeJobResult(
            worker_id=worker_id,
            returncode=proc.returncode,
            stdout=out_bytes.decode("utf-8"),
            stderr=err_bytes.decode("utf-8"),
        )
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        proc.kill()
        await proc.wait()
        if isinstance(e, asyncio.TimeoutError):
            raise ToolError(f"Claude process timed out after {timeout} seconds")
        raise  # Re-raise CancelledError


async def _flush_completed_tasks(timeout: float) -> List[CompleteTask]:
    if not active_tasks:
        raise ToolError("No active workers to flush")

    done, _ = await asyncio.wait(
        (task.task for task in active_tasks.values()),
        timeout=timeout,
        return_when=asyncio.FIRST_COMPLETED,
    )
    if not done:
        return []

    results = [task.result() for task in done]
    failures = [r for r in results if r.returncode != 0]
    if len(failures) > 0:
        raise ToolError("One or more workers failed")

    def materialize(result: ClaudeJobResult) -> CompleteTask:
        data = json.loads(result.stdout)
        session_id = data.get("session_id")
        if not isinstance(session_id, str):
            raise ToolError(f"Invalid or missing session_id: {session_id}")

        active = active_tasks.pop(result.worker_id)
        complete = CompleteTask(
            result.worker_id,
            session_id,
            result.stdout,
            result.stderr,
            active.timeout,
        )
        complete_tasks[result.worker_id] = complete
        return complete

    return [materialize(result) for result in results]


if __name__ == "__main__":
    mcp.run()
