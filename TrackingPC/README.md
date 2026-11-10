# MRLab Hub (tracking PC)

The program for the tracking PC (the PC with the 8 OAK cameras). It replaces the Moverse hub while
Frank runs: it shows the cameras, tracks the visitor's head for the wall's 3D view, and describes
the people in front of the wall for Frank. Main README: section 4.12 (vision) and Step 8.

## Two parts
| Part | Where | Changes |
|---|---|---|
| Code: `MRLabHub.exe`, `hub\`, `launcher\`, scripts | Git (this folder) | often; copy the new files over the old ones |
| `runtime\`: portable Python with its packages (incl. ONNX Runtime), Ollama, the vision model, the tracking model (`pc_models\yolo11n-pose.onnx`), the lab defaults (`defaults.json`: Unreal PC address and Moverse port); about 6.8 GB | USB stick, not in Git | once |

The hub only runs when both are together: `runtime\` must sit next to `MRLabHub.exe`.
To build `runtime\` again (on a PC with internet): `2_setup.bat` downloads everything into it.

## Rule: nothing outside this folder (D63)
- Nothing is installed and no setting of the PC is changed. Everything stays in this folder.
- `MRLabHub.exe` starts the hub with home, AppData and temp folders inside `runtime\`, so the caches and
  logs of the hub, Ollama, the camera library and the NVIDIA driver also stay here (checked on the laptop).
- The hub only sends (UDP) to the Unreal PC; it opens no port, so the firewall needs no change.
- Its settings are saved in `hub.local.json` in this folder (not in Git).
- To remove everything: close the hub and delete this folder.
- Windows itself still notes that programs ran (for example its Prefetch folder); outside our control.

## The 8 cameras
All at ceiling height (305 cm). Left and right as seen standing in front of the wall, facing it (owner, 2026-11-10).

| Camera | Where |
|---|---|
| 1 | front (frontal camera for Frank's view by default) |
| 2 | top left of the LED wall |
| 3 | left side of the area in front of the wall, near the wall |
| 4 | left side of the area in front of the wall |
| 5 | back of the area, on the ceiling |
| 6 | top right of the LED wall |
| 7 | right side of the area in front of the wall, near the wall |
| 8 | right side of the area in front of the wall |

The hub numbers them in this order from their network addresses, listed as `camera_order` in
`runtime\defaults.json` (not in Git: the repository is public).

## Procedure in the lab
1. Copy this whole folder (with `runtime\`) from the USB stick to the tracking PC, for example to the desktop.
2. Close Moverse (it holds the cameras and the graphics card).
3. On the Unreal PC: `git pull`; write the port for Frank's view into `Saved\VisionPort.txt` (one line,
   any free port, not the Moverse port). Start Play or nDisplay Launch.
4. Double-click `MRLabHub.exe`.
   - **Cameras**: the hub searches at start (Search to repeat). Each tile shows ID, address and state
     ("found", "in use by another program" = Moverse still running). Press **Connect**: the cameras open
     one after another ("waiting", "connecting", then the picture), a few seconds each. On the camera on top of the wall press **Use as frontal** (blue frame).
   - **Vision**: enter the Unreal PC's address and the port from step 3, press **Start vision**. The first
     start in a new folder loads the model for a few minutes ("loading the model"). Then "What Frank sees"
     shows the description; the Unreal log shows "Camera service: first view from ...". Talk to Frank.
   - **Tracking** (first version, never tested with an OAK): the Unreal PC's address and the Moverse
     port are filled in from `runtime\defaults.json` (the values Moverse uses). Enter the frontal camera's
     position and tilt in tracking space (measure them; the defaults are a guess). Press **Start
     tracking**: the hub times the pose model (YOLO11 nano pose) on this PC's graphics card and processor
     (about 5 s) and uses the faster; the info line shows which and how many ms per frame. The camera
     only sends colour and depth. The followed person gets a box and a green dot between the eyes, X/Y/Z
     show the head position ("distance from camera depth"), and `NDC_Basic` on the Unreal PC moves the
     view as with Moverse. Moverse must not run at the same time.
     Several people: each gets a number (P1, P2, ...). Only the main person (blue box, "MAIN") is sent.
     **Click a person** in the picture to make them the main person. Without a click it is the nearest;
     if the clicked person is gone for 2 s, the nearest again. **Automatic (nearest)** undoes the click.
     With tracking on, "What Frank sees" (Vision page) starts with "Main visitor": that person first,
     then the others as Person 2, 3, ...
   - **3D view**: the lab with the LED wall and the floor, every tracked person live (own colour, the
     main person bigger, a fading trail, a line down to a ring on the floor for the height). Drag with
     the mouse to turn and tilt the view. Use it to check the camera position and tilt settings: a
     person standing 2 m in front of the middle of the wall should appear there.
5. Copy the **Log** (Vision page) to Claude when something does not work.
6. Close the hub window (it also stops its Ollama). Start Moverse again if needed.

## If the hub does not start
- A message box with an error: the text is also saved in `runtime\temp\hub_error.txt`; send it to Claude.
- "The runtime folder is missing": `runtime\` is not next to `MRLabHub.exe`.
- Console fallback without a window: `1_check_pc.bat` (read-only report about the PC),
  `3_find_cameras.bat` (lists the cameras, one picture of each), `4_run.bat` (vision only, asks for the
  Unreal PC address:port and the camera ID once). They use the same `runtime\`.

## Files
| File | What it does |
|---|---|
| `MRLabHub.exe` | Starts the hub (`launcher\MRLabHub.cs`, built by `launcher\build.bat` with the C# compiler that is part of Windows) |
| `hub\app.py` | The window: Cameras, Tracking, Vision |
| `hub\cameras.py` | Search, connect, stream (frontal camera: colour 960x540 at 30 fps and depth aligned to it; others: small preview); no model runs on the cameras |
| `hub\pose.py` | YOLO11 nano pose on this PC (ONNX Runtime; graphics card or processor, whichever is faster) |
| `hub\tracking.py` | Head tracker: head point and its distance, tracking space, smoothing, Moverse packets |
| `hub\space.py`, `hub\led_wall.json` | The 3D view; the wall's panel edges in tracking space |
| `tools\led_wall_from_fbx.py` | Makes `led_wall.json` from the lab's `LEDWall.fbx` (run again if the wall model changes) |
| `hub\vision.py` | Description of the people with the local model, sent to Unreal |
| `hub\ollama.py` | Starts and stops the hub's own Ollama |
| `mrlab_camera_service.py` | Vision without a window (also for the laptop: `--source webcam`) |
| `1_check_pc.bat` ... `4_run.bat`, `env.bat`, `tracking_pc.ps1`, `find_cameras.py` | Console tools and `2_setup.bat`, which builds `runtime\` |
| `hub.local.json`, `mrlab_camera_service.local.json` | Local settings, not in Git |
