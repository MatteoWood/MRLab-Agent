r"""Brings this folder's code (everything of TrackingPC in Git: hub, tools, scripts, MRLabHub.exe) to a
version from GitHub, in one go. Usually started by double-clicking update.bat (GUIDE.md, section 1); or,
in the TrackingPC folder:
    runtime\python\python.exe tools\update.py            the newest version
    runtime\python\python.exe tools\update.py b09109f    a given version (a commit)

Only this folder is changed:
- it runs only from tools\ of a TrackingPC folder (next to MRLabHub.exe and hub\), and every file it writes
  must lie inside that folder (checked before writing);
- runtime\, hub.local.json and the recordings are never written (they are not in Git anyway);
- everything is downloaded into runtime\temp\update\ first; then it checks that every file to replace can be
  written (MRLabHub.exe cannot while the hub runs); only then are the changed files copied over the old
  ones. If anything fails before that, nothing is changed. Files here that the version does not have are
  listed and kept (nothing is deleted).
Only standard Python, no Git needed.
"""
import json
import pathlib
import shutil
import sys
import time
import urllib.error
import urllib.request

REPO = "MatteoWood/MRLab-Agent"
FOLDER = "TrackingPC"
HERE = pathlib.Path(__file__).resolve().parent.parent  # the TrackingPC folder
STAGE = HERE / "runtime" / "temp" / "update"
LFS = b"version https://git-lfs.github.com/spec/v1"   # start of a Git LFS pointer (e.g. hub/icon.png)
NEVER = ("runtime", "recordings")                      # top-level folders never written


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "MRLab-Hub-update"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code in (403, 429) and error.headers.get("X-RateLimit-Remaining") == "0":
            reset = time.strftime("%H:%M", time.localtime(int(error.headers.get("X-RateLimit-Reset", "0"))))
            sys.exit(f"GitHub answers only 60 version questions an hour from one network (an update asks 2); "
                     f"try again after {reset}. Nothing was changed.")
        raise


def listing(commit):
    """Paths of all files of FOLDER at the commit: GitHub's list of all files of that version (one request)."""
    tree = json.loads(fetch(f"https://api.github.com/repos/{REPO}/git/trees/{commit['commit']['tree']['sha']}?recursive=1"))
    if tree.get("truncated"):
        raise RuntimeError("GitHub sent only part of the list of files")
    return [entry["path"] for entry in tree["tree"] if entry["type"] == "blob" and entry["path"].startswith(FOLDER + "/")]


def inside(relative):
    """The file's place in this folder, or None if it would lie outside it or in a folder never written."""
    target = (HERE / relative).resolve()
    if HERE not in target.parents or target.parts[len(HERE.parts)].lower().startswith(NEVER) \
            or target.name.lower().endswith(".local.json"):
        return None
    return target


def same(target, copy):
    """Whether the file here equals the downloaded one (a file that cannot be read counts as different)."""
    try:
        return target.is_file() and target.read_bytes() == copy.read_bytes()
    except OSError:
        return False


def update(commit):
    """Downloads the version into STAGE, then replaces the changed files; ({target: copy}, [changed targets])."""
    sha, files = commit["sha"], {}  # files: target in this folder -> downloaded copy
    try:
        for path in listing(commit):
            relative = pathlib.PurePosixPath(path).relative_to(FOLDER)
            target = inside(relative)
            if target is None:
                print(f"  skipped {relative}: not to be written by an update")
                continue
            data = fetch(f"https://raw.githubusercontent.com/{REPO}/{sha}/{path}")
            if data.startswith(LFS):
                data = fetch(f"https://media.githubusercontent.com/media/{REPO}/{sha}/{path}")
            if path.endswith((".bat", ".ps1")):  # Windows line ends, as Git checks them out (.gitattributes)
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            copy = STAGE / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(data)
            files[target] = copy
    except Exception as error:
        sys.exit(f"Download failed ({error}). Nothing was changed.")
    changed = [t for t, c in files.items() if not same(t, c)]
    for target in changed:  # all replaceable before the first one is replaced
        try:
            if target.exists():
                with open(target, "r+b"):
                    pass
        except OSError:
            sys.exit(f"{target.relative_to(HERE)} cannot be replaced: is the hub (MRLabHub) still open? Close it and "
                     "run the update again. Nothing was changed.")
    for target in changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files[target], target)
    return files, changed


def main():
    if not ((HERE / "MRLabHub.exe").is_file() and (HERE / "hub").is_dir()):
        sys.exit(f"{HERE} is not the TrackingPC folder (no MRLabHub.exe and hub folder): nothing was changed.")
    wanted = sys.argv[1] if len(sys.argv) > 1 else "main"
    try:
        commit = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits/{wanted}"))
    except Exception as error:
        sys.exit(f"Could not reach GitHub or find version '{wanted}': {error}. Nothing was changed.")
    sha = commit["sha"]
    print(f"Version {sha[:7]} of {commit['commit']['committer']['date'][:10]}: {commit['commit']['message'].splitlines()[0]}")
    shutil.rmtree(STAGE, ignore_errors=True)
    try:
        files, changed = update(commit)
    finally:
        shutil.rmtree(STAGE, ignore_errors=True)
    names = sorted(str(t.relative_to(HERE)) for t in changed)
    print(f"{len(changed)} of {len(files)} files changed" + (":\n  " + "\n  ".join(names) if names else ": already up to date."))
    known = {t.relative_to(HERE) for t in files}
    extra = sorted(str(p.relative_to(HERE)) for folder in ("hub", "tools") for p in (HERE / folder).rglob("*.py")
                   if p.relative_to(HERE) not in known and "__pycache__" not in p.parts)
    if extra:
        print("Not in this version (kept): " + ", ".join(extra))


if __name__ == "__main__":
    main()
