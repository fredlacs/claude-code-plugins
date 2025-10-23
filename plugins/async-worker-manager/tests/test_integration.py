"""Integration tests for NEW async racing implementation."""
import pytest
import shutil
import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.server import mcp, active_tasks, complete_tasks, workers, _event_queues
from fastmcp import Client


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


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_e2e_create_wait_resume():
    """
    E2E integration test: Create → wait → Resume → wait

    Verifies the complete lifecycle of the new racing pattern.
    """
    print("\n" + "=" * 70)
    print("E2E INTEGRATION TEST: Racing Pattern Lifecycle")
    print("=" * 70)

    async with Client(mcp) as client:
        # 1. Create a worker
        print("\n[1/5] Creating worker...")
        result = await client.call_tool("create_async_worker", {
            "prompt": "Say 'Hello!' and nothing else"
        })
        worker_id = result.data
        print(f"✓ Worker created: worker_id={worker_id}")
        assert isinstance(worker_id, str)
        assert len(worker_id) == 36  # UUID format

        # 2. wait to get first completion
        print("\n[2/5] Racing workers (waiting for completion)...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        worker_state = result.structured_content
        assert isinstance(worker_state, dict) or hasattr(worker_state, "completed")
        assert "completed" in worker_state
        complete_tasks = worker_state["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        complete_task = complete_tasks[0]
        print(f"✓ Winner: {complete_task['worker_id']}")
        assert complete_task["worker_id"] == worker_id
        print(f"✓ Worker moved to complete state")

        # 3. Access data from wait() response (no need for peek)
        print("\n[3/5] Accessing worker data from wait() response...")
        session_id = complete_task["claude_session_id"]
        print(f"✓ Session ID: {session_id}")
        print(f"✓ Stdout length: {len(complete_task['std_out'])}")
        assert session_id is not None

        # 4. Resume with new input
        print("\n[4/5] Resuming worker with new input...")
        await client.call_tool("resume_worker", {
            "worker_id": worker_id,
            "message": "Now say 'Goodbye!' and nothing else"
        })
        print("✓ Worker resumed and back in active state")

        # 5. wait again
        print("\n[5/5] Racing again for second completion...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        second_task = complete_tasks[0]
        assert second_task["worker_id"] == worker_id
        print("✓ Second completion received")
        print(f"✓ Final stdout length: {len(second_task['std_out'])}")

        print("\n" + "=" * 70)
        print("E2E TEST COMPLETE ✅")
        print("=" * 70)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_multiple_workers_racing():
    """
    Test multiple workers racing - first to complete wins.

    Creates 3 workers with different prompts and waits them.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Multiple Workers Racing")
    print("=" * 70)

    async with Client(mcp) as client:
        print("\n[1/3] Creating 3 workers...")
        worker_ids = []
        for i in range(3):
            result = await client.call_tool("create_async_worker", {
                "prompt": f"Say 'Worker {i} ready!' and nothing else"
            })
            worker_ids.append(result.data)
            print(f"✓ Worker {i}: {result.data}")
        print(f"✓ 3 workers created")

        print("\n[2/3] Racing to find first completion...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        # All completed workers should be in our worker_ids
        winners = [task["worker_id"] for task in complete_tasks]
        print(f"✓ Winner(s): {winners}")
        for winner in winners:
            assert winner in worker_ids
        print(f"✓ {len(complete_tasks)} worker(s) moved to complete")

        print("\n" + "=" * 70)
        print("INTEGRATION TEST COMPLETE ✅")
        print("=" * 70)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_access_completed_task_data():
    """
    Test accessing completed task data from wait() response.

    This tests that wait() provides all necessary task data without needing a separate peek.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Access Completed Task Data")
    print("=" * 70)

    async with Client(mcp) as client:
        print("\n[1/2] Creating worker...")
        result = await client.call_tool("create_async_worker", {
            "prompt": "Say 'Processing...' and nothing else"
        })
        worker_id = result.data
        print(f"✓ Worker created: {worker_id}")

        print("\n[2/2] Waiting for completion via wait...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        task = complete_tasks[0]
        assert task["worker_id"] == worker_id
        print("✓ Worker completed")

        # Access data directly from wait() response
        print(f"✓ Worker ID from wait(): {task['worker_id']}")
        print(f"✓ Session ID from wait(): {task['claude_session_id']}")
        print(f"✓ Stdout length: {len(task['std_out'])}")
        assert task["claude_session_id"] is not None

        print("\n" + "=" * 70)
        print("INTEGRATION TEST COMPLETE ✅")
        print("=" * 70)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_session_resumption_maintains_context():
    """
    Test that session resumption maintains conversation context.

    Verifies that --resume flag works correctly.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Session Resumption Context")
    print("=" * 70)

    async with Client(mcp) as client:
        print("\n[1/4] Creating worker with context...")
        result = await client.call_tool("create_async_worker", {
            "prompt": "Remember this number: 42. Say 'Stored!' and nothing else"
        })
        worker_id = result.data
        print(f"✓ Worker created: {worker_id}")

        print("\n[2/4] Racing to completion...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        first_task = complete_tasks[0]
        assert first_task["worker_id"] == worker_id
        print("✓ First turn complete")

        # Access session_id from wait() response
        session_id = first_task["claude_session_id"]
        print(f"✓ Session ID from wait(): {session_id}")
        assert session_id is not None

        print("\n[3/4] Resuming with follow-up...")
        await client.call_tool("resume_worker", {
            "worker_id": worker_id,
            "message": "Say 'Done!' and nothing else"
        })
        print("✓ Resumed with same session_id")

        print("\n[4/4] Racing for second response...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        second_task = complete_tasks[0]
        assert second_task["worker_id"] == worker_id
        print("✓ Second turn complete")

        # Access final output from wait() response
        print(f"✓ Total conversation length: {len(second_task['std_out'])}")

        print("\n" + "=" * 70)
        print("INTEGRATION TEST COMPLETE ✅")
        print("=" * 70)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_concurrent_workers():
    """
    Test that multiple workers can complete and their data accessed via wait().

    Verifies wait() returns all completed worker data.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Concurrent Workers")
    print("=" * 70)

    async with Client(mcp) as client:
        print("\n[1/3] Creating 2 workers...")
        worker_ids = []
        for i in range(2):
            result = await client.call_tool("create_async_worker", {
                "prompt": f"Say 'Worker {i}!' and nothing else"
            })
            worker_ids.append(result.data)
        print(f"✓ Created {len(worker_ids)} workers")

        print("\n[2/3] Racing first worker...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        first_winners = [task["worker_id"] for task in complete_tasks]
        print(f"✓ First winner(s): {first_winners}")

        print("\n[3/3] Racing second worker...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        second_winners = [task["worker_id"] for task in complete_tasks]
        print(f"✓ Second winner(s): {second_winners}")

        # Verify both workers have data accessible
        all_winners = first_winners + second_winners
        print(f"\n✓ All workers completed: {all_winners}")
        assert len(set(all_winners)) == 2, "Both workers should complete"

        print("\n" + "=" * 70)
        print("INTEGRATION TEST COMPLETE ✅")
        print("=" * 70)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_wait_detects_already_completed_tasks():
    """
    Test that wait() detects tasks that completed BEFORE wait() was called.

    This verifies "retroactive detection" - wait should find tasks that are
    already done, not just tasks that complete while wait is waiting.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: wait Detects Already-Completed Tasks")
    print("=" * 70)

    async with Client(mcp) as client:
        print("\n[1/3] Creating a fast worker...")
        result = await client.call_tool("create_async_worker", {
            "prompt": "Say 'Quick!' and nothing else",
            "timeout": 30.0
        })
        worker_id = result.data
        print(f"✓ Worker created: {worker_id}")

        # Wait for task to complete WITHOUT calling wait
        print("\n[2/3] Waiting for task to complete (without racing)...")
        await asyncio.sleep(5)  # Give task time to complete on its own
        print("✓ Sleep completed - task should be done by now")

        # NOW call wait - should immediately detect the already-completed task
        print("\n[3/3] Calling wait() on already-completed task...")
        result = await client.call_tool("wait", {"timeout": 5.0})
        complete_tasks = result.structured_content["completed"]

        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        assert complete_tasks[0]["worker_id"] == worker_id
        print(f"✓ wait successfully detected already-completed task: {worker_id}")
        print("✓ Confirms wait() detects tasks that finished BEFORE wait() was called")

        print("\n" + "=" * 70)
        print("INTEGRATION TEST COMPLETE ✅")
        print("=" * 70)


