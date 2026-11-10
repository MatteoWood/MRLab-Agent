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
OAK-D-W-PoE cameras (IMX378 colour sensor; the hub uses 1280x960 at 60 fps), all at ceiling height (about 305 cm). Left and right as seen standing in front of the wall, facing it (owner, 2026-11-10).

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
     ("found", "in use by another program" = Moverse still running). Press **Connect**: all cameras open at
     the same time, each in its own helper program (about 10 s). Each sends its full picture (1280x960) at
     60 fps, compressed to JPEG on the camera. Camera 1 is the frontal camera (blue frame): it gives Frank's
     view. **Use as frontal** picks another one, without reconnecting. All cameras are used for tracking.
   - **Calibration** (once, and again whenever a camera moves): where each camera is and where it points.
     1. **Walk**: press Start. Hold the checkerboard by its edges (pattern fully visible), high (about 2 m), facing
        two or three neighbouring cameras at once, and tilt it now and then (tilted views measure each camera's
        lens). Move slowly from group to group around the whole space for about 3 minutes. A green frame shows which cameras find the board right now; each
        camera needs 20 or more views (a view counts when another camera finds the board at the same moment).
        Press Stop.
     2. **Floor**: lay the board flat on the floor, face up, its long side parallel to the wall and its middle
        in front of the middle of the wall. Measure from the bottom of the LED wall to the near edge of the
        black and white pattern (not the white border), enter it, step away, press **Take the floor board**.
        One camera finding it is enough. If none does, move it a little and measure again.
     3. **Compute** (up to two minutes), read the score and the line per camera (pixel error, views, position,
        height against 305 cm, measured focal length), check the distance between cameras 2 and 6 with a tape,
        then **Use this calibration**. It is saved in `hub.local.json`.
   - **Tracking**: the Unreal PC's address and the Moverse port come from `runtime\defaults.json` (the values
     Moverse uses). Press **Start tracking**: the hub times the pose model (YOLO11 nano pose) on the graphics
     card and the processor and starts the faster in every camera's helper; each tile then shows its ms per
     picture. A head needs two cameras: the hub finds where their lines of sight to the eyes meet; a new person counts once three cameras see them at the same moment, and not on or behind the LED wall
     (some cameras see Frank on it as a person). Pick a
     camera above the picture to see its view: each person has a number (P1, P2, ...), the same in every
     camera. Only the main person (blue box, "MAIN") is sent; **click a person** to choose them. Without a
     click it is the person nearest to the wall; if the clicked person is gone for 2 s, the nearest again.
     X/Y/Z show the head position, Rate the updates per second, the line below which cameras see the main
     person. `NDC_Basic` on the Unreal PC moves the view as with Moverse. Moverse must not run at the same time.
     With tracking on, "What Frank sees" (Vision page) starts with "Main visitor" when Camera 1 sees them.
   - **3D view**: the lab with the LED wall, the floor, the calibrated cameras (dot and a short line where they
     look) and every tracked person live (own colour, the main person bigger, a fading trail, a line down to a
     ring on the floor). Drag with the mouse to turn and tilt the view. Check: a person standing 2 m in front of
     the middle of the wall should appear there, at their eye height.
   - **Vision**: enter the Unreal PC's address and the port from step 3, press **Start vision**. The first
     start in a new folder loads the model for a few minutes ("loading the model"). Then "What Frank sees"
     shows the description; the Unreal log shows "Camera service: first view from ...". Talk to Frank.
5. Copy the **Log** (Vision page) to Claude when something does not work.
6. Close the hub window (it also stops its Ollama). Start Moverse again if needed.

## If Unreal does not receive the tracking
The hub sends the same packets as Moverse (same format, same port), so check, in this order:
1. Tracking page, line under the picture: "... N packets sent to <address>:<port>" must count up while you are
   tracked. The Log (Vision page) shows "tracking: first packet sent to ..." or "send failed: ...".
2. The address and port on the Tracking page are the ones Moverse sends to (from `runtime\defaults.json`).
3. On the Unreal PC, in Play: Window > Virtual Production > Live Link: the Moverse source and the subject
   `Actor0` (green while data arrives). Moverse itself works with this Unreal session (proves the Unreal side).
4. Firewall of the tracking PC (read only, nothing changed): in a Command Prompt
   `netsh advfirewall show currentprofile` shows "Firewall Policy". `BlockInbound,AllowOutbound` is the normal
   setting; with `BlockOutbound` only allowed programs may send, and the portable Python is not one of them
   (allowing it is the owner's or the lab IT's decision).

## If the hub does not start
- A message box with an error: the text is also saved in `runtime\temp\hub_error.txt`; send it to Claude.
- "The runtime folder is missing": `runtime\` is not next to `MRLabHub.exe`.
- Console fallback without a window: `1_check_pc.bat` (read-only report about the PC),
  `3_find_cameras.bat` (lists the cameras, one picture of each), `4_run.bat` (vision only, asks for the
  Unreal PC address:port and the camera ID once). They use the same `runtime\`.

## Files
| File | What it does |
|---|---|
| `MRLabHub.exe` | Starts the hub (`launcher\MRLabHub.cs`, built by `launcher\build.bat` with the C# compiler that is part of Windows; icon `launcher\MRLabHub.ico`, the window's copy `hub\icon.png`) |
| `hub\app.py` | The window: Cameras, Calibration, Tracking, 3D view, Vision |
| `hub\cameras.py` | Search, connect, stream: one helper program per camera (full picture as JPEG at 60 fps; the pose model runs in the helper, on this PC); no model runs on the cameras |
| `hub\pose.py` | YOLO11 nano pose on this PC (ONNX Runtime; graphics card or processor, whichever is faster) |
| `hub\calibration.py` | Camera positions from the checkerboard: board finder, collecting moments, solving, score |
| `hub\tracking.py` | Head tracker: lines of sight from all calibrated cameras, people across cameras, smoothing, Moverse packets |
| `hub\space.py`, `hub\led_wall.json` | The 3D view; the wall's panel edges in tracking space |
| `tools\led_wall_from_fbx.py` | Makes `led_wall.json` from the lab's `LEDWall.fbx` (run again if the wall model changes) |
| `hub\vision.py` | Description of the people with the local model, sent to Unreal |
| `hub\ollama.py` | Starts and stops the hub's own Ollama |
| `mrlab_camera_service.py` | Vision without a window (also for the laptop: `--source webcam`) |
| `record_cameras.py` | Records 30 s of all cameras' pictures with their times into `recordings\` (for testing the tracking without the lab; the recordings show people: each recordings folder has its own `.gitignore`, keep them out of Git and delete them when done) |
| `1_check_pc.bat` ... `4_run.bat`, `env.bat`, `tracking_pc.ps1`, `find_cameras.py` | Console tools and `2_setup.bat`, which builds `runtime\` |
| `hub.local.json`, `mrlab_camera_service.local.json` | Local settings, not in Git |
