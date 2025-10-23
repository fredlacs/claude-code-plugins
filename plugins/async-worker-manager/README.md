# Agent Manager

**Async MCP server for managing concurrent Claude Code workers with racing pattern.**

Fire up multiple Claude workers, wait them to completion, and resume conversations seamlessly.

---

## What It Does

Manage multiple Claude Code workers as async subprocesses using a racing pattern:

```
create_async_worker(prompt)           → Spawn worker, returns task_id
wait(timeout)                         → Wait for completion, returns WorkerState
resume_worker(worker_id, message)     → Resume completed worker
approve_worker_permission(...)         → Approve pending permissions
```

---

## Architecture

**Core Concept:** Task-based concurrency with racing pattern

```
┌─────────────────────────────────────────┐
│  Active Tasks (running)                 │
│  [task-1] [task-2] [task-3]             │
│     ↓         ↓         ↓               │
│  claude   claude    claude              │
└─────────────────────────────────────────┘
                  │
            wait()
                  │
                  ↓
         ┌────────────────┐
         │ First to finish │  (winner moved to complete)
         └────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────┐
│  Complete Tasks (awaiting input)        │
│  [winner] ← write_to_worker()           │
└─────────────────────────────────────────┘
```

**Two-Phase Lifecycle:**
1. **Active** - Worker running, awaiting completion
2. **Complete** - Worker finished, awaiting input for resumption

---

## Quick Start

**Install:**
```bash
uv sync
```

**Run Server:**
```bash
uv run python src/server.py
```

**Configure in Claude Code:**
```json
{
  "mcpServers": {
    "agent-manager": {
      "command": "uv",
      "args": ["run", "python", "src/server.py"],
      "cwd": "/path/to/agent-manager"
    }
  }
}
```

---

## Worker Output Files

Workers write output to deterministic file paths for minimal context usage:
- **JSON output**: `logs/worker-{worker_id}.json` (in plugin directory)
- Absolute path returned in `CompleteTask.output_file`

Use bash tools to inspect when needed:
```bash
# Full output
cat logs/worker-{worker_id}.json

# Extract specific fields
jq -r .result logs/worker-{worker_id}.json
jq .total_cost_usd logs/worker-{worker_id}.json
jq .duration_ms logs/worker-{worker_id}.json

# Preview
head -20 logs/worker-{worker_id}.json
```

---

## Example Usage

Use via Claude Code's MCP integration, or programmatically:

```python
from fastmcp import Client
from server import mcp

async with Client(mcp) as client:
    # 1. Create multiple workers with custom timeouts
    task1 = await client.call_tool("create_async_worker", {
        "prompt": "Research Python async patterns",
        "timeout": 600.0  # 10 minutes for complex research
    })
    task2 = await client.call_tool("create_async_worker", {
        "prompt": "Find examples of racing in asyncio",
        "timeout": 300.0  # 5 minutes (default)
    })

    # 2. Wait to find first completion
    state = await client.call_tool("wait", {"timeout": 60.0})
    winner = state["completed"][0]
    print(f"Worker ID: {winner['worker_id']}")
    print(f"Output file: {winner['output_file']}")

    # 3. Access output via file (use bash tools like cat, jq)
    # cat {winner['output_file']}
    # jq -r .result {winner['output_file']}

    # 4. Resume conversation (uses original worker timeout)
    await client.call_tool("resume_worker", {
        "worker_id": winner['worker_id'],
        "message": "Can you elaborate on that?"
    })

    # 5. Wait again for response
    state = await client.call_tool("wait", {"timeout": 60.0})
```

---

## API Reference

### create_async_worker(prompt: str, timeout: float = 300.0) → str

Create a new Claude worker and start it with the given prompt.

**Parameters:**
- `prompt` - The initial prompt for the Claude worker
- `timeout` - Maximum seconds to wait for worker completion (default: 300 seconds / 5 minutes)

**Returns:** `task_id` (UUID string)
**Raises:** ToolError if max workers (10) reached or claude not in PATH

```python
# With default 5-minute timeout
task_id = await client.call_tool("create_async_worker", {
    "prompt": "Explain async/await in Python"
})
# → "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# With custom timeout
task_id = await client.call_tool("create_async_worker", {
    "prompt": "Complex research task",
    "timeout": 600.0  # 10 minutes
})
```

**Note:** The timeout is preserved when resuming the worker via `write_to_worker`.

---

### wait(timeout: float = 30.0) → WorkerState

Wait for workers to complete or request permissions.

**Returns:** `WorkerState` with completed/failed workers and pending permissions
**Raises:** ToolError if no active workers

```python
state = await client.call_tool("wait", {"timeout": 60.0})
# → {
#   "completed": [{"worker_id": "...", "output_file": "/path/to/logs/worker-xyz.json", ...}],
#   "failed": [],
#   "pending_permissions": []
# }
```

**Behavior:**
- Event-driven: Returns instantly when workers complete (<100ms latency)
- Returns WorkerState with file paths to output (not full content)
- Completed workers include `output_file` path for file-based access
- Failed workers include `error_hint` with actionable guidance

---

### resume_worker(worker_id: str, message: str)

Resume a completed worker with new input.

**Returns:** Success confirmation
**Raises:** ToolError if worker not found

```python
await client.call_tool("resume_worker", {
    "worker_id": worker_id,
    "message": "Can you elaborate on that?"
})
```

**Behavior:**
- Uses `claude --resume <session_id>` to continue conversation
- Moves worker back to active state
- Use wait() again to wait for response
- Original timeout is preserved

---

## Use Cases

### 1. Parallel Research Tasks

Create multiple research workers and use the first result that completes:

