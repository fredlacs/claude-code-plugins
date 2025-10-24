---
name: integration-test
description: Run integration tests for the async-worker-manager MCP server. Validates all 4 core tools (spawn_worker, wait, resume_worker, approve_permission), racing pattern, error handling, permissions, and session resumption. Use when the user asks to "test the async-worker-manager MCP", "run integration tests", "verify async workers", or mentions "testing MCP server".
allowed-tools:
  - mcp__async_worker_manager__spawn_worker
  - mcp__async_worker_manager__wait
  - mcp__async_worker_manager__resume_worker
  - mcp__async_worker_manager__approve_permission
  - Read
---

# Integration Test Skill

This skill runs comprehensive integration tests for the async-worker-manager MCP server to validate all functionality in a live Claude Code instance.

## Test Suite Overview

The integration test validates 10 key scenarios:

1. **Basic Worker Creation** - Verify worker spawning and ID generation
2. **Wait for Completion** - Test the wait mechanism
3. **File-Based Output** - Validate conversation history file access
4. **Resume Conversation** - Test session continuity
5. **Parallel Workers** - Verify batch mode with multiple workers
6. **Agent Types** - Test custom agent types
7. **Worker Options** - Test temperature, model, thinking settings
8. **Permission Handling** - Test permission request flow
9. **Failed Workers** - Validate error handling and hints
10. **Error Cases** - Validate error messages for invalid operations

## Detailed Test Scenarios

### Test 1: Create Worker
**Objective:** Verify that `spawn_worker` spawns a worker and returns a valid UUID.

**Command:**
```
spawn_worker(
  description: "List programming languages",
  prompt: "Say hello and list exactly 3 programming languages"
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
wait()
```

**Expected Outcome:**
- Returns WorkerState with:
  - completed: list with CompleteTask object(s)
  - failed: empty list
  - pending_permissions: empty list
- Completes successfully
- worker_id matches the one from Test 1

**Validation:**
- Response contains completed list with worker_id
- Response includes claude_session_id
- Response includes conversation_history_file_path
- File path exists and points to logs/worker-{id}.json

---

### Test 3: File-Based Output
**Objective:** Verify that conversation history file contains the complete output.

**Command:**
```
Read(file_path: "<conversation_history_file_path_from_test_2>")
```

**Expected Outcome:**
- File exists and is readable
- Contains JSON with:
  - session_id (session-XXXXX format)
  - output (the actual response text)

**Validation:**
- JSON parses correctly
- session_id matches claude_session_id from Test 2
- output contains "hello" (case-insensitive)
- output contains 3 programming languages

---

### Test 4: Resume Conversation
**Objective:** Verify that `resume_worker` resumes a completed worker's conversation.

**Command:**
```
resume_worker(
  worker_id: "<worker_id_from_test_1>",
  prompt: "Tell me more about the first language you mentioned"
)
```

Then:
```
wait()
```

Then:
```
Read(file_path: "<conversation_history_file_path>")
```

**Expected Outcome:**
- `resume_worker` succeeds without error
- Second `wait` returns the same worker_id in completed list
- Conversation history file shows response about the first language
- Same session_id maintained across resume

**Validation:**
- worker transitions from completed → active → completed
- session_id remains consistent
- Output contains relevant information about the programming language

---

### Test 5: Parallel Workers (Batch Mode)
**Objective:** Verify that multiple workers run concurrently and `wait` returns all completions.

**Commands:**
```
# Create 3 workers
worker1 = spawn_worker(description: "Count slowly", prompt: "Count to 3 slowly")
worker2 = spawn_worker(description: "Quick response", prompt: "Say 'quick response'")
worker3 = spawn_worker(description: "List colors", prompt: "List 5 colors")

# Wait for all completions
result = wait()
```

**Expected Outcome:**
- All 3 workers created successfully
- `wait` returns WorkerState with all 3 workers in completed list
- Each worker has unique worker_id
- Each has conversation_history_file_path

**Validation:**
- 3 unique worker_ids generated
- wait returns all 3 completions
- All conversation history files accessible
- Batch mode works correctly

---

### Test 6: Agent Types
**Objective:** Verify that custom agent_type parameter works.

**Command:**
```
spawn_worker(
  description: "Explore codebase",
  prompt: "Find all Python files in the current directory",
  agent_type: "Explore"
)
wait()
```

**Expected Outcome:**
- Worker created with agent_type
- Completes successfully
- Output reflects the agent's behavior

**Validation:**
- Worker spawns without error
- wait returns completion
- Conversation history shows agent followed the Explore pattern

---

### Test 7: Worker Options
**Objective:** Verify that options (temperature, model, thinking) work.

**Command:**
```
spawn_worker(
  description: "Test with options",
  prompt: "Explain what temperature means in LLMs",
  options: {
    "temperature": 0.5,
    "model": "claude-sonnet-4-5",
    "thinking": true
  }
)
wait()
```

**Expected Outcome:**
- Worker created with custom options
- Completes successfully
- Settings are applied (check stderr for model confirmation)

**Validation:**
- Worker spawns without error
- wait returns completion
- Model setting is respected

