import asyncio
from dataclasses import dataclass
import json
import os
import shutil
import uuid
from asyncio import Task
from pathlib import Path
from typing import Dict, List, Optional
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError


@dataclass
class ClaudeJobResult:
    worker_id: str
    output_file: str  # Absolute path to logs/worker-{id}.json


@dataclass
class CompleteTask:
    conversation_history_file_path: str  # Absolute path to logs/worker-{id}.json


@dataclass
class WorkerOptions:
    model: Optional[str] = "claude-sonnet-4-5"
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    thinking: Optional[bool] = False
    top_p: Optional[float] = None
    top_k: Optional[int] = None


complete_tasks: Dict[str, CompleteTask] = {}
active_tasks: Dict[str, Task[ClaudeJobResult]] = {}

mcp = FastMCP("Async Worker Manager")


@mcp.tool
async def spawn_worker(
    description: str,
    prompt: str,
    agent_type: Optional[str] = None,
    options: Optional[WorkerOptions] = None,
) -> str:
    """
    Spawn a Claude worker (like Task but non-blocking and able to resume). Returns worker_id.

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
    if len(active_tasks) >= 10:
        raise ToolError("Max 10 active workers.")

    worker_id = str(uuid.uuid4())
    task = asyncio.create_task(
        run_claude_job(
            prompt=prompt, worker_id=worker_id, agent_type=agent_type, options=options
        )
    )
    active_tasks[worker_id] = task
    return worker_id


@mcp.tool
async def resume_worker(
    worker_id: str, prompt: str, options: Optional[WorkerOptions] = None
):
    """Resume a completed worker with new input."""
    _ = _flush_completed_tasks()

    # Read phase - validate everything before any mutations
    complete_task = complete_tasks.get(worker_id)
    if complete_task is None:
        raise ToolError(f"Worker {worker_id} not found. maybe still working")

    # Validate session file
    try:
        path = Path(complete_task.conversation_history_file_path).resolve()
        stdout: dict = json.loads(path.read_text("utf-8"))
        session_id = stdout.get("session_id")
        if not isinstance(session_id, str):
            raise ToolError("invalid std out format without session id")
    except FileNotFoundError:
        raise ToolError(f"Conversation history file not found: {complete_task.conversation_history_file_path}")
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON in conversation history: {e}")
    except OSError as e:
        raise ToolError(f"Failed to read conversation history: {e}")

    # Create new task
    new_task = asyncio.create_task(
        run_claude_job(
            prompt=prompt,
            worker_id=worker_id,
            agent_type=None,  # we assume agent type is still used given session id resumes convo history
            session_id=session_id,
            options=options,
        )
    )

    del complete_tasks[worker_id]
    active_tasks[worker_id] = new_task


@mcp.tool
async def wait() -> Dict[str, CompleteTask]:
    if not active_tasks:
        raise ToolError("No active workers to wait for")
    # await for all active tasks
    _ = await asyncio.gather(*active_tasks.values())
    return _flush_completed_tasks()


def _flush_completed_tasks() -> Dict[str, CompleteTask]:
    """Flush completed tasks - only track completions, remove from active."""
    # Build new completions locally (read phase - no mutations)
    new_complete: Dict[str, CompleteTask] = {}

    for worker_id, task in active_tasks.items():
        if not task.done():
            continue  # Skip still-active tasks

        # Task is done - try to get result
        try:
            result = task.result()
            path = Path(result.output_file).resolve()
            ct = CompleteTask(conversation_history_file_path=str(path))
            new_complete[worker_id] = ct
        except Exception:
            # On error: don't update globals (original state preserved), re-raise immediately
            raise

    # Write phase - atomic update (add to complete first, then delete from active)
    # This prevents race condition where worker exists in neither dict
    complete_tasks.update(new_complete)
    for worker_id in new_complete.keys():
        del active_tasks[worker_id]

    return new_complete


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

    # Get plugin root for uv run --directory
    plugin_root = os.environ.get(
        "CLAUDE_PLUGIN_ROOT",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )

    # Create MCP config JSON for permission proxy server
    # Use uv run with python -m to properly handle package imports
    mcp_config = {
        "mcpServers": {
            "permission_proxy": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    plugin_root,
                    "python3",
                    "src/permission_proxy.py",
                ],
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
        "-p",
        prompt,
        "--output-format",
        "json",
        "--mcp-config",
        mcp_config_json,
        "--permission-prompt-tool",
        "mcp__permission_proxy__request_permission",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ},
    )

    # Close stdin since we're in non-interactive mode
    # But keep the pipe open so MCP servers can still function
    if proc.stdin:
        proc.stdin.close()

    try:
        # No timeout - wait indefinitely for completion
        out_bytes, err_bytes = await proc.communicate()

        # Write stdout to file
        try:
            output_file.write_text(out_bytes.decode("utf-8"))
        except OSError as e:
            raise ToolError(f"Failed to write output file: {e}")

        # Check returncode - raise on failure
        if proc.returncode != 0:
            stderr_preview = err_bytes.decode("utf-8")[:200]
            raise ToolError(
                f"Worker {worker_id} failed with exit code {proc.returncode}. "
                f"stderr: {stderr_preview}"
            )

        return ClaudeJobResult(
            worker_id=worker_id,
            output_file=str(output_file.absolute()),
        )
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise  # Re-raise CancelledError
    except Exception:
        # Kill process on any error to prevent leaks
        proc.kill()
        await proc.wait()
        raise


if __name__ == "__main__":
    mcp.run()
