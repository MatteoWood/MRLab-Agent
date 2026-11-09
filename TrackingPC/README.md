# Tracking PC tools: Frank's eyes

These files run on the tracking PC (the PC with the 8 OAK cameras). They read the frontal camera,
describe the people in front of the wall with a local vision model, and send that text to the PC
that runs Unreal. How it works: section 4.12 of the main README.

## Rule: nothing outside this folder (D63)
- Everything the tools need (Python, its packages, Ollama, the vision model) is downloaded into
  `runtime\` inside this folder. Nothing is installed, no setting of the PC is changed.
- Every program started by the tools gets its home, AppData and temp folders inside `runtime\`
  (`env.bat`), so caches and logs (Ollama, the NVIDIA driver, PowerShell) also stay here.
- The camera service only reads the camera and sends UDP packets out; it opens no port, so the
  firewall needs no change.
- To remove everything: close the windows and delete this folder.
- Windows itself still notes that programs ran (for example its Prefetch folder); that is outside
  the tools' control.

## Procedure
Copy this folder to the tracking PC (for example to the desktop or a USB stick). Double-click the
numbered files in order. Each opens a window and waits for a key at the end; copy what it shows
to Claude.

1. `1_check_pc.bat`: read-only report: Windows, graphics card and what uses it, free disk space,
   whether Moverse runs, the PC's network addresses, internet access, setup state.
   Needs: about 9 GB free while setting up (7 GB after); internet for step 2.
2. **Close Moverse** (it holds the cameras and the graphics card).
3. `2_setup.bat`: downloads into `runtime\` (checksums checked): portable Python 3.11.9 (11 MB),
   numpy, opencv-python, depthai (about 130 MB), Ollama (1.6 GB), the vision model
   `qwen3.5:4b` (3.3 GB). Run it again if it stops; it continues where it stopped.
4. `3_find_cameras.bat`: lists the OAK cameras with ID, address and state, then shows one picture
   of each. Note the ID of the camera on top of the wall (the one looking at the visitors).
   If it finds no camera: is Moverse closed? If you know the camera addresses (for example from
   Moverse's settings), run it from a command window with them: `3_find_cameras.bat <address> <address>`.
5. On the PC that runs Unreal: `git pull`; write the port number the packets should go to into
   `Saved\VisionPort.txt` (one line; any free port, not the Moverse port). Start Play or nDisplay
   Launch. The log (`LogMRLabLive`) shows "Listening for the camera service on UDP port ...".
6. `4_run.bat`: asks once for the Unreal PC's address and port (`address:port`) and the camera ID
   from step 4 (saved in `mrlab_camera_service.local.json` here, not in Git), starts the vision
   model (a minimized "ollama" window) and the camera service. The first start loads the model and
   can take a few minutes. Then each new description is printed, for example
   `view 3 (model 900 ms): Person 1: position: centre, near; clothes: ...`.
   The Unreal log shows "Camera service: first view from ...". Then talk to Frank.
7. To stop: Ctrl+C in the `4_run.bat` window (it also stops Ollama). Start Moverse again if needed.

## If something fails
- A step stops with an error: copy the whole window text to Claude.
- Unreal never logs "first view from": the packets do not arrive. Check the address and port in
  `mrlab_camera_service.local.json` (delete the file to be asked again) and `Saved\VisionPort.txt`;
  then the Unreal PC's firewall (Q29). Frank says he cannot see while no views arrive.
- To change the settings: delete `mrlab_camera_service.local.json`; `4_run.bat` asks again.

## Files
| File | What it does |
|---|---|
| `1_check_pc.bat` ... `4_run.bat` | The steps above; each calls `env.bat` and `tracking_pc.ps1` |
| `env.bat` | Points home, AppData and temp of the window to `runtime\` |
| `tracking_pc.ps1` | The actions check, setup, cameras, run |
| `find_cameras.py` | Lists the OAK cameras and shows one picture of each (read only) |
| `mrlab_camera_service.py` | The camera service (also runs on a laptop with `--source webcam`) |
| `mrlab_camera_service.local.json` | Local settings, written by `4_run.bat`, not in Git |
| `runtime\` | Everything downloaded and every cache, not in Git |
