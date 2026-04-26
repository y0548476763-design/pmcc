import json
import os
from datetime import datetime

NOTIFICATIONS_FILE = "notifications_log.json"

def add_message(msg: str):
    """Adds a message to the internal notification log."""
    logs = load_messages()
    logs.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": msg
    })
    # Keep only last 100 messages
    logs = logs[-100:]
    try:
        with open(NOTIFICATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save notification: {e}")

def load_messages():
    """Loads historical messages from the log file."""
    if not os.path.exists(NOTIFICATIONS_FILE):
        return []
    try:
        with open(NOTIFICATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []
