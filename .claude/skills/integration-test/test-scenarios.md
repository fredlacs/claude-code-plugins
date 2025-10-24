# Integration Test Scenarios Reference

Complete reference for manually executing integration tests against the async-worker-manager MCP server.

## Quick Reference

| Test | Primary Tool | Duration | Dependencies |
|------|-------------|----------|--------------|
| 1. Create Worker | `spawn_worker` | ~30s | None |
| 2. Wait Completion | `wait` | ~30s | Test 1 |
| 3. File-Based Output | `Read` | <1s | Test 2 |
| 4. Resume Conversation | `resume_worker`, `wait`, `Read` | ~60s | Test 3 |
| 5. Parallel Workers | `spawn_worker`, `wait` | ~45s | None |
| 6. Agent Types | `spawn_worker`, `wait` | ~30s | None |
| 7. Worker Options | `spawn_worker`, `wait` | ~30s | None |
| 8. Permission Handling | `spawn_worker`, `wait`, `approve_permission` | ~45s | None |
| 9. Failed Workers | `spawn_worker`, `wait` | ~30s | None |
| 10. Error Handling | `resume_worker`, `wait` | <5s | None |

---

## Test 1: Create Worker

### Command Syntax
```json
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "List programming languages",
    "prompt": "Say hello and list exactly 3 programming languages"
  }
}
```

### Expected Response
```json
"a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

### Validation Checklist
- [ ] Response is a string (worker_id)
- [ ] `worker_id` matches UUID v4 format (8-4-4-4-12 hex digits)
- [ ] No error message in response
- [ ] Worker process spawned successfully

### Common Issues
- **"Max 10 active workers"** - Wait for existing workers to complete
- **"Claude not in PATH"** - Verify `which claude` returns a valid path
- **Missing description** - description parameter is required

---

## Test 2: Wait for Completion

### Command Syntax
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

### Expected Response
```json
{
  "completed": [
    {
      "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "claude_session_id": "session-20251022123456-abc123",
      "conversation_history_file_path": "/absolute/path/to/logs/worker-a1b2c3d4-e5f6-7890-abcd-ef1234567890.json"
    }
  ],
  "failed": [],
  "pending_permissions": []
}
```

### Validation Checklist
- [ ] Response is a WorkerState object
- [ ] `completed` list contains CompleteTask for worker from Test 1
- [ ] `worker_id` matches the one from Test 1
- [ ] `claude_session_id` starts with "session-"
- [ ] `conversation_history_file_path` is an absolute path
- [ ] `failed` and `pending_permissions` are empty lists

### Common Issues
- **"No active workers to wait for"** - Create a worker first with Test 1
- **Worker still active** - Worker may be taking longer than expected
- **Empty completed list** - No workers have completed yet; wait is blocking until they do

---

## Test 3: File-Based Output

### Command Syntax
```json
{
  "tool": "Read",
  "arguments": {
    "file_path": "/absolute/path/to/logs/worker-a1b2c3d4-e5f6-7890-abcd-ef1234567890.json"
  }
}
```

### Expected Response
```json
{
  "session_id": "session-20251022123456-abc123",
  "output": "Hello! Here are 3 programming languages:\n1. Python\n2. JavaScript\n3. Rust"
}
```

### Validation Checklist
- [ ] File exists and is readable
- [ ] JSON parses correctly
- [ ] `session_id` field present and matches claude_session_id from Test 2
- [ ] `session_id` format is correct (session-TIMESTAMP-HASH)
- [ ] `output` field contains the response
- [ ] `output` contains greeting (e.g., "hello", "Hi")
- [ ] `output` lists 3 programming languages

### Content Validation
Parse the file contents and verify:
```python
import json
with open(file_path) as f:
    data = json.load(f)
