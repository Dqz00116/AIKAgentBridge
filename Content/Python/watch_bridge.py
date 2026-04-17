#!/usr/bin/env python3
"""
AIK Agent Bridge Watcher
Mode 1 (default): Continuous polling every 10 seconds (background daemon)
Mode 2 (--detect-once): Block until a pending AIK task is detected, lock it, print info, then exit.
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


def write_notify(data: dict):
    with open(NOTIFY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def clear_notify():
    if NOTIFY_PATH.exists():
        NOTIFY_PATH.unlink()


def read_status() -> dict | None:
    if not STATUS_PATH.exists():
        return None
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def lock_task(data: dict) -> str:
    task_id = data["current_task_id"]
    data["status"] = "in_progress"
    data["locked_by"] = "Kimi"
    data["last_updated"] = now_iso()

    tmp_path = STATUS_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(str(tmp_path), str(STATUS_PATH))

    notify = {
        "detected_at": now_iso(),
        "task_id": task_id,
        "status": "in_progress",
        "metadata": data.get("metadata", {}),
    }
    write_notify(notify)
    return task_id


def run_daemon(interval: int):
    print("[watch_bridge] Daemon mode started. Polling every 10s...")
    while True:
        try:
            data = read_status()
            if data and data.get("status") == "pending" and data.get("metadata", {}).get("tool") == "aik":
                task_id = lock_task(data)
                print(f"[watch_bridge] DETECTED & LOCKED pending task: {task_id}")
            elif data and data.get("status") in ("completed", "blocked", "cancelled"):
                if NOTIFY_PATH.exists():
                    clear_notify()
                    print(f"[watch_bridge] Task {data.get('current_task_id')} reached terminal state: {data.get('status')}")
        except Exception as e:
            print(f"[watch_bridge] ERROR: {e}", file=sys.stderr)
        time.sleep(interval)


def run_detect_once(timeout: int, interval: int) -> int:
    start = time.time()
    print(f"[watch_bridge] Detect-once mode: waiting for pending AIK task (timeout={timeout}s, interval={interval}s)...")
    while True:
        data = read_status()
        if data and data.get("status") == "pending" and data.get("metadata", {}).get("tool") == "aik":
            task_id = lock_task(data)
            print(f"[watch_bridge] DETECTED & LOCKED pending task: {task_id}")
            print(json.dumps(data.get("metadata", {}), indent=2, ensure_ascii=False))
            return 0

        if time.time() - start > timeout:
            print("[watch_bridge] Timeout: no pending task detected.")
            return 1

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="AIK Agent Bridge Watcher")
    parser.add_argument("--detect-once", action="store_true", help="Block until a pending task is detected, then exit")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds for detect-once mode")
    parser.add_argument("--interval", type=int, default=10, help="Poll interval in seconds")
    args = parser.parse_args()

    if args.detect_once:
        rc = run_detect_once(args.timeout, args.interval)
        sys.exit(rc)
    else:
        run_daemon(args.interval)


if __name__ == "__main__":
    main()
