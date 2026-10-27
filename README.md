# MRLab Agent

Conversational MetaHuman agent for the curved LED wall of the TU Wien Mixed Reality Lab (MRLab, Vienna).
Unreal Engine 5.8 project: `MRLabProject58.uproject`.

This README is the handoff document. Anyone (person or AI agent) continuing the work starts here, then reads the local `CLAUDE.md` of the machine they work on for how to operate the editor. `CLAUDE.md` is not tracked in Git: each machine keeps its own (see section 2). Keep sections 4 (current state), 6 (open questions), 7 (decisions) and 8 (work log) up to date at the end of every work session.

## Contents
1. [Goals](#1-goals)
2. [Working agreements](#2-working-agreements)
3. [Environment](#3-environment)
4. [Current state](#4-current-state)
5. [Roadmap](#5-roadmap)
6. [Open questions and TODO](#6-open-questions-and-todo)
7. [Decisions log](#7-decisions-log)
8. [Work log](#8-work-log)

---

## 1. Goals

As stated by the project owner (Matteo Bosco). Wording kept close to the original requests.

| # | Goal | Details |
|---|---|---|
| G1 | Conversational agent | An agent that can interact with a user. It lives on the MRLab curved LED wall, which works through the nDisplay plugin. |
| G2 | Language model | OpenAI `gpt-live-1`: https://developers.openai.com/api/docs/models/gpt-live-1 |
| G3 | Knowledge (RAG) | RAG over custom Markdown files from https://gitlab.tuwien.ac.at/mixed-reality-labor/mrlab-agent-knowledge. Currently 2 test files; it will contain one file per lab system, so the agent knows everything about the lab and can answer user questions. |
| G3a | Realtime RAG in UE | Realtime RAG inside Unreal Engine is "crucial". A previous prototype proved it is possible: `C:\Users\bosco\Desktop\VSCode Projects\realtime_rag`. The owner thinks a better approach may exist now and does not know yet whether the gpt-live-1 API allows a simpler, more effective approach than tokenizing the dataset themselves every time it changes. |
| G3b | Robust to dataset changes | The dataset lives in its own GitLab repo and changes over time. The agent framework must stay solid when it changes, for example through an "update dataset" function. |
| G4 | Gaze | Use the Moverse tracking system so the agent follows the user with its gaze. |
| G5 | Vision | Use the frontal camera on top of the wall (the owner listed it under the Moverse system) so the agent can "see" the user and answer questions such as "what color is my shirt" or "in which pose am I now". |
| G6 | Natural behaviour (LAST step) | Natural lip sync and natural movements: movements while talking, body language adapted to what it says, facial microexpressions. The owner expects MetaHuman to give a high degree of realism. This is the last step, after the rest of the framework is up and working. Lip sync work was started earlier (see 4.5). |
| G7 | Stereo 3D | The LED wall shows 3D through polarization. Its settings must work in the 5.8 project. |

## 2. Working agreements

- One step at a time. Before starting a step, a precise plan for that step is written and agreed with the owner.
- Items in section 6 are not decided. Do not decide them; ask the owner.
- Development happens on the owner's laptop now. The project moves to the lab rendering PC later. This repo is the bridge between the two machines.
- Version control is this GitHub repo (public, Git LFS for binaries). GitLab was too small for the project. The knowledge base stays in its own GitLab repo.
- AI tooling is Claude Code. Codex is no longer used.
- The repo is public. Never write IP addresses, ports, hostnames or credentials of lab machines in tracked files (README, config, scripts, commit messages). Keep them in each machine's local `CLAUDE.md`.
- `CLAUDE.md` (agent instructions) is machine-specific and ignored by Git. The laptop version includes committing and pushing to GitHub. The lab PC has no push credentials for GitHub, so its version has no GitHub steps. Both files exist only locally on their machine (laptop: `C:\Users\bosco\Documents\Unreal Projects\MRLabProject 5.8\CLAUDE.md`; lab PC: `CLAUDE.md` in its clone, created on 2026-10-21 from the former `CLAUDE.lab.md`, commit `8ea546d`).

## 3. Environment

### 3.1 Lab hardware

| Item | Known facts | Source |
|---|---|---|
| LED wall | Curved. Driven by nDisplay. Native 2560x1536 pixels over 499.9 cm (along the curve) x 300 cm, i.e. 5.12 px/cm in both directions. Passive stereo 3D: the polarization alternates per pixel in a checkerboard, viewed with passive polarized glasses. | Owner, mesh, 2026-10-21 test |
| LED processor | Colorlight Z8t ("Z8t DP" = Windows `DISPLAY2`, "Z8t HDMI" = `DISPLAY3`). In its current mode it shows only the DP input, 1:1, as a 2D image; the HDMI input is not shown. Its 3D settings were not changed (hardware, outside the project). A config backup from 2025-10-15 is on the lab PC desktop (`coloradeptbackup20251015.capf`). | Lab PC, 2026-10-21 test |
| LED wall mesh in this project | `/Game/Assets/LEDWall`: 494 cm wide, 300 cm high, 30 cm curve depth, 20 x 12 panels. Imported from `C:\Users\bosco\Desktop\MRLab model\LEDWall.fbx`. Each panel has its own 0..1 UVs, so it cannot be used for nDisplay mesh projection. `/Game/Assets/LEDWall_nDisplay` is a copy with one UV layout over the whole wall (u = arc length, v = top to bottom), used for the projection (D20). | Asset |
| Moverse tracking | Markerless. 8 Luxonis OAK-D Pro W PoE cameras in a circle at the ceiling, covering the LED wall area. Tracking zone 5 m x 8 m, up to 4 users, 50 or 60 Hz. Tracking PC (server room) runs the Moverse capture software and sends data to the rendering PC. Calibrate every session (about 2 min). Tracking gets worse in dark lighting or with dark clothes. | `C:\Users\bosco\Downloads\Moverse-Tracking-System Kopie.md` |
| Moverse network endpoint | Live Link source address and port of the Tracking PC: kept only in each machine's local `CLAUDE.md` (rule in section 2). UDP, bound on the rendering PC; only one process on the PC receives the data. | Lab preset `LiveLinkMoverseMRLab`, plugin source |
| Moverse coordinates | Head bone `moverserig_Head` in cm; after the axis conversion in `NDC_Basic` (4.4): +X towards the wall, Z = height above the floor. Measured 2026-10-21: middle of the wall surface at tracking (309, 16). | Calibration run (4.4) |
| Frontal camera on top of the wall | Mentioned by the owner for vision (G5). Model, connection and access method unknown. | Owner |
| Lab rendering PC | Ran the 5.7 lab project through Switchboard as nDisplay node `Node_0` (host: the rendering PC itself, fullscreen 2560x1536). Now runs UE 5.8. Displays: `DISPLAY2` 2560x1536 at (0, 0), primary, Z8t DP (the wall); `DISPLAY3` 2560x1536 at (2560, 0), Z8t HDMI; `DISPLAY1` 1920x1080 at (5120, 0), operator monitor. | Lab logs, owner, Windows |
| Engine modification on the lab PC | Someone in the lab edited nDisplay's output remap shader in the engine installs: `UE_5.8\Engine\Plugins\Runtime\nDisplay\Shaders\Private\OutputRemapShaders.usf` (2026-09-16, original kept as `OutputRemapShadersBACKUP.usf`) and the 5.7 equivalent (2026-04-09). For source pixels with x < 2560 it samples at 2560 - x and discards every other pixel in a checkerboard; pixels with x >= 2560 pass unchanged. The 3D output of this project depends on it (4.3). The laptop's engine is unmodified (checked 2026-10-27: no backup copy, same install date as the other nDisplay shaders). | Lab PC files |

### 3.2 Machines

| Machine | Role | Notes |
|---|---|---|
| Owner laptop | Development now | UE 5.8 at `C:\Program Files\Epic Games\UE_5.8`, Visual Studio 2022 17.14, Git + Git LFS, Python (Anaconda). No Moverse plugin. |
| Lab rendering PC | Target | UE 5.8 at `C:\Program Files\Epic Games\UE_5.8`. No Python on PATH (use the engine's bundled Python). In the 5.7 setup the Moverse plugin was installed in the engine (`Engine/Plugins/Marketplace/MoversePlugin`, plus a duplicate under `Engine/Plugins/Runtime/Marketplace/MoversePlugin`). For 5.8 the plugin is a project plugin in `Plugins/MoversePlugin`, not in Git (D15). Read-only Git access (cannot push, Q19). |

### 3.3 Repositories and paths

| What | Where |
|---|---|
| This project | https://github.com/MatteoWood/MRLab-Agent (branch `main`), local `C:\Users\bosco\Documents\Unreal Projects\MRLabProject 5.8` (laptop), `C:\Users\VR Group\Documents\Unreal Projects\Matteo\MRLab-Agent` (lab PC) |
| Moverse plugin, UE 5.8 build | `C:\Users\VR Group\Documents\Unreal Projects\Matteo\MoversePlugin_UE5.8_v1.0.zip` (lab PC). Prebuilt binaries match the UE 5.8 engine build ID. |
| 5.7 lab project on the lab PC | `C:\Users\VR Group\Documents\Unreal Projects\Matteo\Frank Demo 5.7 (old)`. Its Moverse plugin is the one in the UE 5.7 engine. |
| Knowledge base | https://gitlab.tuwien.ac.at/mixed-reality-labor/mrlab-agent-knowledge |
| Earlier RAG prototype | `C:\Users\bosco\Desktop\VSCode Projects\realtime_rag` (`mrlab_rag.py`, `realtime_lab_chat.py`, `MRLab_knowledge/`, `requirements.txt`, `.env`). Not reviewed yet. |
| 5.7 lab project, latest (2026-07-07) | `C:\Users\bosco\Desktop\Frank Demo.zip`. Source of the port in Step 2. Does not contain the Moverse plugin. |
| 5.7 lab project, June snapshot (2026-06-16) | `C:\Users\bosco\Documents\Unreal Projects\mrlab-project-frank` (GitLab `matteo.bosco/mrlab-project-frank`). Older than the zip. |

## 4. Current state

State on 2026-10-27: the lab PC changes of 2026-10-21 are now in the repo (section 8). On the lab PC the wall runs head-tracked stereo 3D with live Moverse tracking (verified by the owner on 2026-10-21).

### 4.1 Project setup
- Blueprint-only (no `Source/` folder). Not decided whether C++ will be needed (see Q9).
- Main level: `/Game/DefaultMap` (World Partition).
- Plugins enabled in `MRLabProject58.uproject`: MetaHuman set (MetaHuman, MetaHumanCalibrationProcessing, MetaHumanCoreTech, MetaHumanLiveLink, MetaHumanCharacter), MovieRenderPipeline, NVIDIA ACE (NV_ACE_Reference, NvAudio2FaceClaire, NvAudio2FaceJames, NvAudio2FaceMark), nDisplay, DisplayClusterLaunch, Switchboard, ModelingToolsEditorMode, editor AI tooling (ModelContextProtocol, EditorToolset, Terminal, ConfigSettingsToolset, SlateInspectorToolset, LiveCodingToolset), and `MoversePlugin` marked `"Optional": true` (D10).
- Optional plugins in UE 5.8: in a Blueprint-only project on the Launcher engine, an optional plugin is only loaded if it is in the engine's build receipt (`Engine/Binaries/Win64/UnrealEditor.target`) or passed on the command line. So `MoversePlugin` is skipped silently even when installed, unless the process starts with `-EnablePlugins=MoversePlugin` (D16, Q20).
- Config: `DefaultEngine.ini` enables Python remote execution (`bRemoteExecution=True`). `DefaultGame.ini` holds the Live Link settings copied from the lab project. `DefaultDisplayClusterLaunch.ini` (new, lab PC) holds the nDisplay Launch arguments, including `EnablePlugins=MoversePlugin`. `Config/nDisplay/StereoCheckerboardRemap.obj` (new, lab PC) is the nDisplay output remap mesh for the 3D output (4.3).

### 4.2 Level contents (`DefaultMap`)

| Actor | Class | Notes |
|---|---|---|
| `MRLab` | StaticMeshActor | Lab room model, the virtual extension of the real lab behind the wall. Inside: y -270..270, z 0..319, back wall at x=-638, open at the front (x=50). Its emissive materials `M_LightsCold` and `M_LightsWarm` are the only light sources of the scene. |
| `LEDWall` | StaticMeshActor | LED wall model, surface at x 10..40, inside the room's opening. Hidden in game (D23): it sits exactly on the projection surface. |
| `BP_Agent` | `BP_Agent_C` | The MetaHuman agent (see 4.5), at x=-220, about 2.4 m behind the wall |
| `NDC_Basic` | `NDC_Basic_C` | nDisplay config ported from the lab, at (319, 16, 10), yaw 180. Its origin is the Moverse tracking origin (see 4.3, 4.4). |
| `NDC_HD_02` | `NDC_HD_02_C` | Older nDisplay config of this project, at (300, -60, 100), yaw -170 (Q4) |
| `PPV_FixedExposure` | PostProcessVolume | New. Unbound; auto exposure locked at -2.9 EV100 (min = max). See 4.7. |
| `Walking` | LevelSequenceActor | Plays `/Game/MetaHumans/Animations/Walking` |
| `SpotLight` | SpotLight | At (260, 0, 280). Switched off (light component not visible), so only the emissive lab lights light the scene (D22). |
| `PlayerStart` | | |

The lab level also had SkyLight, DirectionalLight, SkyAtmosphere, VolumetricCloud and ExponentialHeightFog. These were not ported (see Q8).

### 4.3 nDisplay

| | `NDC_Basic` (ported from the lab) | `NDC_HD_02` (pre-existing) |
|---|---|---|
| Asset | `/Game/ExampleConfigs/NDC_Basic` | `/Game/NDC_HD_02` |
| Cluster | 1 node `Node_0` on the rendering PC itself, windowed (borderless) 5120x1536 at (0, 0), spanning `DISPLAY2` and `DISPLAY3` | 1 node, 1920x1080 |
| Viewports | `VP_1` = left eye (camera `ViewPointL`) at (0, 0, 2560, 1536); `VP_0` = right eye (camera `ViewPointR`) at (2560, 0, 2560, 1536). Viewport remap off. | 1 viewport, `DefaultViewPoint` |
| Projection | Mesh policy on component `LEDWALL`, mesh `/Game/Assets/LEDWall_nDisplay` (D20) | Simple policy on a flat screen |
| Output remap | On: external file `Config/nDisplay/StereoCheckerboardRemap.obj` (3D, see below) | Off |
| Inner frustum cameras | `ICVFXCameraL`, `ICVFXCameraR` present; inner frustums disabled at stage level | None |
| Tracking | Yes (see 4.4) | No |

Details of `NDC_Basic`:
- Components: `nDisplayXform` local (279, 16, 150), the measured wall position in tracking space (4.4); `LEDWALL` local (0, 0, -150), yaw 180, scale 1 (D8); `Rig` local (0, 0, 50), moved by the tracking at runtime; `ViewPointL` at `Rig` local (0, -3.2, 0) and `ViewPointR` at (0, 3.2, 0), i.e. 6.4 cm between the eyes, stereo offset None.
- World placement: the `LEDWALL` surface is at x 10..40, y -247..247, z 10..310, exactly on the `LEDWall` model actor and inside the room's open front (Q3 answered, D21). Every view through the wall therefore stays inside the virtual room.
- The placed `NDC_Basic` actor keeps its own copy of the nDisplay config. Changes to the Blueprint's config (window, viewports, output remap, stage settings) do not reach it; both were changed and saved.
- Launch: editor toolbar, nDisplay Launch, config `NDC_Basic`, node `Node_0` (D17). Arguments come from `Config/DefaultDisplayClusterLaunch.ini` (same as the 5.7 Switchboard launch, including `-dc_dev_mono`, plus `-EnablePlugins=MoversePlugin`). Play-In-Editor does not render through nDisplay: it shows the normal player camera, without tracking-driven view or 3D.
- Head-tracked view: the mesh projection computes the frustum from each eye through the wall, so the wall's edges always match the virtual room and the view widens as the user walks closer.
- 3D (D19): the frame holds the left eye at x 0..2559 and the right eye at x 2560..5119. The output remap mesh draws the right eye over the DP half, then the left eye on top with reversed u; the lab's modified engine shader (3.1) mirrors it back and keeps every other pixel. Result on DP: a per-pixel checkerboard of both eyes, which the polarized wall separates. The HDMI half shows the right eye and is ignored by the processor. Verified 2026-10-21 with a red/green per-eye tint: each eye saw only its own colour through the glasses. If the engine shader is restored to the original, the DP output becomes a mirrored left eye and the 3D breaks (Q21).
- History: in all lab runs the node was launched with `-dc_dev_mono`. The 5.7 configs overlapped both eye viewports with a flipped `VP_1`, made for an earlier version of the same shader hack. The June lab version had eye cameras at y = -3 / +3 cm on a flat 500x300 cm screen.
- Lab crash history: 20 of the 23 crash reports in the 5.7 lab project were GPU crashes ("GPU Crashed or D3D Device Removed"), on 2026-06-16 and 2026-07-07 (see Q7). No crash during the 2026-10-21 runs.

### 4.4 Moverse integration
- Plugin on the lab PC: the UE 5.8 build (3.3) is installed as a project plugin in `Plugins/MoversePlugin` (D15), not in the engine and not in Git (excluded locally through `.git/info/exclude`). Its module type was changed from `Editor` to `Runtime` with loading phase `PreDefault`, as in the 5.7 build; an `Editor` module does not load in nDisplay nodes, which run with `-game`. It loads only with `-EnablePlugins=MoversePlugin` (4.1): nDisplay Launch passes it; the editor itself does not load it unless started with that flag.
- Live Link preset `/Game/Tracking/LiveLinkMoverseMRLab`: Moverse source (Tracking PC address in the local `CLAUDE.md`), subject `Actor0` (animation role). It also contains an Apple ARKit Live Link source from the lab project. The lab PC did not change it (byte-identical in the lab copy of 2026-10-21). It must not be re-saved in an editor session without the Moverse plugin loaded, or the Moverse source is lost.
- `NDC_Basic` BeginPlay calls `ApplyToClient` on its variable `MoversePreset` (default: the preset above), so the Moverse source is set up at start. In the lab this was done by the level Blueprint (decision D9).
- Head tracking in `NDC_Basic`: on `OnLiveLinkUpdated` of its `LiveLinkComponentController`, it reads bone `moverserig_Head` of subject `Actor0`, converts the location (x, y, z) to (z, -x, -y), and sets it as the relative location of `Rig`. The eye cameras follow `Rig`. A PrintString logs the position every frame ("INVALID" while no frame arrives); in nDisplay nodes it only goes to `Saved/Logs/Node_0.log`.
- Only one process on the PC receives the Moverse data (UDP). If the editor has applied the preset (for example after PIE with the plugin loaded), clear it with the console command `LiveLink.Preset.Clear` before launching nDisplay.
- Calibration (2026-10-21, D21): the owner stood with the head about 50 cm in front of the middle of the wall, then stepped 2 m straight back. Measured head positions: (259, 16, 155) and (58.5, 2, 159); distance 200.5 cm, so units and direction are right. Middle of the wall surface in tracking space: (309, 16). The `NDC_Basic` origin is the tracking origin; the wall is placed at the measured position. Not applied: the offset from the head bone to the eyes (about 8 cm forward), and a possible small rotation (Y changed by 14 cm over the 2 m step, which may also be the step not being straight) (Q23).
- `/Game/Actor0/`: Moverse rig skeletal mesh (`asset`), skeleton, physics asset and AnimBlueprint (`asset_Animation`). Bones are named `moverserig_*`.
- Tested on the laptop (2026-10-21): assets load, `NDC_Basic` compiles, a Simulate session runs BeginPlay and the tracking callback. Applying the preset fails on the laptop ("Could not apply") because the Moverse plugin is missing there.
- Tested on the lab PC (2026-10-21): plugin loads, preset applies, `Actor0` is connected, and the head position drives the view on the wall at runtime (verified by the owner).

### 4.5 Agent (`/Game/MetaHumans/Agent/BP_Agent`)
- MetaHuman character asset `/Game/MetaHumans/Agent`, with body, face, grooms and clothing under `/Game/MetaHumans/Agent/`.
- Components include `ACEAudioCurveSourceComponent` (NVIDIA ACE Audio2Face), `MetaHumanComponentUE`, grooms, LODSync.
- Event graph: BeginPlay enables input for player controller 0. OnAnimInitialized (Face, Body) runs the standard MetaHuman `LiveLinkSetup`. A keyboard event `T` exists; when read as text it showed no attached nodes (not confirmed in the Blueprint editor).
- Test audio: `/Game/Audio/test_audio`.
- No conversation, RAG, tracking-driven behaviour, vision or UI yet.
- On 2026-10-21 the editor showed `BP_Agent` as modified but unsaved, without anyone editing it in that session. It was left unsaved.

### 4.6 Tooling for AI agents
Described in each machine's local `CLAUDE.md`: UE's built-in MCP server (`.mcp.json`), Python remote execution (`Tools/ue_py.py`), viewport capture (`Tools/capture_viewport.py`), and direct file access.
- Lab PC: the MCP server auto-start is enabled (Q6 answered, D18). `CLAUDE.md` was created from `CLAUDE.lab.md`, with a mandatory rule from the owner: nothing outside `C:\Users\VR Group\Documents\Unreal Projects\Matteo\` may be changed (D24).
- Lab PC: `Tools/capture_viewport.py` fails there (the MCP server answers with plain JSON; the script expects a streamed reply). Calling `CaptureViewport` through another MCP client works.

### 4.7 Lighting and exposure
- Light sources: only the emissive materials of the `MRLab` model (`M_LightsCold`, `M_LightsWarm`), as the owner asked; `SpotLight` is switched off (D22).
- Exposure: `PPV_FixedExposure` locks auto exposure at -2.9 EV100 for the editor, PIE and nDisplay. Before, each eye's viewport adapted on its own, so the brightness and colour changed with the user's position. -2.9 was chosen by matching the average brightness of the previous automatic exposure in the room; each +1 halves the brightness.
- Known remaining effects: the bounce light from the emissive materials (Lumen) is computed per view and may still change slightly with the viewer's position; a pale, noisy silhouette of the agent appears on the back wall in editor captures (Lumen artifact, not investigated) (Q22).

## 5. Roadmap

Generic steps. A precise plan is written and agreed before each step starts (section 2). The order of Steps 3 to 7 is not decided. Step 8 is fixed as the last step.

### Step 1. Editor connection and version control: DONE
- Result: Claude Code operates the editor through MCP, Python remote execution and files. The project is in Git with LFS on GitHub.

### Step 2. Port the lab setup (Moverse and nDisplay) from the 5.7 lab project: DONE
- Result: see 4.3 and 4.4. The 5.8 LED wall mesh was kept for the model; a copy with whole-wall UVs is used for the projection (D20).
- Validated on the lab PC as part of Step 3.

### Step 3. Lab PC setup and validation: DONE (2026-10-21 on the lab PC, in the repo since 2026-10-27)
- Goal: the project runs on the lab rendering PC with nDisplay stereo on the wall and live Moverse tracking.
- Result: head-tracked stereo 3D on the wall with live Moverse tracking, launched from the editor with nDisplay Launch (4.3, 4.4, 4.7). Verified by the owner.
- Remaining: a regular way to get lab PC changes into the repo (Q19); Moverse plugin long term (Q20); decide on the engine shader dependency (Q21); lighting stability and eye offset fine-tuning (Q22, Q23); Q4, Q7, Q8.

### Step 4. Conversation with gpt-live-1: TODO
- Goal: the agent holds a spoken conversation with a user through OpenAI `gpt-live-1` (G1, G2).
- Known inputs: model docs link (G2). No integration exists yet.
- Open: Q9, Q10, Q11.
- Detailed plan: not written yet.

### Step 5. Knowledge base and realtime RAG: TODO
- Goal: the agent answers questions about the lab from the GitLab knowledge base, in real time, and survives dataset changes (G3, G3a, G3b).
- Known inputs: knowledge repo, earlier prototype `realtime_rag`.
- Open: Q12, Q13, Q14.
- Detailed plan: not written yet.

### Step 6. Gaze following: TODO
- Goal: the agent follows the user with its gaze using Moverse (G4).
- Known inputs: Moverse subject `Actor0`, head bone `moverserig_Head`, axis conversion used in `NDC_Basic` (4.4). The `NDC_Basic` origin is the calibrated tracking origin, so the user's head in world space is the `NDC_Basic` transform applied to the `Rig` location. Up to 4 tracked users (3.1).
- Open: Q15.
- Detailed plan: not written yet.

### Step 7. Vision: TODO
- Goal: the agent can see the user through the frontal camera on top of the wall and answer questions about appearance and pose (G5).
- Known inputs: none beyond the owner's description.
- Open: Q16, Q17.
- Detailed plan: not written yet.

### Step 8. Lip sync and natural behaviour (LAST): TODO
- Goal: natural lip sync, movements while talking, body language matching the content, facial microexpressions (G6).
- Known inputs: NVIDIA ACE Audio2Face plugins enabled, `ACEAudioCurveSourceComponent` on `BP_Agent`, `test_audio`, MetaHuman character (4.5).
- Open: Q18.
- Detailed plan: not written yet.

## 6. Open questions and TODO

Lab and display:
- **Q1.** ANSWERED 2026-10-21: one signal on the DP input, both eyes interleaved per pixel in a checkerboard (4.3, D19).
- **Q2.** ANSWERED 2026-10-21: eye cameras at -3.2 / +3.2 cm under `Rig` (D19).
- **Q3.** ANSWERED 2026-10-21: the projection wall now sits on the `LEDWall` model actor (x 10..40), inside the room's opening; the tracking calibration was kept (D21).
- **Q4.** Keep or remove `NDC_HD_02` from the level?
- **Q5.** ANSWERED 2026-10-21: build from `MoversePlugin_UE5.8_v1.0.zip`, installed as a project plugin on the lab PC (D15).
- **Q6.** ANSWERED 2026-10-21: MCP auto-start enabled on the lab PC (D18).
- **Q7.** GPU crashes seen in the lab (4.3): cause unknown. Check whether they still happen in 5.8 (none in the 2026-10-21 runs).
- **Q8.** Bring over the lab level's sky, sun and fog actors or not? The owner wants the lab model's emissive lights to be the only light sources (D22), which suggests not.
- **Q20.** Moverse plugin long term: keep `"Optional": true` plus the `-EnablePlugins=MoversePlugin` flag (current; the editor needs the flag too for PIE tracking), or remove `"Optional"` and add the plugin to the repo so every machine has it (the laptop would build it from source or get the binaries)?
- **Q21.** The 3D output depends on the lab's edit of the engine's nDisplay shader (3.1), which an engine update or "Verify" would undo, and which the laptop does not have. Keep relying on it, or move the checkerboard into the project (needs a C++ plugin, see Q9)?
- **Q22.** Lighting: is the remaining view dependence of the emissive bounce light acceptable, or should Lumen quality be raised (GPU cost, two eyes at 2560x1536)? Look at the agent silhouette artifact on the back wall.
- **Q23.** Tracking fine-tuning: add the head-bone-to-eye offset (about 8 cm forward) and check for a small rotation between the tracking axes and the wall?

Conversation:
- **Q9.** Will the project need C++ (for example for realtime audio streaming or a WebSocket client), or can it stay Blueprint-only? Not decided.
- **Q10.** How gpt-live-1 is connected from Unreal (transport, audio capture and playback, session handling). Read the model docs first.
- **Q11.** Where the OpenAI API key is stored on each machine. Rule so far: never in tracked files.

Knowledge base:
- **Q12.** RAG approach: does the gpt-live-1 API offer something simpler and more effective than tokenizing the dataset locally on every change? Compare with the `realtime_rag` prototype.
- **Q13.** How and when the dataset is updated from GitLab (manual "update dataset" function, check at startup, other).
- **Q14.** Access to the knowledge repo from the lab PC (credentials, network).

Tracking and vision:
- **Q15.** Which tracked user the agent looks at when several are present.
- **Q16.** Frontal camera: device model, how it connects, and how Unreal or the agent reads its frames.
- **Q17.** Pose questions: answer from camera images, from Moverse skeleton data, or both?

Behaviour:
- **Q18.** Lip sync and animation approach for Step 8 (ACE Audio2Face, MetaHuman features, other). Decide when Step 8 starts.

Process:
- **Q19.** The lab PC can pull from GitHub but cannot push. How do changes made on the lab PC (assets, config, README updates) get back into the repo? Done once on 2026-10-27: the owner zipped the lab project and the laptop merged it (section 8).

## 7. Decisions log

| ID | Date | Decision | By |
|---|---|---|---|
| D1 | 2026-10-21 | Use OpenAI gpt-live-1 as the model. | Owner |
| D2 | 2026-10-21 | Knowledge base stays in its own GitLab repo. | Owner |
| D3 | 2026-10-21 | Lip sync and natural movements are the last step. | Owner |
| D4 | 2026-10-21 | Develop on the laptop now, move to the lab PC later. | Owner |
| D5 | 2026-10-21 | Version control on GitHub `MatteoWood/MRLab-Agent` (GitLab too small). | Owner |
| D6 | 2026-10-21 | Work one step at a time, with a precise plan before each step. | Owner |
| D7 | 2026-10-21 | Port the Moverse and nDisplay setup from the lab project, keeping the 5.8 LED wall mesh. Remove the unused `.codex` folder. | Owner |
| D8 | 2026-10-21 | `NDC_Basic` `LEDWALL` component scale 100 changed to 1. The lab mesh was imported in meters and scaled up; the 5.8 mesh is already in cm. | Claude (follows D7) |
| D9 | 2026-10-21 | Apply the Moverse preset in `NDC_Basic` BeginPlay instead of the level Blueprint. The level Blueprint cannot be edited from Python, and the 5.8 level has none. | Claude |
| D10 | 2026-10-21 | `MoversePlugin` marked optional in the `.uproject`, so the laptop opens the project without it. | Claude |
| D11 | 2026-10-21 | AI editor access through UE's built-in MCP server plus Python remote execution. | Claude (plan approved by owner) |
| D12 | 2026-10-21 | `CLAUDE.md` is per machine and not in Git; the lab PC gets its own version without GitHub steps (it has no push credentials). | Owner |
| D13 | 2026-10-21 | The repo is public: no IP addresses of lab machines in tracked files; they live in each machine's local `CLAUDE.md`. | Owner |
| D14 | 2026-10-21 | Leave the Tracking PC address that remains in Git history and in the binary preset `LiveLinkMoverseMRLab.uasset` as it is: no history rewrite, repo stays public. | Owner |
| D15 | 2026-10-21 | Lab PC: install the Moverse UE 5.8 build as a project plugin (`Plugins/MoversePlugin`), not in the engine; set its module to `Runtime` / `PreDefault` like the 5.7 build so it loads in nDisplay nodes. | Claude (owner asked to try the 5.8 build) |
| D16 | 2026-10-21 | Keep `MoversePlugin` optional for now and load it with `-EnablePlugins=MoversePlugin`, set in the nDisplay Launch arguments (`DefaultDisplayClusterLaunch.ini`). Long-term choice open (Q20). | Claude |
| D17 | 2026-10-21 | Launch the wall from the editor with nDisplay Launch (`NDC_Basic` / `Node_0`), not by hand from the command line. | Owner |
| D18 | 2026-10-21 | MCP server auto-start enabled on the lab PC (per-user setting under `Saved/`). | Owner |
| D19 | 2026-10-21 | Stereo: left eye `VP_1` and right eye `VP_0` side by side in a 5120x1536 window; an output remap mesh (`Config/nDisplay/StereoCheckerboardRemap.obj`) with the lab's modified engine shader turns them into a per-pixel checkerboard on DP. Eye cameras at -3.2 / +3.2 cm. The old horizontal flip on `VP_1` removed. | Claude (owner verified) |
| D20 | 2026-10-21 | Project onto `/Game/Assets/LEDWall_nDisplay`, a copy of the wall mesh with UVs over the whole wall (u = arc length), instead of the per-panel UVs of `LEDWall`. | Claude |
| D21 | 2026-10-21 | `NDC_Basic` origin = Moverse tracking origin, wall placed at the position measured in the calibration run, and the whole setup placed so the projection wall sits on the `LEDWall` model actor (answers Q3). | Claude (from the owner's calibration run; owner confirmed the result) |
| D22 | 2026-10-21 | Only the lab model's emissive materials light the scene; `SpotLight` switched off. Exposure fixed at -2.9 EV100 with `PPV_FixedExposure`. | Owner (emissive only), Claude (exposure value) |
| D23 | 2026-10-21 | `LEDWall` model actor hidden in game: it sits exactly on the projection surface and would cover the view. | Claude |
| D24 | 2026-10-21 | Mandatory rule for AI agents on the lab PC: change nothing outside `C:\Users\VR Group\Documents\Unreal Projects\Matteo\` (reading and temp files are allowed). Written in `CLAUDE.md` / `CLAUDE.lab.md`. | Owner |

## 8. Work log

Newest first. One entry per work session: what was done, what was verified, what is left.

### 2026-10-27 (Claude Code, laptop)
Done:
- Brought the lab PC changes of 2026-10-21 into the repo from the owner's zip of the lab project (`Desktop\MRLab Agent 21-10\MRLabAgent.zip`). Compared every file (outside `Saved/`) with the repo: the 6 changed or new assets and the 2 new config files listed in the lab PC entry below were copied over unchanged. Everything else matches (`.uproject`, other config, other content, `LiveLinkMoverseMRLab`), apart from line endings.
- README: merged the lab version with the laptop commits made after `8ea546d`. Lab decisions D13 to D22 are now D15 to D24 (the laptop had already used D13 and D14). The Tracking PC address, ports and the node's host address from the lab text were removed again (D13). `CLAUDE.lab.md` from the zip was not re-added (the lab PC keeps its own `CLAUDE.md`, D12).
- `Plugins.zip` from the lab (project plugin `MoversePlugin`, NVIDIA ACE plugins, StudioTwin) was not needed: the laptop already has the ACE plugins in its engine, and Moverse stays on the lab PC only (Q20).
Verified on the laptop: the editor opens `DefaultMap` without errors from the new assets; `NDC_Basic` (window 5120x1536, `VP_1` left / `VP_0` right side by side, output remap file set, `LEDWALL` on `LEDWall_nDisplay`, eye cameras at -3.2 / +3.2), `PPV_FixedExposure` (unbound, -2.9 EV100), `SpotLight` (off) and `LEDWall` (hidden in game) match section 4.
Not verified: tracking and 3D (the laptop has no Moverse plugin and an unmodified engine shader, 3.1).
Left: Q19 to Q23, Q4, Q7, Q8.

### 2026-10-21 (Claude Code, lab PC)
Done:
- MCP: the server was not running (auto-start off); enabled auto-start (D18). `CLAUDE.md` created from `CLAUDE.lab.md`, with the owner's rule to change nothing outside the Matteo folder (D24); same rule added to `CLAUDE.lab.md`.
- Moverse: found why it did not load in 5.8 (plugin only in the UE 5.7 engine; `"Optional"` plugins skipped in 5.8, 4.1). Installed the 5.8 build as a project plugin (D15) and added `-EnablePlugins=MoversePlugin` to the nDisplay Launch arguments (D16).
- nDisplay: two eye viewports side by side in a 5120x1536 window, eye offsets, flip removed; projection mesh with whole-wall UVs (D20); `LEDWall` model hidden in game (D23); tracking calibrated from a measurement run and the wall placed on the lab model's wall (D21).
- 3D: found the lab's modified engine shader; added the checkerboard output remap (D19). Diagnosed with a temporary red/green per-eye tint (removed again).
- Lighting: `SpotLight` off, exposure fixed with `PPV_FixedExposure` (D22).
Verified: by the owner on the wall: head-tracked view with matching edges, live tracking, stereo 3D through the polarized glasses.
Not verified: behaviour with several tracked users; long runs (GPU crashes, Q7).
Left: Q19 to Q23, Q4, Q7, Q8.
Changed files on the lab PC (not committed, no push possible from here):
- Modified: `README.md`, `CLAUDE.lab.md`, `Content/ExampleConfigs/NDC_Basic.uasset`, level actors `Content/__ExternalActors__/DefaultMap/8/20/BYDHEQD265B040BKAIZ09D.uasset` (`NDC_Basic`), `.../3/8L/MZS0K667T1Z3EQ8Z1YMELF.uasset` (`LEDWall`), `.../4/6C/72YJRQ3L52RNW3SD9MDBLS.uasset` (`SpotLight`).
- New: `Content/Assets/LEDWall_nDisplay.uasset`, `Content/__ExternalActors__/DefaultMap/A/FO/6WRBYAQF6CXURGN2HUCM5S.uasset` (`PPV_FixedExposure`), `Config/DefaultDisplayClusterLaunch.ini`, `Config/nDisplay/StereoCheckerboardRemap.obj`.
- Not in Git: `CLAUDE.md`, `Plugins/MoversePlugin/` (excluded in `.git/info/exclude`), per-user settings under `Saved/`.

### 2026-10-21 (Claude Code)
- Removed IP addresses from this README and added the rule in section 2 (D13). The address remains in Git history and in the Moverse preset asset; the owner accepted this (D14).
- Stopped tracking `CLAUDE.md` (now in `.gitignore`, each machine keeps its own). Published the lab PC version as `CLAUDE.lab.md`; the owner copied it to `CLAUDE.md` on the lab PC, then `CLAUDE.lab.md` was deleted from the repo.
- Added this README (handoff document) and the session workflow and gotchas in CLAUDE.md.
- `67b75a7` Ported Moverse and nDisplay from `Frank Demo.zip`: preset, `Actor0` rig, `NDC_Basic` and its level actor, Live Link settings, optional Moverse plugin entry. Verified on the laptop: load, compile, Simulate run (4.4). Not verified on the lab PC.
- Compared `Frank Demo.zip` (5.7, 2026-07-07) with this project. Other config files match. Findings are in 4.3 and 4.4.
- `6837592` Connected Claude Code to the editor (MCP, Python remote execution, viewport capture script), enabled three extra toolsets, added CLAUDE.md, removed `.codex`.
- `a81683f` Baseline commit of the project as it was, pushed with Git LFS (about 1.6 GB).
