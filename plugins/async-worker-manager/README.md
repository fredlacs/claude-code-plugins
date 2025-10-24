# Async Worker Manager

**Task tool, but async + resumable**

Spawn multiple Claude instances as async workers using the same API as the Task tool. Workers run until completion, write conversation histories to files for minimal context usage, and support multi-turn resumption.

---

## Quick Start

**Install:**
```bash
uv sync
```

**Configure in Claude Code:**
```json
{
  "mcpServers": {
    "async-worker-manager": {
      "command": "uv",
      "args": ["run", "python", "src/server.py"],
      "cwd": "/path/to/async-worker-manager"
    }
  }
}
```

**Basic Usage (Same as Task):**
```python
# Spawn workers
id1 = spawn_worker("Research", "Research Python async patterns")
id2 = spawn_worker("Analyze", "Analyze codebase architecture")

# Wait for ALL to complete
result = wait()

# Access results
for worker in result.completed:
    # cat {worker.conversation_history_file_path}
    pass
```

---

## API Reference

### spawn_worker

```python
spawn_worker(
    description: str,
    prompt: str,
    agent_type: Optional[str] = None,
    options: Optional[dict] = None
) -> str  # worker_id
```

Spawn a Claude worker (non-blocking). **Same parameters as Task tool.**

**Parameters:**
- `description`: Short 3-5 word task description
- `prompt`: Detailed instructions
- `agent_type`: Optional agent specialization
  - `"general-purpose"` - General tasks
  - `"Explore"` - Fast codebase exploration
  - `"statusline-setup"` - Status line configuration
  - `"output-style-setup"` - Output style configuration
- `options`: Optional settings dict (see Advanced Options below)

**Returns:** `worker_id` (UUID string)

**Examples:**

```python
# Basic (same as Task)
id = spawn_worker("Research", "Research async patterns")

# With agent type
id = spawn_worker("Find files", "Find all .env files", agent_type="Explore")

# With options
id = spawn_worker(
    "Quick check",
    "Check for syntax errors",
    options={"model": "claude-haiku-4", "temperature": 0.3}
)
```

---

### wait

```python
wait() -> WorkerState
```

Wait for ALL active workers to complete or permissions to be needed.

**Returns:**
```python
{
    "completed": [
        {
            "worker_id": "...",
            "claude_session_id": "...",
            "conversation_history_file_path": "/path/to/logs/worker-{id}.json"
        }
    ],
    "failed": [
        {
            "worker_id": "...",
            "returncode": 1,
            "conversation_history_file_path": "/path/to/logs/worker-{id}.json",
            "error_hint": "Brief error description"
        }
    ],
    "pending_permissions": [
        {
            "request_id": "...",
            "worker_id": "...",
            "tool": "Bash",
            "input": {"command": "ls"}
        }
    ]
}
```

**Examples:**

```python
# Batch mode
spawn_worker("Task 1", "...")
spawn_worker("Task 2", "...")
result = wait()  # Blocks until both complete

# Sequential mode
spawn_worker("Task", "...")
result = wait()
spawn_worker("Next", "...")
result = wait()
```

---

### resume_worker

```python
resume_worker(worker_id: str, prompt: str)
```

Resume a completed worker with follow-up prompt. **Extends Task tool with resumability.**

**Examples:**

```python
id = spawn_worker("Analyze", "Analyze this codebase")
result = wait()

resume_worker(id, "What about test coverage?")
result = wait()

resume_worker(id, "Suggest improvements")
result = wait()
```

---

### approve_permission

```python
approve_permission(request_id: str, allow: bool, reason: Optional[str] = None)
```

Approve or deny worker permission request.

**Example:**

```python
id = spawn_worker("System check", "Analyze /etc files")

while True:
    result = wait()

    for perm in result.pending_permissions:
        approve_permission(perm.request_id, allow=True)

    if result.completed:
        break
```

---

## Advanced Options

