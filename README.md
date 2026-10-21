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
- Version control is this GitHub repo (private, Git LFS for binaries). GitLab was too small for the project. The knowledge base stays in its own GitLab repo.
- AI tooling is Claude Code. Codex is no longer used.
- `CLAUDE.md` (agent instructions) is machine-specific and ignored by Git. The laptop version includes committing and pushing to GitHub. The lab PC has no push credentials for GitHub, so its version has no GitHub steps. Both files exist only locally on their machine (laptop: `C:\Users\bosco\Documents\Unreal Projects\MRLabProject 5.8\CLAUDE.md`; lab PC: `CLAUDE.md` in its clone, created on 2026-10-21 from the former `CLAUDE.lab.md`, commit `8ea546d`).

## 3. Environment

### 3.1 Lab hardware

| Item | Known facts | Source |
|---|---|---|
| LED wall | Curved. Driven by nDisplay. Stereo 3D through polarization. | Owner |
| LED wall mesh in this project | `/Game/Assets/LEDWall`: 494 cm wide, 300 cm high, 30 cm curve depth (mesh bounds). Imported from `C:\Users\bosco\Desktop\MRLab model\LEDWall.fbx`. Not checked against the physical wall. | Asset |
| Moverse tracking | Markerless. 8 Luxonis OAK-D Pro W PoE cameras in a circle at the ceiling, covering the LED wall area. Tracking zone 5 m x 8 m, up to 4 users, 50 or 60 Hz. Tracking PC (server room) runs the Moverse capture software and sends data to the rendering PC. Calibrate every session (about 2 min). Tracking gets worse in dark lighting or with dark clothes. | `C:\Users\bosco\Downloads\Moverse-Tracking-System Kopie.md` |
| Moverse network endpoint | Live Link source `128.130.143.140:54321` | Lab preset `LiveLinkMoverseMRLab` |
| Frontal camera on top of the wall | Mentioned by the owner for vision (G5). Model, connection and access method unknown. | Owner |
| Lab rendering PC | Ran the 5.7 lab project through Switchboard as nDisplay node `Node_0` (host 127.0.0.1, fullscreen 2560x1536). Now runs UE 5.8. | Lab logs, owner |

### 3.2 Machines

| Machine | Role | Notes |
|---|---|---|
| Owner laptop | Development now | UE 5.8 at `C:\Program Files\Epic Games\UE_5.8`, Visual Studio 2022 17.14, Git + Git LFS, Python (Anaconda). No Moverse plugin. |
| Lab rendering PC | Target | UE 5.8. In the 5.7 setup the Moverse plugin was installed in the engine (`Engine/Plugins/Marketplace/MoversePlugin`, plus a duplicate under `Engine/Plugins/Runtime/Marketplace/MoversePlugin`). A 5.8 build of the plugin is not confirmed. |

### 3.3 Repositories and paths

| What | Where |
|---|---|
| This project | https://github.com/MatteoWood/MRLab-Agent (branch `main`), local `C:\Users\bosco\Documents\Unreal Projects\MRLabProject 5.8` |
| Knowledge base | https://gitlab.tuwien.ac.at/mixed-reality-labor/mrlab-agent-knowledge |
| Earlier RAG prototype | `C:\Users\bosco\Desktop\VSCode Projects\realtime_rag` (`mrlab_rag.py`, `realtime_lab_chat.py`, `MRLab_knowledge/`, `requirements.txt`, `.env`). Not reviewed yet. |
| 5.7 lab project, latest (2026-07-07) | `C:\Users\bosco\Desktop\Frank Demo.zip`. Source of the port in Step 2. Does not contain the Moverse plugin. |
| 5.7 lab project, June snapshot (2026-06-16) | `C:\Users\bosco\Documents\Unreal Projects\mrlab-project-frank` (GitLab `matteo.bosco/mrlab-project-frank`). Older than the zip. |

## 4. Current state

State on 2026-10-21, commit `67b75a7`.

### 4.1 Project setup
- Blueprint-only (no `Source/` folder). Not decided whether C++ will be needed (see Q9).
- Main level: `/Game/DefaultMap` (World Partition).
- Plugins enabled in `MRLabProject58.uproject`: MetaHuman set (MetaHuman, MetaHumanCalibrationProcessing, MetaHumanCoreTech, MetaHumanLiveLink, MetaHumanCharacter), MovieRenderPipeline, NVIDIA ACE (NV_ACE_Reference, NvAudio2FaceClaire, NvAudio2FaceJames, NvAudio2FaceMark), nDisplay, DisplayClusterLaunch, Switchboard, ModelingToolsEditorMode, editor AI tooling (ModelContextProtocol, EditorToolset, Terminal, ConfigSettingsToolset, SlateInspectorToolset, LiveCodingToolset), and `MoversePlugin` marked `"Optional": true` (loaded on the lab PC, skipped on the laptop).
- Config: `DefaultEngine.ini` enables Python remote execution (`bRemoteExecution=True`). `DefaultGame.ini` holds the Live Link settings copied from the lab project.

