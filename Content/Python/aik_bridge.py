#!/usr/bin/env python3
"""
AIK Agent Bridge CLI

A file-system bridge that lets external agents delegate AIK (Agent Integration Kit)
operations to an internal ACP client agent running inside Unreal Editor.

External agents write tasks via this CLI; internal agents read them, execute through
AIK's tool set over ACP, and write results back.

Usage:
    python aik_bridge.py init
    python aik_bridge.py submit --from ExternalAgent --to InternalAgent \
        --task "Create a WBP..." \
        --metadata '{"tool":"aik","action":"create_asset"}'
    python aik_bridge.py status
    python aik_bridge.py resolve --status completed --result "Done."
    python aik_bridge.py poll --wait-for completed,blocked,cancelled
    python aik_bridge.py archive
"""

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BRIDGE_SUBDIR = ".bridge"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_project_root() -> Path:
    """Auto-detect project root when running inside UE or from CLI."""
    env_root = os.environ.get("AIK_BRIDGE_PROJECT_ROOT")
    if env_root:
        return Path(env_root)
    try:
        import unreal
        return Path(unreal.Paths.project_dir())
    except Exception:
        pass
    # Walk upward from this script looking for a .uproject file
    current = Path(__file__).resolve().parent
    for parent in current.parents:
        if any(p.suffix == ".uproject" for p in parent.iterdir()):
            return parent
    return Path.cwd()


def _get_plugin_dir(project_root: str | None = None) -> Path:
    env_plugin = os.environ.get("AIK_BRIDGE_PLUGIN_DIR")
    if env_plugin:
        return Path(env_plugin)
    root = Path(project_root) if project_root else _detect_project_root()
    return root / "Plugins" / "AIKAgentBridge"


def get_bridge_dir(project_root: str | None = None) -> Path:
    return _get_plugin_dir(project_root) / DEFAULT_BRIDGE_SUBDIR


def ensure_bridge_dir(project_root: str | None = None) -> Path:
    d = get_bridge_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def status_path(project_root: str | None = None) -> Path:
    return ensure_bridge_dir(project_root) / "status.json"


def taskboard_path(project_root: str | None = None) -> Path:
    return ensure_bridge_dir(project_root) / "taskboard.md"


def history_dir(project_root: str | None = None) -> Path:
    d = ensure_bridge_dir(project_root) / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_status(project_root: str | None = None) -> dict:
    p = status_path(project_root)
    if not p.exists():
        return {
            "current_task_id": None,
            "status": "idle",
            "locked_by": None,
            "metadata": {},
            "last_updated": now_iso(),
        }
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_status(data: dict, project_root: str | None = None):
    p = status_path(project_root)
    data["last_updated"] = now_iso()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    text = text.strip()
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm_text = parts[1].strip()
    body = parts[2].strip()
    data = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data, body


def build_frontmatter(data: dict, body: str) -> str:
    lines = ["---"]
    for k, v in data.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body.strip())
    return "\n".join(lines)


def read_taskboard(project_root: str | None = None) -> tuple[dict, str]:
    p = taskboard_path(project_root)
    if not p.exists():
        return {}, ""
    with open(p, "r", encoding="utf-8") as f:
        return parse_frontmatter(f.read())


def write_taskboard(fm: dict, body: str, project_root: str | None = None):
    p = taskboard_path(project_root)
    with open(p, "w", encoding="utf-8") as f:
        f.write(build_frontmatter(fm, body))


def cmd_init(args):
    d = ensure_bridge_dir(args.project_root)
    history_dir(args.project_root)

    s = status_path(args.project_root)
    if not s.exists():
        write_status(
            {
                "current_task_id": None,
                "status": "idle",
                "locked_by": None,
                "metadata": {},
            },
            args.project_root,
        )
        print(f"[init] Created {s}")

    t = taskboard_path(args.project_root)
    if not t.exists():
        fm = {
            "task_id": "none",
            "from": "system",
            "to": "system",
            "status": "idle",
            "created_at": now_iso(),
        }
        body = "# AIK Agent Bridge Taskboard\n\nNo active task."
        write_taskboard(fm, body, args.project_root)
        print(f"[init] Created {t}")

    print(f"[init] AIK Agent Bridge ready at {d}")


