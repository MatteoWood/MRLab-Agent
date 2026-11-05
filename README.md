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
| G6 | Natural behaviour (LAST step) | Natural lip sync and natural movements: movements while talking, body language adapted to what it says, facial microexpressions. The owner expects MetaHuman to give a high degree of realism. Lip sync was moved ahead (Step 7, D40, 4.11); the natural movements stay the last step (Step 9). |
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
| Moverse network endpoint | Live Link source address and port: kept only in each machine's local `CLAUDE.md` (rule in section 2). The plugin binds this address (UDP) on the PC that runs Unreal, so it is the rendering PC's own address, where the Tracking PC sends the data (from the plugin source); only one process on the PC receives the data. | Lab preset `LiveLinkMoverseMRLab`, plugin source |
| Moverse coordinates | Head bone `moverserig_Head` in cm; after the axis conversion in `NDC_Basic` (4.4): +X towards the wall, Z = height above the floor. Measured 2026-10-21: middle of the wall surface at tracking (309, 16). | Calibration run (4.4) |
| Frontal camera on top of the wall | Mentioned by the owner for vision (G5). Model, connection and access method unknown. | Owner |
| Lab rendering PC | Ran the 5.7 lab project through Switchboard as nDisplay node `Node_0` (host: the rendering PC itself, fullscreen 2560x1536). Now runs UE 5.8. Displays: `DISPLAY2` 2560x1536 at (0, 0), primary, Z8t DP (the wall); `DISPLAY3` 2560x1536 at (2560, 0), Z8t HDMI; `DISPLAY1` 1920x1080 at (5120, 0), operator monitor. | Lab logs, owner, Windows |
| Engine modification on the lab PC | Someone in the lab edited nDisplay's output remap shader in the engine installs: `UE_5.8\Engine\Plugins\Runtime\nDisplay\Shaders\Private\OutputRemapShaders.usf` (2026-09-16, original kept as `OutputRemapShadersBACKUP.usf`) and the 5.7 equivalent (2026-04-09). For source pixels with x < 2560 it samples at 2560 - x and discards every other pixel in a checkerboard; pixels with x >= 2560 pass unchanged. The 3D output of this project depends on it (4.3). The laptop's engine is unmodified (checked 2026-10-27: no backup copy, same install date as the other nDisplay shaders). | Lab PC files |

### 3.2 Machines

