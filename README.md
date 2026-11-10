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
- `NDC_Basic` is locked (D54, details in 4.3): do not change any of its parameters, in the Blueprint or the placed actor, unless the owner asks for that specific change. A change can break the 3D effect on the wall.
- `CLAUDE.md` (agent instructions) is machine-specific and ignored by Git. The laptop version includes committing and pushing to GitHub. The lab PC has no push credentials for GitHub, so its version has no GitHub steps. Both files exist only locally on their machine (laptop: `C:\Users\bosco\Documents\Unreal Projects\MRLabProject 5.8\CLAUDE.md`; lab PC: `CLAUDE.md` in its clone, created on 2026-10-21 from the former `CLAUDE.lab.md`, commit `8ea546d`).

## 3. Environment

### 3.1 Lab hardware

| Item | Known facts | Source |
|---|---|---|
| LED wall | Curved. Driven by nDisplay. Native 2560x1536 pixels over 499.9 cm (along the curve) x 300 cm, i.e. 5.12 px/cm in both directions. Passive stereo 3D: the polarization alternates per pixel in a checkerboard, viewed with passive polarized glasses. | Owner, mesh, 2026-10-21 test |
| LED processor | Colorlight Z8t ("Z8t DP" = Windows `DISPLAY2`, "Z8t HDMI" = `DISPLAY3`). In its current mode it shows only the DP input, 1:1, as a 2D image; the HDMI input is not shown. Its 3D settings were not changed (hardware, outside the project). A config backup from 2025-10-15 is on the lab PC desktop (`coloradeptbackup20251015.capf`). | Lab PC, 2026-10-21 test |
| LED wall mesh in this project | `/Game/Assets/LEDWall`: 494 cm wide, 300 cm high, 30 cm curve depth, 20 x 12 panels. Imported from `C:\Users\bosco\Desktop\MRLab model\LEDWall.fbx`. Each panel has its own 0..1 UVs, so it cannot be used for nDisplay mesh projection. `/Game/Assets/LEDWall_nDisplay` is a copy with one UV layout over the whole wall (u = arc length, v = top to bottom), used for the projection (D20). | Asset |
| Moverse tracking | Markerless. 8 Luxonis OAK-D-W-PoE cameras (IMX378 colour sensor, read from the cameras 2026-11-10) in a circle at the ceiling, covering the LED wall area. Tracking zone 5 m x 8 m, up to 4 users, 50 or 60 Hz. Tracking PC (server room) runs the Moverse capture software and sends data to the rendering PC. Calibrate every session (about 2 min). Tracking gets worse in dark lighting or with dark clothes. | `C:\Users\bosco\Downloads\Moverse-Tracking-System Kopie.md` |
| Moverse network endpoint | Live Link source address and port: kept only in each machine's local `CLAUDE.md` (rule in section 2). The plugin binds this address (UDP) on the PC that runs Unreal, so it is the rendering PC's own address, where the Tracking PC sends the data (from the plugin source); only one process on the PC receives the data. | Lab preset `LiveLinkMoverseMRLab`, plugin source |
| Moverse coordinates | Head bone `moverserig_Head` in cm; after the axis conversion in `NDC_Basic` (4.4): +X towards the wall, Z = height above the floor. Measured 2026-10-21: middle of the wall surface at tracking (309, 16). | Calibration run (4.4) |
| Frontal camera on top of the wall | One of the 8 Moverse OAK-D-W-PoE cameras, on top of the wall, right above where the agent stands; connected to the tracking PC like the others. Used for vision (4.12). Device ID not known yet. | Owner, 2026-11-09 |
| Tracking PC | Runs the Moverse hub; all 8 OAK cameras are connected to it (PoE); networked with the rendering PC. Moverse runs its body-tracking AI on its NVIDIA GPU, so the GPU is free for the vision model when Moverse is closed. Exact GPU and installed software not checked. | Owner, Moverse docs |
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

