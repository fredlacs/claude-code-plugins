#!/usr/bin/env python3
from contextlib import suppress
import json
from pathlib import Path
import sys


CONFIG_PATH = Path.home() / ".claude" / "async-worker-config.json"
cfg = {}
with suppress(OSError, json.JSONDecodeError):
    loaded = json.loads(CONFIG_PATH.read_text())
    if isinstance(loaded, dict):
        cfg = loaded

def main():
    if cfg.get("intercept_task") is True:
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