| Machine | Role | Notes |
|---|---|---|
| Owner laptop | Development now | UE 5.8 at `C:\Program Files\Epic Games\UE_5.8`, Visual Studio 2022 17.14, Git + Git LFS, Python (Anaconda). Builds the `MRLabLive` plugin (4.8). Moverse plugin copied from the lab PC as a project plugin, not in Git, with one laptop-only change (4.4); local fake tracking script, not in Git (4.4). OpenAI key in `Saved/OpenAIKey.txt` (4.8), GitLab token in `Saved/GitLabToken.txt` (4.9). |
| Lab rendering PC | Target | UE 5.8 at `C:\Program Files\Epic Games\UE_5.8`. No Python on PATH (use the engine's bundled Python). Uses the committed `MRLabLive` DLL; needs its own `Saved/OpenAIKey.txt` and `Saved/GitLabToken.txt` (not there yet). In the 5.7 setup the Moverse plugin was installed in the engine (`Engine/Plugins/Marketplace/MoversePlugin`, plus a duplicate under `Engine/Plugins/Runtime/Marketplace/MoversePlugin`). For 5.8 the plugin is a project plugin in `Plugins/MoversePlugin`, not in Git (D15). Read-only Git access (cannot push, Q19). |

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

State on 2026-11-05: on the lab PC the wall runs head-tracked stereo 3D with live Moverse tracking (verified by the owner on 2026-10-21). On the laptop the agent holds a spoken English conversation through gpt-live-1 (4.8), answers lab questions from the GitLab knowledge base (4.9) and follows the tracked user with its eyes and head (4.10); none of these three is tested on the lab PC yet.

### 4.1 Project setup
- No project `Source/` folder. C++ lives in the project plugin `Plugins/MRLabLive` (4.8, D25). Building it also makes the build tool generate a stub project module and `Binaries/Win64/MRLabProject58Editor.target`; both are ignored by Git and not needed to run.
- Main level: `/Game/DefaultMap` (World Partition).
- Plugins enabled in `MRLabProject58.uproject`: MetaHuman set (MetaHuman, MetaHumanCalibrationProcessing, MetaHumanCoreTech, MetaHumanLiveLink, MetaHumanCharacter), MovieRenderPipeline, NVIDIA ACE (NV_ACE_Reference, NvAudio2FaceClaire, NvAudio2FaceJames, NvAudio2FaceMark), nDisplay, DisplayClusterLaunch, Switchboard, ModelingToolsEditorMode, editor AI tooling (ModelContextProtocol, EditorToolset, Terminal, ConfigSettingsToolset, SlateInspectorToolset, LiveCodingToolset), `MoversePlugin` marked `"Optional": true` (D10), and the project plugin `MRLabLive` (4.8).
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
- Variable `bHeadTracked` on `NDC_Basic` (2026-11-05, for gaze): on the valid path it is true while subject `Actor0` is `Connected` (`GetLiveLinkSubjectState`), on the `Invalid Frame` path false. Live Link keeps returning the last frame after the data stops, so the frame alone does not tell; the subject turns `Unresponsive` after `TimeWithoutFrameToBeConsiderAsInvalid` (0.5 s, `DefaultGame.ini`).
- Laptop observation (2026-11-05): with tracking data flowing, starting Play a second time in the same editor session crashed the editor inside the Moverse plugin (`FMoversePluginSource::HandleReceivedData`, access violation; most likely the receive thread of the replaced source keeps running after the source is deleted). One Play per editor start, or starting the data after Play, avoided it. Not seen on the lab PC so far (Q26).
- Only one process on the PC receives the Moverse data (UDP). If the editor has applied the preset (for example after PIE with the plugin loaded), clear it with the console command `LiveLink.Preset.Clear` before launching nDisplay.
- Calibration (2026-10-21, D21): the owner stood with the head about 50 cm in front of the middle of the wall, then stepped 2 m straight back. Measured head positions: (259, 16, 155) and (58.5, 2, 159); distance 200.5 cm, so units and direction are right. Middle of the wall surface in tracking space: (309, 16). The `NDC_Basic` origin is the tracking origin; the wall is placed at the measured position. Not applied: the offset from the head bone to the eyes (about 8 cm forward), and a possible small rotation (Y changed by 14 cm over the 2 m step, which may also be the step not being straight) (Q23).
- `/Game/Actor0/`: Moverse rig skeletal mesh (`asset`), skeleton, physics asset and AnimBlueprint (`asset_Animation`). Bones are named `moverserig_*`.
- Tested on the laptop (2026-10-21): assets load, `NDC_Basic` compiles, a Simulate session runs BeginPlay and the tracking callback. Applying the preset fails on the laptop ("Could not apply") because the Moverse plugin is missing there.
- Fake tracking on the laptop (2026-10-27): `Tools/moverse_sim.py` (local only, not in Git) sends the packets the plugin reads (JSON over UDP, subject `Actor0`, the 25 `moverserig_*` bones) with the head on a looping path; path parameters at the top of the script. The laptop's copy of the plugin falls back to listening on all local addresses when the preset address does not exist on the machine; the project, the preset and the lab PC are unchanged. How to run it is in the laptop's `CLAUDE.md`.
- Rig axes of the Moverse data (from `/Game/Actor0/asset`): root bone `moverserig_Pivot`, X to the person's left, Y down, Z forward; standing head about 158 cm above the root. The plugin rotates the root bone by +90 degrees about X on arrival.
- Tested on the lab PC (2026-10-21): plugin loads, preset applies, `Actor0` is connected, and the head position drives the view on the wall at runtime (verified by the owner).

### 4.5 Agent (`/Game/MetaHumans/Agent/BP_Agent`)
- MetaHuman character asset `/Game/MetaHumans/Agent`, with body, face, grooms and clothing under `/Game/MetaHumans/Agent/`.
- Components include `MetaHumanComponentUE`, grooms, LODSync. An `ACEAudioCurveSourceComponent` (NVIDIA ACE Audio2Face) sits only on the agent placed in `DefaultMap`, not in the class; it is unused (D43).
- Event graph: BeginPlay enables input for player controller 0. OnAnimInitialized (Face, Body) runs the standard MetaHuman `LiveLinkSetup`. A keyboard event `T` sits next to unconnected ACE test nodes from the 5.7 project (`AnimateCharacterFromWavFileAsync` with a desktop WAV path); unused.
- Lip sync (4.11): function `UpdateLipSync`, called from Event Tick after `UpdateGaze`.
- Test audio: `/Game/Audio/test_audio`.
- Component `LiveSession` (`MRLabLiveSession`, 4.8). BeginPlay (after EnableInput) calls `StartSession`. `OnUserTranscript` and `OnAgentTranscript` go to PrintString with keys `User` / `Agent`, so each side shows one growing line on screen (hidden in nDisplay nodes by `DisableAllScreenMessages`) and in the log.
- Gaze (4.10): functions `InitGaze` (called after `StartSession` at BeginPlay) and `UpdateGaze` (called from Event Tick); variables `NDC`, `HeadTarget`, `EyeTarget`.
- No vision or UI yet.
- On 2026-10-21 the editor showed `BP_Agent` as modified but unsaved, without anyone editing it in that session. It was left unsaved.

### 4.6 Tooling for AI agents
Described in each machine's local `CLAUDE.md`: UE's built-in MCP server (`.mcp.json`), Python remote execution (`Tools/ue_py.py`), viewport capture (`Tools/capture_viewport.py`), and direct file access.
- Lab PC: the MCP server auto-start is enabled (Q6 answered, D18). `CLAUDE.md` was created from `CLAUDE.lab.md`, with a mandatory rule from the owner: nothing outside `C:\Users\VR Group\Documents\Unreal Projects\Matteo\` may be changed (D24).
- Lab PC: `Tools/capture_viewport.py` fails there (the MCP server answers with plain JSON; the script expects a streamed reply). Calling `CaptureViewport` through another MCP client works.

### 4.7 Lighting and exposure
- Light sources: only the emissive materials of the `MRLab` model (`M_LightsCold`, `M_LightsWarm`), as the owner asked; `SpotLight` is switched off (D22).
- Exposure: `PPV_FixedExposure` locks auto exposure at -2.9 EV100 for the editor, PIE and nDisplay. Before, each eye's viewport adapted on its own, so the brightness and colour changed with the user's position. -2.9 was chosen by matching the average brightness of the previous automatic exposure in the room; each +1 halves the brightness.
- Known remaining effects: the bounce light from the emissive materials (Lumen) is computed per view and may still change slightly with the viewer's position; a pale, noisy silhouette of the agent appears on the back wall in editor captures (Lumen artifact, not investigated) (Q22).

### 4.8 Conversation (`Plugins/MRLabLive`)
- C++ project plugin, one Runtime module, Win64 only (D25). Source and the built `UnrealEditor-MRLabLive.dll` + `UnrealEditor.modules` are in Git (DLL via LFS, the `.pdb` is not), so the lab PC runs it without a compiler (D27). The DLL only loads in an engine with the same build ID (5.8.0 changelist 55116800 on both machines); after an engine update it must be rebuilt on the laptop and committed again.
- Rebuild (editor closed): `Engine\Build\BatchFiles\Build.bat Development Win64 -Project=<uproject> -TargetType=Editor -NoEngineChanges`.
- Component `UMRLabLiveSession` (`MRLabLive Session` in the Add Component list). Properties `Model` (`gpt-live-1`), `Voice` (`marin`; the agent placed in `DefaultMap` overrides it with `ash`, D39), `Instructions` (set on `BP_Agent`, edit it there; the C++ default is the older plain technician prompt). Prompt on `BP_Agent` since 2026-11-05 (D38): persona Frank, 57, has worked at TU Wien all his life, now the technician of the new lab's LED wall who lives on the wall as a digital human; grumpy, sarcastic, funny, a know-it-all who always adds one more detail, but warm and never insulting; short spoken answers in English, at most one joke per answer; lab facts only from the lab knowledge (4.9), admitting gaps in character; no invented people, departments or dates from his past. `StartSession` / `StopSession`; events `OnUserTranscript`, `OnAgentTranscript` (text of the current utterance so far), `OnSessionClosed` (reason). Log category `LogMRLabLive`; each finished utterance is logged as `User: ...` / `Agent: ...`.
- API key: one line in `Saved/OpenAIKey.txt` on each machine (D26). `Saved/` is ignored by Git, but it is included when the whole project folder is zipped. Without the file the component logs an error and does nothing.
- Live API, as used (verified on 2026-10-27 against the API): WebSocket `wss://api.openai.com/v1/live/sessions`, header `Authorization: Bearer <key>`, first message `session.start` with `model`, `instructions`, `audio.format` (`audio/pcm`, 24000) and `audio.output.voice`; no `delegation`, so the session runs in client delegation mode (the API has no setting to turn delegation off). Mic audio goes up as `session.input_audio.append` (base64 PCM16 mono 24 kHz, sent every frame); the voice comes back as `session.output_audio.delta`, a continuous real-time stream in 100 ms chunks (silence included); the model decides itself when to speak and handles interruptions. Transcripts: `session.input_transcript.delta`, `session.output_transcript.delta`. Sessions expire 2 hours after start (`expires_at`); the component only logs the close, it does not restart (Q25). Price: $0.05 per session minute.
- No delegation (D45): every session gets a fixed rule after `Instructions` and before the lab knowledge, worded as OpenAI's GPT-Live prompting guide recommends for `gpt-live-1`: never generate `<|SpawnThinking|>`, never check, search, look up or use tools, answer only from the lab knowledge and the conversation, say "I don't know" otherwise. If the model still delegates (`session.delegation.created`), the plugin answers at once with `session.commentary.append` (that `delegation_id`, content: nothing can be looked up, answer from the lab knowledge or say you don't know) and logs a warning. Before this, the owner saw Frank delegate once ("just a sec, I'm digging that out"), get no answer and stop. Tested 2026-11-05 with a question outside the knowledge (the lab's quality management system): Frank said he doesn't know; no delegation happened, so the reply path is untested.
- The handshake is refused (403) when the request carries an `Origin` header. Unreal's own WebSocket client (libwebsockets on Windows) always sends one, so the plugin uses the Windows WinHttp WebSocket API instead (D29).
- Microphone: default Windows recording device through `AudioCapture`, mixed to mono and resampled to 24 kHz. No echo cancellation: the agent may hear itself through open speakers (Q24). Voice: a procedural sound wave on an audio component attached to the agent (2D, no attenuation), held back by 0.12 s for lip sync (4.11).
- Tested on the laptop (2026-10-27), with a spoken question played through the laptop speakers into the laptop microphone: in Play-In-Editor and in an nDisplay node (`NDC_Basic` / `Node_0`, `-game`), the session starts, the question is transcribed correctly and the agent answers (transcripts in the logs). Closing the node ends it cleanly. The agent's answer did not come back as user speech in these short tests. Also checked: the editor loads the plugin from the committed DLL with the project's own `Binaries` folder removed, as on the lab PC.