assert "session_id" in data
assert data["session_id"].startswith("session-")
assert "output" in data
assert "hello" in data["output"].lower() or "hi" in data["output"].lower()
```

### Common Issues
- **File not found** - Verify path from Test 2 is correct
- **Invalid JSON** - Check worker completed successfully without errors
- **Missing session_id** - Verify worker used --output-format json

---

## Test 4: Resume Conversation

### Part 4a: Resume Worker

**Command Syntax:**
```json
{
  "tool": "mcp__async_worker_manager__resume_worker",
  "arguments": {
    "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "prompt": "Tell me more about the first language you mentioned"
  }
}
```

**Expected Response:**
```json
null
```
(Success returns null/None)

### Part 4b: Wait for Response

**Command Syntax:**
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

**Expected Response:**
```json
{
  "completed": [
    {
      "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "claude_session_id": "session-20251022123456-abc123",
      "conversation_history_file_path": "/absolute/path/to/logs/worker-a1b2c3d4-e5f6-7890-abcd-ef1234567890.json"
    }
  ],
  "failed": [],
  "pending_permissions": []
}
```

### Part 4c: Read New Response

**Command Syntax:**
```json
{
  "tool": "Read",
  "arguments": {
    "file_path": "/absolute/path/to/logs/worker-a1b2c3d4-e5f6-7890-abcd-ef1234567890.json"
  }
}
```

**Expected Response:**
```json
{
  "session_id": "session-20251022123456-abc123",
  "output": "...response about the first language (Python)..."
}
```

### Validation Checklist
- [ ] `resume_worker` succeeds without error
- [ ] Worker transitions: completed → active (after resume) → completed (after wait)
- [ ] `session_id` remains the same across resume
- [ ] New `output` contains response about the programming language
- [ ] File contents updated with new conversation

### Session Continuity Verification
```python
# Compare session IDs
initial_session_id = test3_data["session_id"]
resumed_session_id = test4c_data["session_id"]
assert initial_session_id == resumed_session_id, "Session ID should remain consistent"
```

### Common Issues
- **"Worker not found"** - Verify worker_id is correct
- **"Worker ... is not in completed state"** - Worker must be completed before resuming
- **Session ID changed** - Indicates new session instead of resume; check implementation

---

## Test 5: Parallel Workers (Batch Mode)

### Part 5a: Create Multiple Workers

**Worker 1:**
```json
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "Count slowly",
    "prompt": "Count to 3 slowly: 1... 2... 3..."
  }
}
```
Response: `"worker-1-uuid"`

**Worker 2:**
```json
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "Quick response",
    "prompt": "Say 'quick response' immediately"
  }
}
```
Response: `"worker-2-uuid"`

**Worker 3:**
```json
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "List colors",
    "prompt": "List 5 colors: red, blue, green, yellow, purple"
  }
}
```
Response: `"worker-3-uuid"`

### Part 5b: Wait for All Completions

**Command Syntax:**
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

**Expected Response:**
```json
{
  "completed": [
    {
      "worker_id": "worker-1-uuid",
      "claude_session_id": "session-...",
      "conversation_history_file_path": "/path/to/logs/worker-1-uuid.json"
    },
    {
      "worker_id": "worker-2-uuid",
      "claude_session_id": "session-...",
      "conversation_history_file_path": "/path/to/logs/worker-2-uuid.json"
    },
    {
      "worker_id": "worker-3-uuid",
      "claude_session_id": "session-...",
      "conversation_history_file_path": "/path/to/logs/worker-3-uuid.json"
    }
  ],
  "failed": [],
  "pending_permissions": []
}
```

### Validation Checklist
- [ ] 3 workers created with unique IDs
- [ ] `wait` returns WorkerState with all 3 workers in completed list
- [ ] All workers have unique worker_ids
- [ ] All workers have conversation_history_file_path
- [ ] All conversation history files exist and are accessible

### Batch Mode Verification
```python
# Verify all 3 workers completed
worker_ids = [worker1_id, worker2_id, worker3_id]
completed_ids = [w["worker_id"] for w in result["completed"]]
assert set(completed_ids) == set(worker_ids)

# Verify all files exist
for worker in result["completed"]:
    assert os.path.exists(worker["conversation_history_file_path"])
