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
| 8. Permission Handling | `spawn_worker`, `wait` | ~45s | None |
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
  "a1b2c3d4-e5f6-7890-abcd-ef1234567890": {
    "conversation_history_file_path": "/absolute/path/to/logs/worker-a1b2c3d4-e5f6-7890-abcd-ef1234567890.json"
  }
}
```

### Validation Checklist
- [ ] Response is a dict with worker_id as key
- [ ] Dict contains key with worker_id from Test 1
- [ ] Each value has `conversation_history_file_path`
- [ ] `conversation_history_file_path` is an absolute path
- [ ] File path points to logs/worker-{id}.json

### Common Issues
- **"No active workers to wait for"** - Create a worker first with Test 1
- **Worker still active** - Worker may be taking longer than expected
- **Empty dict** - No workers have completed yet; wait is blocking until they do

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
  "type": "result",
  "subtype": "success",
  "session_id": "879dfa34-3253-4158-bf19-5eb6c6b89e3b",
  "result": "Hello! Here are exactly 3 programming languages:\n\n1. Python\n2. JavaScript\n3. Rust",
  "duration_ms": 2000,
  "num_turns": 1,
  "total_cost_usd": 0.007871
}
```

### Validation Checklist
- [ ] File exists and is readable
- [ ] JSON parses correctly
- [ ] `session_id` field present in file (UUID format)
- [ ] `result` field contains the response
- [ ] `result` contains greeting (e.g., "hello", "Hi")
- [ ] `result` lists 3 programming languages

### Content Validation
Parse the file contents and verify:
```python
import json
with open(file_path) as f:
    data = json.load(f)
assert "session_id" in data
assert "result" in data
assert "hello" in data["result"].lower() or "hi" in data["result"].lower()
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
  "a1b2c3d4-e5f6-7890-abcd-ef1234567890": {
    "conversation_history_file_path": "/absolute/path/to/logs/worker-a1b2c3d4-e5f6-7890-abcd-ef1234567890.json"
  }
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
  "session_id": "879dfa34-3253-4158-bf19-5eb6c6b89e3b",
  "result": "Python is a high-level, interpreted programming language known for its clear and readable syntax...",
  "num_turns": 3
}
```

### Validation Checklist
- [ ] `resume_worker` succeeds without error
- [ ] Worker transitions: completed → active (after resume) → completed (after wait)
- [ ] `session_id` remains the same across resume
- [ ] New `result` contains response about the programming language
- [ ] File contents updated with new conversation
- [ ] `num_turns` increased from previous value

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
  "worker-1-uuid": {
    "conversation_history_file_path": "/path/to/logs/worker-1-uuid.json"
  },
  "worker-2-uuid": {
    "conversation_history_file_path": "/path/to/logs/worker-2-uuid.json"
  },
  "worker-3-uuid": {
    "conversation_history_file_path": "/path/to/logs/worker-3-uuid.json"
  }
}
```

### Validation Checklist
- [ ] 3 workers created with unique IDs
- [ ] `wait` returns dict with all 3 worker IDs as keys
- [ ] All workers have conversation_history_file_path
- [ ] All conversation history files exist and are accessible

### Batch Mode Verification
```python
# Verify all 3 workers completed
worker_ids = [worker1_id, worker2_id, worker3_id]
completed_ids = list(result.keys())
assert set(completed_ids) == set(worker_ids)

# Verify all files exist
for worker_id, task_data in result.items():
    assert os.path.exists(task_data["conversation_history_file_path"])
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
  "worker-uuid": {
    "conversation_history_file_path": "/path/to/logs/worker-uuid.json"
  }
}
```

### Validation Checklist
- [ ] Worker spawns without error
- [ ] wait returns dict with worker completion
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
  "worker-uuid": {
    "conversation_history_file_path": "/path/to/logs/worker-uuid.json"
  }
}
```

### Validation Checklist
- [ ] Worker spawns without error
- [ ] wait returns dict with worker completion
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

**Note:** Permissions are now auto-approved as of v0.3.0.

### Command Syntax

**Create Worker:**
```json
{
  "tool": "mcp__async_worker_manager__spawn_worker",
  "arguments": {
    "description": "File write test",
    "prompt": "Create a test file named /tmp/test-async-worker.txt with content 'hello'"
  }
}
```

**Wait for Completion:**
```json
{
  "tool": "mcp__async_worker_manager__wait",
  "arguments": {}
}
```

**Expected Response:**
```json
{
  "worker-uuid": {
    "conversation_history_file_path": "/path/to/logs/worker-uuid.json"
  }
}
```

### Validation Checklist
- [ ] Worker spawns successfully
- [ ] wait returns dict with worker completion
- [ ] File was created (/tmp/test-async-worker.txt)
- [ ] File contains "hello"
- [ ] No permission prompts or manual approval needed

### Common Issues
- **File not created** - Check worker completed successfully
- **Permission denied** - Verify path is in auto-approved locations (/tmp, home directory)

---

## Test 9: Failed Workers

**Note:** As of v0.3.0, workers handle errors gracefully and explain issues to the user.

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
  "worker-uuid": {
    "conversation_history_file_path": "/path/to/logs/worker-uuid.json"
  }
}
```

The worker completes successfully with a helpful explanation about why the tool doesn't exist.

### Validation Checklist
- [ ] Worker spawns successfully
- [ ] wait() returns dict with worker completion
- [ ] Conversation history contains helpful explanation
- [ ] Worker explains available tools as alternative
- [ ] Server doesn't crash
- [ ] No exceptions raised

### Common Issues
- **Worker crashes** - Workers should handle invalid requests gracefully
- **Server crash** - Check error handling in worker implementation

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
```
Error: Worker 00000000-0000-0000-0000-000000000000 not found. maybe still working
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
```
Error: Worker slow-worker-uuid not found. maybe still working
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
```
Error: No active workers to wait for
```

### Validation Checklist
- [ ] Error messages are descriptive and actionable
- [ ] Server remains stable (no crashes)
- [ ] Subsequent valid requests still work
- [ ] Error identifies specific worker_id when applicable
- [ ] Error explains why operation failed

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
# Permissions are auto-approved, file should be created

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
| Test Pass Rate | 100% | All 11 tests pass |
| Worker Creation Time | < 5s | Time to spawn worker |
| Wait Response Time | < 2s after all complete | Time for wait to return |
| Session Resumption | 100% | Same session_id maintained |
| Permission Handling | 100% | Auto-approval works correctly |
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

### Permission Issues
- Permissions are auto-approved for /tmp and home directory
- Workers should complete without manual intervention
- Check worker completed successfully in wait result

### File Not Found
- conversation_history_file_path is absolute path
- Files are in logs/ directory relative to plugin root
- Check file was created (returncode 0)

### Failed Workers
- Workers handle errors gracefully with helpful explanations
- Read conversation_history_file_path for worker's response
- Check that worker completed without crashing

---

## Version History

- **v0.3.0** (2025-10-24) - Major API refactor
  - **BREAKING**: `wait()` now returns `Dict[str, CompleteTask]` instead of `WorkerState`
  - **BREAKING**: Removed `failed` list - failed workers now raise exceptions
  - **BREAKING**: Removed `pending_permissions` - permissions auto-approved
  - **BREAKING**: Removed `approve_permission` tool
  - **BREAKING**: `CompleteTask` simplified - removed `worker_id` and `claude_session_id` fields
  - Updated all test scenarios for dict-based API
  - Marked Test 8 (Permission Handling) as obsolete
  - Updated Test 9 (Failed Workers) for exception-based error handling
  - Updated Test 10 error messages
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
