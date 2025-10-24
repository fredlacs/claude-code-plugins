"""Unit tests for UnixSocketManager - key behaviors and edge cases."""
import pytest
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.unix_socket_manager import UnixSocketManager
from src.models import PermissionRequest, PermissionResponseMessage
from fastmcp.exceptions import ToolError


# --- Unit Tests (Fast, with mocking) ---

@pytest.mark.anyio
async def test_get_env_vars_returns_correct_values():
    """Test that get_env_vars returns socket path and worker_id."""
    worker_id = "test-worker-env"

    # Mock server with proper async methods
    mock_server = Mock()
    mock_server.close = Mock()
    mock_server.wait_closed = AsyncMock()

    with patch('asyncio.start_unix_server', return_value=mock_server), patch('os.chmod'):
        async with UnixSocketManager(worker_id) as mgr:
            env_vars = mgr.get_env_vars()

            assert "PERM_SOCKET_PATH" in env_vars
            assert "WORKER_ID" in env_vars
            assert env_vars["WORKER_ID"] == worker_id
            assert env_vars["PERM_SOCKET_PATH"] == str(mgr.socket_path)
            assert worker_id in env_vars["PERM_SOCKET_PATH"]


@pytest.mark.anyio
async def test_approve_request_allow_sets_response():
    """Test that approve_request with allow=True creates proper response."""
    worker_id = "test-worker-approve"

    # Mock server with proper async methods
    mock_server = Mock()
    mock_server.close = Mock()
    mock_server.wait_closed = AsyncMock()

    with patch('asyncio.start_unix_server', return_value=mock_server), patch('os.chmod'):
        async with UnixSocketManager(worker_id) as mgr:
            # Manually add a pending request
            request_id = "req-123"
            event = asyncio.Event()
            from src.models import PendingPermission
            mgr._pending[request_id] = PendingPermission(
                request_id=request_id,
                worker_id=worker_id,
                tool="Bash",
                input={"command": "ls"},
                event=event,
                socket=None,
                response=None
            )

            # Approve it
            result = await mgr.approve_request(request_id, allow=True)

            assert result["status"] == "approved"
            assert result["request_id"] == request_id
            assert mgr._pending[request_id].response.allow is True
            assert mgr._pending[request_id].response.request_id == request_id
            assert event.is_set()  # Should unblock


@pytest.mark.anyio
async def test_approve_request_deny_sets_response():
    """Test that approve_request with allow=False creates denial response."""
    worker_id = "test-worker-deny"

    # Mock server with proper async methods
    mock_server = Mock()
    mock_server.close = Mock()
    mock_server.wait_closed = AsyncMock()

    with patch('asyncio.start_unix_server', return_value=mock_server), patch('os.chmod'):
        async with UnixSocketManager(worker_id) as mgr:
            # Manually add a pending request
            request_id = "req-456"
            event = asyncio.Event()
            from src.models import PendingPermission
            mgr._pending[request_id] = PendingPermission(
                request_id=request_id,
                worker_id=worker_id,
                tool="Bash",
                input={"command": "rm -rf /"},
                event=event,
                socket=None,
                response=None
            )

            # Deny it
            result = await mgr.approve_request(
                request_id,
                allow=False,
                message="Too dangerous"
            )

            assert result["status"] == "denied"
            assert result["request_id"] == request_id
            assert mgr._pending[request_id].response.allow is False
            assert mgr._pending[request_id].response.message == "Too dangerous"
            assert event.is_set()


@pytest.mark.anyio
async def test_approve_request_nonexistent_raises_error():
    """Test that approving non-existent request raises ToolError."""
    worker_id = "test-worker-noexist"

    # Mock server with proper async methods
    mock_server = Mock()
    mock_server.close = Mock()
    mock_server.wait_closed = AsyncMock()

    with patch('asyncio.start_unix_server', return_value=mock_server), patch('os.chmod'):
        async with UnixSocketManager(worker_id) as mgr:
            with pytest.raises(ToolError) as exc_info:
                await mgr.approve_request("nonexistent", allow=True)

            assert "not found" in str(exc_info.value)


