"""Unit tests for server.py (NEW async racing implementation)."""
import pytest
from unittest.mock import AsyncMock, patch, Mock
import json
import sys
from pathlib import Path
import asyncio
import contextlib

# Add src to path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.server import mcp, active_tasks, complete_tasks, workers, _event_queues
from src.server import ActiveTask, CompleteTask, ClaudeJobResult, Worker, WorkerStatus
from fastmcp import Client
from fastmcp.exceptions import ToolError


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before/after each test."""
    workers.clear()
    active_tasks.clear()
    complete_tasks.clear()
    # Clear all event queues
    _event_queues.clear()
    yield
    workers.clear()
    active_tasks.clear()
    complete_tasks.clear()
    # Clear all event queues
    _event_queues.clear()


# --- Test create_async_worker ---

@pytest.mark.anyio
async def test_create_async_worker_returns_worker_id():
    """Test that create_async_worker returns a string worker_id."""
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
            # Create a mock process
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123", "result": "Hello"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
            # Mock stdin.close() as a regular method (not async)
            mock_proc.stdin = Mock()
            mock_proc.stdin.close = Mock()
            mock_exec.return_value = mock_proc

            async with Client(mcp) as client:
                result = await client.call_tool("create_async_worker", {"prompt": "test"})

                # Should return string worker_id
                assert isinstance(result.data, str)
                # Should have UUID format
                assert len(result.data) == 36  # UUID length with dashes
                # Should have 1 active task
                assert len(active_tasks) == 1
                assert result.data in active_tasks
                assert active_tasks[result.data].worker_id == result.data


@pytest.mark.anyio
async def test_create_async_worker_max_workers_enforced():
    """Test that 11th active worker is rejected."""
    # Create 10 active tasks
    for i in range(10):
        worker_id = f"task-{i}"
        active_tasks[worker_id] = ActiveTask(
            worker_id=worker_id,
            task=AsyncMock(),
            timeout=300.0
        )

    async with Client(mcp) as client:
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("create_async_worker", {"prompt": "test"})
        assert "Max 10 active workers" in str(exc_info.value)


@pytest.mark.anyio
async def test_create_async_worker_complete_tasks_dont_count():
    """Test that complete tasks don't count toward max workers limit."""
    # Create 10 complete tasks
    for i in range(10):
        worker_id = f"complete-{i}"
        complete_tasks[worker_id] = CompleteTask(
            worker_id=worker_id,
            claude_session_id=f"session-{i}",
            output_file=f"/tmp/worker-{worker_id}.json",
            timeout=300.0
        )

    # Should still be able to create 10 active workers
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
            # Mock stdin.close() as a regular method (not async)
            mock_proc.stdin = Mock()
            mock_proc.stdin.close = Mock()
            mock_exec.return_value = mock_proc

            async with Client(mcp) as client:
                # Create 10 workers - should succeed
                for i in range(10):
                    result = await client.call_tool("create_async_worker", {"prompt": "test"})
                    assert isinstance(result.data, str)

                assert len(active_tasks) == 10
                assert len(complete_tasks) == 10


@pytest.mark.anyio
async def test_create_async_worker_claude_not_in_path():
    """Test error when claude command not found."""
    with patch('src.server.shutil.which', return_value=None):
        async with Client(mcp) as client:
            # create_async_worker will return worker_id, but the background task will fail
            result = await client.call_tool("create_async_worker", {"prompt": "test"})
            worker_id = result.data

            # Give the background task time to fail
            await asyncio.sleep(0.1)

            # Verify task is in active_tasks and failed
            assert len(active_tasks) == 1
            assert worker_id in active_tasks
            assert active_tasks[worker_id].worker_id == worker_id
            assert active_tasks[worker_id].task.done()

            # Verify it raised the expected error
            with pytest.raises(ToolError) as exc_info:
                active_tasks[worker_id].task.result()
            assert "not in PATH" in str(exc_info.value)


# --- Test resume_worker ---

@pytest.mark.anyio
async def test_resume_worker_resumes_conversation():
    """Test that resume_worker resumes a complete worker."""
    complete_tasks["task-1"] = CompleteTask(
        worker_id="task-1",
        claude_session_id="session-123",
        output_file="/tmp/worker-task-1.json",
        timeout=300.0
    )

    with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(
            json.dumps({"session_id": "session-123", "result": "Response"}).encode(),
            b""
        ))
        mock_proc.returncode = 0
        # Mock stdin.close() as a regular method (not async)
        mock_proc.stdin = Mock()
        mock_proc.stdin.close = Mock()
        mock_exec.return_value = mock_proc

        async with Client(mcp) as client:
            await client.call_tool("resume_worker", {
                "worker_id": "task-1",
                "message": "Follow up"
            })

            # Worker should be moved back to active
            assert len(complete_tasks) == 0
            assert len(active_tasks) == 1
            assert "task-1" in active_tasks
            assert active_tasks["task-1"].worker_id == "task-1"

            # Should call claude with --resume
            call_args = mock_exec.call_args[0]
            assert "claude" in call_args
            assert "--resume" in call_args
            assert "session-123" in call_args


