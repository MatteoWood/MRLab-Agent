# MRLab Hub: how to use the tools

Step by step, for the lab. The commands go into a Command Prompt (the black window) opened in the
TrackingPC folder on the tracking PC, unless it says "on the Unreal PC". Copy them as they are.

What is where:
- **Tracking PC**: the 8 cameras, the hub (`MRLabHub.exe`), the recording tool.
- **Unreal PC**: Unreal with `NDC_Basic`; receives the head position from the hub.
- **Laptop**: where Claude replays your recordings to test changes (section 9).

## 1. Update the tracking PC

Close MRLabHub, then **double-click `update.bat`** in the TrackingPC folder. The window asks you to press a
key, then shows the version it brought (a short code like `86aae77`, its date and what changed) and the
files it replaced. Press a key to close it. That is all.

What it does and does not touch:
- It changes files only inside this folder: it checks every file's place before writing, and refuses to run
  if it is not in a TrackingPC folder (next to `MRLabHub.exe` and `hub`). Nothing else on the PC changes.
- It never writes `runtime`, your settings (`hub.local.json`) or the recordings, and deletes nothing.
- It downloads everything first. If the download fails, or the hub is still open (its files cannot be
  replaced then), it says so and nothing is changed.

The first time only, `update.bat` is not there yet. Open the black window in the TrackingPC folder and run:

```bat
curl -L -o update.bat https://raw.githubusercontent.com/MatteoWood/MRLab-Agent/main/TrackingPC/update.bat
```

Then double-click it. To bring a given version instead of the newest, in the black window: `update.bat 86aae77`.

## 2. Start the hub

Double-click `MRLabHub.exe`. If something goes wrong and Claude needs the error, start it from the black
window instead, so the messages stay visible:

```bat
runtime\python\python.exe -X faulthandler -m hub
```

## 3. Calibrate

As in `README.md` ("Procedure in the lab"): Cameras page, Connect; Calibration page: walk with the board
(about 3 minutes), lay it on the floor, enter the measured distance, Compute, Use this calibration.

Read the report: the score, per camera the pixel error (under 0.5 px is good), its height and its focal
length (now measured with all cameras together, about 725 to 740 px; 4 to 5 % below what the cameras
report about themselves, that is expected). Check with a tape: the distance between cameras 2 and 6
(the report says how far apart they came out). Send the report to Claude.

## 4. Tracking: what the Tracking page shows

Press **Start tracking**. Under the camera picture:
- **X, Y, Z**: the head position sent to Unreal (cm; X towards the wall, Y to the right, Z up).
- **Rate**: head positions sent per second.
- **Picture age**: how old the newest picture is when its head position is sent (ms): the hub's part of
  the delay. Unreal and the wall add their own on top (section 8).
- **State**: **standing** (the sent head stays exactly where it is, so the view on the wall is still) or
  **moving** (it follows at once). Swaying gently on the spot stays "standing". A move shows on the wall once
  the head is 1.5 to 4 cm away from where you stood.

On the left, after about 20 seconds with someone in the room, the **calibration watch**: per camera, by how
many degrees it points beside where the other cameras see the people. Normal: under 0.2. Above 0.5 the
camera is marked **MOVED? calibrate again**: it was probably bumped or turned since the calibration.
Calibrate again (section 3).

## 5. Record tracking data (a log, no pictures)

To let Claude replay a lab session exactly, with any newer version of the tracking:
1. On the Tracking page press **Record tracking data** (it stays pressed), then **Start tracking**.
2. Do what you want to test. Every Start/Stop of tracking makes its own file.
3. Press **Stop tracking**. The Log (Vision page) says where the file is:
   `recordings\tracking_<date>_<time>.jsonl.gz`, about 7 MB a minute.

