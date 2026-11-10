"""Entry point (pythonw -m hub). The window has no console, so a crash is written to runtime\\temp\\hub_error.txt
(inside this folder) and shown in a message box. The camera helper programs (hub/cameras.py) start this file
again under another name; the check below keeps them from opening a window."""
import ctypes
import pathlib
import traceback

if __name__ == "__main__":
    try:
        from hub.app import main

        main()
    except SystemExit:
        raise
    except BaseException:
        text = traceback.format_exc()
        report = pathlib.Path(__file__).resolve().parent.parent / "runtime" / "temp" / "hub_error.txt"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(text)
        ctypes.windll.user32.MessageBoxW(None, f"{text[-1500:]}\n\nSaved in {report}", "MRLab Hub error", 0x10)
