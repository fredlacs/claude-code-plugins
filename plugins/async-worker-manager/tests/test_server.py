"""Unit tests for async worker manager - current API."""
import pytest
from unittest.mock import AsyncMock, patch, Mock, MagicMock
import json
import sys
from pathlib import Path
import asyncio
import contextlib

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.server import mcp, tasks, WorkerResult, WorkerOptions
from fastmcp import Client
from fastmcp.exceptions import ToolError


@pytest.fixture(autouse=True)
async def reset_state():
    """Reset global state before/after each test."""
    # Cancel any existing tasks before starting
    for task_or_result in list(tasks.values()):
        if isinstance(task_or_result, asyncio.Task) and not task_or_result.done():
            task_or_result.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task_or_result
    tasks.clear()

    yield

    # Cancel any tasks after test completes
    for task_or_result in list(tasks.values()):
        if isinstance(task_or_result, asyncio.Task) and not task_or_result.done():
            task_or_result.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task_or_result
    tasks.clear()

    # Give asyncio a chance to clean up
    await asyncio.sleep(0)


# --- Test spawn_worker ---

@pytest.mark.anyio
async def test_spawn_worker_returns_worker_id():
    """Test that spawn_worker returns a string worker_id."""
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
            # Create a mock process with only async methods where needed
            mock_proc = Mock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123", "result": "Hello"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
            mock_proc.stdin = Mock()
            mock_proc.stdin.close = Mock(return_value=None)
            mock_exec.return_value = mock_proc

            async with Client(mcp) as client:
                result = await client.call_tool("spawn_worker", {
                    "description": "Test task",
                    "prompt": "test"
                })

                # Should return string worker_id
                assert isinstance(result.data, str)
                # Should have UUID format
                assert len(result.data) == 36  # UUID length with dashes
                # Should have 1 active worker
                assert len(tasks) == 1
                assert result.data in tasks
                assert isinstance(tasks[result.data], asyncio.Task)


@pytest.mark.anyio
async def test_spawn_worker_max_workers_enforced():
    """Test that 11th active worker is rejected."""
    # Create 10 active tasks (simple mocks)
    for i in range(10):
        worker_id = f"worker-{i}"
        # Create a mock task
        mock_task = Mock(spec=asyncio.Task)
        tasks[worker_id] = mock_task

    async with Client(mcp) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool("spawn_worker", {
                "description": "Test",
                "prompt": "test"
            })
        assert "Max 10 active workers" in str(exc_info.value)


@pytest.mark.anyio
async def test_spawn_worker_completed_workers_dont_count():
    """Test that completed workers don't count toward max workers limit."""
    # Create 10 completed workers
    for i in range(10):
        worker_id = f"complete-{i}"
        tasks[worker_id] = WorkerResult(
            worker_id=worker_id,
            output_file=f"/tmp/worker-{i}.json"
        )

    # Should still be able to create 10 active workers
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
            # Create a mock process with only async methods where needed
            mock_proc = Mock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
            mock_proc.stdin = Mock()
            mock_proc.stdin.close = Mock(return_value=None)
            mock_exec.return_value = mock_proc

            async with Client(mcp) as client:
                # Create 10 active workers - should succeed
                for i in range(10):
                    result = await client.call_tool("spawn_worker", {
                        "description": f"Task {i}",
                        "prompt": "test"
                    })
                    assert isinstance(result.data, str)

                # Should have 10 completed + 10 active = 20 total
                completed_count = sum(1 for t in tasks.values() if isinstance(t, WorkerResult))
                active_count = sum(1 for t in tasks.values() if isinstance(t, asyncio.Task))
                assert completed_count == 10
                assert active_count == 10


# --- Test wait ---

@pytest.mark.anyio
async def test_wait_no_active_workers():
    """Test wait() with no active workers raises error."""
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool("wait", {})
        assert "No active workers" in str(exc_info.value)


@pytest.mark.anyio
async def test_wait_returns_completed_workers():
    """Test wait() returns completed workers."""
    # Create a real completed task
    async def complete_immediately():
        return WorkerResult(
            worker_id="worker-1",
            output_file="/tmp/output.json"
        )

    task = asyncio.create_task(complete_immediately())
    await task  # Let it complete

    tasks["worker-1"] = task

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {})

        # Should return Dict[str, WorkerResult]
        assert isinstance(result.data, dict)
        assert len(result.data) == 1
        assert "worker-1" in result.data
        # FastMCP deserializes to Root objects with attribute access
        # Path is resolved so /tmp -> /private/tmp on macOS
        assert result.data["worker-1"].output_file.endswith("output.json")

        # Worker should now be a WorkerResult in tasks
        assert "worker-1" in tasks
        assert isinstance(tasks["worker-1"], WorkerResult)


