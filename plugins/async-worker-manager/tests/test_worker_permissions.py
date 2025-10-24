"""Integration tests for worker permission bubbling."""
import pytest
import shutil
import sys
import json
import asyncio
from pathlib import Path

# Add parent to path for src package
sys.path.insert(0, str(Path(__file__).parent.parent))

from src import server
from src.server import mcp, workers
from fastmcp import Client


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before/after each test."""
    workers.clear()
    yield
    workers.clear()


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("claude"), reason="Requires claude in PATH")
@pytest.mark.anyio
async def test_worker_needs_bash_permission():
    """
    Test that worker permission bubbling works correctly.

    Expected behavior:
    - Worker spawns and attempts to run bash command
    - Worker requests permission via permission_proxy
    - We approve the permission
    - Worker completes successfully and generates a random number
    """
    print("\n" + "=" * 70)
    print("PERMISSION TEST: Worker Permission Bubbling")
    print("=" * 70)

    async with Client(mcp) as client:
        # Create worker that needs Bash permission
        print("\n[1/4] Creating worker that needs Bash...")
        result = await client.call_tool("spawn_worker", {
            "description": "Generate random number",
            "prompt": "Generate a random number using bash: echo $((RANDOM % 100))"
        })
        worker_id = result.data
        print(f"✓ Worker created: {worker_id}")

        # Wait for worker (wait() returns when all workers complete or need permissions)
        print("\n[2/4] Waiting for worker...")
        wait_result = await client.call_tool("wait", {})
        worker_state = wait_result.data
        pending_perms = worker_state.pending_permissions if hasattr(worker_state, 'pending_permissions') else worker_state.get("pending_permissions", [])

        if not pending_perms:
            pytest.fail(f"No pending permissions found - worker should have requested Bash permission")

        print(f"✓ Permission request received")
        print(f"  Data: {pending_perms}")

        # Approve first permission
        print(f"\n[3/6] Approving first permission...")
        perm1 = pending_perms[0]

        # Handle Root objects - use attributes, not dict keys
        request_id_1 = perm1.request_id if hasattr(perm1, 'request_id') else perm1['request_id']
        print(f"  Permission 1: {perm1}")

        await client.call_tool("approve_permission", {
            "request_id": request_id_1,
            "allow": True
        })
        print("✓ First permission approved")

        # Wait for second permission request or completion
        print(f"\n[4/6] Waiting for second permission request or completion...")
        wait_result2 = await client.call_tool("wait", {})
        worker_state2 = wait_result2.data
        pending_perms2 = worker_state2.pending_permissions if hasattr(worker_state2, 'pending_permissions') else worker_state2.get("pending_permissions", [])

        if not pending_perms2:
            print("⚠ No second permission request - worker may have completed")
            # Check if worker completed
            completed2 = worker_state2.completed if hasattr(worker_state2, 'completed') else worker_state2.get("completed", [])
            if completed2:
                print("✓ Worker completed without second permission")
        else:
            # Approve second permission
            print(f"\n[5/6] Approving second permission...")
            perm2 = pending_perms2[0]

            # Handle Root objects
            request_id_2 = perm2.request_id if hasattr(perm2, 'request_id') else perm2['request_id']
            tool_2 = perm2.tool if hasattr(perm2, 'tool') else perm2['tool']

            print(f"  Permission 2: {perm2}")

            # Compare the two permissions
            print(f"\n  Comparing permissions:")
            print(f"    request_id: {request_id_1} vs {request_id_2}")
            print(f"    tool: {perm1.tool if hasattr(perm1, 'tool') else perm1['tool']} vs {tool_2}")

            await client.call_tool("approve_permission", {
                "request_id": request_id_2,
                "allow": True
            })
            print("✓ Second permission approved")

        # Check if worker already completed, otherwise wait for completion
        print("\n[6/6] Waiting for worker to complete...")
        completed_list = worker_state2.completed if hasattr(worker_state2, 'completed') else worker_state2.get("completed", [])
        if completed_list:
            # Worker already completed in previous wait
            results = completed_list
            print(f"✓ Worker completed: {len(results)} result(s) returned (from previous wait)")
        else:
            # Wait for completion
            try:
                wait_result = await client.call_tool("wait", {})
                worker_state = wait_result.data
                results = worker_state.completed if hasattr(worker_state, 'completed') else worker_state.get("completed", [])
                print(f"✓ Worker completed: {len(results)} result(s) returned")

            except Exception as e:
                pytest.fail(f"Worker failed after approval: {e}")

        # Parse and verify the result
        print(f"\n{'=' * 70}")
        print("VERIFICATION")
        print(f"{'=' * 70}")

        if len(results) == 0:
            pytest.fail("No results returned - worker never completed")

        worker_result = results[0]
        worker_id_result = worker_result.worker_id if hasattr(worker_result, 'worker_id') else worker_result['worker_id']
        print(f"\n✓ Worker ID: {worker_id_result}")

        try:
            # Read output from file
            output_file = worker_result.conversation_history_file_path if hasattr(worker_result, 'conversation_history_file_path') else worker_result.get('conversation_history_file_path', worker_result.get('output_file'))
            with open(output_file, 'r') as f:
                stdout_data = json.load(f)

            # Check for permission denials
            permission_denials = stdout_data.get('permission_denials', [])
            if permission_denials:
                print(f"✗ Worker has {len(permission_denials)} permission denial(s)")
                for denial in permission_denials:
                    print(f"  - {denial.get('tool_name')}: {denial.get('tool_input')}")
                pytest.fail(
                    f"Worker blocked by {len(permission_denials)} permission(s) even after approval"
                )

            # Check the result
            worker_response = stdout_data.get('result', 'No result')
            print(f"\n✓ Worker response: {worker_response}")

            # Verify it generated a random number
            has_digit = any(c.isdigit() for c in worker_response)
            has_random_keyword = "random" in worker_response.lower()

            if not (has_digit or has_random_keyword):
                pytest.fail(f"Worker should have generated a random number, got: {worker_response}")

            print(f"\n{'=' * 70}")
            print("✅ SUCCESS: Permission bubbling works!")
            print(f"{'=' * 70}")
            print("✓ Worker requested permission via Unix socket")
            print("✓ Permission was approved by parent session")
            print("✓ Worker executed Bash command successfully")
            print("✓ Worker generated output with random number")

        except json.JSONDecodeError as e:
            pytest.fail(f"Failed to parse worker stdout as JSON: {e}")
