# MRLabProject 5.8 (lab rendering PC)

MetaHuman conversational agent for the TU Wien MRLab curved LED wall (nDisplay). This machine is the lab rendering PC that drives the wall. Engine: UE 5.8. Blueprint-only so far (no `Source/`). Knowledge base for RAG lives separately: https://gitlab.tuwien.ac.at/mixed-reality-labor/mrlab-agent-knowledge

**[README.md](README.md) is the shared project document**: goals, current state, roadmap, open questions (Q*), decisions (D*), work log. This file only covers how to work on this machine.

## This machine
- The project is a Git clone with read-only access: you can `git pull`, you cannot push. Do not run `git push`.
- How work done here gets back into the shared project is not decided yet (README Q19). Until then, ask the owner before committing anything.
- Hardware connected here: the LED wall (nDisplay, stereo 3D through polarization) and the Moverse tracking data from the Tracking PC (Live Link source `128.130.143.140:54321`). Details in README 3.1, 4.3, 4.4.
- nDisplay was launched through Switchboard in the 5.7 setup. Node logs: `Saved/Logs/Node_0.log`, Switchboard logs: `Saved/Logs/Switchboard/`.

## Session workflow
Start:
1. `git pull` to get the latest project state. If it reports conflicts or local changes, stop and ask the owner.
2. Read README sections 4 (current state), 5 (roadmap), 6 (open questions), 8 (latest work log entry).
3. Check the editor is open and reachable: MCP `list_toolsets`, or `python Tools/ue_py.py -c "import unreal; print(unreal.SystemLibrary.get_engine_version())"`.

During:
- One roadmap step at a time. Before a step starts, write a precise plan for it and get the owner's approval.
- Do not decide anything listed as an open question in README section 6. Ask the owner.

End:
- Update README locally: section 4 for anything that changed, section 5 step status, section 6 (answered or new questions), section 7 for new decisions (who decided), section 8 with a dated entry marked "lab PC" (done, verified, not verified, left).
- Tell the owner which files changed on this machine.

## How to work on the editor
The editor must be open for channels A and B.

- **A. UE MCP server** (`unreal-mcp` in `.mcp.json`, `http://127.0.0.1:8000/mcp`). Built-in ModelContextProtocol + EditorToolset plugins. Three meta-tools: `list_toolsets`, `describe_toolset`, `call_tool`. Use it for assets, actors, Blueprints (nodes, pins, variables, graph DSL), materials, object properties, output log (`EditorToolset.LogsToolset` GetLogEntries), PIE start/stop (`EditorToolset.EditorAppToolset` StartPIE/StopPIE), config sections (ConfigSettingsToolset), editor UI automation (SlateInspectorToolset), Live Coding.
  - Pass every argument a tool lists, even ones with defaults (e.g. `GetLogEntries` needs `pattern`, `find_node_types` needs `context_pins`), or the call is rejected.
  - Do not call `CaptureViewport` through MCP: it returns the PNG as base64 text. Run `python Tools/capture_viewport.py` instead and read `Saved/Screenshots/viewport.png`. Move the camera first with `unreal.UnrealEditorSubsystem.set_level_viewport_camera_info`.
- **B. Python remote execution** for anything the toolsets cannot do (nDisplay, Live Link, MetaHuman, batch scripting): `python Tools/ue_py.py -c "<code>"` or `python Tools/ue_py.py <file.py>`. Full `unreal` module; `import unreal` explicitly in each snippet. EditorToolset functions are importable too (`from editor_toolset.toolsets.blueprint import BlueprintTools`, `from editor_toolset.toolsets.object import ObjectTools`).
- **C. Files**: `Config/*.ini`, `MRLabProject58.uproject`, `Content/Python`, logs in `Saved/Logs/`. `.uasset`/`.umap` are binary, never edit them as files. Copying a `.uasset` into `Content/` is fine; call `AssetRegistry.scan_paths_synchronous` afterwards.

## Setup on this machine
- MCP server auto-start is a per-user setting under `Saved/`, so it is off on a fresh clone: enable it once in Project Settings > Plugins > Model Context Protocol, or launch the editor with `-ModelContextProtocolStartServer`. Then register it for Claude Code with the `.mcp.json` in the project root (restart the Claude Code session after the editor is up).
- `Tools/ue_py.py` hardcodes the engine path `C:\Program Files\Epic Games\UE_5.8` and project name `MRLabProject58`. If UE 5.8 is installed elsewhere here, ask the owner before changing it (it is a shared file).
- Moverse plugin: `MoversePlugin` is listed as optional in the `.uproject`. In the 5.7 setup it was installed in the engine under `Engine/Plugins/Marketplace/MoversePlugin` (plus a duplicate under `Engine/Plugins/Runtime/Marketplace/`). A 5.8 build is not confirmed (README Q5). Check the editor log for `Mounting Engine plugin MoversePlugin` before relying on it.
- The MCP plugin logs that data sent through it to an LLM provider is Licensed Technology under the UE EULA (section 6(e)); the provider must not train on it.

## Gotchas
- Editing a Blueprint graph: for small changes add nodes with `BlueprintTools.create_node` / `connect_pins`. Rewriting a whole graph with `write_graph_dsl` can break graphs that use split struct pins (e.g. `NDC_Basic`).
- A Blueprint target pin cannot hold an asset reference; use a variable with a default value and a getter node.
- The level Blueprint is not reachable from Python, and `DefaultMap` has none.
- After deleting an asset in the editor and copying a file back to the same path, `load_asset` returns None. Fix: `unreal.EditorLoadingAndSavingUtils.reload_packages([pkg], unreal.ReloadPackagesInteractionMode.ASSUME_POSITIVE)`.
- New World Partition actor files copied into `__ExternalActors__` appear only after reloading the map (`EditorLoadingAndSavingUtils.load_map`). Check for unsaved maps first so no save dialog blocks the editor.
- Save only what you changed: `EditorLoadingAndSavingUtils.save_packages([...], True)` or `EditorAssetLibrary.save_asset`. Do not save all; other assets may hold unsaved state you did not create.
- `unreal.AutomationLibrary.take_high_res_screenshot` writes nothing while the viewport is not redrawing; use `Tools/capture_viewport.py`.
- Python's `urllib` gets an empty body from the MCP server; `http.client` works.

## Rules
- Save assets after modifying them; put throwaway test content in `/Game/_Sandbox`.
- Never put API keys or tokens in project files.
- Editing `.uproject` while the editor runs takes effect only after an editor restart, and toggling plugins in the editor UI rewrites that file.
- Only save `/Game/Tracking/LiveLinkMoverseMRLab` when the Moverse plugin is loaded; without it the Moverse source inside the preset is lost.