@pytest.mark.anyio
async def test_resume_worker_nonexistent():
    """Test resuming non-existent worker raises error."""
    async with Client(mcp) as client:
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("resume_worker", {
                "worker_id": "nonexistent",
                "message": "test"
            })
        assert "not found" in str(exc_info.value)


# --- Test race ---

@pytest.mark.anyio
async def test_wait_no_active_tasks():
    """Test waitwith no active tasks raises error."""
    async with Client(mcp) as client:
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("wait", {"timeout": 1.0})
        assert "No active workers" in str(exc_info.value)


@pytest.mark.anyio
async def test_wait_returns_first_completion():
    """Test waitreturns first completed worker."""
    # Create a real completed task
    async def complete_immediately():
        return ClaudeJobResult(
            worker_id="task-1",
            returncode=0,
            stdout=json.dumps({"session_id": "session-1"}),
            stderr="",
            output_file="/tmp/worker-task-1.json"
        )

    task = asyncio.create_task(complete_immediately())
    await task  # Let it complete

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {"timeout": 5.0})

        # Should return WorkerState with completed tasks and permissions
        assert isinstance(result.structured_content, dict)
        assert "completed" in result.structured_content
        assert "pending_permissions" in result.structured_content
        assert isinstance(result.structured_content["completed"], list)
        assert len(result.structured_content["completed"]) == 1
        # Access as dict since fastmcp serializes dataclasses
        assert result.structured_content["completed"][0]["worker_id"] == "task-1"
        assert result.structured_content["completed"][0]["claude_session_id"] == "session-1"
        # Pending permissions should be empty (no permissions requested)
        assert result.structured_content["pending_permissions"] == []
        # Task should be moved to complete
        assert len(active_tasks) == 0
        assert len(complete_tasks) == 1
        assert "task-1" in complete_tasks
        assert complete_tasks["task-1"].claude_session_id == "session-1"


@pytest.mark.anyio
async def test_wait_timeout():
    """Test waittimeout raises error."""
    # Create a real task that never completes
    async def wait_forever():
        await asyncio.sleep(1000)
        return ClaudeJobResult(worker_id="task-1", returncode=0, stdout="", stderr="", output_file="/tmp/worker-task-1.json")

    task = asyncio.create_task(wait_forever())

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)

    try:
        async with Client(mcp) as client:
            res = await client.call_tool("wait", {"timeout": 0.1})
            # WorkerState with no completed tasks
            assert len(res.structured_content["completed"]) == 0
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_wait_returns_failed_workers():
    """Test that wait() returns failed workers in WorkerState.failed."""
    # Create a task that will fail
    async def failing_worker():
        return ClaudeJobResult(
            worker_id="task-1",
            returncode=1,
            stdout="",
            stderr="Error: something went wrong",
            output_file="/tmp/worker-task-1.json"
        )

    task = asyncio.create_task(failing_worker())
    await task  # Let it complete

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {"timeout": 5.0})

        # Should have failed task, not raise exception
        assert "failed" in result.structured_content
        assert len(result.structured_content["failed"]) == 1
        assert result.structured_content["failed"][0]["worker_id"] == "task-1"
        assert result.structured_content["failed"][0]["returncode"] == 1
        assert "Error: something went wrong" in result.structured_content["failed"][0]["error_hint"]


@pytest.mark.anyio
async def test_wait_bad_return_code():
    """Test that wait() returns failed workers (not exceptions) for bad return codes."""
    # Create a real task that returns bad exit code
    async def bad_return_code():
        return ClaudeJobResult(worker_id="task-1", returncode=1, stdout="", stderr="error", output_file="/tmp/worker-task-1.json")

    task = asyncio.create_task(bad_return_code())
    await task  # Let it complete

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {"timeout": 5.0})

        # Should return failed task in WorkerState, not raise exception
        assert "failed" in result.structured_content
        assert len(result.structured_content["failed"]) == 1
        assert result.structured_content["failed"][0]["worker_id"] == "task-1"
        assert result.structured_content["failed"][0]["returncode"] == 1