```

### Common Issues
- **"Max 10 active workers"** - Clear previous workers first
- **Not all workers returned** - wait() blocks until ALL active workers complete
- **Mixed completed/failed** - Some workers may have failed; check failed list

---

## Test 6: Agent Types

### Command Syntax
```json
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "Explore codebase",
    "prompt": "Find all Python files in the current directory",
    "agent_type": "Explore"
  }
}
```

Then:
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

### Expected Response
```json
{
  "completed": [
    {
      "worker_id": "...",
      "claude_session_id": "session-...",
      "conversation_history_file_path": "/path/to/logs/worker-....json"
    }
  ],
  "failed": [],
  "pending_permissions": []
}
```

### Validation Checklist
- [ ] Worker spawns without error
- [ ] wait returns completion
- [ ] Conversation history shows agent used Explore behavior
- [ ] No errors related to agent_type

### Agent Types Available
- `"Explore"` - Fast agent for exploring codebases
- `"general-purpose"` - General-purpose agent
- Custom string - Arbitrary system prompt

### Common Issues
- **Invalid agent_type** - Agent type is optional; any string accepted
- **Different behavior** - agent_type sets system prompt; behavior may vary

---

## Test 7: Worker Options

### Command Syntax
```json
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "Test with options",
    "prompt": "Explain what temperature means in LLMs",
    "options": {
      "temperature": 0.5,
      "model": "claude-sonnet-4-5",
      "thinking": true
    }
  }
}
```

Then:
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

### Expected Response
```json
{
  "completed": [
    {
      "worker_id": "...",
      "claude_session_id": "session-...",
      "conversation_history_file_path": "/path/to/logs/worker-....json"
    }
  ],
  "failed": [],
  "pending_permissions": []
}
```

### Validation Checklist
- [ ] Worker spawns without error
- [ ] wait returns completion
- [ ] Settings applied (check conversation for thinking blocks if thinking=true)
- [ ] No errors related to options

### Available Options
```json
{
  "model": "claude-sonnet-4-5",        // Claude model
  "temperature": 0.5,                  // 0.0-1.0 (default: 1.0)
  "max_tokens": 4096,                  // Max generation tokens
  "thinking": true,                    // Enable extended thinking (default: false)
  "top_p": 0.9,                        // Nucleus sampling
  "top_k": 40                          // Top-k sampling
}
```

### Common Issues
- **Invalid temperature** - Must be 0.0-1.0
- **Invalid model** - Check available Claude models
- **Options ignored** - Verify options dict is properly formatted

---

## Test 8: Permission Handling

### Part 8a: Create Worker Needing Permission

**Command Syntax:**
```json
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "File write test",
    "prompt": "Create a test file named /tmp/test-async-worker.txt with content 'hello'"
  }
}
```

### Part 8b: Wait (Returns Pending Permission)

**Command Syntax:**
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

**Expected Response:**
```json
{
  "completed": [],
  "failed": [],
  "pending_permissions": [
    {
      "request_id": "req-abc123",
      "worker_id": "worker-uuid",
      "tool": "Write",
      "input": {
        "file_path": "/tmp/test-async-worker.txt",
        "content": "hello"
      }
    }
  ]
}
```

### Part 8c: Approve Permission

**Command Syntax:**
```json
{
  "tool": "mcp__async_worker_manager__approve_permission",
  "arguments": {
    "request_id": "req-abc123",
    "allow": true
  }
}
```

**Expected Response:**
```json
{
  "status": "approved",
  "tool": "Write",
  "input": {...}
}
```

### Part 8d: Wait Again (Gets Completion)

**Command Syntax:**
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

**Expected Response:**
```json
{
  "completed": [
    {
      "worker_id": "worker-uuid",
      "claude_session_id": "session-...",
      "conversation_history_file_path": "/path/to/logs/worker-uuid.json"
    }
  ],
  "failed": [],
  "pending_permissions": []
}
```

### Validation Checklist
- [ ] Worker spawns successfully
- [ ] First wait returns pending_permissions list
- [ ] PermissionRequest structure is correct (request_id, worker_id, tool, input)
- [ ] approve_permission succeeds
- [ ] Second wait returns worker in completed list
- [ ] File was created (/tmp/test-async-worker.txt)

### Permission Flow
1. Worker requests permission → wait() returns with pending_permissions
2. Approve/deny → approve_permission()
3. Worker continues → wait() again for completion

### Common Issues
- **Permission not in list** - Worker may not have requested permission yet
- **"Request not found"** - Request_id may have expired or worker completed
- **Worker in failed list** - Permission was denied or worker errored

---

## Test 9: Failed Workers

### Command Syntax
```json
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "Invalid tool",
    "prompt": "Use the tool 'nonexistent_tool' to do something"
  }
}
```

Then:
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

### Expected Response
```json
{
  "completed": [],
  "failed": [
    {
      "worker_id": "worker-uuid",
      "returncode": 1,
      "conversation_history_file_path": "/path/to/logs/worker-uuid.json",
      "error_hint": "Tool not found. Check MCP server config."
    }
  ],
  "pending_permissions": []
}
```

### Validation Checklist
- [ ] Worker spawns successfully
- [ ] wait returns WorkerState with worker in failed list
- [ ] FailedTask has worker_id, returncode, error_hint
- [ ] returncode is non-zero
- [ ] error_hint is descriptive and actionable
- [ ] conversation_history_file_path may be present (partial output)
- [ ] Server doesn't crash

### Error Hint Examples
- "Timed out. Increase timeout parameter."
- "Permission denied. Check pending_permissions and approve."
- "Tool not found. Check MCP server config."
- "Connection failed. Check MCP server is running."
- First 150 chars of stderr

### Common Issues
- **Worker in completed instead** - Worker may have succeeded despite intent
- **No error_hint** - Check implementation generates hints
- **Server crash** - Failed workers should be handled gracefully

---

## Test 10: Error Handling

### Test 10a: Resume Non-Existent Worker

**Command Syntax:**
```json
{
  "tool": "mcp__async_worker_manager__resume_worker",
  "arguments": {
    "worker_id": "00000000-0000-0000-0000-000000000000",
    "prompt": "Hello"
  }
}
```

**Expected Response:**
```json
{
  "error": "Worker 00000000-0000-0000-0000-000000000000 not found",
  "type": "ToolError"
}
```

### Test 10b: Resume Active Worker

**Setup:**
```json
// Create a slow worker
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "Slow task",
    "prompt": "Count to 100 slowly"
  }
}
// Returns: "slow-worker-uuid"
```

**Command Syntax (immediately after creation):**
```json
{
  "tool": "mcp__async_worker_manager__resume_worker",
  "arguments": {
    "worker_id": "slow-worker-uuid",
    "prompt": "Stop counting"
  }
}
```

**Expected Response:**
```json
{
  "error": "Worker slow-worker-uuid is not in completed state (current: WorkerStatus.ACTIVE)",
  "type": "ToolError"
}
```

### Test 10c: Wait with No Active Workers

**Setup:**
```
// After all workers have completed
```

**Command Syntax:**
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

**Expected Response:**
```json
{
  "error": "No active workers to wait for",
  "type": "ToolError"
}
```

### Validation Checklist
- [ ] Error messages are descriptive and actionable
- [ ] Error type is "ToolError"
- [ ] Server remains stable (no crashes)
- [ ] Subsequent valid requests still work
- [ ] Error identifies specific worker_id when applicable
- [ ] Error explains why operation failed
- [ ] Error suggests next steps when possible

### Error Message Quality
Good error messages should:
- Identify the specific worker_id
- Explain why the operation failed
- Suggest next steps (e.g., "try wait first")

### Common Issues
- **Error not raised** - Check server error handling implementation
- **Generic error message** - Improve error message specificity
- **Server crash** - Add proper exception handling

---

## Full Test Run Script

Execute all tests in sequence:

```bash
#!/bin/bash

