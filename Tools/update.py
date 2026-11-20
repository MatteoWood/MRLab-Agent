r"""Brings this project folder (the LED wall PC's copy of the repo) to a version from GitHub, in one go.
Usually started by double-clicking update.bat in the project folder (README 4.1); or, in that folder:
    "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -I Tools\update.py
    ... -I Tools\update.py c2f6a54    a given version (a commit) instead of the newest
    ... -I Tools\update.py locked     also takes the locked NDC_Basic files without asking (see below)

Same idea as TrackingPC\tools\update.py, for the whole project; no Git or Git LFS needed:
- it compares every file of the version with the file here (as stored in Git, as its LFS pointer, or with
  Windows line ends) and downloads only the ones that differ or are LFS placeholders, checked against GitHub;
- it refuses while Unreal runs (editor or nDisplay window), and checks that every file to replace can be
  written; if anything fails before the first file is replaced, nothing is changed;
- each replaced file is first copied to Saved\UpdateBackup\<date_time>\;
- the locked nDisplay config NDC_Basic and its level actor (README 4.3) are written only when you say so: when
  one differs, the update says which commit changed it and whether the file here is an earlier version from
  the repo or has changes made on this PC, and asks; anything but "yes" keeps the file here;
- Saved, Plugins\MoversePlugin, CLAUDE.md and other untracked files are never written; files here that the
  version does not have are listed and kept (nothing is deleted);
- if the folder is a Git clone and Git is installed, Git's record of the version (HEAD and index) is moved to
  the new version afterwards (git fetch, git reset), so git status shows only real differences. The files
  are not touched by that.
"""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = "MatteoWood/MRLab-Agent"
HERE = pathlib.Path(__file__).resolve().parent.parent  # the project folder
STAGE = HERE / "Saved" / "UpdateTemp"
BACKUP = HERE / "Saved" / "UpdateBackup" / time.strftime("%Y-%m-%d_%H%M%S")
LFS = b"version https://git-lfs.github.com/spec/v1"  # start of a Git LFS pointer (placeholder)
NEVER = ("saved/", ".git/", "binaries/", "intermediate/", "deriveddatacache/", "plugins/moverseplugin/",
         "trackingpc/runtime/", "claude.md")  # never written (lower case, from the project folder)
LOCKED = ("Content/ExampleConfigs/NDC_Basic.uasset",
          "Content/__ExternalActors__/DefaultMap/8/20/BYDHEQD265B040BKAIZ09D.uasset")  # README 4.3, D54


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "MRLab-wall-update"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code in (403, 429) and error.headers.get("X-RateLimit-Remaining") == "0":
            reset = time.strftime("%H:%M", time.localtime(int(error.headers.get("X-RateLimit-Reset", "0"))))
            sys.exit(f"GitHub answers only 60 version questions an hour from one network (an update asks 2); "
                     f"try again after {reset}. Nothing was changed.")
        raise


def blob_id(data):
    """Git's id of a file with this content."""
    h = hashlib.sha1(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def pointer(data):
    """The Git LFS pointer of a file with this content."""
    return b"%s\noid sha256:%s\nsize %d\n" % (LFS, hashlib.sha256(data).hexdigest().encode(), len(data))


def same(target, sha):
    """Whether the file here is the version's file (Git id sha). A placeholder (LFS pointer) never is."""
    try:
        data = target.read_bytes()
    except OSError:
        return False
    if data.startswith(LFS):
        return False
    if blob_id(data) == sha or blob_id(pointer(data)) == sha:
        return True
    return b"\0" not in data and b"\r\n" in data and blob_id(data.replace(b"\r\n", b"\n")) == sha


def download(sha, path, blob):
    """The version's file at path (Git id blob), the real content for LFS files; checked against its id."""
    data = fetch(f"https://raw.githubusercontent.com/{REPO}/{sha}/{urllib.parse.quote(path)}")
    if blob_id(data) != blob:
        raise RuntimeError(f"{path} arrived damaged")
    if data.startswith(LFS):
        oid = data.split(b"oid sha256:")[1].split(b"\n")[0].decode()
        data = fetch(f"https://media.githubusercontent.com/media/{REPO}/{sha}/{urllib.parse.quote(path)}")
        if hashlib.sha256(data).hexdigest() != oid:
            raise RuntimeError(f"{path} arrived damaged")
    elif path.endswith((".bat", ".ps1")):  # Windows line ends, as Git checks them out (.gitattributes)
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def inside(path):
    """The file's place in this folder, or None if it would lie outside it or must never be written."""
    target = (HERE / path).resolve()
    low = path.lower()
    if HERE not in target.parents or low.startswith(NEVER) or low.endswith(".local.json"):
        return None
    return target


def locked_changes(sha, path, target):
    """What to tell about a locked file that differs: (the commit that last changed it in this version, what the
    file here is). One more question to GitHub per file."""
    try:
        data = target.read_bytes()
    except OSError:
        return "", "there is no such file here"
    if data.startswith(LFS):
        return "", "the file here is only a placeholder, not the real file"
    try:
        commits = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits?path={urllib.parse.quote(path)}"
                                   f"&sha={sha}&per_page=6"))
    except Exception:
        return "", "could not ask GitHub about the file's earlier versions"
    last = commits[0]
    changed = f"{last['sha'][:7]} of {last['commit']['committer']['date'][:10]}: {last['commit']['message'].splitlines()[0]}"
    for earlier in commits[1:]:
        try:
            old = fetch(f"https://raw.githubusercontent.com/{REPO}/{earlier['sha']}/{urllib.parse.quote(path)}")
        except Exception:
            continue
        if old in (data, pointer(data)):
            return changed, (f"the file here is the repo's earlier version ({earlier['sha'][:7]} of "
                             f"{earlier['commit']['committer']['date'][:10]}), without changes made on this PC")
    return changed, "the file here is NOT a version from the repo: it has changes made on this PC, which a replacement would drop"