The `options` parameter accepts:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `model` | str | `"claude-sonnet-4-5"` | Model to use |
| `system` | str | None | Custom system prompt |
| `temperature` | float | 1.0 | Randomness (0.0-1.0) |
| `max_tokens` | int | 4096 | Max generation tokens |
| `thinking` | bool | False | Enable extended thinking |
| `top_p` | float | None | Nucleus sampling |
| `top_k` | int | None | Top-k sampling |

**Examples:**

```python
# Different model
spawn_worker("Quick scan", "...", options={"model": "claude-haiku-4"})

# Custom system prompt
spawn_worker("Security review", "...", options={
    "system": "You are a security expert. Focus on vulnerabilities."
})

# Temperature sweep (same prompt, different creativity)
for temp in [0.0, 0.5, 1.0]:
    spawn_worker(f"Temp {temp}", "Generate function names", options={
        "temperature": temp
    })

# Extended thinking
spawn_worker("Complex design", "Design a caching system", options={
    "thinking": True,
    "max_tokens": 8192
})
```

---

## Comparison with Task Tool

| Feature | Task Tool | Async Workers |
|---------|-----------|---------------|
| **Core API** | ✅ `description`, `prompt`, `agent_type` | ✅ Same |
| **Blocking** | Yes (fire & forget) | No (spawn returns immediately) |
| **Parallel** | Automatic | Explicit (spawn → wait) |
| **Resumable** | No | ✅ Yes (resume_worker) |
| **Permissions** | Automatic | Explicit (approve_permission) |
| **Output** | Inline text | File paths (98% smaller) |
| **Options** | All Task params | ✅ Same (via options dict) |

**Use Task when:** You want fire-and-forget parallel execution with inline results

**Use Async Workers when:** You need:
- Explicit control over when to wait
- Multi-turn conversations (resume)
- Minimal context usage (file-based output)
- Permission approval control

---

## Conversation History Files

Workers write to `logs/worker-{id}.json` containing:
- Full conversation history
- Result text
- Session ID (for resume)
- Cost tracking
- Model settings

**Access via bash:**

```bash
# From result
worker = result.completed[0]
file = worker.conversation_history_file_path

# Read full output
cat {file}

# Extract fields
jq -r .result {file}           # Response text
jq .total_cost_usd {file}       # Cost
jq .model {file}                # Model used
jq .session_id {file}           # For resume

# Compare costs across workers
for f in logs/worker-*.json; do
    echo "$(jq -r .model $f): \$$(jq .total_cost_usd $f)"
done
```

**Benefits:**
- 98% context reduction (file path vs full output)
- Persistent records for later review
- Easy comparison with jq/grep
- Cost tracking

---

## Use Cases

### Temperature Sweep
```python
prompt = "Generate creative function names for auth service"

for temp in [0.0, 0.5, 1.0]:
    spawn_worker(f"Temp {temp}", prompt, options={"temperature": temp})

result = wait()
# Compare: deterministic → balanced → creative
```

### Model Racing
```python
# Compare speed vs quality
haiku = spawn_worker("Fast", "...", options={"model": "claude-haiku-4"})
sonnet = spawn_worker("Deep", "...", options={"model": "claude-sonnet-4-5"})

result = wait()
```

### Multi-Perspective Code Review
```python
personas = [
    ("Security", "You are a security auditor"),
    ("Performance", "You are a performance engineer"),
]

for name, system in personas:
    spawn_worker(name, "Review this code", options={"system": system})

result = wait()
# Get different expert perspectives
```

---

## Requirements

- **Python:** 3.13+
- **OS:** macOS or Linux (Unix sockets)
- **Commands:** `claude` in PATH
- **Dependencies:** `fastmcp>=2.12.5`

---

## Development

**Run tests:**
```bash
uv run pytest -v
```

**Debug workers:**
```bash
cat logs/worker-{id}.json | jq .
```

---

## License

MIT