State on 2026-11-05: the repo holds the last working lab PC version (owner's zip of the lab project, evening of 2026-11-05, section 8). On the lab PC the wall runs head-tracked stereo 3D with live Moverse tracking (verified by the owner on 2026-10-21, and again on 2026-11-05 with the new `NDC_Basic` output settings, D49). `NDC_Basic` is locked: do not change its settings (4.3, D54). On the laptop the agent holds a spoken English conversation through gpt-live-1 (4.8), answers lab questions from the GitLab knowledge base (4.9) and follows the tracked user with its eyes and head (4.10); none of these three is tested on the lab PC yet. Since 2026-11-05 (lab PC) the virtual room is lit by real lights on its ceiling LED strips plus a fill light, with one post-process volume for the wall (4.7); not yet checked on the wall.

### 4.1 Project setup
- No project `Source/` folder. C++ lives in the project plugin `Plugins/MRLabLive` (4.8, D25). Building it also makes the build tool generate a stub project module and `Binaries/Win64/MRLabProject58Editor.target`; both are ignored by Git and not needed to run.
- Main level: `/Game/DefaultMap` (World Partition).
- Plugins enabled in `MRLabProject58.uproject`: MetaHuman set (MetaHuman, MetaHumanCalibrationProcessing, MetaHumanCoreTech, MetaHumanLiveLink, MetaHumanCharacter), MovieRenderPipeline, NVIDIA ACE (NV_ACE_Reference, NvAudio2FaceClaire, NvAudio2FaceJames, NvAudio2FaceMark), nDisplay, DisplayClusterLaunch, Switchboard, ModelingToolsEditorMode, editor AI tooling (ModelContextProtocol, EditorToolset, Terminal, ConfigSettingsToolset, SlateInspectorToolset, LiveCodingToolset), `MoversePlugin` marked `"Optional": true` (D10), and the project plugin `MRLabLive` (4.8).
- Optional plugins in UE 5.8: in a Blueprint-only project on the Launcher engine, an optional plugin is only loaded if it is in the engine's build receipt (`Engine/Binaries/Win64/UnrealEditor.target`) or passed on the command line. So `MoversePlugin` is skipped silently even when installed, unless the process starts with `-EnablePlugins=MoversePlugin` (D16, Q20).
- Config: `DefaultEngine.ini` enables Python remote execution (`bRemoteExecution=True`) and, since 2026-11-05 (lab PC), sets `[SystemSettings]` `r.ScreenPercentage=100` and `r.ViewTextureMipBias.Offset=0` (4.7). `DefaultGame.ini` holds the Live Link settings copied from the lab project. `DefaultDisplayClusterLaunch.ini` (new, lab PC) holds the nDisplay Launch arguments, including `EnablePlugins=MoversePlugin`. `Config/nDisplay/StereoCheckerboardRemap.obj` (new, lab PC) is the nDisplay output remap mesh for the 3D output (4.3).

### 4.2 Level contents (`DefaultMap`)

| Actor | Class | Notes |
|---|---|---|
| `MRLab` | StaticMeshActor | Lab room model, the virtual extension of the real lab behind the wall. Inside: y -270..270, z 0..319, back wall at x=-638, open at the front (x=50). Its emissive materials `M_LightsCold` and `M_LightsWarm` are 9 thin LED strips across the ceiling (x = -96, -156, ... -576, every 60 cm, y -261..261, z 319..320, a cold and a warm tube side by side). Since 2026-11-05 they are only the visible sources; the light comes from the `Lighting` actors (4.7). |
| `LEDWall` | StaticMeshActor | LED wall model, surface at x 10..40, inside the room's opening. Hidden in game (D23): it sits exactly on the projection surface. |
| `BP_Agent` | `BP_Agent_C` | The MetaHuman agent (see 4.5), at x=-220, about 2.4 m behind the wall |
| `NDC_Basic` | `NDC_Basic_C` | nDisplay config ported from the lab, at (319, 16, 10), yaw 180. Its origin is the Moverse tracking origin (see 4.3, 4.4). |
| `PPV_Lab` | PostProcessVolume | Unbound; the only post-process volume. Was `PPV_FixedExposure` (exposure only) until 2026-11-05. Settings in 4.7. |
| `Light_Strip_1` .. `Light_Strip_9` | RectLight | Folder `Lighting` (2026-11-05). One per ceiling LED strip, 2 cm below it, pointing down (4.7). |
| `Light_Fill` | RectLight | Folder `Lighting` (2026-11-05). Soft front light from the wall opening onto the agent's face (4.7). |
| `Light_CeilingFill` | RectLight | Folder `Lighting` (2026-11-05). Weak shadowless uplight 20 cm under the ceiling; lights only the ceiling (4.7). |
| `Walking` | LevelSequenceActor | Plays `/Game/MetaHumans/Animations/Walking` |
| `SpotLight` | SpotLight | At (260, 0, 280). Switched off (light component not visible) since D22; left off and unused. |
| `PlayerStart` | | |

The lab level also had SkyLight, DirectionalLight, SkyAtmosphere, VolumetricCloud and ExponentialHeightFog. These were not ported (see Q8).

### 4.3 nDisplay

**Rule (D54): `NDC_Basic` is locked.** It is configured as it runs on the lab PC since 2026-11-05, with head-tracked 3D verified on the wall by the owner. Do not change any of its parameters, in the Blueprint `/Game/ExampleConfigs/NDC_Basic` or in its placed actor in `DefaultMap` (cluster and window, viewports, stereo mode, output remap, projection, components and their transforms, eye cameras, tracking graph, actor transform), and do not re-save or replace their files (`Content/ExampleConfigs/NDC_Basic.uasset`, `Content/__ExternalActors__/DefaultMap/8/20/BYDHEQD265B040BKAIZ09D.uasset`). Any change can break the 3D effect on the wall. Only the owner can ask for a change, for a specific setting; after it, the owner checks the 3D on the wall. `git status` shows if either file changed.

`NDC_Basic` (ported from the lab) is the config that runs the wall. The older `NDC_HD_02` (1 node 1920x1080, one flat viewport, no tracking) was removed on 2026-11-05 (D50). `NDC_BasicLED` (owner, lab PC, 2026-11-05) is a test config, asset `/Game/ExampleConfigs/NDC_BasicLED`: flat 500x300 screen component `nDisplayScreen`, eye cameras `DisplayClusterCameraL1` / `R1` at -3 / +3 cm under `Rig`, no output remap. The owner reported 3D working with it, and `NDC_Basic` copies its output settings since then (D49). Its actor (was at (959, 16, 10), yaw 180) was removed from `DefaultMap` by the owner on the lab PC on 2026-11-05; the asset stays as reference for Q27.

| | `NDC_Basic` |
|---|---|
| Asset | `/Game/ExampleConfigs/NDC_Basic` |
| Cluster | 1 node `Node_0` on the rendering PC itself, fullscreen 2560x1536 at (0, 0), `DISPLAY2` (the wall's DP input) only. Until 2026-11-05: windowed 5120x1536 spanning `DISPLAY2` and `DISPLAY3`. |
| Viewports | `VP_1` = left eye (camera `ViewPointL`) and `VP_0` = right eye (camera `ViewPointR`), both at (0, 0, 2560, 1536), on top of each other; stereo mode Default (was Force Mono). Same layout as `NDC_BasicLED` (D49). Viewport remap off. |
| Projection | Mesh policy on component `LEDWALL`, mesh `/Game/Assets/LEDWall_nDisplay` (D20) |
| Output remap | Off since 2026-11-05, as in `NDC_BasicLED` (D49). Before: external file `Config/nDisplay/StereoCheckerboardRemap.obj` (see 3D below). |
| Inner frustum cameras | `ICVFXCameraL`, `ICVFXCameraR` present (enabled); inner frustums disabled at stage level. Left off on purpose: `NDC_BasicLED` has them on but has no ICVFX cameras, so on would add two inner-frustum images here. |
| Tracking | Yes (see 4.4) |

Details of `NDC_Basic`:
- Components: `nDisplayXform` local (279, 16, 150), the measured wall position in tracking space (4.4); `LEDWALL` local (0, 0, -150), yaw 180, scale 1 (D8); `Rig` local (0, 0, 50), moved by the tracking at runtime; `ViewPointL` at `Rig` local (0, -3.2, 0) and `ViewPointR` at (0, 3.2, 0), i.e. 6.4 cm between the eyes, stereo offset None.
- World placement: the `LEDWALL` surface is at x 10..40, y -247..247, z 10..310, exactly on the `LEDWall` model actor and inside the room's open front (Q3 answered, D21). Every view through the wall therefore stays inside the virtual room.
- The placed `NDC_Basic` actor keeps its own copy of the nDisplay config. Changes to the Blueprint's config (window, viewports, output remap, stage settings) do not reach it; both were changed and saved.
- Launch: editor toolbar, nDisplay Launch, config `NDC_Basic`, node `Node_0` (D17). Arguments come from `Config/DefaultDisplayClusterLaunch.ini` (same as the 5.7 Switchboard launch, including `-dc_dev_mono`, plus `-EnablePlugins=MoversePlugin`). Play-In-Editor does not render through nDisplay: it shows the normal player camera, without tracking-driven view or 3D.
- Head-tracked view: the mesh projection computes the frustum from each eye through the wall, so the wall's edges always match the virtual room and the view widens as the user walks closer.
- 3D since 2026-11-05 (D49): `NDC_Basic` uses the same output as `NDC_BasicLED` (one fullscreen 2560x1536 window, both eye viewports on top of each other, no output remap); the owner verified 3D on the wall with `NDC_Basic` on 2026-11-05. How the two eyes reach the wall without the checkerboard remap is not documented yet (Q27). With the old settings and the 2560-wide window, `NDC_Basic` showed only half the picture: the remap mesh expects a 5120-wide frame. The engine shader `OutputRemapShaders.usf` on the lab PC was edited again on 2026-11-05 17:56 (not by Claude); `NDC_Basic` no longer uses it.
- 3D until 2026-11-05 (D19): the frame holds the left eye at x 0..2559 and the right eye at x 2560..5119. The output remap mesh draws the right eye over the DP half, then the left eye on top with reversed u; the lab's modified engine shader (3.1) mirrors it back and keeps every other pixel. Result on DP: a per-pixel checkerboard of both eyes, which the polarized wall separates. The HDMI half shows the right eye and is ignored by the processor. Verified 2026-10-21 with a red/green per-eye tint: each eye saw only its own colour through the glasses. If the engine shader is restored to the original, the DP output becomes a mirrored left eye and the 3D breaks (Q21).
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
- Vision through `LiveSession` and the camera service (4.12). No UI.
- LOD (2026-11-05, lab PC, D52): the agent placed in `DefaultMap` has its `LODSync` component set to `Forced LOD` 0, so face, body and hair (strands) always render at full detail. Before, `LODSync` chose LODs from the screen size, and at wall viewing distance the face dropped to LOD 2 and the body to LOD 1. Only the level instance was changed; the `BP_Agent` asset keeps automatic LODs.
- On 2026-10-21 the editor showed `BP_Agent` as modified but unsaved, without anyone editing it in that session. It was left unsaved.

### 4.6 Tooling for AI agents
Described in each machine's local `CLAUDE.md`: UE's built-in MCP server (`.mcp.json`), Python remote execution (`Tools/ue_py.py`), viewport capture (`Tools/capture_viewport.py`), and direct file access.
- Lab PC: the MCP server auto-start is enabled (Q6 answered, D18). `CLAUDE.md` was created from `CLAUDE.lab.md`, with a mandatory rule from the owner: nothing outside `C:\Users\VR Group\Documents\Unreal Projects\Matteo\` may be changed (D24).
- Lab PC: `Tools/capture_viewport.py` fails there (the MCP server answers with plain JSON; the script expects a streamed reply). Calling `CaptureViewport` through another MCP client works.

### 4.7 Lighting and exposure
Since 2026-11-05 (lab PC, D51 to D53). Before: emissive light only (D22), see History below.
- Light sources (folder `Lighting` in `DefaultMap`, all movable rect lights, 4000 K, intensities in lumens):
  - `Light_Strip_1` .. `Light_Strip_9`: the main light, like the real lab. One per ceiling LED strip of the `MRLab` model, centred on it at z = 318.5 (2 cm under the strip), pointing straight down; source 520 x 4 cm along the strip; 80 lm each; soft shadows; barn doors off (angle 90, length 0); attenuation radius 1200.
  - `Light_Fill`: keeps the agent's face readable. At (30, 0, 210) in the wall opening, aimed at the agent's face (pitch -11.7, yaw -178.3); source 250 x 150 cm; 120 lm; shadows on; attenuation radius 500, so it fades before the back wall.
  - `Light_CeilingFill`: at (-336, 0, 300), pointing up; source 640 x 520 cm; 40 lm; no shadows, no specular. A rect light only lights what is in front of its plane, so it reaches only the ceiling and the top 20 cm of the walls. Why: the downlights leave the ceiling with bounce light only, and the ceiling panel material's AO texture (`panels_ao`) darkens bounce light, which showed as dark blotches on the panels.
  - The emissive strips (`M_LightsCold`, `M_LightsWarm`, unchanged) stay as the visible light sources. At the new exposure their own bounce light is about 3 % of the wall brightness (measured with all lights at 0).
  - `SpotLight` stays off.
- Post-process `PPV_Lab` (unbound, the only volume; overridden settings): exposure fixed at 3.3 EV100 (histogram method, min = max; was -2.9 with the emissive light; each +1 halves the brightness); local exposure off (highlight and shadow contrast scale 1.0, the project default 0.8 depended on what was in view); motion blur 0; vignette 0; lens flares 0; bloom 0.4; white balance 6500 K, tint 0; Lumen GI with screen traces off, final gather quality 2, scene lighting quality 2, scene detail 2, scene lighting and final gather update speed 2; Lumen reflections quality 2.
- Why motion blur is off: nDisplay sets `vr.AllowMotionBlurInVR=1` for stereo (`DisplayClusterViewportClient.cpp`), and the default motion blur (0.5) then blurred the whole picture whenever the head moved, which smeared fine textures. A window does not blur when you move.
- Why screen traces are off: with screen traces, Lumen's bounce light depends on what is on screen. The head-tracked frustum changes with the user's position, so the bounce from the thin emissive strips, and with it the colour of the room, changed with distance (the owner saw warmer far away, cooler close up). Without screen traces the bounce comes from the Lumen scene only, and the real lights carry most of the light anyway.
- Render config (`DefaultEngine.ini` `[SystemSettings]`): `r.ScreenPercentage=100`; nDisplay multiplies each viewport's buffer ratio by this value (`DisplayClusterViewport.cpp`, `SetViewportBufferRatio`), and the editor had 75 at runtime. `r.ViewTextureMipBias.Offset=0` (TSR default -0.3): textures are no longer sharpened beyond the render resolution, which reduces shimmer and moiré on the fine wall, floor and ceiling textures.
- Measured in editor captures (2026-11-05), camera at 90, 250 and 450 cm in front of the wall plus one off-axis: back wall and side walls have the same colour and brightness in all views (back wall RGB 213/195/165 near and 214/195/166 far). The scene is warmer than before (white walls R/B about 1.3 instead of 1.14) because of the 4000 K light; the old emissive mix had a yellow-green cast (G above R).
- GPU (editor `ProfileGPU`, one view of about 4 MP, close to one eye on the wall): about 6.5 ms for the scene; the largest new costs are shadow projection for the 10 shadowed lights (about 1.5 ms) and strand hair from LOD 0 (about 1.4 ms). Not measured in the nDisplay node.
- Not verified on the wall: colour stability while walking, texture shimmer, frame rate of the node, how the 4000 K light compares with the real lab (Q28).
- To change the light colour or brightness: select all actors in folder `Lighting` and edit `Temperature` / `Intensity` together in the Details panel; change the overall brightness with the exposure in `PPV_Lab` instead.
- History: until 2026-11-05 the only light was the emissive materials (D22), exposure -2.9 EV100 in `PPV_FixedExposure`. Before that volume existed, each eye's viewport adapted its exposure on its own, so brightness and colour changed with the user's position.

### 4.8 Conversation (`Plugins/MRLabLive`)
- C++ project plugin, one Runtime module, Win64 only (D25). Source and the built `UnrealEditor-MRLabLive.dll` + `UnrealEditor.modules` are in Git (DLL via LFS, the `.pdb` is not), so the lab PC runs it without a compiler (D27). The DLL only loads in an engine with the same build ID (5.8.0 changelist 55116800 on both machines); after an engine update it must be rebuilt on the laptop and committed again.
- Rebuild (editor closed): `Engine\Build\BatchFiles\Build.bat Development Win64 -Project=<uproject> -TargetType=Editor -NoEngineChanges`.
- Component `UMRLabLiveSession` (`MRLabLive Session` in the Add Component list). Properties `Model` (`gpt-live-1`), `Voice` (`marin`; the agent placed in `DefaultMap` overrides it with `ash`, D39), `Instructions` (set on `BP_Agent`, edit it there; the C++ default is the older plain technician prompt). Prompt on `BP_Agent` since 2026-11-05 (D38): persona Frank, 57, has worked at TU Wien all his life, now the technician of the new lab's LED wall who lives on the wall as a digital human; grumpy, sarcastic, funny, a know-it-all who always adds one more detail, but warm and never insulting; short spoken answers in English, at most one joke per answer; lab facts only from the lab knowledge (4.9), admitting gaps in character, general topics from general knowledge (D47); no invented people, departments or dates from his past. Section "Sound like a real person, not an assistant" (D48, wording partly from OpenAI's GPT-Live prompting guide): contractions and everyday words, varied rhythm, answer or react first instead of praise, none of the typical assistant phrases ("Great question", "I'd be happy to help", "Is there anything else"), no restating the question, no summary, no closing question or offer every time, sometimes a one-word answer, small hesitations, self-corrections, chuckles or sighs acted out rather than said, opinions of his own, matching the visitor's mood, relaxed pace. `StartSession` / `StopSession`; events `OnUserTranscript`, `OnAgentTranscript` (text of the current utterance so far), `OnSessionClosed` (reason). Log category `LogMRLabLive`; each finished utterance is logged as `User: ...` / `Agent: ...`.
- API key: one line in `Saved/OpenAIKey.txt` on each machine (D26). `Saved/` is ignored by Git, but it is included when the whole project folder is zipped. Without the file the component logs an error and does nothing.
- Live API, as used (verified on 2026-10-27 against the API): WebSocket `wss://api.openai.com/v1/live/sessions`, header `Authorization: Bearer <key>`, first message `session.start` with `model`, `instructions`, `audio.format` (`audio/pcm`, 24000) and `audio.output.voice`; no `delegation`, so the session runs in client delegation mode (the API has no setting to turn delegation off). Mic audio goes up as `session.input_audio.append` (base64 PCM16 mono 24 kHz, sent every frame); the voice comes back as `session.output_audio.delta`, a continuous real-time stream in 100 ms chunks (silence included); the model decides itself when to speak and handles interruptions. Transcripts: `session.input_transcript.delta`, `session.output_transcript.delta`. Sessions expire 2 hours after start (`expires_at`); the component only logs the close, it does not restart (Q25). Price: $0.05 per session minute.
- No delegation (D45, D59): every session gets a fixed rule after `Instructions`, worded as OpenAI's GPT-Live prompting guide recommends for `gpt-live-1`: never generate `<|SpawnThinking|>`, never check, search, look up or use tools, answer right away from what he knows, lab facts only from the lab knowledge, "I don't know" for lab facts that are not there (D47). Then the seeing rule (4.12), then the lab knowledge. If the model still delegates (`session.delegation.created`), the plugin answers at once with `session.commentary.append` (that `delegation_id`, content: nothing can be looked up, answer from the lab knowledge or say you don't know) and logs a warning. Before this, the owner saw Frank delegate once ("just a sec, I'm digging that out"), get no answer and stop. On 2026-11-09 Frank still delegated about once per session when asked about what he sees; the immediate reply let him go on. History: for a few hours on 2026-11-09 Frank delegated on purpose to look (D56) and said "let me have a look" first; the owner did not want that (D59).
- Mid-session text, as used: `session.thinking.append` (`content`, `delegation_id` null for general context) adds silent context, confirmed by `session.thinking.appended`; OpenAI's docs say it "does not directly request speech", but in the laptop test views sent while nobody spoke did make the model speak (4.12). Instructions cannot be replaced after `session.start`, and appended context cannot be removed. `session.usage.updated` reports `context_window.usage_ratio`.
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
- Not tested: real Moverse, the wall, the nDisplay node (its config file had to be regenerated by nDisplay Launch, which was not used), how natural it looks to a person. Known limits: the head-bone-to-eye offset of the user (Q23) is not applied (about 1 to 1.5 degrees at 3 to 5 m); both eyes get the same rotation (no convergence). The face was dark under the emissive-only lighting; since 2026-11-05 `Light_Fill` lights it (4.7).

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

### 4.12 Vision
- How Frank sees (D55, D59 to D62): `gpt-live-1` takes no images. A camera service on the tracking PC keeps a short text description of the people the frontal camera sees and sends it to the PC that runs Unreal; the plugin adds every new description to Frank's session as silent context, but only while the visitor speaks. Frank answers questions about what he sees at once, from the newest description, without delegating and without saying that he looks. Images never leave the tracking PC; only text crosses the network.
```
Tracking PC (cameras, GPU)                                   PC that runs Unreal
TrackingPC/mrlab_camera_service.py
  frontal OAK: newest frame + 3 earlier ones (0.5 s apart)
  -> local vision model (Ollama): people, pose, action
  -> UDP packet 5 times a second  ------------------------->  MRLabLive (port in Saved/VisionPort.txt)
     {"seq", "description", "age_ms", "frame_age_ms"}          -> session.thinking.append, while the visitor speaks
```
- Camera service `TrackingPC/mrlab_camera_service.py` (Python 3.10+, `opencv-python`, `depthai` only for the OAK): `--source oak` (frontal OAK-D Pro W PoE, DepthAI v3, colour camera 640x400 at 10 fps, opened by the ID or address in the local settings) or `--source webcam` (laptop testing). It checks the picture 5 times a second (80x50 greyscale against the last described picture; changed when more than 1 % of the pixels differ by more than 30 grey levels) and, as soon as it changed, sends the newest frame (640 px wide) and the 3 frames from the last 1.5 s (320 px) to the vision model, mirrored left to right (the model names hands correctly more often then: 6 of 7 instead of 5 of 7 in the photo test). The model writes one line per person, from Frank's left to his right, in fixed fields: position, clothes (with any text or picture on them), details (glasses, hair, beard, hat), holding (which hand), pose now, gesture now (which hand, how many fingers), action across the frames (waving, jumping jacks, walking...), expression; "Nobody in view." when nobody is. Only people, never the room. Temperature 0, so an unchanged scene gives the same words and only real changes make a new description (`seq` + 1). Each new description is printed. The model is loaded once at start with a 10 min limit (the first start in a fresh folder also builds the NVIDIA driver's caches; more than 30 s on the laptop).
- Every 0.2 s the current description goes to the Unreal PC as one UDP packet; `age_ms` is the age of the newest camera frame (camera alive), `frame_age_ms` the age of the newest frame the description was made from. The tracking PC only sends, so it needs no open port and no firewall change; on the Unreal PC the packets go to UnrealEditor.exe, which already receives the Moverse packets (whether its firewall rule covers another port is checked in the lab).
- Local settings, not in Git (the repo is public): `TrackingPC/mrlab_camera_service.local.json`, `{"send_to": "<Unreal PC address>:<port>", "oak_device": "<camera ID or address>"}`; `Saved/VisionPort.txt` on the Unreal PC, one line with the port. On the laptop: 127.0.0.1 and a local port.
- Plugin side (`MRLabLive`, 4.8): from `session.started` it listens on the UDP port (logs "Listening for the camera service on UDP port .." and "Camera service: first view from .."); each tick it reads all waiting packets and keeps the newest. It adds the newest description to the session (`session.thinking.append`, `delegation_id` null, content "View N: ...") only while the visitor speaks (their transcript grew in the last 1 s), only if it differs from the last one added, and only if its picture was taken before the visitor's latest words, so Frank sees what was there while the visitor spoke (fingers held up during a question and lowered right after it stay up). Views added at other times made Frank start talking on his own (laptop test, 2026-11-09). No packet for 3 s, no port file, or a camera frame older than 5 s: the next view says "Your eyes are not working right now". Log line per added view: `View N: <description>`.
- Frank's rule (after the no-delegation rule, D62): the camera on the wall is his eyes; a person listed as "Main visitor" is the one his gaze follows, usually the one talking with him; views arrive silently, the newest replaces the older ones and is always there, so he never needs to look and never generates `<|SpawnThinking|>` for it; a new view is never a reason to speak; questions about anything visible are answered at once as if he saw it himself; he never mentions views or a camera feed unless asked how he sees; now and then he may add a short remark about something he sees (for example something funny on a shirt) to a reply, never on his own.
- Laptop results (2026-11-09, webcam, owner speaking): Frank answered "What am I doing", "How many fingers", thumbs up and pose questions from the views, never started talking on his own once views were limited to the visitor's speech, and his context was 9.5 % full after 5 minutes (`context_window.usage_ratio` in `session.usage.updated`; about 7 % at start with the 7 knowledge files). He still delegated about once per session despite the rule; the immediate reply (4.8) kept him from getting stuck. On the laptop the vision model shares the GPU with Unreal: 1 to 1.7 s per description with the GPU free, 2.5 to 6 s during Play, so changes reached Frank 3 to 5 s late. Not tested: the OAK camera, several people, real motion sequences such as jumping jacks (only sequences stitched from still photos: waving recognised, a person arriving not).
- Model choice (A1, laptop with RTX 4090 Laptop GPU, 2026-11-09): `qwen3.5:4b` (Apache 2.0, through Ollama 0.40.15). The benchmark was made for the first design, in which Frank delegated and the service answered one question per look (`NOT_VISUAL` was its answer to a question that is not about the picture; replaced the same day, D59). Benchmark: 10 webcam photos of the owner (sitting, right hand raised, phone held up, arms crossed, thumbs up with the left hand, hand on head, head turned sideways, pointing at the camera, leaning sideways, nobody in view) x 6 questions (shirt colour, what am I holding, pose, how many people, what do you see, and the non-visual "Who is the head of the lab?"), the service's prompt, model kept loaded. Every look sends a new image, so the time that counts is the first question on a new image (later questions on the same image are faster because the model caches the image).

  | Model | GPU memory | Answer time, new image | Answers |
  |---|---|---|---|
  | `qwen3.5:4b` (chosen) | 3.1 GB | 0.6 s (0.42 to 0.81) | Short and spoken. Counts and "nobody is in view" right; `NOT_VISUAL` 9 of 10; raised right hand, phone in the right hand and thumbs up with the left hand named correctly; wrong side for the turned head; missed the sideways lean; once "both hands" for the thumbs up. |
  | `qwen3-vl:4b-instruct` | 3.6 GB | 0.95 s (0.86 to 1.05) | Similar quality; `NOT_VISUAL` 10 of 10; wrong hand for the thumbs up (twice) and once for the raised hand; on the empty picture it invented a grey shirt and empty hands; missed the lean. |
  | `minicpm-v4.6:1b` | 0.7 GB | about 0.5 s | Not usable: long answers about the task ("The visitor is asking..."), speaks as the visitor ("the shirt I'm wearing"), stray `<tool_call>` text, never `NOT_VISUAL`, called the person in view the head of the lab. |

  Known weak points of both Qwen models: left and right (the prompt asks for the visitor's side; mostly right, not always) and subtle poses such as leaning. The photos and answers are not in Git (they show the owner).
- MRLab Hub (`TrackingPC/`, procedure in `TrackingPC/README.md`, D65 to D67): the tracking PC program with a window, started by `MRLabHub.exe` without installation. Pages: Cameras (search, state of each camera, connect, the 8 camera pictures, numbered 1 to 8 in the order of `camera_order` in `runtime/defaults.json` (D75); the frontal camera, Camera 1 unless another is chosen, only gives Frank's view), Calibration (D74, below), Tracking (D73, below; several people as in D71: each gets a number, the same in every camera; only the main person's head is sent; the main person is the one clicked in any camera's picture (blue box, "MAIN"; the others grey), else the person nearest to the wall, kept while visible; a clicked person hidden for 2 s falls back to that. With tracking on, the vision description names the main person first as "Main visitor" when Camera 1 sees them: one call describes only close-ups of that person (cut from the 4 frames) and the position comes from the tracker (distance from the wall, side as Frank sees it); a second call, only when the tracker sees others, describes the frames with the main person covered by a grey box, numbered from Person 2. A frame or close-up added to the scene in one call was not enough: the 4B model mixed two people up), 3D view (D72: the lab in tracking space with a minimal floor grid, the LED wall and every tracked person live, in a minimal TRON-like style (since 2026-11-10 at the owner's request: thin pale lines, a faint floor grid that fades towards its edges, small LED dots, thin trails, little glow); drag with the mouse to turn and tilt the view, nothing else moves it; each person is a glowing point at the head with a light line down to a ring on the floor and a trail that fades over 2.5 s, in their own colour, the main person bigger. The wall is `hub/led_wall.json`, made from the lab's `LEDWall.fbx` by `tools/led_wall_from_fbx.py` and placed as `NDC_Basic` places the same mesh (origin (279, 16, 0), yaw 180: middle of the curve at X 309, edges at 279, Y 16 +-247, height 0 to 300 cm). Drawn with Qt's painter, the glow of grid and wall from a blurred copy made again only when the view turns: 10 ms per frame at 30 frames a second, 42 ms while turning (laptop); wide soft lines took 0.7 s per frame), Vision (Ollama state, model choice, start and stop, the current description, log). The code is in Git (`hub/`, Python with Qt for Python 6.12); the one-time part `TrackingPC/runtime/` (portable Python 3.11.9 with numpy, opencv-python, depthai, PySide6; Ollama v0.40.15; `qwen3.5:4b`; 6.7 GB) goes by USB stick. `MRLabHub.exe` is a 5 KB launcher built from `launcher/MRLabHub.cs` with the C# compiler that is part of Windows; it starts `runtime\python\pythonw.exe -m hub` with home, AppData and temp inside `runtime`. Settings in `TrackingPC/hub.local.json` (not in Git). Tested on the laptop (2026-11-09, the webcam covered, so the benchmark photos stood in for the frontal camera): camera tile, face box, 15 tracking packets a second in Moverse's format, 37 descriptions in 50 s at 2 to 2.7 s each with tracking running, started from the exe, closing stops the hub's Ollama, nothing written outside the folder. In the lab (2026-11-10) it runs on the tracking PC and connects the 8 cameras (work log).
- Tracking with all 8 cameras (2026-11-10, D73 to D79; replaces the first version with the frontal camera's depth, D70):
  - Cameras (`hub/cameras.py`): the 8 are OAK-D-W-PoE with an IMX378 colour sensor (read from the cameras, 2026-11-10; factory focal length about 770 px at 1280x960). Each runs in its own helper process, opened all at the same time (8 threads opening cameras in one process crashed DepthAI in the lab with heap corruption 0xc0000374; one after another took about 9.5 s per camera, 80 s in all). Each camera sends its full colour picture (1280x960) at 60 fps, compressed to JPEG on the camera (quality 90; compression only, no model); in the lab recordings every camera delivered a picture every 16.66 ms, none missing. A closed PoE camera restarts first, so opening is retried for up to 20 s. Picture times are on `time.perf_counter()`: `time.monotonic()` ticks only every 15.6 ms on Windows with Python 3.11 (D79). The hub keeps the newest JPEG and a 0.66 s history per camera and decodes where needed.
  - Pose model in every helper, on the picture decoded at half size (640x480): YOLO11 nano pose with ONNX Runtime on the graphics card (DirectML, high-performance adapter). The model file declares ONNX opset 22, for which DirectML has no convolution, so every convolution ran on the processor (146 ms per picture on the laptop's RTX 4090, 49 ms on the tracking PC's RTX 5090); the hub loads it declared as opset 21 (in memory, same operations, same outputs): 2.8 ms on the laptop (D77). A built-in graphics chip took 36 ms with wrong outputs. Each helper analyses its newest picture and skips older ones. Laptop throughput, picture prepared and read out included: 1 helper 102 pictures/s; 8 helpers 182 in all (they take turns on the graphics card). Not measured on the tracking PC; if it cannot do 8 x 60, see Q33.
  - Combining (`hub/tracking.py`, D78): every face point a camera sees (nose, eyes, ears, confidence 0.5 or more) becomes a line of sight from the camera's lens (focal length from the calibration) and position. People across cameras: a known person takes, from each camera, the person whose head line passes nearest their expected position (within 35 cm); new people start where two cameras' head lines pass within 20 cm at 40 to 240 cm height, and count only after 8 updates, seen by 3 or more cameras at once, inside the area the cameras surround (30 cm margin), not within 40 cm of a known person; two known people closer than 20 cm are merged. Head: each face point is triangulated on its own (weighted by confidence and 1 / distance squared, lines more than 12 cm off dropped); the head is the middle of the two eyes; without both eyes the other points stand in, shifted by their learned distance from the eyes, and move the position only 35 % of the way. A measurement further from the expected spot than 15 cm + 300 cm/s is held back up to 5 times in a row. Pictures are combined when taken within 25 ms of the newest, each line moved along the person's velocity (measured over 0.15 s) to that moment. No depth (D73): one camera alone gives no position. Up to 120 updates a second; One Euro smoothing (1 Hz, beta 0.05) and the Moverse packets as before; the log says when the first packet was sent.
  - Calibration (`hub/calibration.py`, D74, D79): the lab's checkerboard, 11 x 8 squares of 6.5 cm (10 x 7 inner corners, found with OpenCV's `findChessboardCornersSB`, corner order fixed from the light first square). Walk: every 0.25 s each camera's corners at one moment, interpolated between its pictures just before and after (a picture within 2 ms is used as it is); moments with two or more cameras are kept. Floor: the board lies flat on the floor, long side parallel to the wall, centred on its middle, at a measured distance. Solve: each camera's focal length and picture centre from 40 of its own views (OpenCV `calibrateCamera`, the camera's lens distortion kept; D79), relative poses from shared moments (from the camera with the most shared moments outwards), then boards and cameras refined in turns (20 rounds, views fitting worse than 3 px or 3 x the median dropped). Up is square to the plane through the cameras; the floor board gives the floor height, the wall's direction and position (the wall middle at X 309, Y 16 as in `NDC_Basic`). Score per camera: 100 at 0.3 px or less, 0 at 2 px or more, times views / 20 (up to 1), halved when the height is more than 10 cm off 305 and 0 beyond 25 (see Q34); total = mean over the cameras. The report also gives the measured focal lengths and the distance between cameras 2 and 6, to check with a tape. Kept in `hub.local.json` after "Use this calibration"; the 3D view shows the calibrated cameras.
  - First lab calibration (2026-11-10, before D79): score 48, 472 moments, 0.69 to 1.10 px, heights 310 to 322 cm, cameras 2 and 6 4.45 m apart against about 4.27 m measured by the owner (the space about 4 % too large). Replay of the owner's 30 s board recording with D79 on the laptop: 0.24 to 0.49 px, every camera's focal length 1.6 to 3.5 % below the factory value, cameras 2 and 6 4.36 m apart, heights 309 to 322 cm (cameras 1, 2, 5, 6 about 10 cm above 3, 4, 7, 8, in both runs), floor board 0.3 deg from the cameras' plane, score 72 (lowered by the height check).
  - Replay of the owner's 30 s walking recording (one person; the pose model on all 14,400 pictures, then the tracker fed as live, with the replayed calibration): the first version saw 2 or more people in 38 % of the updates, switched the main person twice, jumped up to 83 cm; with D78: one person in 100 % of the updates, no switch, largest step 11 cm (9 steps over 5 cm), about 100 updates a second, 2.0 cm from the path (noise and lag together, at a median walking speed of 1 m/s). The extra person came from cameras 6 and 7 only, about 1.4 m behind camera 5 (outside the space; likely a reflection, inferred from its position). Camera 8 sees about 2 people in every picture with one person present (something in its view looks like a person to the model). Other One Euro settings were not better on this walk; standing still was not in it.
  - Earlier laptop tests (2026-11-10): simulation with 8 cameras, 400 moments, 0.3 px noise: every camera within 0.84 cm and 0.06 deg; with a 4 % wrong focal length given in, the measured ones within 1 % and the cameras within 2.2 cm; two people walking 60 cm apart: both tracked in 100 % of updates, 0.8 cm median. Board finder on rendered boards: found and correctly ordered at every angle tried; interpolating between two pictures 0.13 px from the board at the moment against 0.31 px for the nearest picture. Stand-in cameras (a fake DepthAI) in 8 helpers: parallel opening, streaming, calibration through the window, tracking start, 3D view, disconnect in under 1 s.
  - Not tested: the new calibration and tracker with the live cameras; the tracking PC's pose throughput; standing still; the packets in Unreal (in the lab, 2026-11-10, Unreal did not receive the tracking packets; cause not found, checklist in `TrackingPC/README.md`).
- Console tools (`TrackingPC/`, fallback when the hub window does not start): `1_check_pc.bat` (read-only report), `2_setup.bat` (downloads portable Python 3.11.9, numpy 2.2.6, opencv-python 4.12.0.88, depthai 3.12.0, Ollama v0.40.15 and `qwen3.5:4b` into `TrackingPC/runtime`, checksums checked), `3_find_cameras.bat` (lists the OAK cameras, one picture of each), `4_run.bat` (asks for the two settings once, starts Ollama on its own port and the service). Rule D63: they write nothing outside their folder; every program they start gets its home, AppData and temp folders inside `runtime` (`env.bat`). Checked on the laptop with the installed Ollama and model and the webcam: everything Ollama, the NVIDIA driver and PowerShell wrote went into the folder, nothing into the user's folders. Not tested: `2_setup.bat` (it downloads), the OAK path.
- Run on the laptop without the tools: `python TrackingPC/mrlab_camera_service.py --source webcam` (Ollama installed, model pulled, local settings with `send_to` 127.0.0.1), then Play.

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
- Remaining: a regular way to get lab PC changes into the repo (Q19); Moverse plugin long term (Q20); decide on the engine shader dependency (Q21); eye offset fine-tuning (Q23); check the new lighting on the wall (Q28); Q7, Q8.

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

### Step 8. Vision, then a fast face tracker: IN PROGRESS
- Goal: the agent can see the user through the frontal camera on top of the wall and answer questions about appearance and pose (G5). Then a head tracker faster than Moverse, which computes a whole-body skeleton when the wall only needs one point (the user's eyes).
- Plan (approved 2026-11-09, D55 to D58; vision design changed the same day by the owner, D59 to D62): a camera service on the tracking PC owns the OAK cameras instead of Moverse.
  - 8A Vision: A1 pick the local vision model on the laptop (done); A2 camera service (done: continuous people description, pushed to the Unreal PC); A3 `MRLabLive` adds the views to the session (done); A4 laptop test with spoken questions (done, 4.12); A5 lab: tracking PC tools (`TrackingPC/README.md`), find which OAK is the frontal one, `Saved/VisionPort.txt` on the rendering PC, the same test in front of the wall.
  - Owner request 2026-11-09: instead of the scripts, a hub program with a window, started from an exe without installation: status of the 8 cameras and a connect button, then the 8 camera pictures, the tracking with its settings (addresses), and a section for the models; minimal, modern look. Built the same day (MRLab Hub, 4.12, D65 to D67), including a first version of the tracker (B2 without calibration).
  - 8B Tracker (lab): B1 measure the current latency (phone slow motion) and jitter; B2 in the same service, the frontal OAK's mono camera with IR flood light, face detection (YuNet) on the camera, stereo depth, the eye midpoint in tracking space, One Euro filter, sent as Moverse-format packets (subject `Actor0`) to the rendering PC's Moverse port, so `NDC_Basic`, the preset and the gaze stay unchanged; B3 calibration with tape marks on the floor (rigid fit); B4 the same measurements as B1, coverage, and the owner's judgement on the wall. Expected depth noise from one 75 mm stereo camera: several cm at 3 m before filtering (estimate); if too noisy, triangulate with two OAKs (not in this step). Note: B2 puts the Moverse packet format into the public repo.
- Status: 8A done on the laptop with the webcam (4.12). Lab, 2026-11-10: the hub runs on the tracking PC and connects all 8 cameras (after fixes for a crash on Connect, reopening a camera and the tracking model running on the processor). 8B changed by the owner the same day: all 8 cameras track, by triangulation without depth, calibrated with the checkerboard (D73 to D77; replaces B2's single camera with depth and B3's tape marks). First lab calibration and tracking the same day; then the calibration and the tracker were improved from the owner's recordings (D78, D79). Next in the lab: calibrate again, tracking (standing still too, accuracy at measured spots, the 3D effect on the wall), why Unreal does not receive the packets. B1 not started.

### Step 9. Natural behaviour (LAST): TODO
- Goal: movements while talking, body language matching the content, facial microexpressions (G6).
- Known inputs: MetaHuman character (4.5); lip sync (4.11) already moves the face while speaking.
- Detailed plan: not written yet.

## 6. Open questions and TODO

Lab and display:
- **Q1.** ANSWERED 2026-10-21: one signal on the DP input, both eyes interleaved per pixel in a checkerboard (4.3, D19).
- **Q2.** ANSWERED 2026-10-21: eye cameras at -3.2 / +3.2 cm under `Rig` (D19).
- **Q3.** ANSWERED 2026-10-21: the projection wall now sits on the `LEDWall` model actor (x 10..40), inside the room's opening; the tracking calibration was kept (D21).
- **Q4.** ANSWERED 2026-11-05: removed, actor and asset (D50).
- **Q5.** ANSWERED 2026-10-21: build from `MoversePlugin_UE5.8_v1.0.zip`, installed as a project plugin on the lab PC (D15).
- **Q6.** ANSWERED 2026-10-21: MCP auto-start enabled on the lab PC (D18).
- **Q7.** GPU crashes seen in the lab (4.3): cause unknown. Check whether they still happen in 5.8 (none in the 2026-10-21 runs).
- **Q8.** Bring over the lab level's sky, sun and fog actors or not? The room is closed except for the wall opening and is lit by its ceiling strips (D51), which suggests not.
- **Q20.** Moverse plugin long term: keep `"Optional": true` plus the `-EnablePlugins=MoversePlugin` flag (current; the editor needs the flag too for PIE tracking), or remove `"Optional"` and add the plugin to the repo so every machine has it (the laptop would build it from source or get the binaries)?
- **Q21.** The 3D output depends on the lab's edit of the engine's nDisplay shader (3.1), which an engine update or "Verify" would undo, and which the laptop does not have. Keep relying on it, or move the checkerboard into the project (needs a C++ plugin, see Q9)?
- **Q22.** ANSWERED 2026-11-05: not acceptable (the owner saw the room turn warmer far away and cooler close up). Real lights on the ceiling strips plus a fill, Lumen screen traces off, Lumen quality 2 (4.7, D51, D52). The agent silhouette on the back wall was not seen in the new captures; check on the wall.
- **Q28.** New lighting on the wall (4.7): does the room stay the same colour while walking, are the fine textures calm, is the node frame rate fine, and does the 4000 K light match the real lab (warmer or cooler, brighter or darker)? Tuning: temperature and intensity of the `Lighting` actors, exposure in `PPV_Lab`.
- **Q23.** Tracking fine-tuning: add the head-bone-to-eye offset (about 8 cm forward) and check for a small rotation between the tracking axes and the wall?
- **Q27.** Since 2026-11-05 `NDC_Basic` runs without the output remap, like `NDC_BasicLED` (D49). How do the two eyes now reach the wall (processor setting, engine shader, something else)? Are `Config/nDisplay/StereoCheckerboardRemap.obj` and the engine shader edit still needed (affects Q21, D19)? Should the eye distance stay 6.4 cm (`NDC_Basic`) or become 6 cm (`NDC_BasicLED`)? `NDC_Basic` is locked (D54): any change that follows from this question needs the owner's explicit request.

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
- **Q16.** ANSWERED 2026-11-09: the frontal Moverse OAK-D Pro W PoE on top of the wall, connected to the tracking PC and read by our camera service there; Unreal gets text answers over the network (4.12, D55, D58).
- **Q17.** ANSWERED 2026-11-09: from the camera image, through the local vision model (D56).
- **Q29.** Partly answered 2026-11-09 (D63): our programs may change no file on the tracking PC outside their own folder. Open: may an AI agent ever work on the tracking PC itself (so far only the owner does, with the tools in `TrackingPC/`)? Does the Unreal PC's firewall let the camera service's UDP packets reach UnrealEditor.exe on the chosen port?
- **Q31.** ANSWERED 2026-11-09: built on the laptop with Qt for Python; Ollama and the model inside its folder, brought by USB; a first tracker included (D65 to D67).
- **Q30.** Is Moverse still needed for anything once our service owns the cameras (other projects or demos on the same PC)? Can DepthAI open the frontal camera while Moverse runs (to be tested in the lab, A5)?
- **Q32.** DepthAI says a NETWORK bootloader update is available for the cameras (installed 0.0.28, available 0.0.29, "recommended to improve device discoverability"). It writes to the cameras Moverse also uses. Update them or not?
- **Q33.** If the tracking PC cannot run the pose model on 8 x 60 pictures a second (to be measured): accept fewer analysed pictures per camera (the combined position still updates whenever any camera has a new one), or convert the model once (Ultralytics with PyTorch, on the laptop) to take all 8 pictures in one run, brought by USB?
- **Q34.** Camera heights: both calibrations put cameras 1, 2, 5 and 6 at about 320 cm and 3, 4, 7 and 8 at about 311 cm. Do they really hang at different heights (measure one of each with a tape or laser)? The score's height check assumes 305 cm for all.

Behaviour:
- **Q18.** ANSWERED 2026-11-05: lip sync with Epic's MetaHuman real-time audio solver, after a video comparison with NVIDIA Audio2Face (D41, D43).

Process:
- **Q19.** The lab PC can pull from GitHub but cannot push. How do changes made on the lab PC (assets, config, README updates) get back into the repo? Done once on 2026-10-27: the owner zipped the lab project and the laptop merged it (section 8). Done the same way again on 2026-11-05 (`MRLabAgent5Nov.zip`).

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
| D22 | 2026-10-21 | Only the lab model's emissive materials light the scene; `SpotLight` switched off. Exposure fixed at -2.9 EV100 with `PPV_FixedExposure`. Changed by D51 and D52 on 2026-11-05. | Owner (emissive only), Claude (exposure value) |
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
| D47 | 2026-11-05 | Lab facts only from the lab knowledge base (else "I don't know"); general topics such as technology, mixed reality or science may come from Frank's general knowledge. Refines D45. | Owner |
| D48 | 2026-11-05 | Frank should sound like a person, not an AI assistant: speaking-style section added to his prompt. | Owner (request), Claude (wording) |
| D49 | 2026-11-05 | `NDC_Basic` takes the output settings of `NDC_BasicLED`: fullscreen, output remap off, stereo mode Default on both eye viewports (window and overlapping viewports were already set that way). Wall (`LEDWALL`, `nDisplayXform`, actor position), tracked eye cameras and inner frustums (off) unchanged. Owner verified 3D on the wall. | Owner (Claude chose which settings to copy) |
| D50 | 2026-11-05 | Remove `NDC_HD_02` (actor in `DefaultMap` and asset `/Game/NDC_HD_02`): nothing used it, and it could be picked by mistake in nDisplay Launch. Answers Q4. | Owner |
| D51 | 2026-11-05 | The scene is lit like the real lab, from the high LED strips, but not only by them: real lights on the 9 ceiling strips plus a soft fill so the agent is not too dark. Light colour 4000 K. Changes D22 (emissive only); the emissive strips stay as visible sources. | Owner (light sources, 4000 K), Claude (placement, intensities) |
| D52 | 2026-11-05 | One unbound post-process volume `PPV_Lab` (the old `PPV_FixedExposure`) with motion blur, vignette, lens flares and local exposure off, fixed exposure and white balance, Lumen GI screen traces off and Lumen quality 2; `r.ScreenPercentage=100` and `r.ViewTextureMipBias.Offset=0` in `DefaultEngine.ini`; agent level instance at forced LOD 0. | Claude (plan approved by owner) |
| D53 | 2026-11-05 | Add `Light_CeilingFill` (weak uplight, ceiling only) instead of changing the ceiling panel material, whose AO texture showed as dark blotches once the ceiling got only bounce light. Not in the approved plan. | Claude |
| D54 | 2026-11-05 | `NDC_Basic` is locked as configured on the lab PC on 2026-11-05 (Blueprint and placed actor, all parameters, rule in 4.3). No changes and no re-saves of its two files unless the owner asks for a specific change; a change can break the 3D effect on the wall. | Owner |
| D55 | 2026-11-09 | Vision camera: the frontal Moverse OAK camera on top of the wall, read by our own service on the tracking PC (where the cameras are connected), which replaces Moverse while the agent runs. The same service will later provide the head tracking (Step 8B). Answers Q16. | Owner |
| D56 | 2026-11-09 | Frank looks on request: he delegates only for questions about what is visible, and a free local vision model on the tracking PC answers, instead of a paid API. Pose questions are answered from the camera image. Changes D45 (delegation now exists, for looking only; lab facts still only from the knowledge). Answers Q17. Replaced the same day by D59 (the local model and pose from the image stay). | Owner |
| D57 | 2026-11-09 | Vision first, then the fast face tracker; the tracker is developed in the lab (no OAK camera at the laptop). | Owner |
| D58 | 2026-11-09 | Images stay on the tracking PC: only text crosses the network. Local model through Ollama; addresses and ports in untracked files on each PC. (First over HTTP, question and answer; since D62 a description pushed over UDP.) | Claude (plan approved by owner) |
| D59 | 2026-11-09 | Frank always has a description of what he sees and never delegates or says "let me have a look"; the description is updated by the local model and added to his session. Back to no delegation (D45). Replaces D56. | Owner |
| D60 | 2026-11-09 | Re-describe only when the picture changed, at most once a second at first; then as soon as it changes, to be faster. Frank may sometimes add a remark about what he sees (for example something funny on a shirt) to a reply, but never speaks on his own: every turn starts with the visitor. Views are given to Frank only while the visitor speaks, from pictures taken before the visitor's latest words. | Owner (rules), Claude (how) |
| D61 | 2026-11-09 | The description covers only the people (several possible), what they do, their pose, and their action over the last seconds (for example jumping jacks), not the room. Done with the newest frame plus 3 earlier frames, mirrored. | Owner (content), Claude (how) |
| D62 | 2026-11-09 | The tracking PC sends the description to the Unreal PC (UDP), so it needs no open port; the Unreal PC listens on a port in `Saved/VisionPort.txt`. | Claude |
| D63 | 2026-11-09 | Mandatory rule for the tracking PC: our scripts and programs must not change any file on that PC outside their own folder; they only read the cameras, compute, and send data to the Unreal PC. Downloads, Python, Ollama, the model and all caches stay in that folder. | Owner |
| D64 | 2026-11-09 | Keep the Unreal project at the repo root for now; the tracking PC files are in `TrackingPC/`. Moving the project into its own folder was postponed. | Owner |
| D65 | 2026-11-09 | The tracking PC software is a program with a window (MRLab Hub), started from an exe without installation: cameras with state and connect, the camera pictures, tracking with its settings, the models; minimal, modern look. Answers Q31. | Owner (what), Claude (Qt for Python, dark style) |
| D66 | 2026-11-09 | Files that change (code) go through Git; the one-time part (portable Python with packages, Ollama, the model) is prepared on the laptop as `TrackingPC/runtime` and brought by USB stick. The exe is a small launcher built with Windows' own C# compiler, so code changes never need a new exe. | Owner (split), Claude (launcher) |
| D67 | 2026-11-09 | First tracker version now, untested until the lab: face in the frontal camera (Haar cascade, no model download), distance from stereo depth or face width, camera pose entered by hand, One Euro smoothing, Moverse packet format. Calibration (B3) later. Detection changed the same day by D68. | Owner (now), Claude (method) |
| D68 | 2026-11-09 | Tracking uses a fast neural network on the OAK camera's own chip: YOLOv8 nano pose (Luxonis model zoo) with the camera's depth, instead of the Haar face detector on the PC. Chosen over YuNet on the PC or on the camera. Replaced the same day by D70. | Owner |
| D70 | 2026-11-09 | All models run on the tracking PC, not on the cameras: the OAK cameras only deliver pictures (colour and depth) to the hub. Tracking model YOLO11 nano pose (successor of YOLOv8 nano pose, published by Ultralytics as a ready ONNX file, so no conversion tools) with ONNX Runtime on the graphics card or the processor, whichever is faster on that PC (measured at the start of tracking). Replaces D68. | Owner (on the PC, YOLO11), Claude (runtime, automatic choice) |
| D71 | 2026-11-10 | With several people in front of the wall, one main person is tracked: their head drives the 3D view (and so Frank's gaze); the main person is chosen by clicking on them in the hub. Vision still describes everyone, the main person first as "Main visitor". | Owner (what), Claude (nearest person when none is chosen, 2 s wait for a hidden chosen person, two-call description) |
| D72 | 2026-11-10 | The hub gets a 3D view of the lab: mouse only turns and tilts the view (no walking or flying); minimal floor grid; the LED wall from the lab's model, placed and oriented as in the lab, no room walls; every tracked person live with height, own colour, main person bigger, fading trail; TRON style (minimal blue LED lines, grid less bright than the wall, LED-like dots). | Owner (what), Claude (drawing method) |
| D69 | 2026-11-09 | In the hub, the Unreal PC address and the Moverse port default to the lab values Moverse uses. They are kept in `TrackingPC/runtime/defaults.json` (USB stick, not in Git), so the public repo still has no lab address (D13). | Owner (defaults), Claude (where) |
| D73 | 2026-11-10 | All 8 cameras track the visitor: the head is where the cameras' lines of sight to the eyes meet (triangulation), without depth. The cameras' stereo depth is rated below 2 % error up to 3.5 m and below 4 % to 6.5 m (6 to 18 cm in the room); cameras metres apart are estimated at 1 to 3 cm. Replaces the depth part of D70. | Owner (all cameras, no depth), Claude (method, comparison) |
| D74 | 2026-11-10 | Camera positions from a checkerboard calibration in the hub (the lab's board, 11 x 8 squares of 6.5 cm: walked around, then laid on the floor at a measured distance from the wall), with a score at the end. Up is taken from the plane through the cameras, as all hang at 305 cm. | Owner (checkerboard, score, camera height), Claude (method, floor step, up from the cameras) |
| D75 | 2026-11-10 | Cameras numbered 1 to 8 in a fixed order of their addresses (positions in `TrackingPC/README.md`); Camera 1 (front) is the frontal camera for vision by default. The addresses are in `runtime/defaults.json` (`camera_order`), not in Git. | Owner |
| D76 | 2026-11-10 | All cameras run at 60 fps, as with Moverse; only the description text and the main person's point leave the tracking PC, as often as possible. Each camera in its own helper process with the pose model; pictures compressed to JPEG on the camera. | Owner (60 fps, what is sent), Claude (helpers, JPEG) |
| D77 | 2026-11-10 | The pose model file is loaded declared as ONNX opset 21 instead of 22 (in memory), so DirectML runs it on the graphics card (49 ms on the processor fallback before, 2.8 ms on the laptop after). | Claude |
| D78 | 2026-11-10 | Tracking made steadier after the owner saw noise, jumps and extra people: each face point triangulated on its own, head between the eyes with learned stand-ins; a new person needs 8 updates, 3 cameras at once and must be inside the area the cameras surround; jumps held back. | Owner (what), Claude (how, tested on the owner's recording) |
| D79 | 2026-11-10 | The calibration measures each camera's focal length and picture centre from its own board views (the cameras' own values made the space about 4 % too large) and takes each camera's board corners at the exact moment (interpolated between two pictures); all picture times on the precise clock. | Claude |

## 8. Work log

Newest first. One entry per work session: what was done, what was verified, what is left.

### 2026-11-10 (Claude Code, laptop; owner in the lab): calibration and tracking from the owner's recordings
Done:
- Owner's results: first calibration score 48 (heights 310 to 322, cameras 2 and 6 4.45 m apart against about 4.27 m measured, squares exactly 6.5 cm); tracking noisy, jumping, extra people while alone; Unreal did not receive the tracking packets. The owner recorded 30 s of walking and 30 s with the board (`record_cameras.py`, `TrackingPC/recordings_*`, not in Git: they show the owner).
- From the recordings: the cameras are OAK-D-W-PoE (IMX378, 1280x960, about 770 px focal length), not the wider model assumed before; the hub's picture times ticked only every 15.6 ms (Python 3.11 `time.monotonic()` on Windows). Fixed: precise clock, board corners interpolated to the moment, each camera's focal length measured (D79); tracker rebuilt (D78). Replays on the laptop (4.12): calibration 0.24 to 0.49 px, tracking one person in 100 % of updates, largest step 11 cm.
Not verified: live in the lab; the packets in Unreal (cause open).
Left (lab): copy the new `hub/` files; calibrate again (walk, floor, compute: up to two minutes); tracking test, standing still too; the packet checklist; Q32, Q33, Q34.

### 2026-11-10 (Claude Code, laptop; owner in the lab with the tracking PC): hub on the tracking PC, tracking with all 8 cameras
Done:
- Lab, step by step with the owner: `1_check_pc.bat` all ready (RTX 5090, 127 GB); 8 of 8 cameras found. Connect crashed the hub: 8 threads opening cameras at once, DepthAI heap corruption (0xc0000374, seen with Python's `-X faulthandler` from a console) -> cameras opened one at a time (8af3a44); then all connected, about 9.5 s per camera (log). "Use as frontal" failed: a closed PoE camera restarts first -> retry for 20 s, connect times logged (fea043e). Random camera order -> fixed order by address, Camera 1 frontal (D75); the tracking model ran on the processor because of the model file's ONNX version -> fixed (D77); 3D view starts lower (pitch 10 instead of 22 degrees, owner) (4e94346).
- Owner then asked for: all 8 cameras for tracking at 60 fps, a checkerboard calibration with a score, only text and the main point sent; after a question about depth, without depth (D73, D74, D76). Built: helper process per camera with JPEG and the pose model, combining lines of sight, Calibration page, cameras in the 3D view (4.12).
Verified on the laptop: simulation (calibration within 1 cm, tracking 1 cm median), board finder on rendered boards, stand-in cameras through the whole window. Test pictures of the simulated room only; nothing of the owner saved.
Not verified: anything with the real cameras after the order fix; the pose throughput on the tracking PC; board detection in real light; Unreal.
Left (lab): copy the new `hub/` files; connect (expect about 10 s); calibration (walk about 3 minutes, floor, score); tracking (rate, a person at measured spots, the wall); Q32, Q33; B1.

### 2026-11-10 (Claude Code, laptop): 3D view in the hub
Done:
- New hub page "3D view" (D72, `hub/space.py`); the tracker now keeps a lightly smoothed tracking-space position for every person (the main person at the smoothed position sent to Unreal). Wall geometry from `LEDWall.fbx` (240 panel quads, metres) with a small FBX reader (`tools/led_wall_from_fbx.py`, no libraries), placed as `NDC_Basic` places it; checked: X 279..309 with the middle at 309, Y -231..263, Z 0..300, as in README 4.3.
Verified on the laptop: pictures from three angles with fake moving people (orientation: a person at +Y shows on the right seen facing the wall; the curve bends towards the visitors), and in the hub with the two-photo feed through the real tracker (both people in the view, the clicked one as main). Drawing time 10 ms per frame (42 ms while turning) after moving the glow to a cached blurred copy (first version 0.7 s per frame).
Owner then asked for a more minimal, elegant look (thinner lines, less neon): done the same evening; before/after pictures in `Saved/HubDesign/` (laptop, not in Git).
Not verified: real people moving, with the OAK's depth.

### 2026-11-10 (Claude Code, laptop): main person among several
Done:
- Owner asked for one main person among several, chosen by a click in the hub (D71). Tracker: numbered people, main person by click or nearest, 2 s wait for a hidden chosen person, filter restarted when the main person changes. Tracking page: all people drawn with their number, the main one in blue with "MAIN", clickable picture, "Automatic (nearest)" button. Vision: main visitor first, from close-ups, position from the tracker; the others with the main person hidden. Frank's seeing rule: who the main visitor is (DLL rebuilt, not tested in Unreal: text only).
Verified on the laptop with two photos side by side (the same person twice, the hardest case): numbering, clicking each person, fallback to the nearest after the clicked one left (logged), and the vision description naming the clicked person as Main visitor both ways (phone or thumbs up), 2 to 4 s per description with tracking running. Tried first and dropped: a green frame around the main person, then the frame plus a close-up in the same call (the model mixed the two up).
Not verified: real different people, the OAK, Frank's answers about the main visitor in Unreal.

### 2026-11-09 (Claude Code, laptop): tracker on the tracking PC
Done:
- Owner: the models must run on the tracking PC, the cameras only give the input (D70). The frontal OAK now streams colour 960x540 at 30 per second and depth aligned to it; `hub/pose.py` runs YOLO11 nano pose with ONNX Runtime. Downloaded into the runtime with `2_setup.bat` (checksums checked): onnxruntime-directml 1.24.4 with flatbuffers, packaging, protobuf, mpmath, sympy; `yolo11n-pose.onnx` (11.9 MB, Ultralytics' assets on GitHub). The setup script now also takes pure-Python wheels. `runtime/oak_models` deleted.
- Laptop timings for one frame: processor 45 ms (16 threads; 56 ms with 8, 88 ms with 4), OpenCV's DNN on the processor 189 ms, DirectML on each of the three graphics adapters about 190 to 260 ms with GPU use at 0 % (not explained; DirectML's recommended session settings did not help). The hub therefore times both at the start and uses the faster.
Verified on the laptop with the benchmark photos: person box and the head point between the eyes, 15 Moverse packets a second (the photo rate), distance from the eye spacing (no depth with photos).
Not verified: the OAK path (colour and aligned depth over PoE at 30 per second, depth at the head), speed on the tracking PC's processor and graphics card.

### 2026-11-09 (Claude Code, laptop): tracker on the camera chip, lab defaults
Done:
- Owner asked for a fast model for tracking: YOLOv8 nano pose now runs on the frontal OAK's chip with its stereo depth (D68). Model downloaded from Luxonis' model zoo into `TrackingPC/runtime/oak_models` (`yolov8n-pose.rvc2.tar.xz`, 6.1 MB); DepthAI 3.12's built-in decoder accepts it (YOLO, yolov8, 17 points decoded on the camera). The frontal colour stream is now 1280x720 (same 16:9 crop as the model's input).
- Lab address and Moverse port as defaults in `TrackingPC/runtime/defaults.json`, outside Git (D69).
Verified on the laptop: the head point maths with DepthAI's own message types (fake person: eyes, nose, depth fallback, nobody); the PC face detector path after the change (box and head point drawn, 15 Moverse packets a second); the app reads the defaults.
Not verified: the pose model on a real OAK (pipeline build, 30 per second next to the 1280x720 stream at 15 per second, depth at the points), the head position against reality.

### 2026-11-09 (Claude Code, laptop): MRLab Hub for the tracking PC
Done:
- MRLab Hub (4.12, D65 to D67): window with Cameras, Tracking and Vision pages; first head tracker; vision moved into `hub/vision.py` (the console service uses it too); launcher `MRLabHub.exe`.
- `TrackingPC/runtime` prepared on the laptop for the USB stick (6.7 GB): `2_setup.bat` downloaded portable Python 3.11.9 and the pinned packages (checksums checked; it now also moves wheel DLLs into place, which depthai needs, and adds PySide6); Ollama and `qwen3.5:4b` copied from the laptop's install.
- Problems found and fixed in the laptop tests: the first image description in a fresh folder takes more than 30 s (the model is now loaded with one small image and a 10 min limit); hidden spin box arrows made the number fields 1 pixel wide under the style sheet (arrows kept, styled away).
Verified on the laptop: see 4.12 (hub with the benchmark photos as camera; the webcam was covered); the console service with the runtime; nothing written outside the folder.
Not verified: everything with OAK cameras; tracking packets arriving in Unreal; the tracking PC's GPU speed; whether Qt starts there (it brings its own runtime libraries; the laptop has the Visual C++ runtime installed anyway).
Left: lab test (A5, tracker first try, measure the frontal camera's pose); copy `TrackingPC` with `runtime` to the USB stick.

### 2026-11-09 (Claude Code, laptop): Step 8A vision
Done:
- Plan for Step 8 written and approved (vision first, then a fast face tracker; our own service on the tracking PC replaces Moverse; free local vision model). Q16, Q17 answered; D55 to D64.
- A1: Ollama 0.40.15 installed on the laptop (by the owner); three free vision models compared on 10 webcam photos of the owner; `qwen3.5:4b` chosen (4.12).
- First design (Frank delegates to look, the service answers one question): built and tried by the owner. Problems: the first look timed out while Unreal used the GPU, the model wrongly called "What am I holding" not visual, and the owner did not want "let me have a look" (D59).
- Second design (4.12): the service keeps a description of the people and sends it to Unreal; the plugin adds it to Frank's session while the visitor speaks. Changes during the owner's tests: a "same or changed" check by the model never saw a change, replaced by fixed fields at temperature 0; views sent while nobody spoke made Frank talk on his own, so they go only during the visitor's speech; the description of a picture taken while the visitor spoke wins over a later one; people only, finger counts, actions over 1.5 s, mirrored frames; HTTP polling replaced by UDP packets from the tracking PC.
- `MRLabLive`: no delegation again, seeing rule, UDP receive (`Sockets` module), views via `session.thinking.append`. DLL rebuilt.
- `TrackingPC/`: camera service, camera finder, numbered tools for the lab with the rule that nothing is written outside their folder (D63), procedure in `TrackingPC/README.md`.
Verified on the laptop: the owner's spoken tests (4.12); Unreal receives the UDP views ("first view from 127.0.0.1", Play without speaking); the tools' run step with the webcam keeps every file inside its folder; the camera finder with no camera and with a wrong address.
Not verified: anything with an OAK camera; `2_setup.bat` (downloads); several people; real motion such as jumping jacks; the Unreal PC's firewall for the UDP port; speed on the tracking PC's GPU.
Left: lab test tomorrow (A5); the hub program the owner asked for (Q31); Step 8B.
Local, not in Git: `Saved/VisionPort.txt` and `TrackingPC/mrlab_camera_service.local.json` (laptop values); Ollama and three models installed on the laptop (`minicpm-v4.6:1b` and `qwen3-vl:4b-instruct` are no longer needed).

### 2026-11-05 (Claude Code, laptop): last working lab PC version into the repo, NDC_Basic locked
Done:
- The owner zipped the lab project (`MRLabAgent5Nov.zip`, saved 19:31, not in Git) as the last working version on the lab PC. Its base is `005151c`, the last commit on GitHub, plus the four lab PC entries below. Compared file by file with the repo.
- Taken from the zip, byte for byte: `Config/DefaultEngine.ini` (`[SystemSettings]`, 4.7); `Content/ExampleConfigs/NDC_Basic.uasset` and the `NDC_Basic` actor `__ExternalActors__/DefaultMap/8/20/BYDHEQD265B040BKAIZ09D.uasset` (D49); new `Content/ExampleConfigs/NDC_BasicLED.uasset`; `BP_Agent.uasset`; the `PPV_Lab` and `BP_Agent` level actors (`A/FO/...`, `B/77/...`); the 11 new `Lighting` actors and the folder object (list in the lighting entry below); `README.md` (the lab version, then this entry). Removed: `Content/NDC_HD_02.uasset` and its actor `C/FP/QEVUQ1QNXPDFXTWZO9HFD6.uasset` (D50).
- Not taken: `Saved/` (lab logs, crash reports, autosaves, backups, editor settings); the lab `CLAUDE.md` (machine-local); `.gitattributes`, `.gitignore`, `.mcp.json`, `Content/Python/*.py`, `Tools/*.py`, `Config/nDisplay/StereoCheckerboardRemap.obj` (differ only in line endings). The zip has no `Plugins/` folder; `Plugins/MRLabLive` stays as in Git (the lab runs the same DLL since its pull of `005151c`).
- `BP_Agent.uasset` was saved on the lab PC at 19:27, after the last lab entry. Its text (names, prompt) is the same as in `005151c`; what changed (numbers, or only a re-save) is unknown, it was not opened in the editor.
- The `NDC_BasicLED` actor is gone from the level in the lab copy (its folder `4/RZ/` is empty, no level file refers to `NDC_BasicLED`). Section 4.2 and 4.3 updated; the asset stays.
- Rule from the owner: `NDC_Basic` is locked, no parameter changes (D54, sections 2 and 4.3, Q27). Also added to the laptop's `CLAUDE.md`.
Verified: every copied file has the same SHA-256 as in the zip, including both `NDC_Basic` files; no level actor other than `NDC_Basic` uses an nDisplay config class.
Not verified: this version in the laptop editor (not opened); anything on the wall.
Left:
- Lab PC: its working tree already holds these changes, uncommitted, so a plain `git pull` will refuse (changed and untracked files). Suggested: `git stash push -u` (keeps a copy), `git pull`, check that `NDC_Basic.uasset` and its actor did not change, then drop the stash and the older `stash@{0}`. `Plugins/MoversePlugin` and `Saved/` are not touched by this (excluded or ignored).
- Lab PC: add the D54 rule to its local `CLAUDE.md`. Its calibration note (move the `NDC_Basic` actor, `nDisplayXform`) now needs the owner's explicit request.
- Laptop: an older uncommitted change to the `MRLab` room actor (`8/PP/UY0ZZTQJH50OALPKDY1JGP.uasset`, collision off, saved on the laptop at 16:52) is not part of this commit; the lab copy of that file equals Git. Q27, Q28.

### 2026-11-05 (Claude Code, lab PC): lighting and post-process
Done:
- Owner's report: fine textures behave strangely when moving, the room gets warmer far away and cooler close up, the picture does not feel high quality; wanted a post-process volume and lights like the real lab (from the high LED strips, but not only those, so the agent is not too dark). Plan approved by the owner, light colour 4000 K (D51, D52).
- Causes found: nDisplay turns motion blur on for stereo and the level had the default motion blur, so every head movement blurred the picture; the only light was Lumen bounce from 1 cm emissive strips, which depended on what was on screen (screen traces); the emissive cold/warm mix gave a yellow-green cast; local exposure 0.8 also depended on the view; the agent's face dropped to LOD 2 at viewing distance; the editor ran at 75 % screen percentage, which nDisplay would also apply.
- `PPV_FixedExposure` renamed `PPV_Lab` and extended (4.7). New rect lights in folder `Lighting`: 9 strip lights, `Light_Fill`, `Light_CeilingFill` (D53). `DefaultEngine.ini` `[SystemSettings]` with `r.ScreenPercentage=100`, `r.ViewTextureMipBias.Offset=0`. Agent level instance: `LODSync` forced LOD 0 (4.5). Exposure recalibrated to 3.3 EV100 so the walls have about the old brightness.
- Saved only these packages; the owner's unsaved `BP_Agent` asset and `NDC_BasicLED` actor (`4/RZ/91VHHPAPD0EL2Y3Z4DA590`) were left as they were. Backups of the changed files before the change: `Saved/ClaudeTemp/Backup_2026-11-05_lighting/`. Before/after captures: `Saved/ClaudeTemp/Lighting_2026-11-05/`.
Verified (editor captures, not the wall): wall colour and brightness the same from 90, 250 and 450 cm and off-axis; emissive bounce about 3 % of the wall light; face lit and readable; ceiling blotches mostly gone with `Light_CeilingFill`; scene render about 6.5 ms on the GPU for a 4 MP view.
Not verified: nDisplay Launch with the new lighting (colour while walking, texture shimmer, node frame rate, 3D); the `DefaultEngine.ini` values take effect in the editor only after a restart (set by console for this session, so the editor already shows them now).
Left: owner checks on the wall (Q28). If fine textures still shimmer there: supersample the eye viewports (nDisplay screen percentage above 1) or calm the high-frequency lab textures (floor carpet, wall plaster).
Changed files on the lab PC (not committed): `Config/DefaultEngine.ini`, `README.md`; level actors `Content/__ExternalActors__/DefaultMap/A/FO/6WRBYAQF6CXURGN2HUCM5S.uasset` (`PPV_Lab`), `.../B/77/Z6Q065VEMQDI7TPI37X790.uasset` (`BP_Agent` instance); new `.../6/N0/I8GEYCZMKDT5I4DKZ9M6MH`, `.../D/DQ/3O4Q7Q5EA8SEWINLYBIX3N`, `.../6/8D/AA50OQGBIXRNZ2KY8RQQQH`, `.../4/BV/RHB1PV7BVX03HQFC50RUZB`, `.../0/YU/2NYV7TL20ZHW5MRMA9ZSLG`, `.../0/PU/2SUV3RKAU3O5MEJ3GLHFCE`, `.../0/VJ/JA632BUZVB1EK1D48TNFTX`, `.../3/CI/4ZDH082II4TZQSU1U84Y2O`, `.../D/RL/ZPY2E33TRWWTJKKVILYPS6` (strip lights 1 to 9), `.../3/GW/LJDG0WQQFOA27JYYZSQXV5` (`Light_Fill`), `.../B/G8/ZBRROZ1OS88B1CO1F8USQF` (`Light_CeilingFill`), all `.uasset` under `Content/__ExternalActors__/DefaultMap/`, and `Content/__ExternalObjects__/DefaultMap/3/LK/R3UHMY6BQO2XH00CUZ81Y6.uasset` (actor folder `Lighting`). Not in Git: `CLAUDE.md` (lighting and capture notes).

### 2026-11-05 (Claude Code, lab PC): NDC_HD_02 removed
Done:
- Owner decided to remove `NDC_HD_02` (Q4, D50). Checked first: the only referencer of `/Game/NDC_HD_02` was its own placed actor; `BP_Agent.InitGaze` finds the nDisplay actor by the class `NDC_Basic_C`; no config, script or tool mentions it.
- Removed the actor from `DefaultMap` and saved only its package (file `__ExternalActors__/DefaultMap/C/FP/QEVUQ1QNXPDFXTWZO9HFD6.uasset` deleted), then deleted the asset `/Game/NDC_HD_02`. Backups in `Saved/ClaudeTemp/Backup_2026-11-05_NDC_HD_02/`; both files are also in Git history.
- Left alone (owner's unsaved editor changes at that time): `BP_Agent`, and the `NDC_BasicLED` actor, which the owner deleted in the editor at 18:54.
Verified: asset gone from disk and from the asset registry; `NDC_Basic` is the only nDisplay actor left in the level; `NDC_Basic` files unchanged.
Not verified: nDisplay Launch after the removal.
Left: owner saves or discards the open `BP_Agent` and `NDC_BasicLED` actor changes; if `NDC_BasicLED` goes, 4.2 and 4.3 should drop it (its asset stays as reference for Q27 unless deleted too).
Changed files on the lab PC (not committed): deleted `Content/NDC_HD_02.uasset` and `Content/__ExternalActors__/DefaultMap/C/FP/QEVUQ1QNXPDFXTWZO9HFD6.uasset`; `README.md`. Not in Git: `CLAUDE.md`.

### 2026-11-05 (Claude Code, lab PC): pull of the lip sync version, NDC_Basic kept
Done:
- Owner verified 3D on the wall with `NDC_Basic` after D49.
- Pulled from GitHub: `be0e203` to `005151c` (7 commits: Step 7 lip sync, its fixes, Frank's prompt). None of them touches the nDisplay configs. The owner closed the editor first (the pull replaces the `MRLabLive` DLL, which the running editor locks) and did not save the `NDC_BasicLED` actor (it was only deleted and undone).
- Before the pull, all local changes were copied to `Saved/ClaudeTemp/Backup_2026-11-05_before_pull/`. `README.md` was put aside with `git stash` (`stash@{0}`, still there), the pull was a fast-forward, and the lab entries (4.2, 4.3, Q27, D49, these work log entries) were merged into the new README by hand.
Verified: `NDC_Basic.uasset`, its actor, `NDC_HD_02.uasset`, `NDC_BasicLED.uasset` and its actor are byte-identical before and after the pull; LFS files downloaded. After the editor restart: `MRLabLive` loads (new DLL), `BP_Agent` loads, both configs of `NDC_Basic` still have fullscreen on, remap off, stereo Default, cameras `ViewPointL/R`, mesh `LEDWALL`; actor at (319, 16, 10) yaw 180, `nDisplayXform` (279, 16, 150), eye cameras at -3.2 / +3.2 cm, `MoversePreset` set; nothing dirty. The editor's startup ensure about matrix precision and the LiveCoding errors for the NV_ACE DLLs also appear in the logs from before the pull.
Not verified: nDisplay Launch after the pull; Step 7 lip sync on the lab PC.
Left: lab PC tests of Steps 4 to 7 (keys `Saved/OpenAIKey.txt` and `Saved/GitLabToken.txt` still to create); Q27; how the lab changes get into the repo (Q19).
Changed files on the lab PC (not committed): `Content/ExampleConfigs/NDC_Basic.uasset`, `Content/__ExternalActors__/DefaultMap/8/20/BYDHEQD265B040BKAIZ09D.uasset`, `README.md`; by the owner: `Content/NDC_HD_02.uasset`, new `Content/ExampleConfigs/NDC_BasicLED.uasset` and `Content/__ExternalActors__/DefaultMap/4/RZ/`. Not in Git: `CLAUDE.md`.

### 2026-11-05 (Claude Code, lab PC): NDC_Basic output like NDC_BasicLED
Done:
- The owner reported that `NDC_BasicLED` (a new config they made, 4.2) shows 3D, while `NDC_Basic` showed only half the screen. The two configs were compared setting by setting in the editor. Differences: fullscreen, output remap, stereo mode, eye cameras, projection mesh, inner frustums.
- `NDC_Basic` (Blueprint and placed actor): fullscreen on, output remap off, stereo mode Default on `VP_0` and `VP_1` (D49). Not changed: wall, Moverse tracking (`Rig`, `ViewPointL/R`, Blueprint graph), actor position, inner frustums (left off, see 4.3). Saved only `/Game/ExampleConfigs/NDC_Basic` and the actor package `__ExternalActors__/DefaultMap/8/20/BYDHEQD265B040BKAIZ09D`.
- Not pulled: the lab PC is 7 commits behind GitHub and has uncommitted changes (the owner's `NDC_Basic`, `NDC_HD_02`, the new `NDC_BasicLED` and its actor), so the pull was left to the owner.
Verified: after saving, both configs of `NDC_Basic` match `NDC_BasicLED` except the eye cameras, the projection mesh and the inner frustums; the actor's position and the wall and eye components are unchanged; no other package dirty.
Not verified: the wall itself (no nDisplay Launch in this session); the 3D through the glasses.
Left: owner tests `NDC_Basic` with nDisplay Launch; Q27. Backups of the two files before the change: `Saved/ClaudeTemp/Backup_2026-11-05_NDC_Basic/`.
Changed files on the lab PC (not committed): `Content/ExampleConfigs/NDC_Basic.uasset`, `Content/__ExternalActors__/DefaultMap/8/20/BYDHEQD265B040BKAIZ09D.uasset`, `README.md`.

### 2026-11-05 (Claude Code, lab PC): pull
Done:
- Pulled from GitHub: the lab PC moved from `8ea546d` to `be0e203` (13 commits: the merge of the 2026-10-21 lab changes, Steps 4 to 6, persona and voice).
- Before the pull, the uncommitted lab changes of 2026-10-21 were discarded (owner's decision). Each file was compared with GitHub first: 5 identical; `Config/DefaultDisplayClusterLaunch.ini` differed only in line endings; `NDC_Basic.uasset` was the merged version (changed again since by Step 6); the `README.md` content is in the merged README (decisions renumbered, addresses removed); `CLAUDE.lab.md` was identical to the local `CLAUDE.md`. Nothing was lost.
- `CLAUDE.md`: removed the note about uncommitted lab changes.
Verified: working tree clean at `be0e203` before this entry; all LFS files downloaded (no pointer files left); `Plugins/MoversePlugin` still in place.
Not verified: the editor with the new `MRLabLive` plugin; Steps 4 to 6 on the lab PC (the editor was not opened in this session).
Left: create `Saved/OpenAIKey.txt` and `Saved/GitLabToken.txt` on the lab PC (both missing), then test Steps 4 to 6 with the lab microphone, speakers and real tracking (Q14). Earlier open items unchanged.
Changed files on the lab PC (not committed): `README.md` (this entry). Not in Git: `CLAUDE.md`.

### 2026-11-05 (Claude Code, laptop): Frank sounds more human
Done:
- Owner asked for answers that sound more human and less like an AI (D48) and confirmed that only lab facts must come from the knowledge base (D47). Frank's prompt on `BP_Agent` got the section "Sound like a real person, not an assistant" (4.8); the plugin's fixed no-delegation rule and delegation reply reworded to allow general knowledge. DLL rebuilt.
Verified on the laptop (Play, three recorded questions): short, in-character answers without assistant phrases ("Oh, living the dream, bolted to a wall..."); a general question answered from general knowledge; the camera count from the knowledge ("Eight of 'em, hanging around the ceiling like nosy pigeons"). Lip sync 11.3 ms per run, 3 % of steps skipped.
Not verified: a conversation with a real person; the lab PC.
Left: owner retest.

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
