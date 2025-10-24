#!/usr/bin/env python3
import json
import sys


def main():
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Task tool disabled. Use async-workers skill: "
                "Task-like but resumable with advanced options."
            ),
        }
    }
    print(json.dumps(output), file=sys.stdout)


if __name__ == "__main__":
    main()
