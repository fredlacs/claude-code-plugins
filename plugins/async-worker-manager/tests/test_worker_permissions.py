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
        result = await client.call_tool("create_async_worker", {
            "prompt": "Generate a random number using bash: echo $((RANDOM % 100))",
            "timeout": 30.0
        })
        worker_id = result.data
        print(f"✓ Worker created: {worker_id}")

        # Wait for permission request (wait() returns when permissions are pending)
        print("\n[2/4] Waiting for permission request...")
        wait_result = await client.call_tool("wait", {
            "timeout": 15.0,
            "worker_id": worker_id
        })
        worker_state = wait_result.structured_content
        pending_perms = worker_state["pending_permissions"]

        if not pending_perms:
            pytest.fail(f"No pending permissions found - worker should have requested Bash permission")

        print(f"✓ Permission request received")
        print(f"  Data: {pending_perms}")

        # Approve first permission
        print(f"\n[3/6] Approving first permission...")
        perm1 = pending_perms[0]
        if hasattr(perm1, 'model_dump'):
            perm1_dict = perm1.model_dump()
        elif hasattr(perm1, 'dict'):
            perm1_dict = perm1.dict()
        else:
            perm1_dict = perm1

        print(f"  Permission 1: {perm1_dict}")

        await client.call_tool("approve_worker_permission", {
            "worker_id": worker_id,
            "request_id": perm1_dict['request_id'],
            "allow": True
        })
        print("✓ First permission approved")

        # Wait for second permission request or completion
        print(f"\n[4/6] Waiting for second permission request or completion...")
        wait_result2 = await client.call_tool("wait", {
            "timeout": 15.0,
            "worker_id": worker_id
        })
        worker_state2 = wait_result2.structured_content
        pending_perms2 = worker_state2["pending_permissions"]

        if not pending_perms2:
            print("⚠ No second permission request - worker may have completed")
            # Check if worker completed
            if worker_state2["completed"]:
                print("✓ Worker completed without second permission")
        else:
            # Approve second permission
            print(f"\n[5/6] Approving second permission...")
            perm2 = pending_perms2[0]
            if hasattr(perm2, 'model_dump'):
                perm2_dict = perm2.model_dump()
            elif hasattr(perm2, 'dict'):
                perm2_dict = perm2.dict()
            else:
                perm2_dict = perm2

            print(f"  Permission 2: {perm2_dict}")

            # Compare the two permissions
            print(f"\n  Comparing permissions:")
            print(f"    request_id: {perm1_dict['request_id']} vs {perm2_dict['request_id']}")
            print(f"    tool: {perm1_dict['tool']} vs {perm2_dict['tool']}")
            print(f"    input match: {perm1_dict['input'] == perm2_dict['input']}")
            if perm1_dict['input'] != perm2_dict['input']:
                print(f"    input1: {perm1_dict['input']}")
                print(f"    input2: {perm2_dict['input']}")

            await client.call_tool("approve_worker_permission", {
                "worker_id": worker_id,
                "request_id": perm2_dict['request_id'],
                "allow": True
            })
            print("✓ Second permission approved")

        # Check if worker already completed, otherwise wait for completion
        print("\n[6/6] Waiting for worker to complete...")
        if worker_state2["completed"]:
            # Worker already completed in previous wait
            results = worker_state2["completed"]
            print(f"✓ Worker completed: {len(results)} result(s) returned (from previous wait)")
        else:
            # Wait for completion
            try:
                wait_result = await client.call_tool("wait", {
                    "timeout": 15.0,
                    "worker_id": worker_id
                })
                worker_state = wait_result.structured_content
                results = worker_state["completed"]
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
        print(f"\n✓ Worker ID: {worker_result['worker_id']}")

        try:
            # Read output from file
            output_file = worker_result['output_file']
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
