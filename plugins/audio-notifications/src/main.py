import json
import sys
import subprocess

def process_hook_notification(hook_data: dict):
    name = hook_data.get("hook_event_name")
    if not isinstance(name, str):
        raise ValueError(f"No 'hook_event_name' in hook data: {hook_data}")

    if name != "Notification":
        return
    
    message = hook_data.get("message")

    if not isinstance(message, str):
        raise ValueError(f"Expected 'message' to be a string, got {type(message).__name__}")

    cmd = ['say']
    cmd.append(message.strip())
    # Spawn detached background process
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

def main():
    hook_data = json.load(sys.stdin)
    process_hook_notification(hook_data)

if __name__ == '__main__':
    main()
