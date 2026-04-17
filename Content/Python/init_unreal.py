import unreal
import os


def _run_bridge_cmd(args_list):
    """Helper to invoke aik_bridge CLI from inside UE."""
    import aik_bridge
    try:
        aik_bridge.main_with_args(args_list)
    except SystemExit:
        pass
    except Exception as e:
        unreal.log_error(f"[AIK Agent Bridge] Command failed: {e}")


def _show_status():
    _run_bridge_cmd(["status", "-v"])
    import aik_bridge
    tb = aik_bridge.taskboard_path()
    if tb.exists():
        unreal.SystemLibrary.launch_url(str(tb))
    else:
        unreal.EditorDialog.show_message(
            "AIK Agent Bridge",
            "No active taskboard found. Please run Initialize first.",
            unreal.AppMsgType.OK
        )


def _init_bridge():
    _run_bridge_cmd(["init"])
    unreal.EditorDialog.show_message(
        "AIK Agent Bridge",
        "AIK Agent Bridge initialized successfully.",
        unreal.AppMsgType.OK
    )


def _archive_bridge():
    _run_bridge_cmd(["archive"])
    unreal.EditorDialog.show_message(
        "AIK Agent Bridge",
        "Task archived and board reset to idle.",
        unreal.AppMsgType.OK
    )


def _submit_task_dialog():
    from_agent, ok1 = unreal.EditorDialog.show_text_input(
        "AIK Agent Bridge - Submit Task",
        "From Agent:",
        "ExternalAgent"
    )
    if not ok1:
        return
    to_agent, ok2 = unreal.EditorDialog.show_text_input(
        "AIK Agent Bridge - Submit Task",
        "To Agent:",
        "InternalAgent"
    )
    if not ok2:
        return
    task_text, ok3 = unreal.EditorDialog.show_text_input(
        "AIK Agent Bridge - Submit Task",
        "Task description:",
        ""
    )
    if not ok3:
        return
    if not task_text.strip():
        unreal.EditorDialog.show_message(
            "AIK Agent Bridge",
            "Task description cannot be empty.",
            unreal.AppMsgType.OK
        )
        return

    import aik_bridge
    import sys
    old_argv = sys.argv
    try:
        sys.argv = [
            "aik_bridge.py",
            "submit",
            "--from", from_agent,
            "--to", to_agent,
            "--task", task_text,
        ]
        aik_bridge.main()
    finally:
        sys.argv = old_argv

    unreal.EditorDialog.show_message(
        "AIK Agent Bridge",
        "Task submitted successfully.",
        unreal.AppMsgType.OK
    )


def _resolve_task_dialog():
    status, ok1 = unreal.EditorDialog.show_text_input(
        "AIK Agent Bridge - Resolve Task",
        "Status (completed/blocked/cancelled):",
        "completed"
    )
    if not ok1:
        return
    result, ok2 = unreal.EditorDialog.show_text_input(
        "AIK Agent Bridge - Resolve Task",
        "Result summary:",
        ""
    )
    if not ok2:
        return

    import aik_bridge
    import sys
    old_argv = sys.argv
    try:
        sys.argv = [
            "aik_bridge.py",
            "resolve",
            "--status", status,
            "--result", result,
        ]
        aik_bridge.main()
    finally:
        sys.argv = old_argv

    unreal.EditorDialog.show_message(
        "AIK Agent Bridge",
        f"Task resolved as '{status}'.",
        unreal.AppMsgType.OK
    )


def register_aik_bridge_menus():
    menus = unreal.ToolMenus.get()
    main_menu = menus.find_menu("LevelEditor.MainMenu")
    if not main_menu:
        unreal.log_error("[AIK Agent Bridge] Could not find main menu.")
        return

    menu_name = "LevelEditor.MainMenu.AIKAgentBridge"
    existing = menus.find_menu(menu_name)
    if existing:
        bridge_menu = existing
    else:
        bridge_menu = main_menu.add_sub_menu(
            main_menu.menu_name,
            "",
            "AIKAgentBridge",
            "AIK Agent Bridge",
            tool_tip="Bridge for external agents to use AIK via internal ACP client"
        )

    # Initialize
    e_init = unreal.ToolMenuEntry(
        name="AIK_Init",
        type=unreal.MultiBlockType.MENU_ENTRY,
        insert_position=unreal.ToolMenuInsert("", unreal.ToolMenuInsertType.DEFAULT),
        label="Initialize Bridge",
        tool_tip="Create .bridge directory inside the plugin and seed files"
    )
    e_init.set_string_command(
        unreal.ToolMenuStringCommandType.PYTHON,
        custom_type="",
        string="import init_unreal; init_unreal._init_bridge()"
    )
    bridge_menu.add_menu_entry("Actions", e_init)

    # Show Status
    e_status = unreal.ToolMenuEntry(
        name="AIK_Status",
        type=unreal.MultiBlockType.MENU_ENTRY,
        label="Show Status",
        tool_tip="Open the current taskboard"
    )
    e_status.set_string_command(
        unreal.ToolMenuStringCommandType.PYTHON,
        custom_type="",
        string="import init_unreal; init_unreal._show_status()"
    )
    bridge_menu.add_menu_entry("Actions", e_status)

    # Separator
    e_sep = unreal.ToolMenuEntry(
        name="AIK_Sep1",
        type=unreal.MultiBlockType.SEPARATOR
    )
    bridge_menu.add_menu_entry("Actions", e_sep)

    # Submit Task Dialog
    e_submit = unreal.ToolMenuEntry(
        name="AIK_Submit",
        type=unreal.MultiBlockType.MENU_ENTRY,
        label="Submit Task...",
        tool_tip="Submit a new task to the internal agent"
    )
    e_submit.set_string_command(
        unreal.ToolMenuStringCommandType.PYTHON,
        custom_type="",
        string="import init_unreal; init_unreal._submit_task_dialog()"
    )
    bridge_menu.add_menu_entry("Actions", e_submit)

    # Resolve Task Dialog
    e_resolve = unreal.ToolMenuEntry(
        name="AIK_Resolve",
        type=unreal.MultiBlockType.MENU_ENTRY,
        label="Resolve Task...",
        tool_tip="Resolve the current task with a result"
    )
    e_resolve.set_string_command(
        unreal.ToolMenuStringCommandType.PYTHON,
        custom_type="",
        string="import init_unreal; init_unreal._resolve_task_dialog()"
    )
    bridge_menu.add_menu_entry("Actions", e_resolve)

    # Archive
    e_archive = unreal.ToolMenuEntry(
        name="AIK_Archive",
        type=unreal.MultiBlockType.MENU_ENTRY,
        label="Archive Task",
        tool_tip="Archive completed task and reset board"
    )
    e_archive.set_string_command(
        unreal.ToolMenuStringCommandType.PYTHON,
        custom_type="",
        string="import init_unreal; init_unreal._archive_bridge()"
    )
    bridge_menu.add_menu_entry("Actions", e_archive)

    menus.refresh_all_widgets()
    unreal.log("[AIK Agent Bridge] Menu registered successfully.")


# Auto-register on module load (when UE starts or Python is reloaded)
register_aik_bridge_menus()
