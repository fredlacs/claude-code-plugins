import asyncio
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError


@dataclass
class WorkerResult:
    worker_id: str
    output_file: str


@dataclass
class WorkerOptions:
    model: Optional[str] = "claude-sonnet-4-5"
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    thinking: Optional[bool] = False
    top_p: Optional[float] = None
    top_k: Optional[int] = None


tasks: Dict[str, asyncio.Task[WorkerResult] | WorkerResult] = {}
mcp = FastMCP("Async Worker Manager")


@mcp.tool
async def spawn_worker(
    description: str,
    prompt: str,
    agent_type: Optional[str] = None,
    options: Optional[WorkerOptions] = None,
) -> str:
    """Spawn a Claude worker (non-blocking, resumable). Returns worker_id."""
    if sum(isinstance(t, asyncio.Task) for t in tasks.values()) >= 10:
        raise ToolError("Max 10 active workers.")

    if options and (options.temperature < 0.0 or options.temperature > 1.0):
        raise ToolError("Temperature must be between 0 and 1")

    worker_id = str(uuid.uuid4())
    tasks[worker_id] = asyncio.create_task(
        run_claude_job(description + prompt, worker_id, agent_type, None, options)
    )
    return worker_id


@mcp.tool
async def resume_worker(
    worker_id: str, prompt: str, options: Optional[WorkerOptions] = None
):
    """Resume a completed worker with new input."""
    _flush_completed_tasks()

    if worker_id not in tasks or isinstance(tasks[worker_id], asyncio.Task):
        raise ToolError(f"Worker {worker_id} not found or still active")

    try:
        path = Path(tasks[worker_id].output_file).resolve()
        session_id = json.loads(path.read_text("utf-8")).get("session_id")
        if not isinstance(session_id, str):
            raise ToolError("Invalid session format")
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        raise ToolError(f"Failed to read worker history: {e}")

    tasks[worker_id] = asyncio.create_task(
        run_claude_job(prompt, worker_id, None, session_id, options)
    )


@mcp.tool
async def wait() -> Dict[str, WorkerResult]:
    active = [t for t in tasks.values() if isinstance(t, asyncio.Task)]
    if not active:
        raise ToolError("No active workers to wait for")
    await asyncio.gather(*active, return_exceptions=True)
    return _flush_completed_tasks()


def _flush_completed_tasks() -> Dict[str, WorkerResult]:
    completed: Dict[str, WorkerResult] = {}
    for worker_id, task in list(tasks.items()):
        if isinstance(task, asyncio.Task) and task.done():
            result = task.result()
            tasks[worker_id] = result
            completed[worker_id] = result
    return completed


async def run_claude_job(
    prompt: str,
    worker_id: str,
    agent_type: Optional[str] = None,
    session_id: Optional[str] = None,
    options: Optional[WorkerOptions] = None,
) -> WorkerResult:
    if options is None:
        options = WorkerOptions()
    if not shutil.which("claude"):
        raise ToolError("Claude not in PATH")

    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    output_file = logs_dir / f"worker-{worker_id}.json"

    plugin_root = os.environ.get(
        "CLAUDE_PLUGIN_ROOT",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    mcp_args = ["run", "--directory", plugin_root, "python3", "src/permission_proxy.py"]
    mcp_server = {"permission_proxy": {"command": "uv", "args": mcp_args}}
    mcp_config_json = json.dumps({"mcpServers": mcp_server})

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

    settings = {
        k: v
        for k, v in {
            "temperature": options.temperature,
            "maxTokens": options.max_tokens,
            "thinking": {"type": "enabled", "budget_tokens": 10000}
            if options.thinking
            else None,
            "topP": options.top_p,
            "topK": options.top_k,
        }.items()
        if v is not None
    }
    # TODO: set enabledPlugins based on explicit allowlist https://docs.claude.com/en/docs/claude-code/settings#plugin-settings
    if settings:
        cmd += ["--settings", json.dumps(settings)]

    cmd += ["-p", prompt, "--output-format", "json"]
    cmd += ["--mcp-config", mcp_config_json]
    cmd += ["--permission-prompt-tool", "mcp__permission_proxy__request_permission"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ},
    )

    if proc.stdin:
        proc.stdin.close()

    try:
        out_bytes, err_bytes = await proc.communicate()
        out_decoded = out_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            output_data = {
                "error_exit_code": proc.returncode,
                "error_stderr": err_bytes.decode("utf-8", errors="replace"),
            }
        else:
            try:
                output_data = json.loads(out_decoded)
            except json.JSONDecodeError:
                output_data = {"result": out_decoded}
    except (asyncio.CancelledError, Exception) as e:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        output_data = {"error_exception": f"{e}"}
    finally:
        try:
            output_file.write_text(json.dumps(output_data, indent=2))
        except Exception:
            pass

    return WorkerResult(worker_id=worker_id, output_file=str(output_file.resolve()))


if __name__ == "__main__":
    mcp.run()
