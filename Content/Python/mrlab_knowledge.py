"""Update the agent's lab knowledge: download the Markdown files of the GitLab knowledge repo
into Saved/Knowledge. The agent (MRLabLive plugin) only reads that local copy.
The GitLab token (read_api) is read from Saved/GitLabToken.txt."""
import http.client
import io
import os
import shutil
import zipfile

import unreal

HOST = "gitlab.tuwien.ac.at"
PROJECT = "mixed-reality-labor%2Fmrlab-agent-knowledge"


def _saved(*parts):
    return os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir()), *parts)


def download():
    """Replace Saved/Knowledge with the .md files of the repo's default branch.
    Returns (number of files, commit). On any error the old files stay."""
    with open(_saved("GitLabToken.txt"), encoding="utf-8") as f:
        token = f.read().strip()
    connection = http.client.HTTPSConnection(HOST, timeout=30)
    connection.request("GET", f"/api/v4/projects/{PROJECT}/repository/archive.zip", headers={"PRIVATE-TOKEN": token})
    response = connection.getresponse()
    body = response.read()
    if response.status != 200:
        raise RuntimeError(f"GitLab answered {response.status}: {body[:200].decode(errors='replace')}")

    new_dir = _saved("Knowledge.new")
    shutil.rmtree(new_dir, ignore_errors=True)
    count = 0
    commit = ""
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for name in archive.namelist():
            # Entries look like "<project>-<branch>-<commit>/path/file.md".
            top, _, path = name.partition("/")
            commit = top.rsplit("-", 1)[-1][:8]
            if path.lower().endswith(".md"):
                target = os.path.join(new_dir, *path.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(archive.read(name))
                count += 1

    old_dir = _saved("Knowledge")
    shutil.rmtree(old_dir, ignore_errors=True)
    os.rename(new_dir, old_dir)
    return count, commit


def update():
    """Toolbar button: download, then report the result in a message box."""
    try:
        with unreal.ScopedSlowTask(1, "Updating lab knowledge from GitLab") as task:
            task.make_dialog()
            count, commit = download()
        message = (f"Downloaded {count} knowledge file(s) from GitLab (commit {commit}).\n"
                   "The agent uses them from the next Play or nDisplay Launch.")
    except Exception as error:
        message = f"Knowledge update failed; the local files are unchanged.\n\n{error}"
    unreal.log(message)
    unreal.EditorDialog.show_message("Update Knowledge", message, unreal.AppMsgType.OK)