### 4.2 Level contents (`DefaultMap`)

| Actor | Class | Notes |
|---|---|---|
| `MRLab` | StaticMeshActor | Lab room model |
| `LEDWall` | StaticMeshActor | LED wall model, at x=40 |
| `BP_Agent` | `BP_Agent_C` | The MetaHuman agent (see 4.5) |
| `NDC_Basic` | `NDC_Basic_C` | nDisplay config ported from the lab, at (1040, 0, 10), yaw 180 (see 4.3) |
| `NDC_HD_02` | `NDC_HD_02_C` | Older nDisplay config of this project, at (300, -60, 100), yaw -170 |
| `Walking` | LevelSequenceActor | Plays `/Game/MetaHumans/Animations/Walking` |
| `SpotLight`, `PlayerStart` | | |

The lab level also had SkyLight, DirectionalLight, SkyAtmosphere, VolumetricCloud and ExponentialHeightFog. These were not ported (see Q8).

### 4.3 nDisplay

| | `NDC_Basic` (ported from the lab) | `NDC_HD_02` (pre-existing) |
|---|---|---|
| Asset | `/Game/ExampleConfigs/NDC_Basic` | `/Game/NDC_HD_02` |
| Cluster | 1 node `Node_0`, 127.0.0.1, fullscreen 2560x1536 | 1 node, 1920x1080 |
| Viewports | `VP_0` uses camera `ViewPointR`, `VP_1` uses `ViewPointL`. Both cover the full window (0, 0, 2560, 1536). Viewport remap on; `VP_1` is flipped horizontally. | 1 viewport, `DefaultViewPoint` |
| Projection | Mesh policy on component `LEDWALL` (mesh `/Game/Assets/LEDWall`) | Simple policy on a flat screen |
| Inner frustum cameras | `ICVFXCameraL`, `ICVFXCameraR` present; inner frustums disabled at stage level | None |
| Tracking | Yes (see 4.4) | No |

Details of `NDC_Basic`:
- Components: `nDisplayXform` local (950, 0, 150); `LEDWALL` local (0, 0, -150), yaw 180, scale 1 (the lab used scale 100, see decision D8); `Rig` local (0, 0, 50); `ViewPointL` and `ViewPointR` attached to `Rig`, both at local (0, 0, 0), IPD 6.4, stereo offset None.
- World placement in this level: the `LEDWALL` surface is at x=90, while the `LEDWall` model actor is at x=40, same size and orientation (50 cm apart, see Q3).
- In all lab runs the node was launched with `-dc_dev_mono` (mono render device). In the July lab version both eye cameras are at the same position, so both eyes render the same image. The June lab version had cameras `DisplayClusterCameraL1`/`R1` at y = -3 / +3 cm under `Rig`, projecting on a flat 500x300 cm screen. How the wall takes the two eyes is not known yet (see Q1, Q2).
- Lab crash history: 20 of the 23 crash reports in the 5.7 lab project were GPU crashes ("GPU Crashed or D3D Device Removed"), on 2026-06-16 and 2026-07-07 (see Q7).

### 4.4 Moverse integration
- Live Link preset `/Game/Tracking/LiveLinkMoverseMRLab`: Moverse source `128.130.143.140:54321`, subject `Actor0` (animation role). It also contains an Apple ARKit Live Link source (port 11111) from the lab project. The file is byte-identical to the lab version and must not be re-saved on a machine without the Moverse plugin.
- `NDC_Basic` BeginPlay calls `ApplyToClient` on its variable `MoversePreset` (default: the preset above), so the Moverse source is set up at start. In the lab this was done by the level Blueprint (decision D9).
- Head tracking in `NDC_Basic`: on `OnLiveLinkUpdated` of its `LiveLinkComponentController`, it reads bone `moverserig_Head` of subject `Actor0`, converts the location (x, y, z) to (z, -x, -y), and sets it as the relative location of `Rig`. The eye cameras follow `Rig`. A PrintString shows "INVALID" while no frame arrives.
- `/Game/Actor0/`: Moverse rig skeletal mesh (`asset`), skeleton, physics asset and AnimBlueprint (`asset_Animation`). Bones are named `moverserig_*`.
- Tested on the laptop (2026-10-21): assets load, `NDC_Basic` compiles, a Simulate session runs BeginPlay and the tracking callback. Applying the preset fails on the laptop ("Could not apply") because the Moverse plugin is missing there. Not tested on the lab PC.

