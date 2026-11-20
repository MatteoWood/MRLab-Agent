"""How the view smoothing got into NDC_Basic (README 4.4, D117), kept so it can be rebuilt or changed. Editor Python.

NDC_Basic is locked (README 4.3): this script only builds the two functions in a test Blueprint,
/Game/_Sandbox/ViewSmooth/BP_ViewSmoothTest (created if missing), and checks SmoothView against
Tools/view_smoothing.py there:
    python Tools/ue_py.py Tools/view_smoothing_blueprint.py
A change to NDC_Basic itself needs the owner's request; then the same steps go into NDC_Basic by hand
(BUILD_IN = its path), followed by the three event graph nodes described at the end of this file.

Blueprint notes: a pure expression is evaluated again by every node that uses it, with the values of that
moment. So everything that must be kept across an assignment is stored in a local variable first (L_...), and
the function is a plain sequence of assignments, in the order of Tools/view_smoothing.py.
"""
import os
import sys

import unreal
from editor_toolset.toolsets.blueprint import BlueprintTools as BT

BUILD_IN = globals().get("BUILD_IN", "/Game/_Sandbox/ViewSmooth/BP_ViewSmoothTest")
CATEGORY = "View Smoothing"
SETTINGS = [("bSmoothView", "bool", True), ("SmoothTime", "float", 0.10), ("LeadTime", "float", 0.02), ("MaxSpeed", "float", 300.0),
            ("JumpTime", "float", 0.08)]
STATE = [("bViewValid", "bool"), ("ViewLastTarget", "Vector"), ("ViewOffset", "Vector"), ("ViewLastCorrected", "Vector"),
         ("ViewVelSlow", "Vector"), ("ViewVelFast", "Vector"), ("ViewPos", "Vector"), ("ViewVel", "Vector")]
LOCALS = [("L_Dt", "float"), ("L_MaxStep", "float"), ("L_Len", "float"), ("L_Smooth", "float"), ("L_W", "float"), ("L_E", "float"),
          ("L_Step", "Vector"), ("L_Corrected", "Vector"), ("L_Raw", "Vector"), ("L_Goal", "Vector"), ("L_D", "Vector"), ("L_C", "Vector")]
ZERO = "(Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 0.0)"
LEN, EXP, MIN, MAX, CLAMP = "Math|Vector|VectorLength", "Math|Float|Exp", "Math|Float|Min(Float)", "Math|Float|Max(Float)", "Math|Float|Clamp(Float)"


def node(name):
    """The variable's node name: members are in the category, a bool loses its b, locals lose the underscore."""
    if name.startswith("L_"):
        return "Variables|Default|%s" + name.replace("_", "")
    return "Variables|ViewSmoothing|%s" + (name[1:] if name[0] == "b" and name[1].isupper() else name)


def g(name):
    return "(%s)" % (node(name) % "Get")


def s(name, expr):
    return "(%s %s)" % (node(name) % "Set", expr)


def blend(time):
    """1 - exp(-dt / time)"""
    return "(- 1.0 (%s (/ (- %s) %s)))" % (EXP, g("L_Dt"), time)


