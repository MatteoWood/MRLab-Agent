"""Run Python inside the running Unreal Editor (Python remote execution).

Usage:
    python Tools/ue_py.py script.py
    python Tools/ue_py.py -c "print(unreal.SystemLibrary.get_engine_version())"

Needs bRemoteExecution=True in Config/DefaultEngine.ini and the editor open.
"""
import sys
import time

sys.path.insert(0, r"C:\Program Files\Epic Games\UE_5.8\Engine\Plugins\Experimental\PythonScriptPlugin\Content\Python")
import remote_execution

PROJECT = "MRLabProject58"


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "-c":
        code = sys.argv[2]
    elif len(sys.argv) == 2:
        with open(sys.argv[1], encoding="utf-8") as f:
            code = f.read()
    else:
        sys.exit(__doc__)

    remote = remote_execution.RemoteExecution()
    remote.start()
    try:
        node = None
        deadline = time.time() + 5
        while node is None and time.time() < deadline:
            node = next((n for n in remote.remote_nodes if n.get("project_name") == PROJECT), None)
            time.sleep(0.1)
        if node is None:
            sys.exit(f"No running editor with project {PROJECT} found.")
        remote.open_command_connection(node["node_id"])
        data = remote.run_command(code)
    finally:
        remote.stop()

    for entry in data["output"]:
        print(entry["output"], end="" if entry["output"].endswith("\n") else "\n",
              file=sys.stderr if entry["type"] == "Error" else sys.stdout)
    if not data["success"]:
        print(data["result"], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
