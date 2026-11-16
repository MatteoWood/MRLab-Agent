r"""Brings this folder's code (everything of TrackingPC in Git: hub, tools, scripts, MRLabHub.exe) to a
version from GitHub, in one go. Close the hub first. In the TrackingPC folder:
    runtime\python\python.exe tools\update.py            the newest version
    runtime\python\python.exe tools\update.py b09109f    a given version (a commit)
Downloads every file into runtime\temp\update\ first; only when all arrived are the changed ones copied
over the old ones. runtime\, hub.local.json and the recordings are not in Git and stay untouched. Files
here that the version does not have are listed and kept. Only standard Python, no Git needed.
"""
import json
import pathlib
import shutil
import sys
import urllib.request

REPO = "MatteoWood/MRLab-Agent"
FOLDER = "TrackingPC"
HERE = pathlib.Path(__file__).resolve().parent.parent  # the TrackingPC folder
LFS = b"version https://git-lfs.github.com/spec/v1"   # start of a Git LFS pointer (e.g. hub/icon.png)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "MRLab-Hub-update"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def listing(path, ref):
    """Paths of all files under path at ref (GitHub contents API, one request per folder)."""
    files = []
    for entry in json.loads(fetch(f"https://api.github.com/repos/{REPO}/contents/{path}?ref={ref}")):
        if entry["type"] == "dir":
            files += listing(entry["path"], ref)
        elif entry["type"] == "file":
            files.append(entry["path"])
    return files


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else "main"
    try:
        commit = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits/{wanted}"))
    except Exception as error:
        sys.exit(f"Could not reach GitHub or find version '{wanted}': {error}. Nothing was changed.")
    sha = commit["sha"]
    print(f"Version {sha[:7]} of {commit['commit']['committer']['date'][:10]}: {commit['commit']['message'].splitlines()[0]}")
    stage = HERE / "runtime" / "temp" / "update"
    shutil.rmtree(stage, ignore_errors=True)
    try:
        paths = listing(FOLDER, sha)
        for path in paths:
            data = fetch(f"https://raw.githubusercontent.com/{REPO}/{sha}/{path}")
            if data.startswith(LFS):
                data = fetch(f"https://media.githubusercontent.com/media/{REPO}/{sha}/{path}")
            if path.endswith((".bat", ".ps1")):  # Windows line ends, as Git checks them out (.gitattributes)
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            target = stage / path[len(FOLDER) + 1:]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    except Exception as error:
        shutil.rmtree(stage, ignore_errors=True)
        sys.exit(f"Download failed ({error}). Nothing was changed.")
    changed = []
    for source in sorted(p for p in stage.rglob("*") if p.is_file()):
        relative = source.relative_to(stage)
        target = HERE / relative
        if target.exists() and target.read_bytes() == source.read_bytes():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        except PermissionError:
            sys.exit(f"Could not replace {relative}: is the hub still open? Close it and run this again.")
        changed.append(str(relative))
    shutil.rmtree(stage, ignore_errors=True)
    known = {pathlib.Path(p[len(FOLDER) + 1:]) for p in paths}
    extra = sorted(str(p.relative_to(HERE)) for folder in ("hub", "tools") for p in (HERE / folder).rglob("*.py")
                   if p.relative_to(HERE) not in known and "__pycache__" not in p.parts)
    print(f"{len(changed)} of {len(paths)} files changed" + (":\n  " + "\n  ".join(changed) if changed else "."))
    if extra:
        print("Not in this version (kept): " + ", ".join(extra))


if __name__ == "__main__":
    main()