### 4.9 Lab knowledge
- Local copy: `Saved/Knowledge/` on each machine, ignored by Git (D33): the knowledge repo is private and this repo is public, so the files must never be committed here.
- Update: editor toolbar button "Update Knowledge" (right end of the main toolbar), editor only (D31). `Content/Python/init_unreal.py` adds the button at editor start; `Content/Python/mrlab_knowledge.py` downloads the default branch of the knowledge repo as one zip through the GitLab API (header `PRIVATE-TOKEN`), unpacks all `.md` files into `Saved/Knowledge.new/` and then replaces `Saved/Knowledge/`. On any error the old files stay. A message box shows the number of files and the commit, or the error. The editor waits during the download.
- GitLab token: one line in `Saved/GitLabToken.txt` on each machine (D32), read access (`read_api`). Present on the laptop since 2026-10-27; not on the lab PC.
- Use (D30): at every session start the plugin reads all `.md` files in `Saved/Knowledge/` (sorted, subfolders included) and appends them to the instructions, each under `--- Knowledge file: <path> ---`. The log shows the file count and an estimate of the tokens. No search step and no extra cost (gpt-live-1 is billed per minute). Limit: the Live API takes up to 16384 instruction tokens, so the whole knowledge base must stay below about 15000 tokens (roughly 60 KB of Markdown); beyond that the approach must change (Q12 alternatives: local search with injected snippets; OpenAI file search through delegation is ruled out by D45). New files take effect at the next session start (next Play or nDisplay Launch).
- Knowledge repo on 2026-10-27: branch `main`, one file `Moverse-Tracking-System_Kopie.md` (about 800 tokens), commit `e8003aeb`.
- Tested on the laptop (2026-10-27): the update downloads that file and the commit matches the repo; with a recorded question in Play-In-Editor the agent answered "Eight Luxonis OAK-D Pro W PoE cameras" (from the file) and "That I don't know" for a question the knowledge does not cover. The button appears on the toolbar; its command ran through Python remote execution, where the editor suppresses the message box, so the box itself has not been seen yet.

