#!/usr/bin/env python3
import json
from pathlib import Path
import sys


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


def main():
    # Check all plugin dependencies
    missing_plugins = []
    for plugin in PLUGIN_DEPENDENCIES:
        if not plugin_available(plugin):
            missing_plugins.append(plugin)

    if missing_plugins:
        # Block session startup if dependencies are missing
        output = {
            "continue": False,
            "systemMessage": f"auto-code-review plugin requires the following plugins to be installed and enabled: {', '.join(missing_plugins)}"
        }
        print(json.dumps(output), file=sys.stdout)
        sys.exit(0)

    # Dependencies satisfied - allow session to continue
    sys.exit(0)


if __name__ == "__main__":
    main()
