r"""Frank at rest in the editor viewport: checks it, and puts him back when he is not (rule: README section 2).

    python Tools/reset_frank.py             check; if he is not at rest, put him back and check again
    python Tools/reset_frank.py --reload    may also load his saved level actor again when only that helps, even
                                            if it has unsaved changes (they are dropped; nothing else is touched)

Run it after anything that touched Frank outside Play: posing or animating him in the editor world, switching
his meshes' animation update in the editor on, reloading or editing BP_Agent or his AnimBPs, an interrupted
test. The editor must be open and not in Play. In Play he moves as designed; this is only about the level as
it stands in the editor.

At rest means, for BP_Agent's actor in the open level:
- every bone of his body is in the mesh's reference pose (upright, arms as modelled, head straight ahead);
- the face mesh sits on the body's head, the outfit follows the body;
- no animation is set to play on his meshes, and their animation update in the editor is off.
(If he gets a standing pose of his own for the editor later, REST_DEGREES and this text change with it.)

What it does when he is not at rest, in this order, checking after each:
1. clears the head target of the body's post-process AnimBP and lets his meshes update for a moment (this
   drops every pose that is not saved with the level: a preview that was stopped, a head left turned, the
   "heap on the floor" after his Blueprint was rebuilt);
2. loads his level actor again from its file, as it was last saved (this drops what a preview changed on the
   actor itself, for example an animation set to play). With unsaved changes on that actor only with --reload.
It saves nothing. If he is still not at rest then, the saved level itself has him posed: restore his actor file
(Content/__ExternalActors__/DefaultMap/B/77/Z6Q065VEMQDI7TPI37X790.uasset) from Git.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ue_py  # noqa: E402  (the editor connection: engine path and project name)

REST_DEGREES = 0.5  # a body bone may differ this much from the reference pose (at rest: 0.000)

EDITOR = r'''
import json, math
import unreal

def _frank_find():
    actors = [a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors() if a.get_class().get_name() == "BP_Agent_C"]
    return actors[0] if len(actors) == 1 else None

def _frank_angle(a, b):
    return math.degrees(2 * math.acos(min(1.0, abs(a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w))))

def _frank_dirty():
    utils = unreal.EditorLoadingAndSavingUtils
    return [p.get_name() for p in list(utils.get_dirty_map_packages()) + list(utils.get_dirty_content_packages())]

def frank_state():
    out = {"play": unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor(), "found": False}
    frank = None if out["play"] else _frank_find()
    if frank is None:
        return out
    meshes = {c.get_name(): c for c in frank.get_components_by_class(unreal.SkeletalMeshComponent)}
    body, face = meshes.get("Body"), meshes.get("Face")
    if body is None or face is None:
        return out
    out["found"] = True
    space = unreal.RelativeTransformSpace
    worst, where = 0.0, ""
    for i in range(1, body.get_num_bones()):
        bone = body.get_bone_name(i)
        off = _frank_angle(body.get_ref_pose_transform(i).rotation, body.get_socket_transform(bone, space.RTS_PARENT_BONE_SPACE).rotation)
        if off > worst:
            worst, where = off, str(bone)
    head, face_head = body.get_socket_transform("head", space.RTS_WORLD), face.get_socket_transform("head", space.RTS_WORLD)
    forward = unreal.MathLibrary.get_right_vector(head.rotation.rotator())  # the head bone looks along its Y axis
    right = frank.get_actor_right_vector()                                  # his face looks along the actor's right vector
    out["bones_off"], out["bone"] = worst, where
    out["head_height"] = head.translation.z - frank.get_actor_location().z
    out["head_off"] = math.degrees(math.acos(max(-1.0, min(1.0, forward.x * right.x + forward.y * right.y + forward.z * right.z))))
    out["face_off"] = max(_frank_angle(head.rotation, face_head.rotation), (head.translation - face_head.translation).length())
    out["updating"] = [n for n, c in meshes.items() if c.get_editor_property("update_animation_in_editor")]
    out["playing"] = [n + ": " + c.get_editor_property("animation_data").get_editor_property("anim_to_play").get_name() for n, c in meshes.items()
                      if c.get_editor_property("animation_data").get_editor_property("anim_to_play")]
    package = frank.get_outermost().get_name()
    out["package"], out["unsaved"] = package, package in _frank_dirty()
    return out

def frank_refresh(on, throttle=True):
    """on: his meshes update in the editor from now on (head target cleared first); returns whether the editor
    slows down in the background, which is switched off meanwhile (a slowed-down editor does not update meshes).
    off: back to no updates, and the slow-down as it was (throttle)."""
    settings = unreal.get_default_object(unreal.load_class(None, "/Script/UnrealEd.EditorPerformanceSettings"))
    before = settings.get_editor_property("bThrottleCPUWhenNotForeground")
    frank = _frank_find()
    for mesh in frank.get_components_by_class(unreal.SkeletalMeshComponent):
        post = mesh.get_post_process_instance()
        if on and post is not None:
            for name, value in (("HeadTarget", unreal.Vector(0, 0, 0)), ("HeadLookWeight", 0.0)):
                try:
                    post.set_editor_property(name, value, unreal.PropertyAccessChangeNotifyMode.NEVER)
                except Exception:
                    pass
        mesh.set_update_animation_in_editor(on)
    levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if on:
        levels.editor_set_viewport_realtime(True)  # meshes only update with a realtime viewport (Unreal's default)
    settings.set_editor_property("bThrottleCPUWhenNotForeground", False if on else throttle)
    levels.editor_invalidate_viewports()
    return before

def frank_reload():
    frank = _frank_find()
    package = frank.get_outermost()
    return unreal.EditorLoadingAndSavingUtils.reload_packages([package], unreal.ReloadPackagesInteractionMode.ASSUME_POSITIVE)[0]
'''


class Editor:
    def __init__(self):
        self.remote = ue_py.remote_execution.RemoteExecution()
        self.remote.start()
        node, deadline = None, time.time() + 5
        while node is None and time.time() < deadline:
            node = next((n for n in self.remote.remote_nodes if n.get("project_name") == ue_py.PROJECT), None)
            time.sleep(0.1)
        if node is None:
            self.remote.stop()
            sys.exit(f"No running editor with project {ue_py.PROJECT} found.")
        self.remote.open_command_connection(node["node_id"])

    def run(self, call):
        """Runs one of the functions above in the editor; returns what it returned."""
        data = self.remote.run_command(EDITOR + f"\nprint('FRANK ' + json.dumps({call}))")
        if not data["success"]:
            self.remote.stop()
            sys.exit(f"The editor could not run {call}: {data['result']}")
        line = next(e["output"] for e in data["output"] if e["output"].startswith("FRANK "))
        return json.loads(line[6:])

    def close(self):
        self.remote.stop()


def problems(state):
    found = []
    if state["bones_off"] > REST_DEGREES:
        found.append(f"his body is not in the reference pose (bone {state['bone']} is {state['bones_off']:.1f} degrees off)")
    if not 150 <= state["head_height"] <= 185:
        found.append(f"his head is {state['head_height']:.0f} cm above his feet (collapsed?)")
    if state["head_off"] > 2:
        found.append(f"his head looks {state['head_off']:.1f} degrees away from straight ahead")
    if state["face_off"] > 1:
        found.append("his face mesh is not on the body's head")
    if state["playing"]:
        found.append("an animation is set on " + ", ".join(state["playing"]))
    if state["updating"]:
        found.append("animation update in the editor is on for " + ", ".join(state["updating"]))
    return found


def refresh(editor):
    """Lets his meshes update for a moment in the editor; returns his state afterwards."""
    throttle = editor.run("frank_refresh(True)")
    time.sleep(2.0)
    editor.run(f"frank_refresh(False, {bool(throttle)})")
    time.sleep(0.5)
    return editor.run("frank_state()")


def main():
    may_reload = "--reload" in sys.argv[1:]
    editor = Editor()
    try:
        state = editor.run("frank_state()")
        if state["play"]:
            sys.exit("The editor is in Play: stop it first (Frank moves in Play; this is about the level in the editor).")
        if not state["found"]:
            sys.exit("No single BP_Agent with Body and Face in the open level.")
        found = problems(state)
        if not found:
            print("Frank is at rest: body in the reference pose, head straight ahead, nothing playing.")
            return
        print("Frank is not at rest:\n  " + "\n  ".join(found))
        state = refresh(editor)
        found = problems(state)
        if found and (may_reload or not state["unsaved"]):
            print("Still not at rest after an update of his meshes: loading his level actor again from its file"
                  + (" (its unsaved changes are dropped)" if state["unsaved"] else ""))
            editor.run("frank_reload()")
            time.sleep(1.0)
            state = refresh(editor)
            found = problems(state)
        if not found:
            print("Put back. Frank is at rest: body in the reference pose, head straight ahead, nothing playing.")
            return
        print("Frank is STILL not at rest:\n  " + "\n  ".join(found))
        if state["unsaved"] and not may_reload:
            sys.exit("His level actor has unsaved changes, so it was not loaded again from its file. If they are leftovers "
                     "of a preview, run:  python Tools/reset_frank.py --reload")
        sys.exit("His saved level actor itself is not at rest (docstring of this tool: restore its file from Git).")
    finally:
        editor.close()


if __name__ == "__main__":
    main()