@pytest.mark.anyio
async def test_wait_mixed_success_and_failure():
    """Test that wait() returns both successful and failed workers."""
    # Create tasks with mixed outcomes
    async def successful_worker():
        return ClaudeJobResult(
            worker_id="task-success",
            returncode=0,
            stdout=json.dumps({"session_id": "session-1"}),
            stderr="",
            output_file="/tmp/worker-task-1.json"
        )

    async def failing_worker():
        return ClaudeJobResult(
            worker_id="task-fail",
            returncode=1,
            stdout="",
            stderr="Error occurred",
            output_file="/tmp/worker-task-fail.json"
        )

    task_success = asyncio.create_task(successful_worker())
    task_fail = asyncio.create_task(failing_worker())
    await asyncio.gather(task_success, task_fail)

    active_tasks["task-success"] = ActiveTask(worker_id="task-success", task=task_success, timeout=300.0)
    active_tasks["task-fail"] = ActiveTask(worker_id="task-fail", task=task_fail, timeout=300.0)

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {"timeout": 5.0})

        # Should have both completed and failed
        assert "completed" in result.structured_content
        assert "failed" in result.structured_content
        assert len(result.structured_content["completed"]) == 1
        assert len(result.structured_content["failed"]) == 1
        assert result.structured_content["completed"][0]["worker_id"] == "task-success"
        assert result.structured_content["failed"][0]["worker_id"] == "task-fail"


@pytest.mark.anyio
async def test_wait_multiple_simultaneous_completions():
    """Test waitreturns all tasks that complete simultaneously."""
    # Create multiple tasks that complete immediately
    async def complete_immediately(worker_id: str, session_id: str):
        return ClaudeJobResult(
            worker_id=worker_id,
            returncode=0,
            stdout=json.dumps({"session_id": session_id}),
            stderr="",
            output_file="/tmp/worker-task-1.json"
        )

    # Create and complete 3 tasks
    task1 = asyncio.create_task(complete_immediately("task-1", "session-1"))
    task2 = asyncio.create_task(complete_immediately("task-2", "session-2"))
    task3 = asyncio.create_task(complete_immediately("task-3", "session-3"))
    await asyncio.gather(task1, task2, task3)

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task1, timeout=300.0)
    active_tasks["task-2"] = ActiveTask(worker_id="task-2", task=task2, timeout=300.0)
    active_tasks["task-3"] = ActiveTask(worker_id="task-3", task=task3, timeout=300.0)

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {"timeout": 5.0})

        # Should return WorkerState with all 3 completed tasks
        assert isinstance(result.structured_content, dict)
        assert "completed" in result.structured_content
        assert isinstance(result.structured_content["completed"], list)
        assert len(result.structured_content["completed"]) == 3

        # Verify all tasks were processed (access as dicts)
        worker_ids = {task["worker_id"] for task in result.structured_content["completed"]}
        assert worker_ids == {"task-1", "task-2", "task-3"}

        # All tasks should be moved to complete
        assert len(active_tasks) == 0
        assert len(complete_tasks) == 3
        assert "task-1" in complete_tasks
        assert "task-2" in complete_tasks
        assert "task-3" in complete_tasks


# --- Test concurrent operations ---

@pytest.mark.anyio
async def test_multiple_workers_concurrent():
    """Test creating multiple workers concurrently."""
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
            # Mock stdin.close() as a regular method (not async)
            mock_proc.stdin = Mock()
            mock_proc.stdin.close = Mock()
            mock_exec.return_value = mock_proc

            async with Client(mcp) as client:
                # Create 3 workers
                worker_ids = []
                for i in range(3):
                    result = await client.call_tool("create_async_worker", {
                        "prompt": f"Task {i}"
                    })
                    worker_ids.append(result.data)

                assert len(worker_ids) == 3
                assert len(set(worker_ids)) == 3  # All unique
                assert len(active_tasks) == 3


# --- Test race with worker_id ---

@pytest.mark.anyio
async def test_wait_with_specific_worker_id():
    """Test waitwaits for a specific worker when worker_id is provided."""
    # Create two tasks that complete at different times
    async def complete_after_delay(worker_id: str, delay: float):
        await asyncio.sleep(delay)
        return ClaudeJobResult(
            worker_id=worker_id,
            returncode=0,
            stdout=json.dumps({"session_id": f"session-{worker_id}"}),
            stderr="",
            output_file="/tmp/worker-task-1.json"
        )

    # Task 1 completes immediately, Task 2 completes after 0.1s
    task1 = asyncio.create_task(complete_after_delay("task-1", 0))
    task2 = asyncio.create_task(complete_after_delay("task-2", 0.1))

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task1, timeout=300.0)
    active_tasks["task-2"] = ActiveTask(worker_id="task-2", task=task2, timeout=300.0)

    async with Client(mcp) as client:
        # Race for task-2 specifically
        result = await client.call_tool("wait", {"timeout": 5.0, "worker_id": "task-2"})

        # Should return WorkerState with only task-2
        assert isinstance(result.structured_content, dict)
        assert "completed" in result.structured_content
        assert len(result.structured_content["completed"]) == 1
        assert result.structured_content["completed"][0]["worker_id"] == "task-2"
        assert result.structured_content["completed"][0]["claude_session_id"] == "session-task-2"

        # Both tasks should be in complete_tasks (task-1 completed first)
        assert len(complete_tasks) >= 1
        assert "task-2" in complete_tasks