### 4.10 Gaze
- Target (D34): the head of Moverse subject `Actor0`, i.e. world location of `NDC_Basic`'s `Rig`, while `bHeadTracked` (4.4). Otherwise a point 3 m straight out of the face at 172 cm height (the face looks along the actor's right vector, +X in the level), so the agent eases back to straight ahead (D36).
- `BP_Agent.UpdateGaze`: smooths the target with `VInterpTo`, speed 15 for the eyes and 3 for the head, so the eyes lead and the head follows. Writes `HeadTarget` to the body post-process instance and four eye curve values to the face post-process instance.
- Head and neck (D35, D37): `/Game/MetaHumans/Agent/ABP_Agent_Body_PostProcess`, a copy of the MetaHuman `ABP_Body_PostProcess`, set as post-process AnimBP of `SKM_Agent_BodyMesh`. At its start: Local to Component, `Look At` on `neck_02` (alpha 0.3), `Look At` on `head` (alpha 0.6), both with forward axis local +Y, up axis local +X, clamp 45 degrees, target `HeadTarget` in world space; then Component to Local and the original chain. Together the head turns about 70 % of the way. The face copies the body pose, so the face turns with it.
- Eyes (D35, D37): `/Game/MetaHumans/Agent/ABP_Agent_Face_PostProcess`, a copy of `ABP_Face_PostProcess`, set on `SKM_Agent_FaceMesh`. A `Modify Curve` node (Blend, alpha 1) before RigLogic sets `CTRL_expressions_eyeLook{Left,Right,Up,Down}{L,R}` from the variables `EyeLookLeft/Right/Up/Down` (same value for both eyes), so RigLogic moves eyes and lids. `UpdateGaze` computes the eye target direction in the head bone's space (X up, Y forward, Z to the agent's right) and divides by the measured eye rotation per curve unit: 40 degrees sideways (37.5 / 42.3 for the two eyes), 29.7 up, 39.9 down; clamped to 0..1.
- The MetaHuman `Common` AnimBPs are unchanged; only the agent's own meshes point to the copies.
- Tested on the laptop (2026-11-05) with fake Moverse data (head moving 2 m to each side and 0.8 m forward/back, 4 to 5 m from the agent): eye direction within 0.4 to 3.2 degrees of the user's head; head turning about two thirds of the angle with a small lag; after the data stops, `bHeadTracked` turns false and head and eyes are back to straight ahead (0 degrees) within about 3 s. Screenshots from the user's line of sight show the face turned to the viewer when tracked and turned away when not (not in Git). The conversation session still starts.
- Not tested: real Moverse, the wall, the nDisplay node (its config file had to be regenerated by nDisplay Launch, which was not used), how natural it looks to a person. Known limits: the head-bone-to-eye offset of the user (Q23) is not applied (about 1 to 1.5 degrees at 3 to 5 m); both eyes get the same rotation (no convergence); the face is dark under the current lighting (Q22).

