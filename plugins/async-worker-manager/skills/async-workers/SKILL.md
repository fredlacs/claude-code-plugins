---
name: async-workers
description: Parallel Claude workers. Same API as Task tool, but async + resumable. Batch mode: spawn multiple, wait() returns all. Sequential: spawn one, wait(), repeat.
---

# Async Workers

**Task tool, but async + resumable**

## Core API (Same as Task)

```
# Spawn worker (non-blocking)
mcp://async_worker_manager/spawn_worker(
    description="Short task name",
    prompt="Detailed instructions",
    agent_type="general-purpose"  # Optional: "Explore", etc
)
→ Returns: worker_id

# Wait for ALL workers to complete
mcp://async_worker_manager/wait()
→ Returns: {completed: [...], failed: [...], pending_permissions: [...]}

# Access conversation history via result.completed[].conversation_history_file_path
```

## Primary Pattern: Batch Mode

```
# 1. Spawn multiple workers (like Task)
mcp://async_worker_manager/spawn_worker("Research", "Research Python async", agent_type="general-purpose")
mcp://async_worker_manager/spawn_worker("Explore", "Find config files", agent_type="Explore")
mcp://async_worker_manager/spawn_worker("Compare", "Compare approaches")

# 2. Wait for ALL to complete
mcp://async_worker_manager/wait()
→ Returns: result with completed, failed, pending_permissions

# 3. Access results via bash
```

```sh
tail -20 logs/worker-{id}.json
```

## Task Tool Comparison

| Feature | Task Tool | Async Workers |
|---------|-----------|---------------|
| **API** | `Task(description, prompt, agent_type)` | `spawn_worker(description, prompt, agent_type)` |
| **Blocking** | Yes (fire & forget) | No (spawn returns immediately) |
| **Resumable** | No | Yes (resume_worker) |
| **Batch** | Automatic | Explicit (spawn → wait) |
| **Output** | Inline text | File paths (98% smaller) |

## Additional Tools

```
# Resume completed worker (extends Task)
mcp://async_worker_manager/resume_worker(worker_id, prompt="Follow-up question")

# Approve permissions
mcp://async_worker_manager/approve_permission(request_id, allow=True)
```

## Advanced Options

For custom model/settings (optional):

```
mcp://async_worker_manager/spawn_worker(
    description="Task",
    prompt="Instructions",
    agent_type="general-purpose",  # Or custom: "You are a security expert..."
    options={
        "model": "claude-haiku-4",      # Fast/cheap model
        "temperature": 0.5,              # More focused (0.0-1.0)
        "max_tokens": 8192,
        "thinking": True,                # Enable extended thinking
        "top_p": 0.9,
        "top_k": 50
    }
)
```

**Key Features:**
- **Same as Task**: description, prompt, agent_type parameters
- **Async execution**: spawn returns immediately, use wait()
- **Resumable**: Multi-turn conversations via resume_worker
- **File output**: low context usage (file paths with output)
- **No timeout**: Workers run until completion

## Output File Schema

Every worker writes to `logs/worker-{id}.json`:

```json
{
  "result": "Worker's final response text",
  "session_id": "uuid-string-for-resume_worker",
  "model": "claude-sonnet-4-5",
  "total_cost_usd": 0.0234,
  "permission_denials": [],
  "messages": [
    {
      "role": "user",
      "content": "..."
    },
    {
      "role": "assistant",
      "content": "..."
    }
  ]
}
```

Access via `worker.conversation_history_file_path` from completed workers.

---

[examples.md](examples.md) - Multi-agent patterns, model comparisons, resume flows
