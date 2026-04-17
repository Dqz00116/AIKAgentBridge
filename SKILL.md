---
name: aik-agent-bridge-operator
description: Use when acting as either an external agent submitting tasks or an internal agent inside Unreal Editor with an ACP connection to AIK, and you need to read from or write to the AIK Agent Bridge file protocol to delegate or execute editor operations.
---

# AIK Agent Bridge Operator

Operate the AIK Agent Bridge. External agents submit tasks via CLI; internal agents execute them via AIK over ACP.

## Overview

The bridge lives at `Plugins/AIKAgentBridge/.bridge/` inside the project. It is the **only** contract between external and internal agents.

- **External agents** never touch `localhost:9315`. They write tasks to the bridge and poll for results.
- **Internal agents** read the bridge, execute tasks through AIK over their ACP connection, and write results back.

## When to Use

- You are an **external agent** that needs an internal agent to perform an AIK operation inside Unreal Editor.
- You are an **internal agent** running inside Unreal Editor with an ACP connection to AIK, and you detect a pending task in the bridge.

## Agent Roles & Behavior Modes

Your behavior depends on which side of the bridge you are on:

| Concern | External Agent | Internal Agent |
|---------|----------------|----------------|
| **Primary action** | `submit` tasks, then `poll` | Poll `status.json`, then `execute` via AIK |
| **AIK access** | **Never.** Do not call `localhost:9315`. | **Via ACP only.** Use AIK tools through your ACP session. |
| **File focus** | Write `status.json` + `taskboard.md` on submit; read them on poll. | Read `status.json` + `taskboard.md`; append logs; write resolve state. |
| **Metadata duty** | Provide accurate `metadata` (especially `action` and `targets`). | Read `metadata` to choose execution strategy; honor `fallback_allowed`. |
| **Error handling** | If `blocked`, read the result and adapt your plan. | If execution fails, resolve as `blocked` with a clear explanation. |
| **Log output** | Read logs from `taskboard.md` for progress. | Append timestamped lines to `taskboard.md` after every meaningful step. |

## Shared Protocol

### Directory Layout

All data lives inside the plugin directory:

```
Plugins/AIKAgentBridge/
└── .bridge/
    ├── status.json      # Task state
    ├── taskboard.md     # Request + log + result
    └── history/         # Archived tasks
```

### status.json

```json
{
  "current_task_id": "task-1234567890",
  "status": "pending | in_progress | completed | blocked | cancelled",
  "locked_by": "InternalAgent",
  "metadata": {
    "tool": "aik",
    "action": "create_asset | modify_blueprint | configure_widget | execute_python | composite",
    "targets": ["/Game/UI/WBP_Hello"],
    "expected_outcome": "WidgetBlueprint exists with a TextBlock",
    "fallback_allowed": true,
    "notes": "If asset already exists, reuse."
  },
  "last_updated": "2026-04-17T12:00:00+00:00"
}
```

### taskboard.md

Uses YAML-style frontmatter followed by Markdown body:

```markdown
---
task_id: task-1234567890
from: ExternalAgent
to: InternalAgent
status: pending
created_at: 2026-04-17T12:00:00+00:00
updated_at: 2026-04-17T12:00:00+00:00
---

# Task: task-1234567890

## Request (ExternalAgent -> InternalAgent)

Create a WidgetBlueprint at /Game/UI/WBP_Hello with a TextBlock.

## Log
- [2026-04-17T12:00:00+00:00] Task submitted by ExternalAgent
- [2026-04-17T12:01:00+00:00] Creating WidgetBlueprint...

## Result
_Awaiting execution..._
```

## External Agent Mode

### What you do
1. **Submit** a task with the CLI:
   ```bash
   python Plugins/AIKAgentBridge/Content/Python/aik_bridge.py submit \
     --from ExternalAgent --to InternalAgent \
     --task "Create a WidgetBlueprint at /Game/UI/WBP_Hello" \
     --metadata '{"tool":"aik","action":"create_asset","targets":["/Game/UI/WBP_Hello"]}'
   ```
2. **Poll** until the internal agent resolves it:
   ```bash
   python Plugins/AIKAgentBridge/Content/Python/aik_bridge.py poll \
     --wait-for completed,blocked,cancelled -v
   ```
3. If successful, **archive** to reset the board:
   ```bash
   python Plugins/AIKAgentBridge/Content/Python/aik_bridge.py archive
   ```

### Rules for external agents
- **Never call MCP directly.** External agents are forbidden from calling `localhost:9315`. All operations must be submitted to the internal agent via the bridge.
- **Always include `metadata`** with `tool: "aik"` and a valid `action`. This is how the internal agent routes the task.
- **Do not embed complex Lua/Python scripts in `--task`.** Describe the goal and let the internal agent choose the implementation.
- **Respect `blocked`.** If the internal agent resolves as `blocked`, read the result in `taskboard.md` and adapt your plan rather than blindly resubmitting.
- **Poll with a background subagent.** Once the internal agent locks the task (status becomes `in_progress`), launch a background subagent that polls every 10 seconds for a terminal state (`completed`, `blocked`, or `cancelled`). Do not block the main thread waiting for the result. If the task resolves as `blocked` or `cancelled`, read the result and adapt rather than assuming success.

