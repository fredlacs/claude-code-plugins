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
result = wait()  # Returns Dict[worker_id → CompleteTask]

# Access results
for worker_id, worker in result.items():
    # Read {worker.conversation_history_file_path}
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
wait() -> Dict[str, CompleteTask]
```

Wait for ALL active workers to complete.

**Returns:** Dictionary mapping worker_id to CompleteTask
```python
{
    "worker-id-1": {
        "conversation_history_file_path": "/absolute/path/to/logs/worker-id-1.json"
    },
    "worker-id-2": {
        "conversation_history_file_path": "/absolute/path/to/logs/worker-id-2.json"
    }
}
```

**Examples:**

```python
# Batch mode
id1 = spawn_worker("Task 1", "...")
id2 = spawn_worker("Task 2", "...")
result = wait()  # Blocks until both complete
# result = {id1: CompleteTask(...), id2: CompleteTask(...)}

# Access conversation history
for worker_id, worker_data in result.items():
    print(worker_data.conversation_history_file_path)

# Sequential mode
id = spawn_worker("Task", "...")
result = wait()
file_path = result[id].conversation_history_file_path

id2 = spawn_worker("Next", "...")
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
| **Permissions** | Automatic | ✅ Auto-approved (no manual approval) |
| **Output** | Inline text | File paths (98% smaller) |
| **Options** | All Task params | ✅ Same (via options dict) |

**Use Task when:** You want fire-and-forget parallel execution with inline results

**Use Async Workers when:** You need:
- Explicit control over when to wait
- Multi-turn conversations (resume)
- Minimal context usage (file-based output)
- Custom model/temperature settings

---

## Permission Handling

**Permissions are auto-approved.** Workers can use all tools (Bash, Write, Read, etc.) without manual approval. All permission requests are automatically approved for simplicity.

**Security Note:** Workers run in sandboxed environments by default (macOS/Linux only). See Sandboxing section below for details.

All tool executions are logged in the conversation history file for audit purposes.

---

## Sandboxing

**Workers run in isolated sandboxes by default** (macOS/Linux only, Windows not supported).

### Two-Layer Security

1. **Permission Proxy (MCP Layer)**: Blocks dangerous commands before execution
   - Detects excluded commands (docker, sudo, rm, etc.)
   - Catches shell obfuscation (eval, base64 injection, command substitution)
   - Uses proper shell parsing with `shlex` to prevent bypasses

2. **OS Sandbox (System Layer)**: Enforces filesystem and network isolation
   - Filesystem: Write access limited to current working directory
   - Network: Proxy-based filtering with domain controls
   - Bash: Auto-approved within sandbox constraints

### Default Configuration

Located in `src/permissions_config.json`:

```json
{
  "excludedCommands": ["docker", "sudo", "su", "rm", "systemctl", ...],
  "deniedTools": [],
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true
  }
}
```

**Default blocked commands:**
- `docker` - Container operations
- `sudo`, `su` - Privilege escalation
- `rm` - File deletion (use with extreme caution)
- `systemctl`, `shutdown`, `reboot` - System control
- `dd`, `mkfs` - Disk operations

**Default blocked patterns:**
- `eval` - Dynamic code execution
- `base64 ... | bash` - Encoded command injection
- `$(...)` / backticks - Command substitution
- `bash -c` / `sh -c` - Shell interpretation

### Customizing Permissions

Edit `src/permissions_config.json`:

**Allow Docker:**
```json
{
  "excludedCommands": ["sudo", "su", "rm"],
  "sandbox": {
    "enabled": true,
    "excludedCommands": ["docker"],
    "network": {
      "allowUnixSockets": ["/var/run/docker.sock"]
    }
  }
}
```

**Read-only mode (research workers):**
```json
{
  "allowedTools": ["Read", "Grep", "Glob"],
  "deniedTools": ["Write", "Edit", "Bash"],
  "excludedCommands": ["docker", "npm", "pip", "git"],
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": false
  }
}
```

**Whitelist specific tools:**
```json
{
  "allowedTools": ["Read", "Write", "Bash"],
  "deniedTools": ["WebSearch", "Skill"]
}
```

### Configuration Fields

| Field | Type | Description |
|-------|------|-------------|
| `excludedCommands` | array | Command names to block (e.g. `["docker", "sudo"]`) |
| `excludedBinaries` | array | Full binary paths to block (e.g. `["/usr/bin/docker"]`) |
| `dangerousPatterns` | array | Regex patterns to block (e.g. `["eval", "base64.*bash"]`) |
| `allowedTools` | array | If set, only these tools allowed (whitelist mode) |
| `deniedTools` | array | Tools to always block (e.g. `["WebSearch"]`) |
| `sandbox.enabled` | bool | Enable OS-level sandboxing |
| `sandbox.autoAllowBashIfSandboxed` | bool | Auto-approve bash within sandbox |
| `sandbox.excludedCommands` | array | Commands excluded from sandbox (run outside) |
| `sandbox.network.allowUnixSockets` | array | Unix socket paths accessible |
| `sandbox.network.allowLocalBinding` | bool | Allow binding to localhost |

### Environment Variables

**Disable sandbox (debugging only):**
```bash
export WORKER_SANDBOX_DISABLED=true
# Workers run without OS-level sandboxing
```

### Security Model

**Defense in Depth:**
```
Worker attempts: Bash("docker run alpine")
     ↓
Layer 1: Permission Proxy
  - Parses command with shlex
  - Checks "docker" in excludedCommands
  - DENIES → Stops immediately
     ↓
Layer 2: OS Sandbox
  - Filesystem isolation (CWD only)
  - Network proxy filtering
  - Backup enforcement
```

**Why two layers?**
- **Proxy**: Fast-fail, catches obfuscation attempts
- **Sandbox**: Deep defense, OS-level guarantees

**What's protected:**
- ✅ Sensitive files (.env, SSH keys, credentials)
- ✅ System directories (/etc, /usr, /var)
- ✅ Network exfiltration (proxy-based filtering)
- ✅ Privilege escalation (sudo/su blocked)
- ✅ Shell injection (eval, command substitution detected)

**Platform support:**
- ✅ macOS (Seatbelt sandbox)
- ✅ Linux (bubblewrap)
- ❌ Windows (sandboxing not available)

### Examples

**Default secure mode:**
```python
# Uses permissions_config.json defaults
spawn_worker("Analyze code", "Review this file for bugs")
# Sandbox enabled, dangerous commands blocked
```

**Custom configuration for Docker workflow:**
```json
// Edit src/permissions_config.json
{
  "excludedCommands": ["sudo"],
  "sandbox": {
    "enabled": true,
    "excludedCommands": ["docker"],
    "network": {"allowUnixSockets": ["/var/run/docker.sock"]}
  }
}
```

**Disable sandbox for debugging:**
```bash
export WORKER_SANDBOX_DISABLED=true
spawn_worker("Debug task", "...")
# Warning: Full filesystem access, use only for debugging
```

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
# From result dict
worker_id=$(echo "first_worker_id_here")
file=$(echo "result[$worker_id].conversation_history_file_path")

# Read full output
cat logs/worker-{id}.json

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
