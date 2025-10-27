# Git Commit Intercept Hook

The plugin includes a PreToolUse hook that automatically intercepts `git commit` commands and prompts Claude to ask if you want to run a code review first.

## How it works

1. **Before committing**, when Claude attempts to run `git commit`, the hook intercepts the command
2. **Claude asks** if you want to run a code review before committing
3. **You choose**:
   - "Yes, review with an agent" → Claude launches a code review agent to review changes
   - "No, commit without review" → Claude proceeds with the commit
4. **After review** (if chosen), Claude automatically retries the commit

## What gets intercepted

The hook blocks simple commit commands but allows special commits:

**Blocked (will prompt for review):**
- `git commit`
- `git commit -m "message"`
- `git add . && git commit -m "fix"`
- Any compound command containing `git commit`

**Allowed (no prompt):**
- `git commit --amend`
- `git commit --fixup`
- `git commit --squash`
- `git add`, `git push` (standalone)

## Disabling the hook

To disable the git commit intercept hook, you can either:

1. **Remove the hook** from your plugin configuration
2. Use special bypass market `__SKIP_REVIEW_CHECK__` in commit command 

## Technical details

- **Hook type**: PreToolUse hook for Bash tool
- **Detection**: Simple regex pattern matching
- **Bypass mechanism**: Special marker `__SKIP_REVIEW_CHECK__` in commit command
- **No dependencies**: Uses only Python standard library
