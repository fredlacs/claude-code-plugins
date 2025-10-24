---
name: async-workers
description: Task tool replacement. Same API (description, prompt, agent_type), but async, resumable, and explicit control. Use spawn_worker() instead of Task(). Batch mode - spawn multiple, wait() returns all. Permissions auto-approved.
---

# Async Workers

**Task tool replacement - same API, more control**

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
→ Returns: Dict[worker_id, CompleteTask]

# Access conversation history via result[worker_id].conversation_history_file_path
```

## Execution Model

**You should:**
- ✅ **Execute** MCP tools directly (spawn_worker, wait, resume_worker)
- ✅ **Read** conversation history files using Read tool
- ⚠️ **Never** write pseudo-code - make actual tool calls

**Correct:**
```
spawn_worker(description="Research task", prompt="Research Python async patterns")
wait()
```

**Incorrect:**
```
mcp://async_worker_manager/spawn_worker(...)  # This is documentation syntax, not executable
```

## Primary Pattern: Batch Mode

```
# 1. Spawn multiple workers (like Task)
mcp://async_worker_manager/spawn_worker("Research", "Research Python async", agent_type="general-purpose")
mcp://async_worker_manager/spawn_worker("Explore", "Find config files", agent_type="Explore")
mcp://async_worker_manager/spawn_worker("Compare", "Compare approaches")

# 2. Wait for ALL to complete
mcp://async_worker_manager/wait()
→ Returns: Dict[worker_id, CompleteTask]

# 3. Access results via bash
```

```sh
tail -20 logs/worker-{id}.json
```

## Migration from Task Tool

**Task tool is disabled and replaced with async-workers.** Use the same API

## Additional Tools

```
# Resume completed worker (extends Task)
mcp://async_worker_manager/resume_worker(worker_id, prompt="Follow-up question")
```

## Permission Handling

**Permissions are auto-approved.** Workers can use all tools (Bash, Write, Read, etc.) without manual approval. All permission requests are automatically approved for simplicity. Use only in trusted environments.

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

## Important: Task Tool Replacement

**Task tool is disabled.** Async workers provide the same API with additional capabilities:

✅ **All Task features** - Same description, prompt, agent_type parameters
✅ **Plus resumability** - Continue conversations with resume_worker
✅ **Plus explicit control** - Choose when to wait for results
✅ **Plus auto-permissions** - Workers can use tools without manual approval
✅ **Plus customization** - Model, temperature, thinking settings

**For any parallel work, use async-workers:**
- ✅ Use `spawn_worker()` instead of `Task()`
- ✅ Call `wait()` when you need results
- ✅ Access output via file paths (98% less context)

---

[examples.md](examples.md) - Multi-agent patterns, model comparisons, resume flows
