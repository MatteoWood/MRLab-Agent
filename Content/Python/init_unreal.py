"""Editor start-up: adds the "Update Knowledge" button to the level editor toolbar (see mrlab_knowledge.py)."""
import unreal

entry = unreal.ToolMenuEntry(name="MRLabUpdateKnowledge", type=unreal.MultiBlockType.TOOL_BAR_BUTTON)
entry.set_label("Update Knowledge")
entry.set_tool_tip("Download the lab knowledge files from GitLab into Saved/Knowledge")
entry.set_icon("EditorStyle", "Icons.Refresh")
entry.style_name_override = "CalloutToolbar"  # show the label next to the icon
entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, "", "import mrlab_knowledge; mrlab_knowledge.update()")
unreal.ToolMenus.get().extend_menu("LevelEditor.LevelEditorToolBar.User").add_menu_entry("MRLab", entry)
unreal.ToolMenus.get().refresh_all_widgets()