### 4.5 Agent (`/Game/MetaHumans/Agent/BP_Agent`)
- MetaHuman character asset `/Game/MetaHumans/Agent`, with body, face, grooms and clothing under `/Game/MetaHumans/Agent/`.
- Components include `ACEAudioCurveSourceComponent` (NVIDIA ACE Audio2Face), `MetaHumanComponentUE`, grooms, LODSync.
- Event graph: BeginPlay enables input for player controller 0. OnAnimInitialized (Face, Body) runs the standard MetaHuman `LiveLinkSetup`. A keyboard event `T` exists; when read as text it showed no attached nodes (not confirmed in the Blueprint editor).
- Test audio: `/Game/Audio/test_audio`.
- No conversation, RAG, tracking-driven behaviour, vision or UI yet.
- On 2026-10-21 the editor showed `BP_Agent` as modified but unsaved, without anyone editing it in that session. It was left unsaved.

### 4.6 Tooling for AI agents
Described in each machine's local `CLAUDE.md`: UE's built-in MCP server (`.mcp.json`), Python remote execution (`Tools/ue_py.py`), viewport capture (`Tools/capture_viewport.py`), and direct file access.

## 5. Roadmap

Generic steps. A precise plan is written and agreed before each step starts (section 2). The order of Steps 3 to 7 is not decided. Step 8 is fixed as the last step.

### Step 1. Editor connection and version control: DONE
- Result: Claude Code operates the editor through MCP, Python remote execution and files. The project is in Git with LFS on GitHub.

### Step 2. Port the lab setup (Moverse and nDisplay) from the 5.7 lab project: DONE on the laptop
- Result: see 4.3 and 4.4. The 5.8 LED wall mesh was kept.
- Remaining: validation on the lab PC is part of Step 3.

### Step 3. Lab PC setup and validation: TODO
- Goal: the project runs on the lab rendering PC with nDisplay stereo on the wall and live Moverse tracking.
- Known inputs: 4.3, 4.4, 3.2.
- Open: Q1 to Q8, Q19.
- Detailed plan: not written yet.

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
- Known inputs: Moverse subject `Actor0`, head bone `moverserig_Head`, axis conversion used in `NDC_Basic` (4.4). Up to 4 tracked users (3.1).
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
- **Q1.** What stereo input does the polarized LED wall expect: one signal with eyes side by side, top and bottom, or line interleaved, or two separate outputs?
- **Q2.** Eye separation: in the July lab config both eye cameras sit at the same position. Restore an offset (the June config used +/-3 cm) or set it some other way? Depends on Q1.
- **Q3.** Wall position: the `NDC_Basic` wall surface (x=90) and the `LEDWall` model actor (x=40) are 50 cm apart. Which one matches the real lab?
- **Q4.** Keep or remove `NDC_HD_02` from the level?
- **Q5.** Moverse plugin for UE 5.8 on the lab PC: where does the build come from, and is it already installed?
- **Q6.** The MCP server auto-start is a per-user setting stored under `Saved/` (not in Git). On the lab PC enable it once in Project Settings or launch with `-ModelContextProtocolStartServer`. To be done when Step 3 starts.
- **Q7.** GPU crashes seen in the lab (4.3): cause unknown. Check whether they still happen in 5.8.
- **Q8.** Bring over the lab level's sky, sun and fog actors or not?

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
- **Q19.** The lab PC can pull from GitHub but cannot push. How do changes made on the lab PC (assets, config, README updates) get back into the repo?

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

## 8. Work log

Newest first. One entry per work session: what was done, what was verified, what is left.

### 2026-10-21 (Claude Code)
- Stopped tracking `CLAUDE.md` (now in `.gitignore`, each machine keeps its own). Published the lab PC version as `CLAUDE.lab.md`; the owner copied it to `CLAUDE.md` on the lab PC, then `CLAUDE.lab.md` was deleted from the repo.
- Added this README (handoff document) and the session workflow and gotchas in CLAUDE.md.
- `67b75a7` Ported Moverse and nDisplay from `Frank Demo.zip`: preset, `Actor0` rig, `NDC_Basic` and its level actor, Live Link settings, optional Moverse plugin entry. Verified on the laptop: load, compile, Simulate run (4.4). Not verified on the lab PC.
- Compared `Frank Demo.zip` (5.7, 2026-07-07) with this project. Other config files match. Findings are in 4.3 and 4.4.
- `6837592` Connected Claude Code to the editor (MCP, Python remote execution, viewport capture script), enabled three extra toolsets, added CLAUDE.md, removed `.codex`.
- `a81683f` Baseline commit of the project as it was, pushed with Git LFS (about 1.6 GB).