def smooth_view():
    return "\n".join([
        "(fn SmoothView (Target DeltaTime Current)",
        "  (if (not %s)" % g("bSmoothView"),
        "    %s" % s("bViewValid", "false"),
        "    (return Target))",
        "  (if (not %s)" % g("bViewValid"),
        "    %s" % s("bViewValid", "true"),
        "    %s" % s("ViewLastTarget", "Current"),
        "    %s" % s("ViewOffset", ZERO),
        "    %s" % s("ViewLastCorrected", "Current"),
        "    %s" % s("ViewVelSlow", ZERO),
        "    %s" % s("ViewVelFast", ZERO),
        "    %s" % s("ViewPos", "Current"),
        "    %s)" % s("ViewVel", ZERO),
        "  %s" % s("L_Dt", "(%s DeltaTime 0.001 0.1)" % CLAMP),
        "  %s" % s("L_Smooth", "(%s %s 0.01 1.0)" % (CLAMP, g("SmoothTime"))),
        "  %s" % s("L_MaxStep", "(* %s %s)" % (g("MaxSpeed"), g("L_Dt"))),
        # 1. jumps
        "  %s" % s("L_Step", "(- Target %s)" % g("ViewLastTarget")),
        "  %s" % s("ViewLastTarget", "Target"),
        "  %s" % s("L_Len", "(%s %s)" % (LEN, g("L_Step"))),
        "  (if (> %s %s)" % (g("L_Len"), g("L_MaxStep")),
        "    %s)" % s("ViewOffset", "(- %s (* %s (- 1.0 (/ %s %s))))" % (g("ViewOffset"), g("L_Step"), g("L_MaxStep"), g("L_Len"))),
        "  %s" % s("L_Len", "(%s %s)" % (LEN, g("ViewOffset"))),
        "  (if (> %s 0.000001)" % g("L_Len"),
        "    %s)" % s("ViewOffset", "(* %s (- 1.0 (/ (%s (* %s %s) %s) %s)))" % (
            g("ViewOffset"), MIN, g("L_Len"), blend("(%s %s 0.01)" % (MAX, g("JumpTime"))), g("L_MaxStep"), g("L_Len"))),
        "  %s" % s("L_Corrected", "(+ Target %s)" % g("ViewOffset")),
        # 2. speed
        "  %s" % s("L_Raw", "(/ (- %s %s) %s)" % (g("L_Corrected"), g("ViewLastCorrected"), g("L_Dt"))),
        "  %s" % s("ViewLastCorrected", g("L_Corrected")),
        "  %s" % s("ViewVelSlow", "(+ %s (* (- %s %s) %s))" % (g("ViewVelSlow"), g("L_Raw"), g("ViewVelSlow"), blend("(* %s 1.2)" % g("L_Smooth")))),
        "  %s" % s("ViewVelFast", "(+ %s (* (- %s %s) %s))" % (g("ViewVelFast"), g("L_Raw"), g("ViewVelFast"), blend("0.03"))),
        "  %s" % s("L_Len", "(%s 1.0 (/ (%s %s) (%s (%s %s) 0.000001)))" % (MIN, LEN, g("ViewVelFast"), MAX, LEN, g("ViewVelSlow"))),
        # 3. follow
        "  %s" % s("L_Goal", "(+ %s (* %s (* (* %s %s) (+ %s %s))))" % (
            g("L_Corrected"), g("ViewVelSlow"), g("L_Len"), g("L_Len"), g("L_Smooth"), g("LeadTime"))),
        "  %s" % s("L_W", "(/ 2.0 %s)" % g("L_Smooth")),
        "  %s" % s("L_D", "(- %s %s)" % (g("ViewPos"), g("L_Goal"))),
        "  %s" % s("L_C", "(+ %s (* %s %s))" % (g("ViewVel"), g("L_D"), g("L_W"))),
        "  %s" % s("L_E", "(%s (- (* %s %s)))" % (EXP, g("L_W"), g("L_Dt"))),
        "  %s" % s("ViewPos", "(+ %s (* (+ %s (* %s %s)) %s))" % (g("L_Goal"), g("L_D"), g("L_C"), g("L_Dt"), g("L_E"))),
        "  %s" % s("ViewVel", "(* (- %s (* %s (* %s %s))) %s)" % (g("ViewVel"), g("L_C"), g("L_W"), g("L_Dt"), g("L_E"))),
        "  (return %s))" % g("ViewPos"),
    ])


def init_view_smoothing():
    """At BeginPlay: the smoothing starts fresh, command line switches replace the settings, one log line."""
    def number(switch, name, low, high):
        return ["  (bind (text%s ok%s) (Utilities|ParseParamValue cmd \"%s=\"))" % (name, name, switch),
                "  (if ok%s" % name,
                "    %s)" % s(name, "(%s (Utilities|String|StringToFloat text%s) %s %s)" % (CLAMP, name, low, high))]
    lines = ["(fn InitViewSmoothing ()",
             "  %s" % s("bViewValid", "false"),
             "  (bind cmd (Utilities|GetCommandLine))",
             "  (if (Utilities|ParseParam cmd \"MRLabViewRaw\")",
             "    %s)" % s("bSmoothView", "false")]
    lines += number("MRLabViewSmooth", "SmoothTime", 0.01, 1.0)
    lines += number("MRLabViewLead", "LeadTime", 0.0, 0.2)
    lines += number("MRLabViewMaxSpeed", "MaxSpeed", 50.0, 2000.0)
    lines += number("MRLabViewJump", "JumpTime", 0.01, 1.0)
    text = "(Utilities|String|BuildString(Boolean) \"MRLab view smoothing:\" \" on \" %s \",\")" % g("bSmoothView")
    for prefix, name, suffix in ((" smooth ", "SmoothTime", " s,"), (" lead ", "LeadTime", " s,"), (" max speed ", "MaxSpeed", " cm/s,"),
                                 (" jump ", "JumpTime", " s")):
        text = "(Utilities|String|BuildString(Float) %s \"%s\" %s \"%s\")" % (text, prefix, g(name), suffix)
    lines.append("  (Development|PrintString :InString %s :bPrintToScreen false :bPrintToLog true))" % text)
    return "\n".join(lines)


