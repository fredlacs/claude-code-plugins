# Integration Test Scenarios Reference

Complete reference for manually executing integration tests against the async-worker-manager MCP server.

## Quick Reference

| Test | Primary Tool | Duration | Dependencies |
|------|-------------|----------|--------------|
| 1. Create Worker | `create_async_worker` | ~30s | None |
| 2. Wait Completion | `wait` | ~30s | Test 1 |
| 3. Peek Output | `peek` | <1s | Test 2 |
| 4. Resume Conversation | `write_to_worker`, `wait`, `peek` | ~60s | Test 3 |
| 5. Parallel Racing | `create_async_worker`, `wait` | ~45s | None |
| 6. Error Handling | `peek`, `write_to_worker` | <5s | None |

---

## Test 1: Create Worker

### Command Syntax
```json
{
  "tool": "mcp__agent_manager__create_async_worker",
  "arguments": {
    "prompt": "Say hello and list exactly 3 programming languages",
    "timeout": 60.0
  }
}
```

### Expected Response
```json
{
  "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### Validation Checklist
- [ ] Response contains `worker_id` field
- [ ] `worker_id` matches UUID v4 format (8-4-4-4-12 hex digits)
- [ ] No error message in response
- [ ] Worker process spawned successfully

### Common Issues
- **"Max 10 active workers"** - Wait for existing workers to complete
- **"Claude not in PATH"** - Verify `which claude` returns a valid path
- **Timeout too short** - Increase timeout if workers don't finish in time

---

## Test 2: Wait for Completion

### Command Syntax
```json
{
  "tool": "mcp__agent_manager__wait",
  "arguments": {
    "timeout": 60.0
  }
}
```

### Expected Response
```json
[
  {
    "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "claude_session_id": "session-20251022123456-abc123",
    "std_out": "{\"session_id\": \"session-...\", \"output\": \"...\" }",
    "std_err": "",
    "timeout": 60.0
  }
]
```

### Validation Checklist
- [ ] Response is a list with at least one CompleteTask
- [ ] `worker_id` matches the one from Test 1
- [ ] `claude_session_id` starts with "session-"
- [ ] `std_out` contains valid JSON with session_id
- [ ] Completes before timeout expires

### Common Issues
- **"No active workers to flush"** - Create a worker first with Test 1
- **Timeout expires** - Worker may be taking longer than expected; increase timeout
- **Empty response** - No workers have completed yet; wait longer

---

## Test 3: Peek at Output

### Command Syntax
```json
{
  "tool": "mcp__agent_manager__peek",
  "arguments": {
    "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

### Expected Response
```json
{
  "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "claude_session_id": "session-20251022123456-abc123",
  "std_out": "{\n  \"session_id\": \"session-...\",\n  \"output\": \"Hello! Here are 3 programming languages:\\n1. Python\\n2. JavaScript\\n3. Rust\"\n}",
  "std_err": "",
  "timeout": 60.0
}
```

### Validation Checklist
- [ ] Response contains all fields: worker_id, claude_session_id, std_out, std_err, timeout
- [ ] `std_out` contains the greeting (e.g., "hello", "Hi")
- [ ] `std_out` lists 3 programming languages
- [ ] `session_id` format is correct (session-TIMESTAMP-HASH)
- [ ] `timeout` matches what was set in Test 1

### Content Validation
Parse the `std_out` JSON and verify:
```python
import json
output_data = json.loads(response["std_out"])
assert "session_id" in output_data
assert output_data["session_id"].startswith("session-")
# Check output contains expected content
assert "hello" in output_data["output"].lower() or "hi" in output_data["output"].lower()
```

### Common Issues
- **"Worker not found or not complete"** - Run Test 2 first to complete the worker
- **Invalid JSON in std_out** - Check claude output format is set to JSON
- **Missing session_id** - Verify worker completed successfully

---

## Test 4: Resume Conversation

### Part 4a: Write to Worker

**Command Syntax:**
```json
{
  "tool": "mcp__agent_manager__write_to_worker",
  "arguments": {
    "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "message": "Tell me more about the first language you mentioned"
  }
}
```

**Expected Response:**
```json
{
  "success": true,
  "message": "Resumed worker a1b2c3d4-..."
}
```

### Part 4b: Wait for Response

**Command Syntax:**
```json
{
  "tool": "mcp__agent_manager__wait",
  "arguments": {
    "timeout": 60.0
  }
}
```

**Expected Response:**
```json
[
  {
    "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "claude_session_id": "session-20251022123456-abc123",
    "std_out": "{\"session_id\": \"session-...\", \"output\": \"Python is a high-level...\"}",
    "std_err": "",
    "timeout": 60.0
  }
]
```

### Part 4c: Peek at New Response

**Command Syntax:**
```json
{
  "tool": "mcp__agent_manager__peek",
  "arguments": {
    "worker_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

### Validation Checklist
- [ ] `write_to_worker` succeeds without error
- [ ] Worker transitions: complete → active (after write) → complete (after wait)
- [ ] `session_id` remains the same across resume
- [ ] New `std_out` contains response about the programming language
- [ ] Second peek shows updated output

### Session Continuity Verification
```python
# Compare session IDs
initial_session_id = test3_response["claude_session_id"]
resumed_session_id = test4c_response["claude_session_id"]
assert initial_session_id == resumed_session_id, "Session ID should remain consistent"
```

### Common Issues
- **"Worker not found in complete tasks"** - Worker must be in complete state before writing
- **Session ID changed** - Indicates new session instead of resume; check --resume flag
- **Worker still active** - Wait for worker to complete before writing again

---

## Test 5: Parallel Workers (Racing Pattern)

### Part 5a: Create Multiple Workers

**Worker 1:**
```json
{
  "tool": "mcp__agent_manager__create_async_worker",
  "arguments": {
    "prompt": "Count to 3 slowly: 1... 2... 3...",
    "timeout": 120.0
  }
}
```
Response: `{ "worker_id": "worker-1-uuid" }`

**Worker 2:**
```json
{
  "tool": "mcp__agent_manager__create_async_worker",
  "arguments": {
    "prompt": "Say 'quick response' immediately",
    "timeout": 120.0
  }
}
```
Response: `{ "worker_id": "worker-2-uuid" }`

**Worker 3:**
```json
{
  "tool": "mcp__agent_manager__create_async_worker",
  "arguments": {
    "prompt": "List 5 colors: red, blue, green, yellow, purple",
    "timeout": 120.0
  }
}
```
Response: `{ "worker_id": "worker-3-uuid" }`

### Part 5b: Wait for First Completion

**Command Syntax:**
```json
{
  "tool": "mcp__agent_manager__wait",
  "arguments": {
    "timeout": 90.0
  }
}
```

**Expected Response:**
```json
[
  {
    "worker_id": "worker-2-uuid",
    "claude_session_id": "session-...",
    "std_out": "{...\"quick response\"...}",
    "std_err": "",
    "timeout": 120.0
  }
]
```

### Validation Checklist
- [ ] 3 workers created with unique IDs
- [ ] `wait` returns within reasonable time (< 45s typically)
- [ ] Winner is one of the 3 worker IDs
- [ ] Winner's output is accessible via peek
- [ ] Other workers still in active state (verify with subsequent wait)

### Racing Pattern Verification
```python
# Typically worker-2 (quick response) should win
winner_id = wait_response[0]["worker_id"]
assert winner_id in [worker1_id, worker2_id, worker3_id]

# Verify others still active by calling wait again
second_winner = wait(timeout=90.0)
assert second_winner[0]["worker_id"] != winner_id
```

### Common Issues
- **"Max 10 active workers"** - Clear previous workers first
- **All workers timeout** - Increase individual worker timeouts
- **Wait timeout expires** - Increase wait timeout or check worker prompts

---

## Test 6: Error Handling

### Test 6a: Peek on Non-Existent Worker

**Command Syntax:**
```json
{
  "tool": "mcp__agent_manager__peek",
  "arguments": {
    "worker_id": "00000000-0000-0000-0000-000000000000"
  }
}
```

**Expected Response:**
```json
{
  "error": "Worker 00000000-0000-0000-0000-000000000000 not found or not complete. try wait",
  "type": "ToolError"
}
```

### Test 6b: Write to Active Worker

**Setup:**
```json
// Create a slow worker
{
  "tool": "mcp__agent_manager__create_async_worker",
  "arguments": {
    "prompt": "Count to 100 slowly",
    "timeout": 300.0
  }
}
// Returns: { "worker_id": "slow-worker-uuid" }
```

**Command Syntax (immediately after creation):**
```json
{
  "tool": "mcp__agent_manager__write_to_worker",
  "arguments": {
    "worker_id": "slow-worker-uuid",
    "message": "Stop counting"
  }
}
```

**Expected Response:**
```json
{
  "error": "Worker slow-worker-uuid not found in complete tasks",
  "type": "ToolError"
}
```

### Validation Checklist
- [ ] Error messages are descriptive and actionable
- [ ] Error type is "ToolError"
- [ ] Server remains stable (no crashes)
- [ ] Subsequent valid requests still work

### Error Message Quality
Good error messages should:
- Identify the specific worker_id
- Explain why the operation failed
- Suggest next steps (e.g., "try wait")

### Common Issues
- **Error not raised** - Check server error handling implementation
- **Generic error message** - Improve error message specificity
- **Server crash** - Add proper exception handling

---

## Full Test Run Script

Execute all tests in sequence:

```bash
# Test 1: Create Worker
worker_id=$(call_mcp_tool create_async_worker '{"prompt": "Say hello and list exactly 3 programming languages", "timeout": 60.0}')

# Test 2: Wait for Completion
wait_result=$(call_mcp_tool wait '{"timeout": 60.0}')

# Test 3: Peek at Output
peek_result=$(call_mcp_tool peek "{\"worker_id\": \"$worker_id\"}")

# Test 4: Resume Conversation
call_mcp_tool write_to_worker "{\"worker_id\": \"$worker_id\", \"message\": \"Tell me more about the first language\"}"
wait_result=$(call_mcp_tool wait '{"timeout": 60.0}')
peek_result=$(call_mcp_tool peek "{\"worker_id\": \"$worker_id\"}")

# Test 5: Parallel Racing
worker1=$(call_mcp_tool create_async_worker '{"prompt": "Count to 3 slowly", "timeout": 120.0}')
worker2=$(call_mcp_tool create_async_worker '{"prompt": "Say quick response", "timeout": 120.0}')
worker3=$(call_mcp_tool create_async_worker '{"prompt": "List 5 colors", "timeout": 120.0}')
winner=$(call_mcp_tool wait '{"timeout": 90.0}')

# Test 6: Error Handling
call_mcp_tool peek '{"worker_id": "00000000-0000-0000-0000-000000000000"}'
slow_worker=$(call_mcp_tool create_async_worker '{"prompt": "Count to 100", "timeout": 300.0}')
call_mcp_tool write_to_worker "{\"worker_id\": \"$slow_worker\", \"message\": \"Stop\"}"
```

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Test Pass Rate | 100% | All 6 tests pass |
| Worker Creation Time | < 5s | Time to spawn worker |
| Wait Response Time | < 2s after completion | Time for wait to return |
| Session Resumption | 100% | Same session_id maintained |
| Error Clarity | 100% | All errors have actionable messages |

---

## Troubleshooting Guide

### Worker Creation Fails
- Check `claude` is in PATH: `which claude`
- Verify Python version: `python --version` (requires 3.13+)
- Check dependencies: `uv sync`

### Wait Timeouts
- Increase timeout parameter
- Check network connectivity for Claude API
- Verify worker prompts are reasonable

### Session Resume Fails
- Verify session_id format in stdout
- Check `--resume` flag is passed to claude
- Ensure worker is in complete state before writing

### Racing Pattern Not Working
- Create all workers before calling wait
- Verify workers are in active state
- Check that wait timeout is sufficient

### Error Messages Not Helpful
- Review server.py error handling
- Add more context to ToolError messages
- Include suggested actions in error text

---

## Version History

- **v0.1.0** (2025-10-22) - Initial test scenarios
  - Complete command reference for all 6 tests
  - Expected responses and validation checklists
  - Troubleshooting guide
  - Full test run script
