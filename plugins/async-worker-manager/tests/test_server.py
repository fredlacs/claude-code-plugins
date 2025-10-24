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
from src.server import mcp, workers, get_event_queue
from src.models import ClaudeJobResult, WorkerStatus
from fastmcp import Client
from fastmcp.exceptions import ToolError


@pytest.fixture(autouse=True)
async def reset_state():
    """Reset global state before/after each test."""
    # Cancel any existing tasks before starting
    for worker in list(workers.values()):
        if hasattr(worker, 'task') and worker.task and not worker.task.done():
            worker.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker.task
    workers.clear()

    # Clear event queue
    queue = get_event_queue()
    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    yield

    # Cancel any tasks after test completes
    for worker in list(workers.values()):
        if hasattr(worker, 'task') and worker.task and not worker.task.done():
            worker.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker.task
    workers.clear()

    # Clear event queue
    queue = get_event_queue()
    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    # Give asyncio a chance to clean up
    await asyncio.sleep(0)


# --- Test spawn_worker ---

@pytest.mark.anyio
async def test_spawn_worker_returns_worker_id():
    """Test that spawn_worker returns a string worker_id."""
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.UnixSocketManager') as mock_socket_mgr:
            # Mock the context manager with simple mocks
            mock_mgr_instance = Mock()
            mock_mgr_instance.get_env_vars = Mock(return_value={})

            async def mock_aenter(*args):
                return mock_mgr_instance
            async def mock_aexit(*args):
                return None

            mock_socket_mgr.return_value.__aenter__ = mock_aenter
            mock_socket_mgr.return_value.__aexit__ = mock_aexit

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
                    # Should have 1 worker
                    assert len(workers) == 1
                    assert result.data in workers
                    assert workers[result.data].worker_id == result.data
                    assert workers[result.data].status == WorkerStatus.ACTIVE


@pytest.mark.anyio
async def test_spawn_worker_max_workers_enforced():
    """Test that 11th active worker is rejected."""
    # Create 10 active workers (simple objects, no async tasks)
    for i in range(10):
        worker_id = f"worker-{i}"
        # Create a simple mock without actual async task to avoid cleanup issues
        mock_worker = Mock()
        mock_worker.worker_id = worker_id
        mock_worker.status = WorkerStatus.ACTIVE
        workers[worker_id] = mock_worker

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
        mock_worker = Mock()
        mock_worker.worker_id = worker_id
        mock_worker.status = WorkerStatus.COMPLETED
        mock_worker.task = None
        workers[worker_id] = mock_worker

    # Should still be able to create 10 active workers
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.UnixSocketManager') as mock_socket_mgr:
            mock_mgr_instance = Mock()
            mock_mgr_instance.get_env_vars = Mock(return_value={})

            async def mock_aenter(*args):
                return mock_mgr_instance
            async def mock_aexit(*args):
                return None

            mock_socket_mgr.return_value.__aenter__ = mock_aenter
            mock_socket_mgr.return_value.__aexit__ = mock_aexit

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
                    active_count = sum(1 for w in workers.values() if w.status == WorkerStatus.ACTIVE)
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
        return ClaudeJobResult(
            worker_id="worker-1",
            returncode=0,
            stdout=json.dumps({"session_id": "session-1", "result": "Done"}),
            stderr="",
            output_file="/tmp/output.json"
        )

    task = asyncio.create_task(complete_immediately())
    await task  # Let it complete

    mock_worker = Mock()
    mock_worker.worker_id = "worker-1"
    mock_worker.status = WorkerStatus.ACTIVE
    mock_worker.task = task
    mock_worker.socket_mgr = None
    workers["worker-1"] = mock_worker

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {})

        # Should return WorkerState
        assert hasattr(result.data, 'completed')
        assert hasattr(result.data, 'failed')
        assert hasattr(result.data, 'pending_permissions')
        assert len(result.data.completed) == 1
        assert result.data.completed[0].worker_id == "worker-1"
        assert result.data.completed[0].claude_session_id == "session-1"
        assert len(result.data.failed) == 0
        assert len(result.data.pending_permissions) == 0

        # Worker should transition to COMPLETED
        assert workers["worker-1"].status == WorkerStatus.COMPLETED


@pytest.mark.anyio
async def test_wait_handles_failed_worker():
    """Test wait() handles failed workers correctly."""
    # Create a task that returns bad exit code
    async def fail_immediately():
        return ClaudeJobResult(
            worker_id="worker-1",
            returncode=1,
            stdout="",
            stderr="Command failed",
            output_file="/tmp/output.json"
        )

    task = asyncio.create_task(fail_immediately())
    await task  # Let it complete

    mock_worker = Mock()
    mock_worker.worker_id = "worker-1"
    mock_worker.status = WorkerStatus.ACTIVE
    mock_worker.task = task
    mock_worker.socket_mgr = None
    workers["worker-1"] = mock_worker

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {})

        # Should return WorkerState with failed worker
        assert len(result.data.completed) == 0
        assert len(result.data.failed) == 1
        assert result.data.failed[0].worker_id == "worker-1"
        assert result.data.failed[0].returncode == 1
        assert result.data.failed[0].error_hint  # Should have error hint

        # Worker should transition to FAILED
        assert workers["worker-1"].status == WorkerStatus.FAILED