### 4.11 Lip sync
- Method (D41, D42): Epic's real-time speech-to-face model from UE 5.8 (`/StreamingADA/xsada_face_base_fp32_v2_0_0`, the model of `FSpeechAnimationSolverV4` in module `SpeechAnimationSolver`, hidden engine plugin `StreamingADA`, enabled through `MetaHumanCoreTech`; the same model as MetaHuman's audio Live Link source). Lookahead 80 ms, mood auto-detected from the voice. Output: the 251 MetaHuman face controls (`CTRL_expressions_*`): jaw, lips, tongue, cheeks, brows, blinks (D42). No head motion.
- Code (`MRLabLive`, 4.8): every voice chunk from the Live API is queued into the voice wave and handed to a lip sync thread (`FLipSync`): resampled to 16 kHz; every 20 ms the model's 1 s input window slides on and the model runs once (NNE, CPU backend `NNERuntimeORTCpu`), with the same inputs and state as `FSpeechAnimationSolverV4`; the 81 outputs are converted to the 251 controls with `GuiToRawControlsUtils`; each frame is tagged with the voice sample it belongs to (newest sample minus the lookahead). Each tick the component takes the frame for the sample now playing (queued samples minus those still waiting in the wave), interpolates, and exposes it as `LipSyncCurves` (Blueprint read-only map).
- Why CPU and why not Epic's solver class (D46): on D3D12, NNE runs the GPU backend (DirectML) on the renderer's own command queue (`NNERuntimeORTUtils.cpp`), so each model run waits behind the frames: 5 to 8 ms with light rendering, 35 ms in the owner's session, 617 ms with heavy rendering (screen percentage 250). The CPU backend does not depend on rendering (about 17 ms per run on the laptop, light or heavy rendering). Epic's solver class restarts its context whenever a step is dropped, and every restart makes the face blink (75 to 85 blinks a minute when steps were dropped, the "blinking too often" the owner saw); running the model directly lets a late step skip only the model run while its audio still enters the input window.
- Voice delay: 0.12 s of silence (lookahead + 40 ms margin) is put in front of the voice at the start of a stream and whenever the voice wave runs dry, so each frame is solved before its sound plays.
- Mouth closed in silence (D44): the Live API sends exact zeros between answers. Each 20 ms step counts as voice above RMS 0.003; the jaw, mouth, tongue and teeth controls are multiplied by a weight that rises within about 60 ms when voice is within the lookahead window and falls to 0 over about 0.3 s after it. At 0 the MetaHuman mouth is closed; blinks and brows are not affected. Measured: mouth controls exactly 0 from 0.4 s after the voice stops.
- Overload: a step whose moment is already playing skips the model run (its audio stays in the window, the model state stays), so the mouth stays in sync, only with fewer frames. The log line at the end of a session reports model runs, average and maximum run time, and skipped steps.
- Face: `BP_Agent.UpdateLipSync` copies `LiveSession.LipSyncCurves` into the variable `LipSyncCurves` of `ABP_Agent_Face_PostProcess`; there a `Modify Curve` node (Blend, alpha 1, `Curve Map` pin) sets them right before the eye-look `Modify Curve` (4.10), so gaze still controls eye direction (the solver's eye-look values are 0 and get overwritten). The face post-process now updates on the game thread (`Use Multi Threaded Animation Update` off): with it on, the map was read by a worker thread while the Blueprint replaced it, which froze the game for seconds and once crashed the editor (`Corrupt source map`).
- Measured on the laptop (2026-11-05, Play, editor in the foreground, recorded question through the speakers, captured face controls and engine output): normal rendering (49 fps): 16.9 ms per model run, 2 % of steps skipped, 8 blinks a minute, mouth controls 0 in silence, jaw leads the voice by 0.02 s (cross-correlation 0.77). Heavy rendering (screen percentage 250, 14 fps): 16.8 ms per run, 11 % skipped, 5 blinks a minute, jaw within 0.05 s of the voice. With the editor in the background the runs took 27.7 ms (37 % skipped; Windows probably moves a background process to the slower cores, inferred). Starting a session costs one hitch of about 2.4 s (model load, before anyone speaks). Without the silence gate the model kept the jaw slightly open at rest (jaw control about 0.13).
- History: the first version ran Epic's solver class on the GPU. The owner saw the mouth freeze (solver 60 to 106 ms per step) and far too much blinking; both came from the GPU waiting behind rendering and from the context restarts (D46).
- Comparison before the choice (D41): the same recorded Frank answer animated by Epic's model (lookahead 0.08 s and 0.24 s) and by NVIDIA ACE Audio2Face 3.0 (Mark), rendered with the same camera; videos sent to the owner (not in Git). ACE facts found on UE 5.8: its sound-asset input passed pure silence to the model (the WAV-file input works); its component crashed the editor once after an animation ended (`Cast of nullptr to BetterSoundWaveProcedural` in `UACEAudioCurveSourceComponent::TickComponent`); 1.2 to 1.7 s from sending audio to the voice starting (model loaded), plus about 11 s on first use; 52 ARKit shapes mapped to the face, no tongue.

## 5. Roadmap

Generic steps. A precise plan is written and agreed before each step starts (section 2). Step 9 is fixed as the last step. On 2026-11-05 lip sync was moved ahead of vision and split from the natural movements (D40).

### Step 1. Editor connection and version control: DONE
- Result: Claude Code operates the editor through MCP, Python remote execution and files. The project is in Git with LFS on GitHub.

### Step 2. Port the lab setup (Moverse and nDisplay) from the 5.7 lab project: DONE
- Result: see 4.3 and 4.4. The 5.8 LED wall mesh was kept for the model; a copy with whole-wall UVs is used for the projection (D20).
- Validated on the lab PC as part of Step 3.

### Step 3. Lab PC setup and validation: DONE (2026-10-21 on the lab PC, in the repo since 2026-10-27)
- Goal: the project runs on the lab rendering PC with nDisplay stereo on the wall and live Moverse tracking.
- Result: head-tracked stereo 3D on the wall with live Moverse tracking, launched from the editor with nDisplay Launch (4.3, 4.4, 4.7). Verified by the owner.
- Remaining: a regular way to get lab PC changes into the repo (Q19); Moverse plugin long term (Q20); decide on the engine shader dependency (Q21); lighting stability and eye offset fine-tuning (Q22, Q23); Q4, Q7, Q8.

### Step 4. Conversation with gpt-live-1: DONE on the laptop (2026-10-27), lab PC test pending
- Goal: the agent holds a spoken conversation with a user through OpenAI `gpt-live-1` (G1, G2).
- Result: plugin `MRLabLive` and the `LiveSession` component on `BP_Agent` (4.5, 4.8). Tested on the laptop in Play-In-Editor and in an nDisplay node, with recorded speech through the speakers.
- Remaining: a real conversation with a person; the lab PC (key file, microphone and speakers, echo, Q24); session expiry (Q25).

### Step 5. Knowledge base and realtime RAG: DONE on the laptop (2026-10-27), lab PC test pending
- Goal: the agent answers questions about the lab from the GitLab knowledge base, in real time, and survives dataset changes (G3, G3a, G3b).
- Result: "Update Knowledge" editor button downloads the repo into `Saved/Knowledge/`; every session puts all local files into the agent's instructions (4.9, D30 to D33).
- Remaining: lab PC (token file, access to GitLab from its network, Q14); switch approach when the knowledge outgrows the instruction limit (4.9).

### Step 6. Gaze following: DONE on the laptop (2026-11-05), lab PC test pending
- Goal: the agent follows the user with its gaze using Moverse (G4).
- Result: eyes aim at the head-tracked user, head and neck turn part of the way, back to straight ahead when nobody is tracked (4.10, D34 to D37).
- Remaining: test on the wall with real tracking; Q26; eye offset (Q23).

### Step 7. Lip sync: DONE on the laptop (2026-11-05), lab PC test pending
- Goal: natural lip sync from the agent's live voice (part of G6), lip sync only.
- Result: Epic's real-time speech-to-face solver in `MRLabLive`, driving the agent's face controls in sync with the voice (4.11, D40 to D43).
- Remaining: lab PC (GPU load next to the stereo rendering; same engine plugins); a real conversation with a person, including interrupting the agent (not tested); how natural it looks to visitors.

### Step 8. Vision: TODO
- Goal: the agent can see the user through the frontal camera on top of the wall and answer questions about appearance and pose (G5).
- Known inputs: none beyond the owner's description.
- Open: Q16, Q17.
- Detailed plan: not written yet.

### Step 9. Natural behaviour (LAST): TODO
- Goal: movements while talking, body language matching the content, facial microexpressions (G6).
- Known inputs: MetaHuman character (4.5); lip sync (4.11) already moves the face while speaking.
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
- **Q9.** ANSWERED 2026-10-27: C++, in the project plugin `MRLabLive` (D25).
- **Q10.** ANSWERED 2026-10-27: Live API WebSocket from inside Unreal (WinHttp), microphone through `AudioCapture`, voice through a procedural sound wave (4.8, D25, D29).
- **Q11.** ANSWERED 2026-10-27: `Saved/OpenAIKey.txt` on each machine (D26).
- **Q24.** Lab microphone and speakers: which devices does the agent use, and does it hear itself (no echo cancellation)? Fallbacks if it does: mute the mic while the agent speaks (`session.input_audio.mute`, but then visitors cannot interrupt), a directional microphone, or a headset.
- **Q25.** Sessions end after 2 hours (or on network loss). Should the agent start a new session automatically, or on a trigger (for example when a visitor steps in front of the wall)?

Knowledge base:
- **Q12.** ANSWERED 2026-10-27: all local knowledge files go into the session instructions, no retrieval step (D30). Alternatives for when the knowledge outgrows the instruction limit: OpenAI file search through Responses delegation (vector store; passing the store id through the Live API is not confirmed by the docs), or local keyword search with snippets injected through `session.thinking.append` (500 tokens each).
- **Q13.** ANSWERED 2026-10-27: by hand with the editor button "Update Knowledge"; the agent only uses the local copy (D31).
- **Q14.** Access to the knowledge repo from the lab PC: credentials answered (token file, D32); network access from the lab PC to `gitlab.tuwien.ac.at` not tested.

Tracking and vision:
- **Q15.** ANSWERED 2026-11-05: the head-tracked user, subject `Actor0` (D34).
- **Q26.** Moverse plugin crash on the laptop when Play starts again in the same editor session while tracking data flows (4.4). Fix the plugin source (it is in `Plugins/MoversePlugin`, not in Git), ask Moverse, or keep working around it? Check whether the lab PC's build shows the same.
- **Q16.** Frontal camera: device model, how it connects, and how Unreal or the agent reads its frames.
- **Q17.** Pose questions: answer from camera images, from Moverse skeleton data, or both?

Behaviour:
- **Q18.** ANSWERED 2026-11-05: lip sync with Epic's MetaHuman real-time audio solver, after a video comparison with NVIDIA Audio2Face (D41, D43).

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
| D25 | 2026-10-27 | The conversation (connection to OpenAI, microphone, agent voice) runs inside Unreal in a small C++ project plugin, not in an external program. Answers Q9, Q10. | Owner |
| D26 | 2026-10-27 | The OpenAI API key is kept in an untracked file in the project: `Saved/OpenAIKey.txt`. Answers Q11. | Owner (untracked file), Claude (path) |
| D27 | 2026-10-27 | The built plugin DLL is committed to Git (LFS), so the lab PC needs no compiler. | Owner |
| D28 | 2026-10-27 | The agent speaks English only. | Owner |
| D29 | 2026-10-27 | The plugin talks to the Live API through WinHttp instead of the engine's WebSocket module, because the engine's client always sends an `Origin` header and the Live API refuses those handshakes. The plugin is Win64 only. | Claude |
| D30 | 2026-10-27 | Knowledge use: all local knowledge files go into the session instructions at session start, no retrieval step. Answers Q12. | Owner |
| D31 | 2026-10-27 | Knowledge update by hand with an "Update Knowledge" button in the editor toolbar (not needed in the final app); it downloads from GitLab into a local copy, and the agent only uses the local copy. Answers Q13. | Owner |
| D32 | 2026-10-27 | GitLab access through a read-only token in `Saved/GitLabToken.txt` on each machine. | Owner |
| D33 | 2026-10-27 | Local knowledge copy in `Saved/Knowledge/` (ignored by Git, because the knowledge repo is private and this repo is public). Button written in the editor's Python (no C++ for an editor-only tool). | Claude |
| D34 | 2026-11-05 | The agent looks at the head-tracked user, Moverse subject `Actor0`. Answers Q15. | Owner |
| D35 | 2026-11-05 | Gaze uses eyes and head: eyes aim at the user, head and neck turn part of the way, body unchanged. | Owner |
| D36 | 2026-11-05 | When nobody is tracked the agent eases back to looking straight ahead. | Owner |
| D37 | 2026-11-05 | Gaze implemented in agent-specific copies of the MetaHuman post-process AnimBPs (`Common` assets untouched) plus a `bHeadTracked` flag in `NDC_Basic` based on the Live Link subject state. | Claude |
| D38 | 2026-11-05 | Agent persona: Frank, 57, lifelong TU Wien technician, now the LED wall technician of the new MR Lab; funny, sarcastic, a bit grumpy, a know-it-all, but pleasant to talk to. | Owner |
| D39 | 2026-11-05 | Agent voice `ash`. | Owner |
| D40 | 2026-11-05 | Lip sync now (Step 7), vision later (Step 8); lip sync only, the other natural movements stay the last step (Step 9). Changes D3. | Owner |
| D41 | 2026-11-05 | Compare Epic's MetaHuman audio solver and NVIDIA Audio2Face on the same recorded answer before choosing; then Epic's MetaHuman audio chosen (answers Q18). | Owner |
| D42 | 2026-11-05 | Lip sync moves the whole speech face (jaw, lips, tongue, cheeks, brows, blinks), not only the mouth; eye direction stays with the gaze. | Owner |
| D43 | 2026-11-05 | Implementation: solver inside `MRLabLive` on its own thread (backend changed by D46), lookahead 80 ms, voice delayed 0.12 s, curves into the agent's face post-process through a `Modify Curve` curve map, that AnimBP updated on the game thread. The unused ACE components and test nodes are left as they are. | Claude |
| D44 | 2026-11-05 | The mouth is closed whenever the agent is not speaking. | Owner |
| D45 | 2026-11-05 | No delegation: Frank answers only from the instructions and the lab knowledge base; what is not there, he does not know. | Owner |
| D46 | 2026-11-05 | Lip sync model run directly through NNE on the CPU, late steps skip only the model run (no context restart). | Claude |

## 8. Work log

Newest first. One entry per work session: what was done, what was verified, what is left.

### 2026-11-05 (Claude Code, laptop): blinking and delegation
Done:
- Owner: Frank blinks far too often; he delegated, got stuck and stopped answering; no delegation, knowledge only from the knowledge base (D45).
- Found: the GPU backend waits behind rendering (35 ms per step in the owner's session, 617 ms under heavy rendering), and each dropped step restarted the model, which blinks at once (75 to 85 blinks a minute). Lip sync now runs the model directly on the CPU and skips late model runs without restarting (D46, 4.11).
- Delegation: fixed no-delegation rule in every session and an immediate reply to `session.delegation.created` (4.8). DLL rebuilt.
Verified on the laptop: see 4.11 (normal and heavy rendering: 8 and 5 blinks a minute, sync within 0.05 s, mouth closed in silence) and 4.8 (question outside the knowledge answered with "I don't know").
Not verified: the delegation reply path (no delegation happened in the test); the lab PC's CPU time per model run.
Left: owner retest; lab PC.

### 2026-11-05 (Claude Code, laptop): lip sync fixes after the owner's test
Done:
- Owner reported lip sync not working while talking to the agent, and the mouth open when silent (D44). Log: the solver was 10 to 20 times slower than normal in those sessions (4.11). Added: mouth closing in silence, skipping when far behind, backend from `mh.RealtimeAudio.Backend`, timing line in the log. DLL rebuilt.
Verified on the laptop (editor in the foreground, Play, recorded question): mouth controls 0 in silence, jaw up to 0.48 while speaking, jaw leads the voice by 0.02 s, 6.1 ms per step, no skipped steps; a new live video was sent.
Not verified: the cause of the slow sessions (not reproduced); a conversation with a person; the lab PC.
Left: owner retest with own voice.

### 2026-11-05 (Claude Code, laptop): Step 7, lip sync
Done:
- Owner moved lip sync ahead of vision and asked for a comparison first (D40 to D42). Recorded a Frank answer, animated it with Epic's real-time solver (Performance asset, lookahead 80 and 240 ms) and with NVIDIA Audio2Face in Play, rendered three videos with the same camera and sent them; owner chose Epic (D41, Q18). Test content in `/Game/_Sandbox/LipSync` and `Saved/LipSyncTest` (not in Git).
- `MRLabLive`: lip sync solver thread, delayed voice, `LipSyncCurves` (4.8, 4.11); DLL rebuilt. `ABP_Agent_Face_PostProcess`: `LipSyncCurves` variable, curve-map `Modify Curve` before the eye curves, game-thread update. `BP_Agent`: `UpdateLipSync`.
- Found and fixed: seconds-long freezes and one crash from the curve map being replaced while a worker thread read it (4.11).
Verified on the laptop: see 4.11 (Play with a recorded question: lip sync running, timing, frame rate); gaze curves still applied with fake Moverse data; a live video of the agent answering was rendered from the captured face controls and voice and sent to the owner.
Not verified: interrupting the agent while it speaks; a real conversation; the nDisplay node; the lab PC.
Left: lab PC tests of Steps 4 to 7; Q19 to Q26 and earlier open items unchanged.

### 2026-11-05 (Claude Code, laptop): agent persona and voice
Done:
- Owner set the voice to `ash` on the agent placed in `DefaultMap` (D39) and described the persona Frank (D38). New `Instructions` prompt written for Frank and saved on `BP_Agent` (4.8); the placed agent picked it up and kept its `ash` voice.
Verified on the laptop: in Play-In-Editor the session starts with the Frank prompt and voice `ash` (no error from the API; the log line is cut before the voice field).
Not verified: how Frank sounds and behaves in a conversation (nobody spoke to him in this test); the lab PC.
Left: unchanged from the previous entry.

### 2026-11-05 (Claude Code, laptop): Step 6, gaze following
Done:
- Owner chose Step 6 and decided Q15 and the gaze behaviour (D34 to D36).
- `NDC_Basic`: `bHeadTracked` flag (4.4). Agent copies of the body and face post-process AnimBPs with head/neck Look At and eye curves, assigned to the agent's meshes; `BP_Agent` functions `InitGaze` / `UpdateGaze` (4.5, 4.10). Eye curves calibrated in Play.
- Found that Live Link keeps the last frame after the data stops; the flag therefore uses the subject state.
Verified on the laptop: see 4.10 (fake Moverse data, Play and Simulate). The conversation session still starts.
Not verified: real tracking, the wall, the nDisplay node, a person's impression.
Left: Q26 (Moverse plugin crash on repeated Play with data flowing, laptop); lab PC tests of Steps 4 to 6; Q22 to Q25 and earlier open items unchanged.

### 2026-10-27 (Claude Code, laptop): Step 5, lab knowledge
Done:
- Owner chose Step 5 next and decided Q12, Q13 and the GitLab access (D30 to D32).
- "Update Knowledge" editor toolbar button (`Content/Python/init_unreal.py`, `Content/Python/mrlab_knowledge.py`) and knowledge loading in `MRLabLive` (4.9). Default instructions now tell the agent to answer lab questions only from the knowledge. Plugin rebuilt, DLL committed again.
- A first access test with `git ls-remote` opened a GitLab sign-in window on the laptop (the repo is private); it was closed without signing in.
Verified on the laptop: the update downloads the repo's one file (commit `e8003aeb`, matches GitLab); in Play-In-Editor the agent answers a question from that file correctly and says it does not know an uncovered one; the toolbar button appears with its label.
Not verified: the message box after a real click (suppressed when run by remote scripting); knowledge in an nDisplay node (same code path as Play-In-Editor); anything on the lab PC.
Left: lab PC needs `Saved/GitLabToken.txt` and `Saved/OpenAIKey.txt` and a test of GitLab access from its network (Q14); Q24, Q25 and earlier open items unchanged.

### 2026-10-27 (Claude Code, laptop): Step 4, conversation with gpt-live-1
Done:
- Owner chose Step 4 next and answered Q9 to Q11 (D25 to D28).
- Found that `gpt-live-1` runs on OpenAI's Live API, not the Realtime API of the `realtime_rag` prototype (different events, no turn-detection settings); checked the protocol with a throwaway Python script against the API.
- New plugin `Plugins/MRLabLive` (4.8): Live API connection over WinHttp (D29), microphone in, voice out, transcripts as Blueprint events. `BP_Agent` got the `LiveSession` component, wired to BeginPlay and PrintString (4.5).
- `.gitignore` keeps this plugin's binaries (without `.pdb`); `.gitattributes` stores `*.dll` in LFS. `MRLabLive` added to the `.uproject`.
- API key copied from the prototype's `.env` into `Saved/OpenAIKey.txt` on the laptop (owner's instruction).
Verified on the laptop: the plugin builds; the editor loads it from the committed DLL without the project's `Binaries` folder; with a recorded question played through the speakers, Play-In-Editor and an nDisplay node both transcribe it and the agent answers (logs); the node closes cleanly.
Not verified: a live conversation with a person; how the voice sounds (nobody listened during the tests; in the background editor the frame rate drops to about 3 fps, which may make playback choppy there); echo during long answers; anything on the lab PC.
Left: Q24, Q25; on the lab PC create `Saved/OpenAIKey.txt`, then pull and test with the lab microphone and speakers. Earlier open items unchanged (Q4, Q7, Q8, Q19 to Q23).

### 2026-10-27 (Claude Code, laptop): fake Moverse data
Done:
- Fake tracking for testing without the lab (4.4): local script `Tools/moverse_sim.py`; Moverse plugin copied from the lab's `Plugins.zip` into `Plugins/MoversePlugin` (excluded from Git as on the lab PC) and rebuilt on the laptop with the fallback to all local addresses. Nothing tracked in the project changed.
- Found from the plugin source that the preset address is bound on the receiving PC (3.1).
Verified on the laptop: with the script running, Play in the editor prints the fake head positions from `NDC_Basic` (one `INVALID` on the first frame, then continuous values along the loop), `Rig` follows them, Live Link shows subject `Actor0`.
Not verified: nDisplay Launch with the fake data on the laptop; that real Moverse sends the root rotation the script assumes (inferred from the lab head heights, no packet capture).
Left: as before.

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