@pytest.mark.anyio
async def test_approve_request_worker_id_mismatch_raises_error():
    """Test that worker_id mismatch raises ToolError."""
    worker_id = "test-worker-mismatch"

    # Mock server with proper async methods
    mock_server = Mock()
    mock_server.close = Mock()
    mock_server.wait_closed = AsyncMock()

    with patch('asyncio.start_unix_server', return_value=mock_server), patch('os.chmod'):
        async with UnixSocketManager(worker_id) as mgr:
            # Add a pending request with different worker_id
            request_id = "req-mismatch"
            event = asyncio.Event()
            from src.models import PendingPermission
            mgr._pending[request_id] = PendingPermission(
                request_id=request_id,
                worker_id="different-worker",  # Mismatch!
                tool="Bash",
                input={},
                event=event,
                socket=None,
                response=None
            )

            with pytest.raises(ToolError) as exc_info:
                await mgr.approve_request(request_id, allow=True)

            assert "mismatch" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_get_pending_requests_returns_list():
    """Test that get_pending_requests returns all pending requests."""
    worker_id = "test-worker-pending"

    # Mock server with proper async methods
    mock_server = Mock()
    mock_server.close = Mock()
    mock_server.wait_closed = AsyncMock()

    with patch('asyncio.start_unix_server', return_value=mock_server), patch('os.chmod'):
        async with UnixSocketManager(worker_id) as mgr:
            # Add multiple pending requests
            from src.models import PendingPermission
            for i in range(3):
                request_id = f"req-{i}"
                mgr._pending[request_id] = PendingPermission(
                    request_id=request_id,
                    worker_id=worker_id,
                    tool=f"Tool{i}",
                    input={"index": i},
                    event=asyncio.Event(),
                    socket=None,
                    response=None
                )

            pending = mgr.get_pending_requests()

            assert len(pending) == 3
            request_ids = {req.request_id for req in pending}
            assert request_ids == {"req-0", "req-1", "req-2"}
            assert all(req.worker_id == worker_id for req in pending)


@pytest.mark.anyio
async def test_max_requests_limit():
    """Test that _max_requests is set to 100 (security limit)."""
    worker_id = "test-worker-maxlimit"

    # Mock server with proper async methods
    mock_server = Mock()
    mock_server.close = Mock()
    mock_server.wait_closed = AsyncMock()

    with patch('asyncio.start_unix_server', return_value=mock_server), patch('os.chmod'):
        async with UnixSocketManager(worker_id) as mgr:
            assert mgr._max_requests == 100


@pytest.mark.anyio
async def test_io_timeout_is_30_seconds():
    """Test that I/O timeout is set to 30 seconds."""
    worker_id = "test-worker-timeout"

    # Mock server with proper async methods
    mock_server = Mock()
    mock_server.close = Mock()
    mock_server.wait_closed = AsyncMock()

    with patch('asyncio.start_unix_server', return_value=mock_server), patch('os.chmod'):
        async with UnixSocketManager(worker_id) as mgr:
            assert mgr.io_timeout == 30.0


# --- Integration Test (Real socket I/O) ---

@pytest.mark.anyio
async def test_socket_lifecycle_integration():
    """Integration test: Real socket creation, permissions, and cleanup."""
    worker_id = "test-worker-integration"
    socket_path = Path(f"/tmp/claude_worker_{worker_id}.sock")

    # Ensure no leftover socket
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass

    async with UnixSocketManager(worker_id) as mgr:
        # Socket should exist during context
        assert socket_path.exists()
        assert mgr.socket_path == socket_path

        # Check permissions (0o600 - owner read/write only)
        stat_result = os.stat(socket_path)
        mode = stat_result.st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    # Socket should be cleaned up after context
    assert not socket_path.exists()
