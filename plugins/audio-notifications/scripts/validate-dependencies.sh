#!/bin/bash
set -e

# Check if running on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Error: This plugin requires macOS" >&2
    exit 1
fi

# Check if Python 3 is installed
python3 --version >/dev/null 2>&1 || {
    echo "Error: Python 3 is required but not installed" >&2
    exit 1
}

echo "✓ Dependencies validated"
say "Audio Notifications plugin enabled"