It holds numbers only: where the cameras saw people's body points, and the head positions sent. No
pictures. Copy the file to the laptop (USB stick) into `TrackingPC\recordings\` and tell Claude its name.

Pressing it while tracking already runs also works, but then the replay is not exact for the first seconds.

## 6. Record a test run (with pictures)

For testing the tracking on the laptop with known truth. These recordings show you: they stay on the PCs,
never in Git. Close the hub and Moverse first (they hold the cameras).

Once, tape two marks on the floor:
- **A**: 150 cm in front of the middle of the LED wall (measured from the bottom of the wall).
- **B**: also 150 cm in front, and 100 cm to the right (seen facing the wall).

Then:

```bat
runtime\python\python.exe record_cameras.py
```

It asks for your eye height (floor to eyes, cm), opens the cameras, counts down 10 seconds, then shows
what to do and beeps at each change (about 60 seconds in all): stand still on A, sway gently on A, lean
towards the wall and back, step aside and back, walk to B and stand, walk around freely.

Other kinds:
- `runtime\python\python.exe record_cameras.py two`: the same, and a second person walks in at the end.
- `runtime\python\python.exe record_cameras.py board`: the calibration board, 60 seconds walking with it,
  then 15 seconds on the floor; at the end it asks for the measured distance of the board from the wall.
- `runtime\python\python.exe record_cameras.py free 30`: 30 seconds of whatever you do.

Each run goes into its own folder, `recordings\<date>_<time>_<kind>\` (about 11 MB a second per camera:
about 5 GB for a guided run). Copy the folder to the laptop (USB stick, or an external drive) into
`TrackingPC\recordings\` and tell Claude its name.

## 7. Do the packets arrive at the Unreal PC?

When Unreal does not move with you although the hub's "packets sent" counts up:

1. On the tracking PC, the Log (Vision page) says from which of its addresses the hub sends:
   "first packet sent to ... from this PC's address ...". If it adds "that is the cameras' network", the
   packets go out on the wrong network card: tell Claude.
2. On the Unreal PC: close Unreal (it holds the port). In a Command Prompt in the project folder (where
   `MRLabProject58.uproject` is):

   ```bat
   "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" Tools\udp_listen.py 54321
   ```

   (54321 is the Moverse port; if `runtime\defaults.json` on the tracking PC says another, use that.)
   Start tracking on the hub and walk in front of the cameras. Every second it prints how many packets
   arrived, from which address, and the head position in them (compare with X/Y/Z on the hub).
   If Windows asks whether Python may use the network: that is your or IT's decision; without allowing
   it, this test may show nothing even when packets arrive. Ctrl+C stops it.
3. Packets arrive: the network is fine, the problem is in Unreal (Live Link source and preset): tell Claude.
   Nothing arrives: on the tracking PC check the way to the Unreal PC (both only read, nothing changes):

   ```bat
   ping <Unreal PC address>
   ```

   ```bat
   powershell Find-NetRoute -RemoteIPAddress <Unreal PC address>
   ```

   (the Unreal PC address is `unreal_address` in `runtime\defaults.json`). Send Claude what they print.

## 8. Measure the delay from your head to the wall

How long the view on the wall takes to follow your head. Claude then sets how far ahead the hub moves the
head to make up for it.

1. Tracking running, Unreal showing the wall in 3D, a scene with things near and far (the view shifts
   clearly when you move your head).
2. Film with a phone in slow motion (240 frames a second if it can), so that your head and the wall are both
   in the picture.
3. Move your head quickly sideways and stop it sharply. Five times, with a pause between.
4. In the video, step frame by frame: count the frames from the moment your head stops to the moment the
   view on the wall stops. Delay = frames / 240 seconds (for example 30 frames = 125 ms).
5. Note the hub's **Picture age** at the time. Send Claude the five frame counts and the picture age.

## 9. On the laptop: the test tools (for Claude)

In the TrackingPC folder of the laptop; each prints what it measures (details at the top of each file):

| Command | What it does |
|---|---|
| `runtime\python\python.exe tools\pose_pass.py recordings\<run>` | runs the hub's pose model over every picture of a recording; saves the numbers next to it (`people.json.gz`) |
| `runtime\python\python.exe tools\replay_calibration.py recordings\<board run> --save cal.json` | the calibration as the hub computes it, checked on moments it did not use; `--half even` / `odd`: two independent ones |
| `runtime\python\python.exe tools\replay_tracking.py recordings\<run> --calibration cal.json` | the tracking on a recording as if live; per phase of a guided run: standing still, moving, distance from marks A and B |
| `runtime\python\python.exe tools\replay_tracking.py recordings\tracking_<...>.jsonl.gz` | a lab session's log replayed (exactly, with the version that wrote it) |
| `runtime\python\python.exe tools\test_person.py recordings\<walking run>` | a test person on a known path with real camera noise: steadiness, delay, overshoot |
| `runtime\python\python.exe tools\live_test.py recordings\<run> --record` | the whole hub with a recording played as the cameras |

Any of the replays takes `--tracker <file>` to try another version of `hub\tracking.py` on the same data.

## 10. Deleting recordings

Everything recorded is in the `recordings` folder (and the older `recordings_walking`,
`recordings_calibration`). Delete a run's folder, or the whole `recordings` folder, when it is no longer
needed. The numbers the tools derive from a recording (`people.json.gz`, `board_corners.json.gz`,
`test_person_noise.npz`) are next to it and go with it.
