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
    for task_or_result in tasks:
        # Only try to cancel real asyncio.Task objects, not Mocks
        if type(task_or_result).__name__ == 'Task' and not task_or_result.done():
            task_or_result.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task_or_result
    tasks.clear()

    yield

    # Cancel any tasks after test completes
    for task_or_result in tasks:
        # Only try to cancel real asyncio.Task objects, not Mocks
        if type(task_or_result).__name__ == 'Task' and not task_or_result.done():
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

                # Should return int worker_id
                assert isinstance(result.data, int)
                # Should have 1 active worker
                assert len(tasks) == 1
                assert result.data < len(tasks)
                assert isinstance(tasks[result.data], asyncio.Task)


@pytest.mark.anyio
async def test_spawn_worker_max_workers_enforced():
    """Test that 11th active worker is rejected."""
    # Create 10 active tasks (simple mocks)
    for i in range(10):
        # Create a mock task that appears active (not done)
        mock_task = Mock(spec=asyncio.Task)
        mock_task.done.return_value = False
        tasks.append(mock_task)

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
    # Create 1 completed worker first
    async def completed_task():
        return WorkerResult(output_file="/tmp/completed.json")

    task = asyncio.create_task(completed_task())
    await task  # Wait for completion
    tasks.append(task)

    # Should still be able to create 10 active workers despite having completed one
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
            # Create a mock process that will stay "active" by sleeping
            async def slow_communicate():
                await asyncio.sleep(10)  # Long enough to keep tasks active during test
                return (json.dumps({"session_id": "test-123"}).encode(), b"")

            mock_proc = Mock()
            mock_proc.communicate = slow_communicate
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
                    assert isinstance(result.data, int)

                # Give tasks a moment to start
                await asyncio.sleep(0.01)

                # Should have 1 completed + 10 active = 11 total
                completed_count = sum(1 for t in tasks if isinstance(t, asyncio.Task) and t.done())
                active_count = sum(1 for t in tasks if isinstance(t, asyncio.Task) and not t.done())
                assert completed_count == 1
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
    # Create a task that's active but will complete when waited on
    async def complete_soon():
        await asyncio.sleep(0.01)  # Small delay so it's active when added
        return WorkerResult(
            output_file="/tmp/output.json"
        )

    task = asyncio.create_task(complete_soon())
    tasks.append(task)

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {})

        # FastMCP returns results in content when there's no output schema
        # Parse the JSON text content
        import json
        content_text = result.content[0].text
        data = json.loads(content_text)

        # Should return List[WorkerResult | BaseException]
        assert isinstance(data, list)
        assert len(data) == 1
        # Path is resolved so /tmp -> /private/tmp on macOS
        assert data[0]["output_file"].endswith("output.json")


@pytest.mark.anyio
async def test_wait_multiple_simultaneous_completions():
    """Test wait() returns all tasks that complete simultaneously."""
    # Create multiple tasks that complete soon
    async def complete_soon(worker_id: str):
        await asyncio.sleep(0.01)  # Small delay so they're active when added
        return WorkerResult(
            output_file=f"/tmp/{worker_id}.json"
        )

    # Create 3 tasks (don't await - let them stay active)
    task1 = asyncio.create_task(complete_soon("worker-1"))
    task2 = asyncio.create_task(complete_soon("worker-2"))
    task3 = asyncio.create_task(complete_soon("worker-3"))

    tasks.append(task1)
    tasks.append(task2)
    tasks.append(task3)

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {})

        # FastMCP returns results in content when there's no output schema
        # Parse the JSON text content
        import json
        content_text = result.content[0].text
        data = json.loads(content_text)

        # Should return List[WorkerResult | BaseException] with all 3 completed tasks
        assert isinstance(data, list)
        assert len(data) == 3
        assert all(r["output_file"].endswith(".json") for r in data)


# --- Test resume_worker ---

@pytest.mark.anyio
async def test_resume_worker_nonexistent():
    """Test resuming non-existent worker raises error."""
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool("resume_worker", {
                "worker_id": 999,  # Use integer worker_id for list-based design
                "prompt": "test"
            })
        assert "not found" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_resume_worker_not_completed():
    """Test resuming active worker raises error."""
    task = asyncio.create_task(asyncio.sleep(1000))
    tasks.append(task)

    try:
        async with Client(mcp) as client:
            with pytest.raises(ToolError) as exc_info:
                await client.call_tool("resume_worker", {
                    "worker_id": 0,  # First task in list
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
        # Create a completed task that returns the WorkerResult
        async def completed_worker():
            return WorkerResult(output_file=temp_file)

        task = asyncio.create_task(completed_worker())
        await task  # Wait for completion
        tasks.append(task)

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
                        "worker_id": 0,  # First task in list
                        "prompt": "Follow up"
                    })

                    # Worker should transition to ACTIVE
                    assert len(tasks) == 1
                    assert isinstance(tasks[0], asyncio.Task)
    finally:
        import os
        os.unlink(temp_file)


# --- Test concurrent operations ---

@pytest.mark.anyio
async def test_multiple_workers_concurrent():
    """Test creating multiple workers concurrently."""
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
            # Create a mock process that stays active
            async def slow_communicate():
                await asyncio.sleep(10)  # Long enough to keep tasks active
                return (json.dumps({"session_id": "test-123"}).encode(), b"")

            mock_proc = Mock()
            mock_proc.communicate = slow_communicate
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

                # Give tasks a moment to start
                await asyncio.sleep(0.01)

                assert len(worker_ids) == 3
                assert len(set(worker_ids)) == 3  # All unique
                active_count = sum(1 for t in tasks if isinstance(t, asyncio.Task) and not t.done())
                assert active_count == 3
                # Verify all worker_ids are valid indices in tasks list
                assert all(0 <= wid < len(tasks) for wid in worker_ids)


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

                assert isinstance(result.data, int)

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
