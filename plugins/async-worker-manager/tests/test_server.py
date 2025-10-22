"""Unit tests for server.py (NEW async racing implementation)."""
import pytest
from unittest.mock import AsyncMock, patch, Mock
import json
import sys
from pathlib import Path
import asyncio
import contextlib

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import server
from server import mcp, active_tasks, complete_tasks
from server import ActiveTask, CompleteTask, ClaudeJobResult
from fastmcp import Client
from fastmcp.exceptions import ToolError


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before/after each test."""
    active_tasks.clear()
    complete_tasks.clear()
    yield
    active_tasks.clear()
    complete_tasks.clear()


# --- Test create_async_worker ---

@pytest.mark.anyio
async def test_create_async_worker_returns_worker_id():
    """Test that create_async_worker returns a string worker_id."""
    with patch('server.shutil.which', return_value='/usr/bin/claude'):
        with patch('server.asyncio.create_subprocess_exec') as mock_exec:
            # Create a mock process
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123", "result": "Hello"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
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
            std_out="output",
            std_err="",
            timeout=300.0
        )

    # Should still be able to create 10 active workers
    with patch('server.shutil.which', return_value='/usr/bin/claude'):
        with patch('server.asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
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
    with patch('server.shutil.which', return_value=None):
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


# --- Test peek ---

@pytest.mark.anyio
async def test_peek_complete_worker():
    """Test peeking at a complete worker."""
    complete_tasks["task-1"] = CompleteTask(
        worker_id="task-1",
        claude_session_id="session-123",
        std_out="Hello world",
        std_err="Some warning",
        timeout=300.0
    )

    async with Client(mcp) as client:
        result = await client.call_tool("peek", {"worker_id": "task-1"})

        # peek returns CompleteTask object - access as attributes
        assert result.data.worker_id == "task-1"
        assert result.data.claude_session_id == "session-123"
        assert result.data.std_out == "Hello world"
        assert result.data.std_err == "Some warning"


@pytest.mark.anyio
async def test_peek_nonexistent_worker():
    """Test peeking at non-existent worker raises error."""
    async with Client(mcp) as client:
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("peek", {"worker_id": "nonexistent"})
        assert "not found" in str(exc_info.value)


# --- Test write_to_worker ---

@pytest.mark.anyio
async def test_write_to_worker_resumes_conversation():
    """Test that write_to_worker resumes a complete worker."""
    complete_tasks["task-1"] = CompleteTask(
        worker_id="task-1",
        claude_session_id="session-123",
        std_out="Previous output",
        std_err="",
        timeout=300.0
    )

    with patch('server.asyncio.create_subprocess_exec') as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(
            json.dumps({"session_id": "session-123", "result": "Response"}).encode(),
            b""
        ))
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        async with Client(mcp) as client:
            await client.call_tool("write_to_worker", {
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
async def test_write_to_worker_nonexistent():
    """Test writing to non-existent worker raises error."""
    async with Client(mcp) as client:
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("write_to_worker", {
                "worker_id": "nonexistent",
                "message": "test"
            })
        assert "not found" in str(exc_info.value)


# --- Test wait ---

@pytest.mark.anyio
async def test_wait_no_active_tasks():
    """Test wait with no active tasks raises error."""
    async with Client(mcp) as client:
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("wait", {"timeout": 1.0})
        assert "No active workers" in str(exc_info.value)


@pytest.mark.anyio
async def test_wait_returns_first_completion():
    """Test wait returns first completed worker."""
    # Create a real completed task
    async def complete_immediately():
        return ClaudeJobResult(
            worker_id="task-1",
            returncode=0,
            stdout=json.dumps({"session_id": "session-1"}),
            stderr=""
        )

    task = asyncio.create_task(complete_immediately())
    await task  # Let it complete

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {"timeout": 5.0})

        # Should return list of CompleteTask objects (serialized as dicts)
        assert isinstance(result.data, list)
        assert len(result.data) == 1
        # Access as dict since fastmcp serializes dataclasses
        assert result.data[0]["worker_id"] == "task-1"
        assert result.data[0]["claude_session_id"] == "session-1"
        # Task should be moved to complete
        assert len(active_tasks) == 0
        assert len(complete_tasks) == 1
        assert "task-1" in complete_tasks
        assert complete_tasks["task-1"].claude_session_id == "session-1"


@pytest.mark.anyio
async def test_wait_timeout():
    """Test wait timeout raises error."""
    # Create a real task that never completes
    async def wait_forever():
        await asyncio.sleep(1000)
        return ClaudeJobResult(worker_id="task-1", returncode=0, stdout="", stderr="")

    task = asyncio.create_task(wait_forever())

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)

    try:
        async with Client(mcp) as client:
            res = await client.call_tool("wait", {"timeout": 0.1})
            assert len(res.data) == 0
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_wait_bad_return_code():
    """Test wait with bad return code raises error."""
    # Create a real task that returns bad exit code
    async def bad_return_code():
        return ClaudeJobResult(worker_id="task-1", returncode=1, stdout="", stderr="error")

    task = asyncio.create_task(bad_return_code())
    await task  # Let it complete

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)

    async with Client(mcp) as client:
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("wait", {"timeout": 5.0})
        error_msg = str(exc_info.value).lower()
        assert "one or more workers failed" in error_msg or "worker" in error_msg


@pytest.mark.anyio
async def test_wait_multiple_simultaneous_completions():
    """Test wait returns all tasks that complete simultaneously."""
    # Create multiple tasks that complete immediately
    async def complete_immediately(worker_id: str, session_id: str):
        return ClaudeJobResult(
            worker_id=worker_id,
            returncode=0,
            stdout=json.dumps({"session_id": session_id}),
            stderr=""
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

        # Should return list with all 3 completed tasks
        assert isinstance(result.data, list)
        assert len(result.data) == 3

        # Verify all tasks were processed (access as dicts)
        worker_ids = {task["worker_id"] for task in result.data}
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
    with patch('server.shutil.which', return_value='/usr/bin/claude'):
        with patch('server.asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
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


# --- Test wait with worker_id ---

@pytest.mark.anyio
async def test_wait_with_specific_worker_id():
    """Test wait waits for a specific worker when worker_id is provided."""
    # Create two tasks that complete at different times
    async def complete_after_delay(worker_id: str, delay: float):
        await asyncio.sleep(delay)
        return ClaudeJobResult(
            worker_id=worker_id,
            returncode=0,
            stdout=json.dumps({"session_id": f"session-{worker_id}"}),
            stderr=""
        )

    # Task 1 completes immediately, Task 2 completes after 0.1s
    task1 = asyncio.create_task(complete_after_delay("task-1", 0))
    task2 = asyncio.create_task(complete_after_delay("task-2", 0.1))

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task1, timeout=300.0)
    active_tasks["task-2"] = ActiveTask(worker_id="task-2", task=task2, timeout=300.0)

    async with Client(mcp) as client:
        # wait for task-2 specifically
        result = await client.call_tool("wait", {"timeout": 5.0, "worker_id": "task-2"})

        # Should return only task-2
        assert isinstance(result.data, list)
        assert len(result.data) == 1
        assert result.data[0]["worker_id"] == "task-2"
        assert result.data[0]["claude_session_id"] == "session-task-2"

        # Both tasks should be in complete_tasks (task-1 completed first)
        assert len(complete_tasks) >= 1
        assert "task-2" in complete_tasks


@pytest.mark.anyio
async def test_wait_with_worker_id_already_complete():
    """Test wait returns immediately if worker_id is already complete."""
    # Add a worker to complete_tasks
    complete_tasks["task-1"] = CompleteTask(
        worker_id="task-1",
        claude_session_id="session-1",
        std_out=json.dumps({"session_id": "session-1"}),
        std_err="",
        timeout=300.0
    )

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {"timeout": 5.0, "worker_id": "task-1"})

        # Should return task-1 immediately
        assert isinstance(result.data, list)
        assert len(result.data) == 1
        assert result.data[0]["worker_id"] == "task-1"
        assert result.data[0]["claude_session_id"] == "session-1"


@pytest.mark.anyio
async def test_wait_with_nonexistent_worker_id():
    """Test wait raises error for nonexistent worker_id."""
    # Create one active task
    async def complete_immediately():
        return ClaudeJobResult(
            worker_id="task-1",
            returncode=0,
            stdout=json.dumps({"session_id": "session-1"}),
            stderr=""
        )

    task = asyncio.create_task(complete_immediately())
    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task, timeout=300.0)

    async with Client(mcp) as client:
        # Try to wait for non-existent worker
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("wait", {"timeout": 5.0, "worker_id": "nonexistent"})
        assert "not found" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_wait_with_worker_id_processes_other_workers():
    """Test wait processes all completed workers while waiting for specific one."""
    # Create three tasks: task-1 completes first, task-2 completes second, task-3 completes third
    async def complete_after_delay(worker_id: str, delay: float):
        await asyncio.sleep(delay)
        return ClaudeJobResult(
            worker_id=worker_id,
            returncode=0,
            stdout=json.dumps({"session_id": f"session-{worker_id}"}),
            stderr=""
        )

    task1 = asyncio.create_task(complete_after_delay("task-1", 0))
    task2 = asyncio.create_task(complete_after_delay("task-2", 0.05))
    task3 = asyncio.create_task(complete_after_delay("task-3", 0.1))

    active_tasks["task-1"] = ActiveTask(worker_id="task-1", task=task1, timeout=300.0)
    active_tasks["task-2"] = ActiveTask(worker_id="task-2", task=task2, timeout=300.0)
    active_tasks["task-3"] = ActiveTask(worker_id="task-3", task=task3, timeout=300.0)

    async with Client(mcp) as client:
        # wait for task-3 specifically (the last to complete)
        result = await client.call_tool("wait", {"timeout": 5.0, "worker_id": "task-3"})

        # Should return only task-3
        assert isinstance(result.data, list)
        assert len(result.data) == 1
        assert result.data[0]["worker_id"] == "task-3"

        # All three tasks should be in complete_tasks since they completed during the wait
        assert len(complete_tasks) == 3
        assert "task-1" in complete_tasks
        assert "task-2" in complete_tasks
        assert "task-3" in complete_tasks