@pytest.mark.anyio
async def test_wait_with_worker_id_already_complete():
    """Test waitreturns immediately if worker_id is already complete."""
    # Add a worker to complete_tasks
    complete_tasks["task-1"] = CompleteTask(
        worker_id="task-1",
        claude_session_id="session-1",
        output_file="/tmp/worker-task-1.json",
        timeout=300.0
    )

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {"timeout": 5.0, "worker_id": "task-1"})

        # Should return WorkerState with task-1 immediately
        assert isinstance(result.structured_content, dict)
        assert "completed" in result.structured_content
        assert len(result.structured_content["completed"]) == 1
        assert result.structured_content["completed"][0]["worker_id"] == "task-1"
        assert result.structured_content["completed"][0]["claude_session_id"] == "session-1"


@pytest.mark.anyio
async def test_wait_with_nonexistent_worker_id():
    """Test waitraises error for nonexistent worker_id."""
    # Create one active task
    async def complete_immediately():
        return ClaudeJobResult(
            worker_id="task-1",
            returncode=0,
            stdout=json.dumps({"session_id": "session-1"}),
            stderr="",
            output_file="/tmp/worker-task-1.json"
        )

    task = asyncio.create_task(complete_immediately())
    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)

    async with Client(mcp) as client:
        # Try to race for non-existent worker
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("wait", {"timeout": 5.0, "worker_id": "nonexistent"})
        assert "not found" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_wait_with_worker_id_processes_other_workers():
    """Test waitprocesses all completed workers while waiting for specific one."""
    # Create three tasks: task-1 completes first, task-2 completes second, task-3 completes third
    async def complete_after_delay(worker_id: str, delay: float):
        await asyncio.sleep(delay)
        return ClaudeJobResult(
            worker_id=worker_id,
            returncode=0,
            stdout=json.dumps({"session_id": f"session-{worker_id}"}),
            stderr="",
            output_file="/tmp/worker-task-1.json"
        )

    task1 = asyncio.create_task(complete_after_delay("task-1", 0))
    task2 = asyncio.create_task(complete_after_delay("task-2", 0.05))
    task3 = asyncio.create_task(complete_after_delay("task-3", 0.1))

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task1, timeout=300.0)
    active_tasks["task-2"] = ActiveTask(worker_id="task-2", task=task2, timeout=300.0)
    active_tasks["task-3"] = ActiveTask(worker_id="task-3", task=task3, timeout=300.0)

    async with Client(mcp) as client:
        # Race for task-3 specifically (the last to complete)
        result = await client.call_tool("wait", {"timeout": 5.0, "worker_id": "task-3"})

        # Should return WorkerState with only task-3
        assert isinstance(result.structured_content, dict)
        assert "completed" in result.structured_content
        assert len(result.structured_content["completed"]) == 1
        assert result.structured_content["completed"][0]["worker_id"] == "task-3"

        # All three tasks should be in complete_tasks since they completed during the wait
        assert len(complete_tasks) == 3
        assert "task-1" in complete_tasks
        assert "task-2" in complete_tasks
        assert "task-3" in complete_tasks


@pytest.mark.anyio
async def test_wait_event_latency():
    """Test that event-driven wait() has sub-150ms latency."""
    import time

    # Create a task that completes immediately
    async def complete_immediately():
        return ClaudeJobResult(
            worker_id="task-1",
            returncode=0,
            stdout=json.dumps({"session_id": "session-1"}),
            stderr="",
            output_file="/tmp/worker-task-1.json"
        )

    task = asyncio.create_task(complete_immediately())
    await task
    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)
    workers["task-1"] = Worker(
        worker_id="task-1",
        status=WorkerStatus.ACTIVE,
        timeout=300.0,
        task=task
    )

    async with Client(mcp) as client:
        start = time.time()
        result = await client.call_tool("wait", {"timeout": 5.0})
        latency = (time.time() - start) * 1000  # Convert to ms

        print(f"\nWait latency: {latency:.1f}ms")
        # Event-driven should be <150ms, old polling was ~500ms
        assert latency < 150, f"Expected <150ms, got {latency:.1f}ms"


