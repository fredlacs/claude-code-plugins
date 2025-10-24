"""Integration tests for async worker manager."""
import pytest
import shutil
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.server import mcp, workers, _event_queues
from fastmcp import Client


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before/after each test."""
    workers.clear()
    _event_queues.clear()
    yield
    workers.clear()
    _event_queues.clear()


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_batch_mode():
    """
    Test batch mode: spawn multiple → wait() → process all
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Batch Mode")
    print("=" * 70)

    async with Client(mcp) as client:
        # Spawn multiple workers
        print("\n[1/3] Spawning workers...")
        worker_ids = []
        for i in range(2):
            result = await client.call_tool("spawn_worker", {
                "description": f"Task {i}",
                "prompt": f"Say 'Worker {i} done!' and nothing else"
            })
            worker_ids.append(result.data)
            print(f"✓ Spawned worker {i}: {result.data}")

        # Wait for all results
        print("\n[2/3] Waiting for results...")
        result = await client.call_tool("wait", {})
        state = result.data

        print(f"✓ Got results: {len(state.completed)} completed")

        # Check results
        assert hasattr(state, 'completed')
        assert hasattr(state, 'failed')
        assert hasattr(state, 'pending_permissions')
        assert len(state.completed) >= 1
        print(f"✓ Workers completed")

        print("\n" + "=" * 70)
        print("BATCH MODE TEST COMPLETE ✅")
        print("=" * 70)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_sequential_mode():
    """
    Test sequential mode: spawn → wait → spawn → wait
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Sequential Mode")
    print("=" * 70)

    async with Client(mcp) as client:
        tasks = ["Task A", "Task B"]

        for i, task in enumerate(tasks):
            # Spawn one
            print(f"\n[{i*2+1}/4] Spawning {task}...")
            result = await client.call_tool("spawn_worker", {
                "description": task,
                "prompt": f"Say '{task} done!' and nothing else"
            })
            worker_id = result.data
            print(f"✓ Spawned: {worker_id}")

            # Wait for this one
            print(f"\n[{i*2+2}/4] Waiting for {task}...")
            result = await client.call_tool("wait", {})
            state = result.data

            assert len(state.completed) >= 1
            print(f"✓ {task} completed")

        print("\n" + "=" * 70)
        print("SEQUENTIAL MODE TEST COMPLETE ✅")
        print("=" * 70)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_resume_worker():
    """
    Test resume functionality: spawn → wait → resume → wait
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Resume Worker")
    print("=" * 70)

    async with Client(mcp) as client:
        # Initial task
        print("\n[1/4] Spawning worker...")
        result = await client.call_tool("spawn_worker", {
            "description": "Say hello",
            "prompt": "Say 'Hello!' and nothing else"
        })
        worker_id = result.data
        print(f"✓ Spawned: {worker_id}")

        # Wait for completion
        print("\n[2/4] Waiting for first completion...")
        result = await client.call_tool("wait", {})
        state = result.data

        assert len(state.completed) >= 1
        completed_worker = state.completed[0]
        assert completed_worker.worker_id == worker_id
        print(f"✓ First completion: {completed_worker.worker_id}")

        # Resume
        print("\n[3/4] Resuming worker...")
        await client.call_tool("resume_worker", {
            "worker_id": worker_id,
            "prompt": "Now say 'Goodbye!' and nothing else"
        })
        print("✓ Resumed")

        # Wait again
        print("\n[4/4] Waiting for second completion...")
        result = await client.call_tool("wait", {})
        state = result.data

        assert len(state.completed) >= 1
        print("✓ Second completion")

        print("\n" + "=" * 70)
        print("RESUME TEST COMPLETE ✅")
        print("=" * 70)
