# Agent Manager

**Async MCP server for managing concurrent Claude Code workers with racing pattern.**

Fire up multiple Claude workers, wait them to completion, and resume conversations seamlessly.

---

## What It Does

Manage multiple Claude Code workers as async subprocesses using a racing pattern:

```
create_async_worker(prompt)      → Spawn worker, returns task_id
wait(timeout)             → Wait for first completion, returns winner
peek(worker_id)                   → View stdout/stderr of complete worker
write_to_worker(worker_id, input) → Resume completed worker
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
    winner = await client.call_tool("wait", {"timeout": 60.0})
    print(f"Winner: {winner}")

    # 3. Peek at the output
    result = await client.call_tool("peek", {"worker_id": winner})
    print(f"Output: {result['stdout']}")

    # 4. Resume conversation (uses original worker timeout)
    await client.call_tool("write_to_worker", {
        "worker_id": winner,
        "input": "Can you elaborate on that?"
    })

    # 5. Wait again for response
    winner = await client.call_tool("wait", {"timeout": 60.0})
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

### wait(timeout: float = 30.0) → str

Wait for the first active worker to complete.

**Returns:** `task_id` of winning worker
**Raises:** ToolError on timeout or if no active workers

```python
winner = await client.call_tool("wait", {"timeout": 60.0})
# → "a1b2c3d4-..."
```

**Behavior:**
- Moves winner from active → complete
- Returns immediately when any worker finishes
- Times out if no worker completes within timeout

---

### peek(worker_id: str) → dict

View stdout/stderr of a complete worker.

**Returns:** dict with status, stdout, stderr
**Raises:** ToolError if worker not found or not complete

```python
result = await client.call_tool("peek", {"worker_id": task_id})
```

**Response format:**

```json
{
  "task_id": "...",
  "status": "complete",
  "session_id": "session-123",
  "stdout": "Hello world!",
  "stderr": ""
}
```

---

### write_to_worker(worker_id: str, input: str) → dict

Resume a completed worker with new input.

**Returns:** Success message
**Raises:** ToolError if worker not found or not in complete state

```python
result = await client.call_tool("write_to_worker", {
    "worker_id": task_id,
    "input": "Can you elaborate on that?"
})
# → {"success": true, "message": "Resumed worker ..."}
```

**Behavior:**
- Worker must be in complete state (after wait)
- Uses `claude --resume <session_id>` to continue conversation
- Moves worker back to active state
- Use wait() again to wait for response

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
winner = await client.call_tool("wait", {"timeout": 120.0})
result = await client.call_tool("peek", {"worker_id": winner})
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
winner = await client.call_tool("wait", {"timeout": 60.0})

# Continue conversation with winner
await client.call_tool("write_to_worker", {
    "worker_id": winner,
    "input": "Can you provide more detail?"
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
        winner = await client.call_tool("wait", {"timeout": 60.0})
        result = await client.call_tool("peek", {"worker_id": winner})
        print(f"Completed: {result['stdout']}")
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
