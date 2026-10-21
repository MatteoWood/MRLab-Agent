# MRLabProject 5.8

MetaHuman conversational agent for the TU Wien MRLab curved LED wall (nDisplay). Engine: UE 5.8 at `C:\Program Files\Epic Games\UE_5.8`. Blueprint-only so far (no `Source/`). Repo: https://github.com/MatteoWood/MRLab-Agent (Git LFS for binaries). Knowledge base for RAG lives separately: https://gitlab.tuwien.ac.at/mixed-reality-labor/mrlab-agent-knowledge

## How to work on the editor
The editor must be open for channels A and B.

- **A. UE MCP server** (`unreal-mcp` in `.mcp.json`, `http://127.0.0.1:8000/mcp`). Built-in ModelContextProtocol + EditorToolset plugins. Three meta-tools: `list_toolsets`, `describe_toolset`, `call_tool`. Use it for assets, actors, Blueprints (nodes, pins, variables, graph DSL), materials, object properties, viewport screenshots (`EditorToolset.EditorAppToolset` CaptureViewport), output log (`EditorToolset.LogsToolset` GetLogEntries), PIE start/stop, config sections (ConfigSettingsToolset), editor UI automation (SlateInspectorToolset), Live Coding.
  - Pass every argument a tool lists, even ones with defaults (e.g. `GetLogEntries` needs `pattern`, `CaptureViewport` needs `captureTransform` and `annotations`), or the call is rejected.
  - Do not call `CaptureViewport` through MCP: it returns the PNG as base64 text. Run `python Tools/capture_viewport.py` instead and read `Saved/Screenshots/viewport.png`.
- **B. Python remote execution** for anything the toolsets cannot do (nDisplay, Live Link, MetaHuman, batch scripting): `python Tools/ue_py.py -c "<code>"` or `python Tools/ue_py.py <file.py>`. Full `unreal` module; `import unreal` explicitly in each snippet.
- **C. Files**: `Config/*.ini`, `MRLabProject58.uproject`, `Content/Python`, logs in `Saved/Logs/MRLabProject58.log`. `.uasset`/`.umap` are binary, never edit them as files.

## Rules
- Pull before editing, commit each working step, push when done.
- Save assets after modifying them; put throwaway test content in `/Game/_Sandbox`.
- Never put API keys or tokens in tracked files.
- Editing `.uproject` while the editor runs takes effect only after an editor restart, and toggling plugins in the editor UI rewrites that file.
