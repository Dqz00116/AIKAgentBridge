#!/usr/bin/env python3
"""
Background poller for AIK Agent Bridge.
Checks status.json every N seconds and writes a notification file when a pending task is detected.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
BRIDGE_DIR = SCRIPT_DIR.parent.parent / ".bridge"
STATUS_PATH = BRIDGE_DIR / "status.json"
NOTIFY_PATH = BRIDGE_DIR / ".pending_notify.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_once() -> dict | None:
    if not STATUS_PATH.exists():
        return None
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def notify_pending(status: dict):
    data = {
        "detected_at": now_iso(),
        "task_id": status.get("current_task_id"),
        "status": status.get("status"),
        "metadata": status.get("metadata"),
        "locked_by": status.get("locked_by"),
    }
    with open(NOTIFY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def clear_notify():
    if NOTIFY_PATH.exists():
        NOTIFY_PATH.unlink()


def poll(interval: int, timeout: int | None = None):
    start = time.time()
    print(f"[poll_bridge] Starting poll loop every {interval}s...")
    while True:
        st = check_once()
        if st and st.get("status") == "pending":
            print(f"[poll_bridge] PENDING task detected: {st.get('current_task_id')}")
            notify_pending(st)
        else:
            clear_notify()

        if timeout and (time.time() - start) > timeout:
            print(f"[poll_bridge] Timeout reached ({timeout}s). Exiting.")
            break
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Poll AIK Agent Bridge for pending tasks.")
    parser.add_argument("--interval", type=int, default=10, help="Poll interval in seconds")
    parser.add_argument("--timeout", type=int, default=None, help="Max runtime in seconds (None = infinite)")
    args = parser.parse_args()
    poll(args.interval, args.timeout)


if __name__ == "__main__":
    main()
