#!/usr/bin/env python3
"""
Permission proxy MCP server for worker Claude sessions.

Enforces permissions based on permissions_config.json:
- Denies tools in deniedTools list
- Denies Bash commands matching excludedCommands patterns
- Detects shell obfuscation attempts (eval, base64 injection, command substitution)
- Auto-approves everything else
"""
import json
import re
import shlex
from pathlib import Path
from typing import List, Tuple
from fastmcp import FastMCP
from mcp.types import TextContent, Content

mcp = FastMCP("Permission Proxy")

CONFIG_PATH = Path(__file__).parent / "permissions_config.json"


def load_config() -> dict:
    """Load and validate permissions config with fail-closed defaults."""
    try:
        if not CONFIG_PATH.exists():
            print(f"WARNING: Config file not found at {CONFIG_PATH}. Using fail-closed defaults.")
            return get_fail_closed_config()

        config = json.loads(CONFIG_PATH.read_text())

        # Validate config structure
        if not isinstance(config.get("excludedCommands", []), list):
            print("WARNING: Invalid excludedCommands format. Using fail-closed defaults.")
            return get_fail_closed_config()

        return config
    except Exception as e:
        # Fail-closed on any error
        print(f"ERROR loading config: {e}. Using fail-closed defaults.")
        return get_fail_closed_config()


def get_fail_closed_config() -> dict:
    """Fail-closed: Deny dangerous commands by default."""
    return {
        "excludedCommands": ["docker", "sudo", "su", "rm", "dd", "mkfs"],
        "excludedBinaries": [],
        "dangerousPatterns": ["eval", "base64.*bash", "base64.*sh"],
        "allowedTools": [],
        "deniedTools": [],
        "sandbox": {"enabled": True}
    }


CONFIG = load_config()


def parse_bash_command(cmd: str) -> Tuple[List[str], List[str]]:
    """
    Parse bash command safely using shlex.
    Returns: (tokens, warnings)
    """
    warnings = []

    try:
        # Use shlex to properly parse shell quoting/escaping
        tokens = shlex.split(cmd)
    except ValueError as e:
        # Unclosed quotes, etc. - suspicious
        warnings.append(f"Invalid shell syntax: {e}")
        # Fallback to simple split
        tokens = cmd.split()

    return tokens, warnings


def check_dangerous_patterns(cmd: str) -> Tuple[bool, str]:
    """Check for shell obfuscation patterns."""
    patterns = CONFIG.get("dangerousPatterns", [])

    for pattern in patterns:
        try:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True, f"Dangerous pattern detected: {pattern}"
        except re.error:
            # Invalid regex pattern in config, skip it
            continue

    # Check for common obfuscation techniques
    if "base64" in cmd.lower() and ("bash" in cmd.lower() or "sh" in cmd.lower()):
        return True, "Potential base64 command injection"

    # Command substitution
    if re.search(r'\$\(', cmd) or re.search(r'`[^`]+`', cmd):
        return True, "Command substitution detected ($(...)  or backticks)"

    # eval command
    if re.search(r'\beval\b', cmd, re.IGNORECASE):
        return True, "eval command detected"

    return False, ""


def is_binary_excluded(binary: str, excluded: List[str]) -> bool:
    """Check if binary name is in excluded list."""
    # Get just the binary name (strip path)
    binary_name = binary.split('/')[-1]

    for excluded_cmd in excluded:
        # Match both bare name and full path
        if binary_name == excluded_cmd or binary == excluded_cmd:
            return True

    return False


@mcp.tool()
async def request_permission(
    tool_name: str,
    input: dict,
    reason: str = "",
    tool_use_id: str = ""
) -> List[Content]:
    """Enforce permissions with robust command parsing."""

    # Check denied tools
    denied_tools = CONFIG.get("deniedTools", [])
    if tool_name in denied_tools:
        response = {
            "behavior": "deny",
            "reason": f"Tool '{tool_name}' is in deniedTools list"
        }
        return [TextContent(type="text", text=json.dumps(response))]

    # Whitelist mode: if allowedTools is set and not empty, only allow those
    allowed_tools = CONFIG.get("allowedTools", [])
    if allowed_tools and tool_name not in allowed_tools:
        response = {
            "behavior": "deny",
            "reason": f"Tool not in allowedTools list. Allowed: {allowed_tools}"
        }
        return [TextContent(type="text", text=json.dumps(response))]

    # Special handling for Bash tool
    if tool_name == "Bash":
        cmd = input.get("command", "")

        # Layer 1: Check for dangerous patterns (eval, base64, command substitution)
        is_dangerous, danger_reason = check_dangerous_patterns(cmd)
        if is_dangerous:
            response = {
                "behavior": "deny",
                "reason": f"Command blocked: {danger_reason}"
            }
            return [TextContent(type="text", text=json.dumps(response))]

        # Layer 2: Parse and check binary name
        tokens, warnings = parse_bash_command(cmd)

        if tokens:
            binary = tokens[0]
            excluded_cmds = CONFIG.get("excludedCommands", [])

            if is_binary_excluded(binary, excluded_cmds):
                response = {
                    "behavior": "deny",
                    "reason": f"Binary '{binary}' is in excludedCommands: {excluded_cmds}"
                }
                return [TextContent(type="text", text=json.dumps(response))]

        # Layer 3: Check for path-based exclusions
        excluded_binaries = CONFIG.get("excludedBinaries", [])
        for excluded_path in excluded_binaries:
            if excluded_path in cmd:
                response = {
                    "behavior": "deny",
                    "reason": f"Binary path '{excluded_path}' is excluded"
                }
                return [TextContent(type="text", text=json.dumps(response))]

    # Auto-approve
    response = {
        "behavior": "allow",
        "updatedInput": input
    }
    return [TextContent(type="text", text=json.dumps(response))]


if __name__ == "__main__":
    mcp.run()