def cmd_submit(args):
    st = read_status(args.project_root)
    if st["status"] in ("pending", "in_progress") and st["current_task_id"]:
        print(
            f"[submit] ERROR: There is already an active task ({st['current_task_id']}) with status '{st['status']}'. "
            f"Please archive it first (`aik_bridge.py archive`) or wait for it to complete.",
            file=sys.stderr,
        )
        sys.exit(1)

    task_id = args.id or f"task-{int(time.time())}"
    fm = {
        "task_id": task_id,
        "from": args.from_agent,
        "to": args.to_agent,
        "status": "pending",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    body_lines = [
        f"# Task: {task_id}",
        "",
        f"## Request ({args.from_agent} -> {args.to_agent})",
        "",
        args.task,
        "",
        "## Log",
        f"- [{now_iso()}] Task submitted by {args.from_agent}",
        "",
        "## Result",
        "_Awaiting execution..._",
    ]
    body = "\n".join(body_lines)

    write_taskboard(fm, body, args.project_root)

    metadata = {}
    if args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError as e:
            print(f"[submit] ERROR: Invalid metadata JSON: {e}", file=sys.stderr)
            sys.exit(1)

    write_status(
        {
            "current_task_id": task_id,
            "status": "pending",
            "locked_by": None,
            "metadata": metadata,
        },
        args.project_root,
    )

    print(f"[submit] Task {task_id} submitted successfully.")
    print(f"[submit] Taskboard: {taskboard_path(args.project_root)}")


def cmd_status(args):
    st = read_status(args.project_root)
    fm, body = read_taskboard(args.project_root)

    print("=== AIK Agent Bridge Status ===")
    print(f"Task ID     : {st.get('current_task_id') or 'None'}")
    print(f"Status      : {st.get('status') or 'idle'}")
    print(f"Locked By   : {st.get('locked_by') or 'None'}")
    print(f"Last Updated: {st.get('last_updated') or 'N/A'}")
    if st.get("metadata"):
        print(f"Metadata    : {json.dumps(st.get('metadata'), ensure_ascii=False)}")
    print("")
    if fm:
        print(f"From        : {fm.get('from', 'N/A')}")
        print(f"To          : {fm.get('to', 'N/A')}")
        print(f"Created     : {fm.get('created_at', 'N/A')}")
    if args.verbose:
        print("")
        print(body)


def cmd_resolve(args):
    st = read_status(args.project_root)
    if st["status"] == "idle":
        print("[resolve] ERROR: No active task to resolve.", file=sys.stderr)
        sys.exit(1)

    fm, body = read_taskboard(args.project_root)
    task_id = fm.get("task_id", st.get("current_task_id", "unknown"))

    fm["status"] = args.status
    fm["updated_at"] = now_iso()

    log_entry = f"- [{now_iso()}] Task resolved with status '{args.status}' by {args.by or 'agent'}"

    result_section = f"## Result\n\n{args.result}\n"
    if "## Result" in body:
        parts = body.split("## Result", 1)
        remainder = parts[1].split("\n## ", 1)
        after = ""
        if len(remainder) > 1:
            after = "\n## " + remainder[1]
        body = parts[0] + result_section + after
    else:
        body += "\n" + result_section

    if "## Log" in body:
        body = body.replace("## Log", f"## Log\n{log_entry}", 1)
    else:
        body += f"\n{log_entry}\n"

    write_taskboard(fm, body, args.project_root)
    write_status(
        {
            "current_task_id": task_id,
            "status": args.status,
            "locked_by": None,
            "metadata": st.get("metadata", {}),
        },
        args.project_root,
    )

    print(f"[resolve] Task {task_id} marked as '{args.status}'.")


def cmd_poll(args):
    start = time.time()
    targets = [s.strip() for s in args.wait_for.split(",")]
    print(f"[poll] Waiting for status in {targets} (timeout: {args.timeout}s)...")
    while True:
        st = read_status(args.project_root)
        if st["status"] in targets:
            print(f"[poll] Status reached: {st['status']}")
            fm, body = read_taskboard(args.project_root)
            print(f"Task ID: {st.get('current_task_id')}")
            if args.verbose:
                print("\n" + body)
            return
        if time.time() - start > args.timeout:
            print(f"[poll] TIMEOUT after {args.timeout}s. Current status: {st['status']}", file=sys.stderr)
            sys.exit(1)
        time.sleep(args.interval)


def cmd_archive(args):
    st = read_status(args.project_root)
    t = taskboard_path(args.project_root)
    if not t.exists():
        print("[archive] No taskboard to archive.")
        write_status(
            {"current_task_id": None, "status": "idle", "locked_by": None, "metadata": {}},
            args.project_root,
        )
        return

    task_id = st.get("current_task_id") or f"archived-{int(time.time())}"
    dest = history_dir(args.project_root) / f"{task_id}.md"
    shutil.move(str(t), str(dest))
    write_status(
        {"current_task_id": None, "status": "idle", "locked_by": None, "metadata": {}},
        args.project_root,
    )

    fm = {
        "task_id": "none",
        "from": "system",
        "to": "system",
        "status": "idle",
        "created_at": now_iso(),
    }
    write_taskboard(fm, "# AIK Agent Bridge Taskboard\n\nNo active task.", args.project_root)

    print(f"[archive] Archived task {task_id} to {dest}")


def main_with_args(args_list=None):
    parser = argparse.ArgumentParser(
        prog="aik_bridge",
        description="AIK Agent Bridge CLI for delegating AIK operations to an internal ACP client agent.",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root path (default: auto-detect; bridge data lives under Plugins/AIKAgentBridge/.bridge)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    subparsers.add_parser("init", help="Initialize the bridge directory")

    # submit
    p_submit = subparsers.add_parser("submit", help="Submit a new task to the internal agent")
    p_submit.add_argument("--from", dest="from_agent", required=True, help="Delegating agent name")
    p_submit.add_argument("--to", dest="to_agent", required=True, help="Target agent name")
    p_submit.add_argument("--task", required=True, help="Task description / requirement")
    p_submit.add_argument("--id", default=None, help="Optional task ID")
    p_submit.add_argument(
        "--metadata",
        default=None,
        help='Optional JSON metadata (e.g., {"tool":"aik","action":"create_asset"})',
    )

    # status
    p_status = subparsers.add_parser("status", help="Show current task status")
    p_status.add_argument("-v", "--verbose", action="store_true", help="Print full taskboard content")

    # resolve
    p_resolve = subparsers.add_parser("resolve", help="Resolve the current task")
    p_resolve.add_argument(
        "--status",
        required=True,
        choices=["completed", "blocked", "cancelled"],
        help="Resolution status",
    )
    p_resolve.add_argument("--result", required=True, help="Result description or summary")
    p_resolve.add_argument("--by", default=None, help="Resolving agent name")

    # poll
    p_poll = subparsers.add_parser("poll", help="Poll until a target status is reached")
    p_poll.add_argument("--wait-for", required=True, help="Target status(es) to wait for, comma-separated (e.g., completed,blocked,cancelled)")
    p_poll.add_argument("--timeout", type=int, default=86400, help="Timeout in seconds (default: 86400 = 24h)")
    p_poll.add_argument("--interval", type=int, default=10, help="Poll interval in seconds (default: 10)")
    p_poll.add_argument("-v", "--verbose", action="store_true", help="Print full taskboard upon reaching status")

    # archive
    subparsers.add_parser("archive", help="Archive the current task and reset to idle")

    args = parser.parse_args(args_list)

    if args.command == "init":
        cmd_init(args)
    elif args.command == "submit":
        cmd_submit(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "resolve":
        cmd_resolve(args)
    elif args.command == "poll":
        cmd_poll(args)
    elif args.command == "archive":
        cmd_archive(args)
    else:
        parser.print_help()
        sys.exit(1)


def main():
    main_with_args(None)


if __name__ == "__main__":
    main()