# Helper function to call MCP tools
call_tool() {
  local tool=$1
  local args=$2
  # Implementation depends on how you invoke MCP tools
  # Example: claude-mcp-client call "$tool" "$args"
}

# Test 1: Create Worker
worker_id=$(call_tool "mcp__async_worker_manager__spawn_worker" \
  '{"description": "List programming languages", "prompt": "Say hello and list exactly 3 programming languages"}')

# Test 2: Wait for Completion
wait_result=$(call_tool "mcp__async_worker_manager__wait" '{}')

# Test 3: File-Based Output
file_path=$(echo "$wait_result" | jq -r '.completed[0].conversation_history_file_path')
cat "$file_path"

# Test 4: Resume Conversation
call_tool "mcp__async_worker_manager__resume_worker" \
  "{\"worker_id\": \"$worker_id\", \"prompt\": \"Tell me more about the first language\"}"
wait_result=$(call_tool "mcp__async_worker_manager__wait" '{}')
cat "$file_path"

# Test 5: Parallel Workers
worker1=$(call_tool "mcp__async_worker_manager__spawn_worker" \
  '{"description": "Count slowly", "prompt": "Count to 3 slowly"}')
worker2=$(call_tool "mcp__async_worker_manager__spawn_worker" \
  '{"description": "Quick response", "prompt": "Say quick response"}')
