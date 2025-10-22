---
name: integration-test
description: Run integration tests for the async-worker-manager MCP server. Validates all 4 core tools (create_async_worker, wait, peek, write_to_worker), racing pattern, error handling, and session resumption. Use when the user asks to "test the agent-manager MCP", "run integration tests", "verify async workers", or mentions "testing MCP server".
allowed-tools:
  - mcp__agent_manager__create_async_worker
  - mcp__agent_manager__wait
  - mcp__agent_manager__peek
  - mcp__agent_manager__write_to_worker
---

# Integration Test Skill

This skill runs comprehensive integration tests for the async-worker-manager MCP server to validate all functionality in a live Claude Code instance.

## Test Suite Overview

The integration test validates 6 key scenarios:

1. **Basic Worker Creation** - Verify worker spawning and ID generation
2. **Wait for Completion** - Test the wait mechanism
3. **Peek at Output** - Validate output retrieval
4. **Resume Conversation** - Test session continuity
5. **Parallel Racing** - Verify racing pattern with multiple workers
6. **Error Handling** - Validate error messages

## Detailed Test Scenarios

### Test 1: Create Worker
**Objective:** Verify that `create_async_worker` spawns a worker and returns a valid UUID.

**Command:**
```
create_async_worker(
  prompt: "Say hello and list exactly 3 programming languages",
  timeout: 60.0
)
```

**Expected Outcome:**
- Returns a worker_id in UUID format (e.g., "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
- No errors thrown

**Validation:**
- worker_id matches UUID pattern
- worker_id is a non-empty string

---

### Test 2: Wait for Completion
**Objective:** Verify that `wait` returns when the worker completes.

**Command:**
```
wait(timeout: 60.0)
```

**Expected Outcome:**
- Returns a list containing CompleteTask object(s)
- Completes within timeout period
- worker_id matches the one from Test 1

**Validation:**
- Response contains worker_id
- Response includes claude_session_id
- status field shows "complete"

---

### Test 3: Peek at Output
**Objective:** Verify that `peek` retrieves stdout/stderr from completed worker.

**Command:**
```
peek(worker_id: "<worker_id_from_test_1>")
```

**Expected Outcome:**
- Returns CompleteTask with:
  - worker_id
  - claude_session_id (session-XXXXX format)
  - std_out containing the response
  - std_err (may be empty)
  - timeout value

**Validation:**
- stdout contains "hello" (case-insensitive)
- stdout contains 3 programming languages
- session_id matches format "session-" + alphanumeric

---

### Test 4: Resume Conversation
**Objective:** Verify that `write_to_worker` resumes a completed worker's conversation.

**Command:**
```
write_to_worker(
  worker_id: "<worker_id_from_test_1>",
  message: "Tell me more about the first language you mentioned"
)
```

Then:
```
wait(timeout: 60.0)
```

Then:
```
peek(worker_id: "<worker_id_from_test_1>")
```

**Expected Outcome:**
- `write_to_worker` succeeds without error
- Second `wait` returns the same worker_id
- Second `peek` shows response about the first language
- Same session_id maintained across resume

**Validation:**
- worker transitions from complete → active → complete
- session_id remains consistent
- stdout from second peek contains relevant information about the programming language

---

### Test 5: Parallel Workers (Racing Pattern)
**Objective:** Verify that multiple workers run concurrently and `wait` returns first completion.

**Commands:**
```
# Create 3 workers
worker1 = create_async_worker(prompt: "Count to 3 slowly", timeout: 120.0)
worker2 = create_async_worker(prompt: "Say 'quick response'", timeout: 120.0)
worker3 = create_async_worker(prompt: "List 5 colors", timeout: 120.0)

# Wait for first completion
winner = wait(timeout: 90.0)
```

**Expected Outcome:**
- All 3 workers created successfully
- `wait` returns immediately when first worker completes
- winner.worker_id matches one of the 3 worker IDs
- Other workers remain in active state

**Validation:**
- 3 unique worker_ids generated
- wait returns within reasonable time
- peek(winner.worker_id) succeeds
- Racing pattern works correctly

---

### Test 6: Error Handling
**Objective:** Verify that proper error messages are returned for invalid operations.

**Test 6a: Peek on Non-Existent Worker**
```
peek(worker_id: "00000000-0000-0000-0000-000000000000")
```
**Expected:** ToolError with message like "Worker ... not found or not complete"

**Test 6b: Write to Active Worker**
```
# Create worker
worker_id = create_async_worker(prompt: "Count to 100", timeout: 300.0)

# Immediately try to write (before it completes)
write_to_worker(worker_id: worker_id, message: "Stop")
```
**Expected:** ToolError with message like "Worker ... not found in complete tasks"

**Validation:**
- Error messages are clear and actionable
- Errors don't crash the server
- Proper ToolError exceptions raised

---

## Test Execution Strategy

1. **Sequential Execution:** Run Tests 1-4 in order (they build on each other)
2. **Independent Tests:** Run Test 5 and 6 independently
3. **Cleanup:** No cleanup needed - workers auto-transition states
4. **Timing:** Allow generous timeouts for worker completion (60-120s)

## Success Criteria

✅ All 6 test scenarios pass without errors
✅ Worker creation returns valid UUIDs
✅ Wait mechanism works correctly
✅ Peek retrieves complete output
✅ Session resumption maintains continuity
✅ Racing pattern returns first completion
✅ Error messages are clear and helpful
✅ No server crashes or hangs

## Supporting Files

For detailed command syntax and expected response formats, see:
- `test-scenarios.md` - Full test command reference

## Troubleshooting

**Worker Timeouts:**
- Default timeout is 60-120s - increase if workers timeout
- Check that `claude` is in PATH
- Verify network connectivity for claude API calls

**Session ID Issues:**
- Ensure stdout parsing works with `--output-format json`
- Verify session_id format is "session-XXXXX"

**Racing Pattern Not Working:**
- Check that all workers are created before calling wait
- Verify workers are in active state before wait

## Version History

- **v0.1.0** (2025-10-22) - Initial integration test skill
  - 6 comprehensive test scenarios
  - Tests all 4 core MCP tools
  - Validates racing pattern and error handling
  - Session resumption verification
