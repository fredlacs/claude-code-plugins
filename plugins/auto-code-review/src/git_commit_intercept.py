#!/usr/bin/env python3
import json
from pathlib import Path
import re
import sys


BYPASS_MARKER = "__SKIP_REVIEW_CHECK__"
PLUGIN_DEPENDENCIES = [
    "async-worker-manager@freds-claude-code-plugins",
    "code-review@claude-code-plugins",
]


def plugin_available(plugin_key: str) -> bool:
    """Check if plugin is installed and enabled."""
    settings_file = Path.home() / ".claude" / "settings.json"
    installed_file = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        with open(settings_file) as f:
            settings = json.load(f)
            enabled = settings.get("enabledPlugins", {}).get(plugin_key, False)
        with open(installed_file) as f:
            installed = json.load(f)
            plugin_exists = plugin_key in installed.get("plugins", {})
        return enabled and plugin_exists
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return False


def contains_git_commit(command: str) -> bool:
    # Early return if no git commit mentioned
    if not re.search(r"\bgit\s+commit\b", command, re.IGNORECASE):
        return False
    # Check if it has special flags that should be allowed (anywhere in command including commit msg)
    if re.search(r"--(?:amend|fixup|squash)\b", command, re.IGNORECASE):
        return False
    return True


def main():
    try:
        raw_input = sys.stdin.read()
        input_data = json.loads(raw_input)
    except Exception:
        sys.exit(0)

    if input_data.get("tool_name") != "Bash":
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command")
    if not command or not isinstance(command, str):
        sys.exit(0)

    if not contains_git_commit(command):
        sys.exit(0)

    if BYPASS_MARKER in command:
        sys.exit(0)

    # Block the command and instruct Claude to ask the user
    reason = """Git commit detected. Before committing, please ask the user if they want to run a code review first.

Use the AskUserQuestion tool with the following question:
- Question: "Would you like to run a code review before committing these changes?"
- Options:
1. "Yes, run code review" - Run the /code-review:code-review command via an agent, then proceed with commit
2. "No, commit without review" - Proceed with the commit immediately

After getting the user's response:
- If they choose "Yes": Use an agent to run the /code-review:code-review slash command to review the changes, then retry the commit. The prompt should instruct them to review the current git changes (staged and unstaged) and treat that as a pull request.
- If they choose "No": Retry the same git commit command with the marker: # __SKIP_REVIEW_CHECK__

Example bypass: git commit -m "fix bug" # __SKIP_REVIEW_CHECK__"""

    # if plugin dependency missing, we override reason for denying tool
    # TODO: run on a startup hook instead
    for plugin in PLUGIN_DEPENDENCIES:
        if not plugin_available(plugin):
            reason = f"auto-code-review requires plugin {plugin} to be installed"
            break

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output), file=sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