def take_locked(sha, path, target, without_asking):
    """Whether to replace a locked file that differs (README 4.3: only when a change to NDC_Basic was agreed)."""
    changed, here = locked_changes(sha, path, target)
    print(f"\nLOCKED (README 4.3), differs from this version: {path}")
    if changed:
        print(f"  last changed in this version by {changed}")
    print(f"  {here}")
    if without_asking:
        print("  replaced, as asked (locked)")
        return True
    print("  Replace it with this version's file? Only if this change to NDC_Basic was agreed. The file here is kept\n"
          "  in Saved\\UpdateBackup, and the 3D on the wall should be checked afterwards.")
    try:
        answer = input("  Type yes to replace it, or just press Enter to keep the file here: ")
    except EOFError:
        answer = ""
    return answer.strip().lower() == "yes"


def record_in_git(sha):
    """Moves Git's record of the version to sha (git fetch, git reset --mixed); the files are not touched."""
    if not (HERE / ".git").exists() or shutil.which("git") is None:
        return
    git = ["git", "-C", str(HERE)]
    if subprocess.run(git + ["fetch", "-q", "origin"]).returncode == 0 \
            and subprocess.run(git + ["reset", "-q", sha]).returncode == 0:
        print(f"Git now records version {sha[:7]}.")
    else:
        print("Git's record of the version was not moved (message above); the files are updated anyway.")


def main():
    if not (HERE / "MRLabProject58.uproject").is_file():
        sys.exit(f"{HERE} is not the project folder (no MRLabProject58.uproject): nothing was changed.")
    tasks = subprocess.run(["tasklist", "/FI", "IMAGENAME eq UnrealEditor.exe", "/NH"],
                           capture_output=True, text=True).stdout
    if "UnrealEditor.exe" in tasks:
        sys.exit("Unreal is still running (editor or nDisplay window): close it and run the update again. "
                 "Nothing was changed.")
    arguments = [a for a in sys.argv[1:] if a.lower() != "locked"]
    without_asking = len(arguments) < len(sys.argv) - 1
    wanted = arguments[0] if arguments else "main"
    try:
        commit = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits/{wanted}"))
        tree = json.loads(fetch(f"https://api.github.com/repos/{REPO}/git/trees/"
                                f"{commit['commit']['tree']['sha']}?recursive=1"))
    except Exception as error:
        sys.exit(f"Could not reach GitHub or find version '{wanted}': {error}. Nothing was changed.")
    if tree.get("truncated"):
        sys.exit("GitHub sent only part of the list of files. Nothing was changed.")
    sha = commit["sha"]
    print(f"Version {sha[:7]} of {commit['commit']['committer']['date'][:10]}: "
          f"{commit['commit']['message'].splitlines()[0]}")
    blobs = {e["path"]: e["sha"] for e in tree["tree"] if e["type"] == "blob"}
    print(f"Comparing {len(blobs)} files with the ones here...")
    changed, locked = {}, []  # changed: path -> target
    for path, blob in blobs.items():
        target = inside(path)
        if target is None:
            print(f"  skipped {path}: not to be written by an update")
        elif not same(target, blob):
            if path in LOCKED and not take_locked(sha, path, target, without_asking):
                locked.append(path)
            else:
                changed[path] = target
    shutil.rmtree(STAGE, ignore_errors=True)
    try:
        if changed:
            print(f"Downloading {len(changed)} files...")
        try:
            for path in changed:
                copy = STAGE / path
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_bytes(download(sha, path, blobs[path]))
        except Exception as error:
            sys.exit(f"Download failed ({error}). Nothing was changed.")
        for path, target in changed.items():  # all replaceable before the first one is replaced
            try:
                if target.exists():
                    with open(target, "r+b"):
                        pass
            except OSError:
                sys.exit(f"{path} cannot be replaced: is a program still using it? Close it and run the update "
                         "again. Nothing was changed.")
        for path, target in changed.items():
            if target.exists():
                (BACKUP / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, BACKUP / path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(STAGE / path, target)
    finally:
        shutil.rmtree(STAGE, ignore_errors=True)
    print(f"{len(changed)} of {len(blobs)} files changed"
          + (":\n  " + "\n  ".join(sorted(changed)) if changed else ": already up to date."))
    if BACKUP.exists():
        print(f"The replaced files are kept in {BACKUP.relative_to(HERE)}")
    for path in locked:
        print(f"NOT replaced, locked (README 4.3), still differs from this version: {path}")
    for path in changed:
        if path in LOCKED:
            print(f"REPLACED, locked (README 4.3): {path}. Check the 3D on the wall.")
    extra = sorted(p.relative_to(HERE).as_posix() for folder in ("Content", "Config")
                   for p in (HERE / folder).rglob("*") if p.is_file() and p.relative_to(HERE).as_posix() not in blobs)
    if extra:
        print("Not in this version (kept):\n  " + "\n  ".join(extra))
    record_in_git(sha)


if __name__ == "__main__":
    main()