@pytest.mark.anyio
async def test_wait_multiple_simultaneous_completions():
    """Test wait() returns all tasks that complete simultaneously."""
    # Create multiple tasks that complete immediately
    async def complete_immediately(worker_id: str, session_id: str):
        return ClaudeJobResult(
            worker_id=worker_id,
            returncode=0,
            stdout=json.dumps({"session_id": session_id, "result": "Done"}),
            stderr="",
            output_file=f"/tmp/{worker_id}.json"
        )

    # Create and complete 3 tasks
    task1 = asyncio.create_task(complete_immediately("worker-1", "session-1"))
    task2 = asyncio.create_task(complete_immediately("worker-2", "session-2"))
    task3 = asyncio.create_task(complete_immediately("worker-3", "session-3"))
    await asyncio.gather(task1, task2, task3)

    for i, (worker_id, task) in enumerate([("worker-1", task1), ("worker-2", task2), ("worker-3", task3)], 1):
        mock_worker = Mock()
        mock_worker.worker_id = worker_id
        mock_worker.status = WorkerStatus.ACTIVE
        mock_worker.task = task
        mock_worker.socket_mgr = None
        workers[worker_id] = mock_worker

    async with Client(mcp) as client:
        result = await client.call_tool("wait", {})

        # Should return WorkerState with all 3 completed tasks
        assert len(result.data.completed) == 3
        worker_ids = {w.worker_id for w in result.data.completed}
        assert worker_ids == {"worker-1", "worker-2", "worker-3"}

        # All workers should be COMPLETED
        assert all(w.status == WorkerStatus.COMPLETED for w in workers.values())


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

    mock_worker = Mock()
    mock_worker.worker_id = "worker-1"
    mock_worker.status = WorkerStatus.ACTIVE
    mock_worker.task = task
    workers["worker-1"] = mock_worker

    try:
        async with Client(mcp) as client:
            with pytest.raises(ToolError) as exc_info:
                await client.call_tool("resume_worker", {
                    "worker_id": "worker-1",
                    "prompt": "test"
                })
            assert "not in completed state" in str(exc_info.value)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_resume_worker_success():
    """Test resuming completed worker transitions to active."""
    # Setup a completed worker
    complete_task_mock = Mock()
    complete_task_mock.worker_id = "worker-1"
    complete_task_mock.claude_session_id = "session-1"

    mock_worker = Mock()
    mock_worker.worker_id = "worker-1"
    mock_worker.status = WorkerStatus.COMPLETED
    mock_worker.complete_task = complete_task_mock
    mock_worker.agent_type = None
    workers["worker-1"] = mock_worker

    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.UnixSocketManager') as mock_socket_mgr:
            mock_mgr_instance = Mock()
            mock_mgr_instance.get_env_vars = Mock(return_value={})

            async def mock_aenter(*args):
                return mock_mgr_instance
            async def mock_aexit(*args):
                return None

            mock_socket_mgr.return_value.__aenter__ = mock_aenter
            mock_socket_mgr.return_value.__aexit__ = mock_aexit

            with patch('src.server.asyncio.create_subprocess_exec') as mock_exec:
                # Create a mock process with only async methods where needed
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
                    assert workers["worker-1"].status == WorkerStatus.ACTIVE
                    assert workers["worker-1"].task is not None
                    assert workers["worker-1"].complete_task is None
                    # Background task spawned - that's enough validation


# --- Test concurrent operations ---

@pytest.mark.anyio
async def test_multiple_workers_concurrent():
    """Test creating multiple workers concurrently."""
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.UnixSocketManager') as mock_socket_mgr:
            mock_mgr_instance = Mock()
            mock_mgr_instance.get_env_vars = Mock(return_value={})

            # Create proper async context manager methods
            async def mock_aenter(*args):
                return mock_mgr_instance

            async def mock_aexit(*args):
                return None

            mock_socket_mgr.return_value.__aenter__ = mock_aenter
            mock_socket_mgr.return_value.__aexit__ = mock_aexit

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
                    assert len(workers) == 3
                    assert all(workers[wid].status == WorkerStatus.ACTIVE for wid in worker_ids)


@pytest.mark.anyio
async def test_spawn_worker_with_options():
    """Test that options parameter works with Pydantic model."""
    with patch('src.server.shutil.which', return_value='/usr/bin/claude'):
        with patch('src.server.UnixSocketManager') as mock_socket_mgr:
            mock_mgr_instance = Mock()
            mock_mgr_instance.get_env_vars = Mock(return_value={})

            async def mock_aenter(*args):
                return mock_mgr_instance
            async def mock_aexit(*args):
                return None

            mock_socket_mgr.return_value.__aenter__ = mock_aenter
            mock_socket_mgr.return_value.__aexit__ = mock_aexit

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
