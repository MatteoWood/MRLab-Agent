"""The local Ollama server for the vision model.

With the runtime folder (runtime\\ollama\\ollama.exe) the hub starts its own server, hidden, on the
address in OLLAMA_HOST (set by MRLabHub.exe to its own port) with the models in OLLAMA_MODELS
(runtime\\models), and stops it when the hub closes. Without it (laptop development) an Ollama that is
already running is used.
"""
import collections
import pathlib
import subprocess
import threading

from hub.vision import ollama_address, ollama_request

EXE = pathlib.Path(__file__).resolve().parent.parent / "runtime" / "ollama" / "ollama.exe"


class OllamaServer:
    def __init__(self):
        self.process = None
        self.log = collections.deque(maxlen=200)
        self.own = EXE.exists()

    def start(self):
        if not self.own or self.process is not None:
            return
        self.process = subprocess.Popen([str(EXE), "serve"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self.read_log, daemon=True).start()

    def read_log(self):
        for line in self.process.stdout:
            self.log.append(line.decode("utf-8", "replace").rstrip())

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            self.process = None

    @staticmethod
    def status():
        """{"version", "models": [names], "loaded": {name: GPU bytes}}; raises OSError if not reachable."""
        version = ollama_request("GET", "/api/version", timeout=2)["version"]
        models = sorted(m["name"] for m in ollama_request("GET", "/api/tags", timeout=2).get("models", []))
        loaded = {m["name"]: m.get("size_vram", 0) for m in ollama_request("GET", "/api/ps", timeout=2).get("models", [])}
        return {"version": version, "models": models, "loaded": loaded}

    @staticmethod
    def address():
        return "%s:%d" % ollama_address()