@pytest.mark.anyio
async def test_wait_multiple_simultaneous_completions():
    """Test wait() returns all tasks that complete simultaneously."""
    # Create multiple tasks that complete immediately
    async def complete_immediately(worker_id: str):
        return WorkerResult(
            worker_id=worker_id,
            output_file=f"/tmp/{worker_id}.json"
        )

    # Create and complete 3 tasks
    task1 = asyncio.create_task(complete_immediately("worker-1"))
    task2 = asyncio.create_task(complete_immediately("worker-2"))
    task3 = asyncio.create_task(complete_immediately("worker-3"))
    await asyncio.gather(task1, task2, task3)

    tasks["worker-1"] = task1
    tasks["worker-2"] = task2
    tasks["worker-3"] = task3

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {})

        # Should return Dict[str, WorkerResult] with all 3 completed tasks
        assert isinstance(result.data, dict)
        assert len(result.data) == 3
        assert "worker-1" in result.data
        assert "worker-2" in result.data
        assert "worker-3" in result.data

        # All workers should now be WorkerResult in tasks
        assert len(tasks) == 3
        assert all(isinstance(tasks[wid], WorkerResult) for wid in ["worker-1", "worker-2", "worker-3"])


# --- Test resume_worker ---

@pytest.mark.anyio
async def test_resume_worker_nonexistent():
    """Test resuming non-existent worker raises error."""
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool("resume_worker", {
                "worker_id": "nonexistent",
                "prompt": "test"
            })
        assert "not found" in str(exc_info.value)


@pytest.mark.anyio
async def test_resume_worker_not_completed():
    """Test resuming active worker raises error."""
    task = asyncio.create_task(asyncio.sleep(1000))
    tasks["worker-1"] = task

    try:
        async with Client(mcp) as client:
            with pytest.raises(ToolError) as exc_info:
                await client.call_tool("resume_worker", {
                    "worker_id": "worker-1",
                    "prompt": "test"
                })
            assert "not found" in str(exc_info.value).lower() or "still active" in str(exc_info.value).lower()
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_resume_worker_success():
    """Test resuming completed worker transitions to active."""
    import tempfile

    # Create a temp file with session_id JSON
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"session_id": "session-1", "result": "Initial response"}, f)
        temp_file = f.name

    try:
        # Setup a completed worker
        tasks["worker-1"] = WorkerResult(
            worker_id="worker-1",
            output_file=temp_file
        )

        with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
            with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
                # Create a mock process
                mock_proc = Mock()
                mock_proc.communicate = AsyncMock(return_value=(
                    json.dumps({"session_id": "session-1", "result": "Response"}).encode(),
                    b""
                ))
                mock_proc.returncode = 0
                mock_proc.stdin = Mock()
                mock_proc.stdin.close = Mock(return_value=None)
                mock_exec.return_value = mock_proc

                async with Client(mcp) as client:
                    await client.call_tool("resume_worker", {
                        "worker_id": "worker-1",
                        "prompt": "Follow up"
                    })

                    # Worker should transition to ACTIVE
                    assert "worker-1" in tasks
                    assert isinstance(tasks["worker-1"], asyncio.Task)
    finally:
        import os
        os.unlink(temp_file)


# --- Test concurrent operations ---

@pytest.mark.anyio
async def test_multiple_workers_concurrent():
    """Test creating multiple workers concurrently."""
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
            # Create a mock process
            mock_proc = Mock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
            mock_proc.stdin = Mock()
            mock_proc.stdin.close = Mock(return_value=None)
            mock_exec.return_value = mock_proc

            async with Client(mcp) as client:
                # Create 3 workers
                worker_ids = []
                for i in range(3):
                    result = await client.call_tool("spawn_worker", {
                        "description": f"Task {i}",
                        "prompt": f"Task {i}"
                    })
                    worker_ids.append(result.data)

                assert len(worker_ids) == 3
                assert len(set(worker_ids)) == 3  # All unique
                active_count = sum(1 for t in tasks.values() if isinstance(t, asyncio.Task))
                assert active_count == 3
                assert all(wid in tasks for wid in worker_ids)


@pytest.mark.anyio
async def test_spawn_worker_with_options():
    """Test that options parameter works with dataclass."""
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = Mock()
            mock_proc.communicate = AsyncMock(return_value=(
                json.dumps({"session_id": "test-123"}).encode(),
                b""
            ))
            mock_proc.returncode = 0
            mock_proc.stdin = Mock()
            mock_proc.stdin.close = Mock(return_value=None)
            mock_exec.return_value = mock_proc

            async with Client(mcp) as client:
                # Test with options dict (should auto-convert)
                result = await client.call_tool("spawn_worker", {
                    "description": "Test with options",
                    "prompt": "test",
                    "options": {
                        "model": "claude-haiku-4",
                        "temperature": 0.5,
                        "thinking": True
                    }
                })

                assert isinstance(result.data, str)

                # Verify subprocess called with correct args
                call_args = mock_exec.call_args[0]
                assert "--model" in call_args
                assert "claude-haiku-4" in call_args

                # Verify settings JSON includes temperature and thinking
                settings_idx = call_args.index("--settings")
                settings_json = call_args[settings_idx + 1]
                settings = json.loads(settings_json)
                assert settings["temperature"] == 0.5
                assert settings["thinking"]["type"] == "enabled"