## Internal Agent Mode

### What you do
1. **Poll** `Plugins/AIKAgentBridge/.bridge/status.json` every 2-5 seconds.
2. **Check eligibility**: `status == "pending"` and `metadata.tool == "aik"`.
3. **Lock** the task:
   ```json
   { "status": "in_progress", "locked_by": "<your_name>" }
   ```
4. **Read** `taskboard.md` for full context.
5. **Execute** via AIK over ACP. Choose strategy from `metadata.action`:
   | `action` | Execution strategy |
   |----------|-------------------|
   | `create_asset` | `create_asset()` → `open_asset()` → `compile()` → `save()` |
   | `modify_blueprint` | `open_asset()` → modify variables/nodes → `compile()` → `save()` |
   | `configure_widget` | `open_asset()` → `add_widget()` / `configure_widget()` → `compile()` → `save()` |
   | `execute_python` | Build Python script, run via `execute_python(py, {mode='file'})` |
   | `composite` | Plan multiple AIK steps; write intermediate progress to `taskboard.md` |
6. **Append logs** to `taskboard.md` under `## Log` after every meaningful step.
7. **Resolve** via CLI or atomic file write:
   ```bash
   python Plugins/AIKAgentBridge/Content/Python/aik_bridge.py resolve \
     --status completed \
     --result "WBP_Hello created with TextBlock."
   ```

### Rules for internal agents
- **Poll continuously with a background subagent.** After reading SKILL.md, launch a background subagent that polls `status.json` every 10 seconds. When a pending task is detected, execute it, resolve it, and then immediately restart the background polling subagent. Never stop polling unless explicitly instructed.
- **Prefer Lua, fallback to Python.** Only use `execute_python` when the Lua domain does not expose the required API.
- **Always check `asset_exists()` before creating.**
- **Always append to `taskboard.md`.** The external agent has no editor visibility; the log is the only progress signal.
- **Write files atomically.** Write to a temporary file and rename to avoid corruption.
- **Retry on transient failures.** If C++ is compiling or Live Coding is active, wait 10 seconds and retry up to 6 times.
- **Do not leave tasks stuck.** If execution fails irrecoverably, resolve as `blocked` with an explanation.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Looking for bridge data at the project root (`.a2a/` or `.aik_bridge/`) | Data lives under `Plugins/AIKAgentBridge/.bridge/` |
| External agent calls MCP directly | External agents are forbidden from `localhost:9315`; submit all operations through the bridge |
| External agent omits `metadata` | Always include `metadata.tool` and `metadata.action` |
| Internal agent tries to set C++ inherited Blueprint defaults with Lua `bp:set()` | Lua cannot see `EditDefaultsOnly` from C++ base classes; resolve `blocked` or use Python fallback |
| Internal agent uses `LevelDesign` Lua to write actor properties | No `set_actor_property` exists; use `execute_python` with `unreal.EditorLevelLibrary` |
| Internal agent assumes `open_asset()` works immediately after `create_asset()` | Call `compile()` first so the asset appears in the Asset Registry |
| Internal agent attempts to start PIE through AIK | No `play_in_editor` API exists in AIK; do not attempt unless a custom Python hook is available |

## Example

### External agent submits
```bash
python Plugins/AIKAgentBridge/Content/Python/aik_bridge.py submit \
  --from ExternalAgent --to InternalAgent \
  --task "Create a WidgetBlueprint at /Game/UI/WBP_Hello with a TextBlock" \
  --metadata '{"tool":"aik","action":"create_asset","targets":["/Game/UI/WBP_Hello"]}'
```

### Internal agent detects and locks
Reads `status.json` with `"status": "pending"`, then sets `"status": "in_progress"`.

### Internal agent executes via AIK
```lua
local result = {}
if not asset_exists('/Game/UI/WBP_Hello') then
    create_asset('/Game/UI/WBP_Hello', 'WidgetBlueprint', {ParentClass='UserWidget'})
    table.insert(result, 'Created asset')
else
    table.insert(result, 'Asset already exists')
end
local a = open_asset('/Game/UI/WBP_Hello')
a:add_widget('TextBlock', {name='Txt_Hello'})
a:configure_widget('Txt_Hello', {Text='Hello'})
a:compile()
a:save()
table.insert(result, 'Added TextBlock and saved')
return table.concat(result, '; ')
```

### Internal agent logs
Appends to `taskboard.md`:
```markdown
- [2026-04-17T12:01:00+00:00] Asset created / verified
- [2026-04-17T12:01:02+00:00] Added TextBlock 'Txt_Hello'
- [2026-04-17T12:01:03+00:00] Compiled and saved
```

### Internal agent resolves
```bash
python Plugins/AIKAgentBridge/Content/Python/aik_bridge.py resolve \
  --status completed \
  --result "WBP_Hello created with TextBlock."
```

### External agent polls
```bash
python Plugins/AIKAgentBridge/Content/Python/aik_bridge.py poll \
  --wait-for completed --timeout 300 -v
```
