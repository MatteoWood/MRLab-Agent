r"""The whole hub on the laptop, with a recording played as the cameras (tools/fakecams): search, connect, the
calibration, Start tracking, then for --seconds: people, state, rate, picture age, the calibration watch, the
packets (sent to a port on this PC and counted there) and the log. With --record the tracking log is written
too and then replayed (replay_tracking.py), which must give every sent head exactly as the hub sent it.
    runtime\python\python.exe tools\live_test.py recordings\<run folder> [--calibration file] [--seconds 40] [--record]
Calibration: --calibration (saved by replay_calibration.py) or the one in use in hub.local.json. The hub's
settings are not saved by this test.
"""
import argparse
import os
import pathlib
import socket
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
PORT = 54399


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder")
    parser.add_argument("--calibration")
    parser.add_argument("--seconds", type=float, default=40.0)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    os.environ["FAKE_RECORDING_DIR"] = str(pathlib.Path(args.folder).resolve())
    sys.path.insert(0, str(HERE / "fakecams"))  # before the real DepthAI, also for the cameras' helper processes
    sys.path.insert(1, str(HERE))
    import replay
    from PySide6.QtWidgets import QApplication
    from hub import app

    poses = replay.load_calibration(args.calibration)
    received = []

    def listen():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", PORT))
        while True:
            received.append(sock.recvfrom(65536)[0])

    threading.Thread(target=listen, daemon=True).start()
    app.SETTINGS = app.ROOT / "runtime" / "temp" / "live_test.local.json"  # the hub's own settings stay as they are
    app.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    app.SETTINGS.unlink(missing_ok=True)
    qt = QApplication([])
    hub = app.Hub(False)
    hub.show()

    def wait(seconds, until=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end and not (until and until()):
            qt.processEvents()
            time.sleep(0.02)

    wait(20, lambda: len(hub.cameras) >= 2)
    hub.connect_cameras()
    wait(60, lambda: all(c.status == "streaming" for c in hub.cameras))
    print(f"{len(hub.cameras)} cameras streaming")
    hub.settings["calibration"] = {"cameras": poses, "score": 0, "report": [], "made": "test"}
    hub.settings["unreal_address"], hub.settings["moverse_port"] = "127.0.0.1", PORT
    hub.select_page(app.PAGES.index("Tracking"))
    if args.record:
        hub.record_button.setChecked(True)  # before Start tracking: the log starts with the tracker
    hub.start_tracking()
    wait(30, lambda: hub.tracker and hub.tracker.position is not None)
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        wait(min(5.0, end - time.monotonic()))
        t = hub.tracker
        print(f"people {len(t.people)}, main P{t.main}, state {t.motion}, rate {t.rate:.0f}/s, picture age "
              f"{t.age or 0:.0f} ms, cameras combined {t.combined}, pose ms {[round(c.pose_ms or 0) for c in hub.cameras]}")
    t = hub.tracker
    print("calibration watch (degrees):", {n: round(m, 2) for n, m in sorted(t.agreement.items())}, "marked:", sorted(t.moved))
    print(f"packets sent {t.sent}, received here {len(received)}")
    path = t.recorder.path if t.recorder else None
    hub.stop_tracking()
    print("log:\n  " + "\n  ".join(line for line in list(hub.log_lines)[-12:] if "opened in" not in line))
    hub.close()
    if path:
        r = replay.replay_log(replay.tracker_module(), path)
        print(f"tracking log replayed: {r['same']} of {r['logged']} sent heads exactly as the hub sent them")


if __name__ == "__main__":
    main()