---

### Test 8: Permission Handling
**Objective:** Verify permission request and approval flow.

**Command:**
```
# Create worker that will need permission
worker_id = spawn_worker(
  description: "File write test",
  prompt: "Create a test file named /tmp/test-async-worker.txt with content 'hello'"
)

# Wait will return pending_permissions
result = wait()
```

**Expected Outcome:**
- `wait` returns WorkerState with:
  - pending_permissions: list with PermissionRequest
  - completed: empty (worker blocked)
  - failed: empty

**Then:**
```
approve_permission(
  request_id: result.pending_permissions[0].request_id,
  allow: true
)

# Wait again for completion
final_result = wait()
```

**Expected Outcome:**
- Permission approved successfully
- Second wait returns worker in completed list
- File was created

**Validation:**
- Permission request structure is correct
- approve_permission unblocks worker
- Worker completes successfully after approval
- Requested action executed

---

### Test 9: Failed Workers
**Objective:** Verify that failed workers are reported correctly.

**Command:**
```
# Create worker with invalid command
spawn_worker(
  description: "Invalid tool",
  prompt: "Use the tool 'nonexistent_tool' to do something"
)
result = wait()
```

**Expected Outcome:**
- `wait` returns WorkerState with:
  - failed: list with FailedTask
  - error_hint: brief actionable message
  - conversation_history_file_path: may contain partial output

**Validation:**
- Failed worker reported in failed list
- error_hint is descriptive
- returncode is non-zero
- Server doesn't crash

---

### Test 10: Error Handling
**Objective:** Verify that proper error messages are returned for invalid operations.

**Test 10a: Resume Non-Existent Worker**
```
resume_worker(worker_id: "00000000-0000-0000-0000-000000000000", prompt: "Hello")
```
**Expected:** ToolError with message like "Worker ... not found"

**Test 10b: Resume Active Worker**
```
# Create worker
worker_id = spawn_worker(description: "Slow task", prompt: "Count to 100")

# Immediately try to resume (before it completes)
resume_worker(worker_id: worker_id, prompt: "Stop")
```
**Expected:** ToolError with message like "Worker ... is not in completed state"

**Test 10c: Wait with No Active Workers**
```
# After all workers complete
wait()
```
**Expected:** ToolError with message like "No active workers to wait for"

**Validation:**
- Error messages are clear and actionable
- Errors don't crash the server
- Proper ToolError exceptions raised

---

## Test Execution Strategy

1. **Sequential Execution:** Run Tests 1-4 in order (they build on each other)
2. **Independent Tests:** Run Tests 5-10 independently
3. **Cleanup:** No cleanup needed - workers auto-transition states
4. **File Access:** Use Read tool to access conversation history files

## Success Criteria

✅ All 10 test scenarios pass without errors
✅ Worker creation returns valid UUIDs
✅ Wait mechanism works correctly
✅ File-based output is accessible and parseable
✅ Session resumption maintains continuity
✅ Batch mode returns all completions
✅ Agent types work correctly
✅ Worker options are applied
✅ Permission flow works end-to-end
✅ Failed workers are reported with helpful hints
✅ Error messages are clear and helpful
✅ No server crashes or hangs

## Supporting Files

For detailed command syntax and expected response formats, see:
- `test-scenarios.md` - Full test command reference

## API Reference

### Tools Available

1. **spawn_worker** - Create new worker
   - description: string (required) - Short 3-5 word description
   - prompt: string (required) - Detailed instructions
   - agent_type: string (optional) - "Explore", "general-purpose", or custom
   - options: dict (optional) - model, temperature, thinking, etc.

2. **wait** - Wait for all active workers
   - No parameters
   - Returns: WorkerState with completed, failed, pending_permissions

3. **resume_worker** - Resume completed worker
   - worker_id: string (required)
   - prompt: string (required)
   - options: dict (optional)

4. **approve_permission** - Approve/deny permission request
   - request_id: string (required)
   - allow: bool (required)
   - reason: string (optional)

## Troubleshooting

**Worker Timeouts:**
- Workers have no timeout by default - they run until completion
- Check that `claude` is in PATH
- Verify network connectivity for Claude API calls

**Session ID Issues:**
- Ensure stdout parsing works with `--output-format json`
- Verify session_id format is "session-XXXXX"

**Permission Issues:**
- Check pending_permissions in wait result
- Call approve_permission before waiting again
- Permissions must be approved for worker to proceed

**File Not Found:**
- conversation_history_file_path is absolute path
- Files are in logs/ directory relative to plugin root
- Use Read tool to access files

## Version History

- **v0.2.0** (2025-10-23) - Updated for current API
  - 10 comprehensive test scenarios
  - Tests all 4 core MCP tools
  - Added permission handling tests
  - Added agent type and options tests
  - Added failed worker tests
  - Updated to file-based output
  - Renamed tools (spawn_worker, resume_worker, wait)
- **v0.1.0** (2025-10-22) - Initial integration test skill
  - 6 comprehensive test scenarios
  - Tests all 4 core MCP tools (old API)
  - Validates racing pattern and error handling
  - Session resumption verification
