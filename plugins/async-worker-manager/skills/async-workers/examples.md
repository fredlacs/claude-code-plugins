# Async Workers: Usage Patterns

## 1. Basic Parallel Execution

```
# Spawn multiple workers in parallel
mcp://async_worker_manager/spawn_worker("Task 1", "Research async patterns in Python")
mcp://async_worker_manager/spawn_worker("Task 2", "Find all config files")
mcp://async_worker_manager/spawn_worker("Task 3", "Analyze project dependencies")

mcp://async_worker_manager/wait()  # Blocks until ALL complete
→ Returns: result.completed with conversation_history_file_path for each worker
```

## 2. Temperature Sweep (Creativity Control)

```
# Same prompt, different creativity levels
mcp://async_worker_manager/spawn_worker("Conservative", "Generate 5 creative function names for a user authentication service", options={"temperature": 0.0})
mcp://async_worker_manager/spawn_worker("Balanced", "Generate 5 creative function names for a user authentication service", options={"temperature": 0.5})
mcp://async_worker_manager/spawn_worker("Creative", "Generate 5 creative function names for a user authentication service", options={"temperature": 1.0})

mcp://async_worker_manager/wait()
# Compare creativity levels: deterministic → balanced → creative
```

## 3. Sampling Control (top_p/top_k)

```
# Focused vs creative token selection
mcp://async_worker_manager/spawn_worker("Focused", "Generate RESTful endpoint names for a blog platform", options={"top_p": 0.1, "top_k": 10})

mcp://async_worker_manager/spawn_worker("Creative", "Generate RESTful endpoint names for a blog platform", options={"top_p": 0.95, "top_k": 100})

mcp://async_worker_manager/wait()
# Compare conventional vs unconventional approaches
```

## 4. Thinking Comparison

```
# Same complex task with/without extended reasoning
mcp://async_worker_manager/spawn_worker("Quick design", "Design a distributed rate-limiting system for a multi-region API", options={"thinking": False})

mcp://async_worker_manager/spawn_worker("Deep design", "Design a distributed rate-limiting system for a multi-region API", options={"thinking": True, "max_tokens": 8192})

mcp://async_worker_manager/wait()
# Compare reasoning depth in conversation histories
```

## 5. Multi-Perspective Analysis (agent_type)

```
# Same task, different expert perspectives
# agent_type can be:
# - Built-in: "Explore", "general-purpose"
# - Custom description: Any string defining the agent's role
# - File reference: Read from user's .md files for longer descriptions

mcp://async_worker_manager/spawn_worker(
    description="Security review",
    prompt="Review this code:\nasync function processPayment() { /* ... */ }",
    agent_type="You are a security auditor. Focus only on vulnerabilities and attack vectors."
)

mcp://async_worker_manager/spawn_worker(
    description="Performance review",
    prompt="Review this code:\nasync function processPayment() { /* ... */ }",
    agent_type="You are a performance engineer. Focus only on optimization opportunities."
)

mcp://async_worker_manager/spawn_worker(
    description="UX review",
    prompt="Review this code:\nasync function processPayment() { /* ... */ }",
    agent_type="You are a UX engineer. Focus only on error handling and user experience."
)

mcp://async_worker_manager/wait()
# Get 3 different expert perspectives on same code
```

## 6. Multi-Turn Conversations (Resume)

```
# Unique feature: continue conversation with completed worker
mcp://async_worker_manager/spawn_worker("Research", "Explain React hooks in detail")
→ Returns: worker_id

mcp://async_worker_manager/wait()
→ Returns: result.completed[0] with session info

# Follow up with same worker (maintains context)
mcp://async_worker_manager/resume_worker(worker_id, "Now show examples with useEffect")
mcp://async_worker_manager/wait()

# Continue the conversation
mcp://async_worker_manager/resume_worker(worker_id, "What are common mistakes beginners make?")
mcp://async_worker_manager/wait()

# Each resume maintains the full conversation history
```

## 7. Advanced: Combined Options

```
# Combine multiple options for fine-tuned control
mcp://async_worker_manager/spawn_worker(
    description="Comprehensive analysis",
    prompt="Design a caching strategy for this API",
    agent_type="You are a senior backend architect with expertise in distributed systems",
    options={
        "model": "claude-sonnet-4-5",
        "temperature": 0.7,
        "max_tokens": 8192,
        "thinking": True,
        "top_p": 0.9
    }
)

mcp://async_worker_manager/wait()
```

## 8. Permission Approval with User Confirmation

```
# Worker that requires permission (e.g., file write, bash execution)
mcp://async_worker_manager/spawn_worker(
    description="File creator",
    prompt="Create a file at /tmp/test.txt with content 'Hello World'"
)

# Permission handling loop
while True:
    result = mcp://async_worker_manager/wait()

    # Check for pending permissions
    if result.pending_permissions:
        for perm in result.pending_permissions:
            # Ask user via AskUserQuestion
            answers = AskUserQuestion(
                questions=[{
                    "question": f"Allow worker to use {perm.tool}?",
                    "header": "Permission",
                    "multiSelect": False,
                    "options": [
                        {
                            "label": "Allow",
                            "description": f"Grant permission for tool: {perm.tool}"
                        },
                        {
                            "label": "Deny",
                            "description": "Reject this permission request"
                        }
                    ]
                }]
            )

            # Parse answer and approve/deny
            question_text = f"Allow worker to use {perm.tool}?"
            allow = (answers[question_text] == "Allow")

            # Apply decision
            mcp://async_worker_manager/approve_permission(
                request_id=perm.request_id,
                allow=allow,
                reason="User denied" if not allow else None
            )
        continue  # Loop back to wait() after approval

    # Workers completed
    if result.completed:
        print("Worker completed successfully")
        break

    # Handle failures
    if result.failed:
        for failed in result.failed:
            print(f"Worker failed: {failed.error_hint}")
        break
```

**Key Points:**
- `AskUserQuestion` surfaces permission to user before auto-approving
- `answers` dict maps question text to selected label ("Allow" or "Deny")
- Compare `answers[question_text] == "Allow"` to determine boolean
- Must call `wait()` again after `approve_permission` to unblock worker

## Accessing Results

```
mcp://async_worker_manager/wait()
→ Returns: result.completed[0].conversation_history_file_path = "logs/worker-{id}.json"

Use the file path with bash:
```

```sh
tail -20 logs/worker-{id}.json
```
