r"""Sends console commands to the running nDisplay node (NDC_Basic / Node_0) on this PC, as Switchboard does:
a cluster event "console exec" to the node's JSON events port (41003 in NDC_Basic).

    python Tools/node_console.py "stat fps"
    python Tools/node_console.py "r.GPUCsvStatsEnabled 1" "CsvProfile Start"     several commands, in order
    python Tools/node_console.py quit                                           ends the node cleanly

On the LED wall PC use the engine's Python:
    "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" Tools\node_console.py "..."
Each command is also written to the node's log (Saved/Logs/Node_0.log). Screen messages are switched off in
the node (DisableAllScreenMessages), so "stat" displays do not show; Tools/node_fps.py reads the frame rate
from the log instead.
"""
import json
import socket
import struct
import sys
import time

PORT = 41003  # ClusterEventsJson of NDC_Basic's primary node


def send(event, host="127.0.0.1", port=PORT):
    data = json.dumps(event).encode()
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(struct.pack("I", len(data)) + data)


def console(command):
    send({"bIsSystemEvent": "true", "Category": "nDisplay", "Type": "control", "Name": "console exec",
          "Parameters": {"ExecString": command, "Executor": ""}})


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for command in sys.argv[1:]:
        try:
            if command.lower() == "quit":
                send({"bIsSystemEvent": "true", "Category": "nDisplay", "Type": "control", "Name": "quit", "Parameters": {}})
            else:
                console(command)
        except OSError as error:
            sys.exit(f"No nDisplay node answers on port {PORT} of this PC ({error}).")
        print("sent:", command)
        time.sleep(0.3)


if __name__ == "__main__":
    main()