```python
tasks = []
for topic in ["async patterns", "concurrency models", "event loops"]:
    result = await client.call_tool("create_async_worker", {
        "prompt": f"Research {topic} in Python"
    })
    tasks.append(result.data)

# Get first result
state = await client.call_tool("wait", {"timeout": 120.0})
winner = state["completed"][0]
# Access output: cat {winner['output_file']} | jq -r .result
```

### 2. Interactive Multi-Agent System

Create agents with different specialties and interact with them:

```python
# Create specialized agents
researcher = await client.call_tool("create_async_worker", {
    "prompt": "You are a research specialist. Research async patterns."
})
coder = await client.call_tool("create_async_worker", {
    "prompt": "You are a coding specialist. Write async examples."
})

# Wait to see who finishes first
state = await client.call_tool("wait", {"timeout": 60.0})
winner = state["completed"][0]

# Continue conversation with winner
await client.call_tool("resume_worker", {
    "worker_id": winner["worker_id"],
    "message": "Can you provide more detail?"
})
```

### 3. Task Queue with First-Come-First-Served

Process tasks as they complete rather than waiting for all:

```python
# Create 5 workers with different tasks
for i in range(5):
    await client.call_tool("create_async_worker", {
        "prompt": f"Process task {i}"
    })

# Process results as they complete
while True:
    try:
        state = await client.call_tool("wait", {"timeout": 60.0})
        for worker in state["completed"]:
            # Access output file if needed
            print(f"Completed: {worker['worker_id']}")
            print(f"Output file: {worker['output_file']}")
            # Use: cat {worker['output_file']} | jq -r .result
    except Exception as e:
        if "No active workers" in str(e):
            break  # All workers complete
        raise  # Other error
```

---

## Requirements

- **Python:** 3.13+
- **OS:** macOS or Linux (Unix-based systems)
- **Commands:** `claude` must be in PATH
- **Dependencies:** `fastmcp>=2.12.5`

---

## Development

**Run unit tests (fast, no claude needed):**
```bash
uv run pytest -v -m "not integration" tests/test_server_v2.py
```

**Run integration tests (requires claude):**
```bash
uv run pytest -v -s -m integration tests/test_integration_v2.py
```

**Run all tests:**
```bash
uv run pytest -v
```

---

## How It Works

### 1. Worker Creation
```python
# Spawn claude as subprocess with timeout
proc = await asyncio.create_subprocess_exec(
    "claude", "-p", prompt, "--output-format", "json",
    stdout=PIPE, stderr=PIPE
)

# Wait with timeout, decode output
out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
stdout_str = out.decode('utf-8')

# Create task to wait for completion
task = asyncio.create_task(run_claude_job(prompt, timeout=timeout))
active_tasks.append(ActiveTask(task_id=uuid, task=task, timeout=timeout))
```

### 2. Racing Pattern
```python
# Wait for first completion using asyncio.wait
done, _ = await asyncio.wait(
    [t.task for t in active_tasks],
    return_when=asyncio.FIRST_COMPLETED
)

# Move winner to complete_tasks
winner = next(iter(done))
rc, stdout, stderr = await winner  # Already decoded strings
session_id = parse_claude_output(stdout)  # Extract & validate
complete_tasks.append(CompleteTask(..., timeout=task.timeout))
```

### 3. Session Resumption
```python
# Resume using claude --resume with original timeout
proc = await asyncio.create_subprocess_exec(
    "claude", "--resume", session_id, "-p", new_input,
    stdout=PIPE, stderr=PIPE
)
out, err = await asyncio.wait_for(proc.communicate(), timeout=complete_task.timeout)
```

---

## Configuration

**Max Active Workers:** 10 (only active workers count, complete workers unlimited)
**Default Worker Timeout:** 300 seconds / 5 minutes (configurable per worker)
**Default Wait Timeout:** 30 seconds (configurable per call)
**Transport:** stdio (standard MCP)
**Output Format:** JSON (from claude --output-format json)

**Timeout Behavior:**
- Each worker has its own timeout set at creation time
- Timeout is preserved when resuming via `write_to_worker`
- Different workers can have different timeouts running concurrently

---

## Trade-offs

**Advantages:**
- ✅ True parallelism - workers run concurrently
- ✅ Efficient - wait pattern returns immediately on first completion
- ✅ Session continuity - resume conversations with --resume
- ✅ Simple state - just two lists (active/complete)
- ✅ Async-first - fully non-blocking

**Limitations:**
- ⚠️ No real-time streaming - output available after completion
- ⚠️ Unix-only - requires Unix-like OS for subprocesses
- ⚠️ Memory - stdout/stderr stored in memory per worker
- ⚠️ Max 10 workers - prevent resource exhaustion

---

## Troubleshooting

**"Claude not in PATH"**
```bash
# Ensure claude is installed and accessible
which claude
# Add to PATH if needed
export PATH="/path/to/claude:$PATH"
```

**"Timeout waiting for workers"**
- Increase timeout parameter in wait()
- Check if claude is responding
- Verify prompt is valid

**"Max 10 active workers"**
- Wait for active workers to complete via wait()
- Workers automatically move from active to complete
- Increase max limit in server.py if needed

**"Claude process timed out after X seconds"**
- Worker exceeded its configured timeout
- Increase timeout when creating worker: `create_async_worker(prompt, timeout=600.0)`
- Check if prompt is too complex or requires more time
- Default is 300 seconds (5 minutes)

---

## Roadmap

- [ ] Add worker prioritization
- [ ] Stream output in real-time during execution
- [ ] Support Windows via different subprocess approach

---

## License

MIT
