#!/bin/bash
cd "$CLAUDE_PLUGIN_ROOT" || exit 1

# send stdin to python then run in background
input=$(cat)
python3 src/main.py <<< "$input" >/dev/null 2>&1 &
# disown
exit 0
