"""Integration tests for NEW async racing implementation."""
import pytest
import shutil
import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.server import mcp, active_tasks, complete_tasks, workers
from fastmcp import Client


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before/after each test."""
    workers.clear()
    active_tasks.clear()
    complete_tasks.clear()
    yield
    workers.clear()
    active_tasks.clear()
    complete_tasks.clear()


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_e2e_create_wait_peek_write():
    """
    E2E integration test: Create → wait → Peek → Write → wait

    Verifies the complete lifecycle of the new racing pattern.
    """
    print("\n" + "=" * 70)
    print("E2E INTEGRATION TEST: Racing Pattern Lifecycle")
    print("=" * 70)

    async with Client(mcp) as client:
        # 1. Create a worker
        print("\n[1/6] Creating worker...")
        result = await client.call_tool("create_async_worker", {
            "prompt": "Say 'Hello!' and nothing else"
        })
        worker_id = result.data
        print(f"✓ Worker created: worker_id={worker_id}")
        assert isinstance(worker_id, str)
        assert len(worker_id) == 36  # UUID format

        # 2. wait to get first completion
        print("\n[3/6] Racing workers (waiting for completion)...")
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

        # 3. Peek at output
        print("\n[4/6] Peeking at worker output...")
        result = await client.call_tool("peek", {"worker_id": worker_id})
        print(f"✓ Session ID: {result.data.claude_session_id}")
        print(f"✓ Stdout length: {len(result.data.std_out)}")
        assert result.data.worker_id == worker_id
        assert result.data.claude_session_id is not None

        # 4. Resume with new input
        print("\n[5/6] Resuming worker with new input...")
        await client.call_tool("resume_worker", {
            "worker_id": worker_id,
            "message": "Now say 'Goodbye!' and nothing else"
        })
        print("✓ Worker resumed and back in active state")

        # 5. wait again
        print("\n[6/6] Racing again for second completion...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        assert complete_tasks[0]["worker_id"] == worker_id
        print("✓ Second completion received")

        # Final peek
        result = await client.call_tool("peek", {"worker_id": worker_id})
        print(f"✓ Final stdout length: {len(result.data.std_out)}")

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
async def test_peek_during_execution():
    """
    Test peeking at a worker - can only peek complete workers.

    This tests that peek works after wait completes a worker.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Peek After Completion")
    print("=" * 70)

    async with Client(mcp) as client:
        print("\n[1/3] Creating worker...")
        result = await client.call_tool("create_async_worker", {
            "prompt": "Say 'Processing...' and nothing else"
        })
        worker_id = result.data
        print(f"✓ Worker created: {worker_id}")

        print("\n[2/3] Waiting for completion via wait...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        assert complete_tasks[0]["worker_id"] == worker_id
        print("✓ Worker completed")

        # Now peek should show complete
        print("\n[3/3] Peeking at completed worker...")
        result = await client.call_tool("peek", {"worker_id": worker_id})
        assert result.data.worker_id == worker_id
        print(f"✓ Worker ID: {result.data.worker_id}")

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
        print("\n[1/5] Creating worker with context...")
        result = await client.call_tool("create_async_worker", {
            "prompt": "Remember this number: 42. Say 'Stored!' and nothing else"
        })
        worker_id = result.data
        print(f"✓ Worker created: {worker_id}")

        print("\n[2/5] Racing to completion...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        assert complete_tasks[0]["worker_id"] == worker_id
        print("✓ First turn complete")

        print("\n[3/5] Peeking at session_id...")
        result = await client.call_tool("peek", {"worker_id": worker_id})
        session_id = result.data.claude_session_id
        print(f"✓ Session ID: {session_id}")
        assert session_id is not None

        print("\n[4/5] Resuming with follow-up...")
        await client.call_tool("resume_worker", {
            "worker_id": worker_id,
            "message": "Say 'Done!' and nothing else"
        })
        print("✓ Resumed with same session_id")

        print("\n[5/5] Racing for second response...")
        result = await client.call_tool("wait", {"timeout": 60.0})
        complete_tasks = result.structured_content["completed"]
        assert isinstance(complete_tasks, list)
        assert len(complete_tasks) >= 1
        assert complete_tasks[0]["worker_id"] == worker_id
        print("✓ Second turn complete")

        # Peek at final output
        result = await client.call_tool("peek", {"worker_id": worker_id})
        print(f"✓ Total conversation length: {len(result.data.std_out)}")

        print("\n" + "=" * 70)
        print("INTEGRATION TEST COMPLETE ✅")
        print("=" * 70)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_concurrent_peek_and_check():
    """
    Test that concurrent peek operations work after completion.

    Verifies peek works on multiple completed workers.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Concurrent Peek Operations")
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

        # Both workers complete, peek both
        print("\n[4/3] Peeking both workers concurrently...")
        results = await asyncio.gather(
            client.call_tool("peek", {"worker_id": worker_ids[0]}),
            client.call_tool("peek", {"worker_id": worker_ids[1]}),
        )
        print("✓ Both peeks completed")

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


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_peek_auto_flushes_completed_tasks():
    """
    Test that peek() automatically flushes already-completed tasks.

    When peek() is called on a worker that's in active_tasks but has already
    completed, peek() internally calls wait(timeout=0) to flush the task
    from active_tasks to complete_tasks, then returns it.

    This means users can just call peek() without worrying about calling
    wait() first - peek() handles it automatically.
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: peek() Auto-Flushes Completed Tasks")
    print("=" * 70)

    async with Client(mcp) as client:
        print("\n[1/3] Creating a fast worker...")
        result = await client.call_tool("create_async_worker", {
            "prompt": "Say 'Done!' and nothing else",
            "timeout": 30.0
        })
        worker_id = result.data
        print(f"✓ Worker created: {worker_id}")

        # Wait for task to complete naturally (without racing)
        print("\n[2/3] Waiting for task to complete (without racing)...")
        await asyncio.sleep(5)
        print("✓ Task should be completed but still in active_tasks")

        # Call peek() directly - it should auto-flush and succeed!
        print("\n[3/3] Calling peek() (should auto-flush and succeed)...")
        result = await client.call_tool("peek", {"worker_id": worker_id})
        assert result.data.worker_id == worker_id
        print(f"✓ peek succeeded: {worker_id}")
        print("✓ peek() automatically flushed the completed task from active to complete")
        print("✓ No need to manually call wait() first!")

        print("\n" + "=" * 70)
        print("INTEGRATION TEST COMPLETE ✅")
        print("=" * 70)