def build(path):
    """Variables and both functions into a Blueprint that has none of them yet. A function graph removed and
    added again in the same run gets another name (SmoothView_0) and the text below then writes nothing."""
    folder, name = path.rsplit("/", 1)
    bp = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else BT.create(folder, name, unreal.Actor.static_class())
    if "SmoothView" in [graph.get_name() for graph in BT.list_graphs(bp)]:
        return bp
    for name, type_name, *_ in SETTINGS + STATE:
        BT.add_variable(bp, name, type_name)
        BT.set_variable_category(bp, name, CATEGORY)
    BT.compile_blueprint(bp)
    graph = BT.add_function_graph(bp, "SmoothView")
    BT.add_function_param(graph, "Target", "Vector", True)
    BT.add_function_param(graph, "DeltaTime", "float", True)
    BT.add_function_param(graph, "Current", "Vector", True)
    BT.add_function_param(graph, "Location", "Vector", False)
    for name, type_name in LOCALS:
        BT.add_variable(bp, name, type_name, graph)
    BT.compile_blueprint(bp)  # variable nodes exist only after a compile
    BT.write_graph_dsl(graph, smooth_view())
    assert len(BT.find_nodes(graph, "")) == 180, "SmoothView was not written completely"
    graph = BT.add_function_graph(bp, "InitViewSmoothing")
    BT.write_graph_dsl(graph, init_view_smoothing())
    assert len(BT.find_nodes(graph, "")) == 37, "InitViewSmoothing was not written completely"
    BT.compile_blueprint(bp, True)
    defaults = unreal.get_default_object(bp.generated_class())
    for name, _, value in SETTINGS:
        defaults.set_editor_property(name, value)
    BT.compile_blueprint(bp, True)
    return bp


def check(bp):
    """SmoothView on the test Blueprint's default object against Tools/view_smoothing.py: jumps, odd frame times,
    a walk with stops, and other settings. Changes that object's variables: never run it on NDC_Basic."""
    sys.path.insert(0, os.path.join(unreal.Paths.project_dir(), "Tools"))
    import view_smoothing
    obj = unreal.get_default_object(bp.generated_class())
    worst, frames = 0.0, 0
    for settings in ({}, dict(smooth_time=0.07, lead_time=0.03, max_speed=200.0, jump_time=0.12)):
        for prop, key in (("SmoothTime", "smooth_time"), ("LeadTime", "lead_time"), ("MaxSpeed", "max_speed"), ("JumpTime", "jump_time")):
            obj.set_editor_property(prop, settings.get(key, view_smoothing.DEFAULTS[key]))
        obj.set_editor_property("bViewValid", False)
        reference = view_smoothing.ViewFilter(**settings)
        x, speed = 100.0, 0.0
        for i in range(900):
            dt = (0.0002, 0.4, 0.05, 1 / 30)[i % 4] if i % 97 == 0 else 1 / 60
            speed = 120.0 if 200 <= i < 380 else max(0.0, speed - 8.0)  # a walk and a stop
            x += speed * dt
            head = (x, 16.0 + (100.0 if 60 <= i < 500 else 0.0), 160.0 + (12.0 if i >= 700 else 0.0))  # two jumps
            out = obj.call_method("SmoothView", args=(unreal.Vector(*head), dt, unreal.Vector(0, 0, 50)))
            want = reference(head, dt, (0.0, 0.0, 50.0) if i == 0 else None)
            worst, frames = max(worst, abs(out.x - want[0]), abs(out.y - want[1]), abs(out.z - want[2])), frames + 1
    for name, _, value in SETTINGS:
        obj.set_editor_property(name, value)
    obj.set_editor_property("bViewValid", False)
    print("SmoothView against Tools/view_smoothing.py over %d frames: largest difference %.1e cm (%s)" % (
        frames, worst, "same" if worst < 1e-6 else "DIFFERENT"))


if BUILD_IN.endswith("NDC_Basic"):
    raise RuntimeError("NDC_Basic is locked (README 4.3): build and check in the sandbox Blueprint")
check(build(BUILD_IN))

# The three nodes in NDC_Basic's event graph (2026-11-20), all else as before:
# - BeginPlay: ApplyToClient.then -> InitViewSmoothing.
# - OnLiveLinkUpdated, valid frame: PrintString.then -> SmoothView -> SetRelativeLocation(Rig), with
#   SmoothView.Target = the Make Vector that went straight into SetRelativeLocation before, DeltaTime = the event's,
#   Current = Rig's Relative Location (third node), and SmoothView.Location -> SetRelativeLocation.NewLocation.