worker3=$(call_tool "mcp__async_worker_manager__spawn_worker" \
  '{"description": "List colors", "prompt": "List 5 colors"}')
wait_result=$(call_tool "mcp__async_worker_manager__wait" '{}')

# Test 6: Agent Types
worker_id=$(call_tool "mcp__async_worker_manager__spawn_worker" \
  '{"description": "Explore codebase", "prompt": "Find all Python files", "agent_type": "Explore"}')
call_tool "mcp__async_worker_manager__wait" '{}'

# Test 7: Worker Options
worker_id=$(call_tool "mcp__async_worker_manager__spawn_worker" \
  '{"description": "Test with options", "prompt": "Explain temperature", "options": {"temperature": 0.5, "thinking": true}}')
call_tool "mcp__async_worker_manager__wait" '{}'

# Test 8: Permission Handling
worker_id=$(call_tool "mcp__async_worker_manager__spawn_worker" \
  '{"description": "File write test", "prompt": "Create /tmp/test-async-worker.txt with hello"}')
wait_result=$(call_tool "mcp__async_worker_manager__wait" '{}')
request_id=$(echo "$wait_result" | jq -r '.pending_permissions[0].request_id')
call_tool "mcp__async_worker_manager__approve_permission" \
  "{\"request_id\": \"$request_id\", \"allow\": true}"
call_tool "mcp__async_worker_manager__wait" '{}'

# Test 9: Failed Workers
worker_id=$(call_tool "mcp__async_worker_manager__spawn_worker" \
  '{"description": "Invalid tool", "prompt": "Use nonexistent_tool"}')
call_tool "mcp__async_worker_manager__wait" '{}'

# Test 10: Error Handling
call_tool "mcp__async_worker_manager__resume_worker" \
  '{"worker_id": "00000000-0000-0000-0000-000000000000", "prompt": "Hello"}'
```

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Test Pass Rate | 100% | All 10 tests pass |
| Worker Creation Time | < 5s | Time to spawn worker |
| Wait Response Time | < 2s after all complete | Time for wait to return |
| Session Resumption | 100% | Same session_id maintained |
| Permission Handling | 100% | Request → approve → complete flow |
| Error Clarity | 100% | All errors have actionable messages |
| File Access | 100% | All conversation history files readable |

---

## Troubleshooting Guide

### Worker Creation Fails
- Check `claude` is in PATH: `which claude`
- Verify Python version: `python --version` (requires 3.10+)
- Check dependencies: `uv sync` or `pip install fastmcp`

### Wait Returns Empty
- Workers may still be active
- Check workers weren't cancelled
- Verify workers didn't fail (check failed list)

### Session Resume Fails
- Verify worker is in completed state
- Check session_id format in conversation history
- Ensure worker_id is correct

### Permission Not Appearing
- Worker must request permission first
- Check pending_permissions list in wait result
- Verify worker is blocked waiting for permission

### File Not Found
- conversation_history_file_path is absolute path
- Files are in logs/ directory relative to plugin root
- Check file was created (returncode 0)

### Failed Workers
- Check error_hint for actionable guidance
- Read conversation_history_file_path for partial output
- Verify tool names and MCP server config

---

## Version History

- **v0.2.0** (2025-10-23) - Updated for current API
  - Complete command reference for all 10 tests
  - Updated tool names (spawn_worker, resume_worker, wait)
  - Added permission handling test
  - Added agent type and options tests
  - Added failed worker test
  - Updated to file-based output
  - Removed peek (replaced with Read)
  - Updated expected responses
  - Added troubleshooting guide
- **v0.1.0** (2025-10-22) - Initial test scenarios
  - Complete command reference for all 6 tests
  - Expected responses and validation checklists
  - Troubleshooting guide
  - Full test run script
