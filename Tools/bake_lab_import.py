"""Second half of the room's light bake (README 4.7, D119), in the open editor (DefaultMap loaded, not in Play):
    python Tools/ue_py.py Tools/bake_lab_import.py

1. Brings Saved/LabBake/T_LabLight.exr, T_LabLightDir.exr (from Tools/bake_lab_light.py) and T_LabShadow.png
   (from Tools/bake_lab_shadow.py) into /Game/Assets/Materials/Baked/.
2. Builds the material M_LabBaked (unlit; its graph is rebuilt on every run) and sets its instances. It finds a
   point's place in the pictures from its position in the room, so the room model needs no extra UVs; the room must
   stay where it is. The panels keep their textures: colour, plus normal and occlusion maps shaded with the baked
   direction of the direct light, so surface relief reads as under live lights; the shadow picture darkens the
   recessed strips and the joints as the model's own shape shades them.
Saves only these assets. The level's actors are not changed.
"""
import json
import os

import unreal

FOLDER = "/Game/Assets/Materials/Baked"
BAKE = os.path.join(unreal.Paths.project_saved_dir(), "LabBake")
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
T = "/Game/Assets/Materials/Textures/"
PLASTER = "/Game/Fab/Megascans/Surfaces/Plastered_Concrete_Wall_ugtkdffg/High/ugtkdffg_tier_1/Textures/T_ugtkdffg_4K_"
INSTANCES = {  # name: colour, normal and occlusion textures (or None), tiling, tint, brightness, desaturate (as the original
    # materials), softness (texture mip bias: below 0 sharper, above 0 blurs; 0 as the originals), specular (shine of the
    # direct light, as the originals' Specular input; 0 = none)
    "MI_Lab_WallPanel": (T + "panels_albedo", T + "panels_normal", T + "panels_ao", 2.0, 1.0, 1.0, 0.0, 0.0, 0.0),         # M_WallPanel
    # ceiling tiles 0.8: the level's live lights left them darker than the bake gives (owner, 2026-11-20); Lumen still
    # sees them at 1.0 (LUMEN below), so the light they bounce onto Frank stays as approved
    "MI_Lab_CeilingPanel": (T + "panels_albedo", T + "panels_normal", T + "panels_ao", 2.0, 1.0, 0.8, 0.0, 0.0, 0.0),      # M_CeilingPanel
    "MI_Lab_Ceiling": (None, None, None, 1.0, 0.816, 1.0, 0.0, 0.0, 0.0),                                                  # M_Ceiling
    "MI_Lab_Button": (None, None, None, 1.0, 0.25, 1.0, 0.0, 0.0, 0.5),                                                    # M_Button (rivets)
    "MI_Lab_WhiteWall": (PLASTER + "B", PLASTER + "N", None, 2.0, 1.0, 2.0, 1.0, 0.0, 0.0),                                # MI_ugtkdffg
    "MI_Lab_Skirting": (T + "floor_albedo", T + "floor_normal", T + "floor_ao", 3.0, 1.0, 0.5, 0.0, 0.0, 0.0),            # M_FloorSide
}
LUMEN = {"MI_Lab_CeilingPanel": 1.0 / 0.8}   # brightness Lumen sees, relative to what the eye sees (default 1)


def import_picture(name, extension=".exr", shadow=False):
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", os.path.join(BAKE, name + extension))
    task.set_editor_property("destination_path", FOLDER)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", False)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    tex = unreal.load_asset(FOLDER + "/" + name)
    tex.modify()
    if shadow:   # fine lines: compressed, with mipmaps so they do not shimmer at a distance
        settings = (("compression_settings", unreal.TextureCompressionSettings.TC_BC7),
                    ("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_SIMPLE_AVERAGE), ("filter", unreal.TextureFilter.TF_TRILINEAR))
    else:        # smooth light: exact values, no mipmaps
        settings = (("compression_settings", unreal.TextureCompressionSettings.TC_HDR),
                    ("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS), ("filter", unreal.TextureFilter.TF_BILINEAR))
    for prop, value in settings + (("srgb", False), ("address_x", unreal.TextureAddress.TA_CLAMP),
                                   ("address_y", unreal.TextureAddress.TA_CLAMP), ("never_stream", True)):
        tex.set_editor_property(prop, value)
    eal.save_loaded_asset(tex, False)
    print("imported", name, tex.blueprint_get_size_x(), "x", tex.blueprint_get_size_y())
    return tex


def shade_code(light, shadow):
    """HLSL of the Custom node that lights a point: finds which baked surface the point P (vertex normal Ng) belongs
    to and its place in the pictures, then shades the bumped normal N with the baked light and the shadow picture."""
    (x0, x1), (y0, y1), (z0, z1) = light["room"]["x"], light["room"]["y"], light["room"]["z"]
    # per surface: its two axes as (expression, length), then which plane coordinates they are
    axes = {"back": (("y", y0, y1 - y0), ("z", z0, z1 - z0)), "left": (("x", x0, x1 - x0), ("z", z0, z1 - z0)),
            "right": (("x", x0, x1 - x0), ("z", z0, z1 - z0)), "ceiling": (("x", x0, x1 - x0), ("y", y0, y1 - y0))}

    def f2(a, b):
        return "float2(%.4f, %.4f)" % (a, b)

    ext = shadow["ext_cm"]   # the shadow picture's maps reach this far beyond the room box

    def branch(name):
        (u, u0, lu), (v, v0, lv) = axes[name]
        lr, sr = light["regions"][name], shadow["regions"][name]
        return ("fc = float2((P.%s - (%.2f)) / %.2f, (P.%s - (%.2f)) / %.2f); " % (u, u0, lu, v, v0, lv)
                + "gx = float2(dPx.%s / %.2f, dPx.%s / %.2f); gy = float2(dPy.%s / %.2f, dPy.%s / %.2f); " % (u, lu, v, lv, u, lu, v, lv)
                + "lo = %s; ls = %s; so = %s; ss = %s; " % (f2(lr[0], lr[1]), f2(lr[2], lr[3]), f2(sr[0], sr[1]), f2(sr[2], sr[3]))
                + "sk = %s; sb = %s;" % (f2(lu / (lu + 2 * ext), lv / (lv + 2 * ext)), f2(ext / (lu + 2 * ext), ext / (lv + 2 * ext))))

    return "\n".join([
        "float3 dPx = ddx(P), dPy = ddy(P);",
        "// the surface the point belongs to: the planes it lies on (2 cm), the one its normal faces most",
        "float best = -2.0; int f = -1;",
        "if (P.x < %.2f && Ng.x > best) { best = Ng.x; f = 0; }" % (x0 + 2.0),
        "if (P.y > %.2f && -Ng.y > best) { best = -Ng.y; f = 1; }" % (y1 - 2.0),
        "if (P.y < %.2f && Ng.y > best) { best = Ng.y; f = 2; }" % (y0 + 2.0),
        "if (P.z > %.2f && -Ng.z > best) { best = -Ng.z; f = 3; }" % (z1 - 2.0),
        "if (f < 0) {",
        "    float4 dist = float4(P.x - (%.2f), %.2f - P.y, P.y - (%.2f), %.2f - P.z);" % (x0, y1, y0, z1),
        "    f = 0; best = dist.x;",
        "    if (dist.y < best) { best = dist.y; f = 1; }",
        "    if (dist.z < best) { best = dist.z; f = 2; }",
        "    if (dist.w < best) { f = 3; }",
        "}",
        "float2 fc, gx, gy, lo, ls, so, ss, sk, sb;",
        "if (f == 0) { %s }" % branch("back"),
        "else if (f == 1) { %s }" % branch("left"),
        "else if (f == 2) { %s }" % branch("right"),
        "else { %s }" % branch("ceiling"),
        "float2 luv = (lo + clamp(fc * ls, 0.5, ls - 0.5)) / %s;" % f2(*light["atlas"]),
        "float2 suv = (so + clamp((fc * sk + sb) * ss, 0.5, ss - 0.5)) / %s;" % f2(*shadow["atlas"]),
        "float2 sg = sk * ss / %s;" % f2(*shadow["atlas"]),
        "float3 L = LightTex.SampleLevel(LightTexSampler, luv, 0).rgb;",
        "float4 Dir = DirTex.SampleLevel(DirTexSampler, luv, 0);",
        "float2 S = ShadowTex.SampleGrad(ShadowTexSampler, suv, gx * sg, gy * sg).rg;",
        "// direct light follows the bumped normal and the model's shadows; bounced light gets the occlusion map too",
        "float3 d = (Dir.rgb - 0.5) * 4.0;",
        "float3 n = normalize(lerp(Ng, normalize(N), Strength));",
        "#if LUMEN_CARD_CAPTURE",
        "// what Lumen sees and bounces into the room (onto Frank): the walls and ceiling as the owner approved them on",
        "// 2026-11-20, without the model's shadows and with the ceiling tiles at their earlier brightness (LumenScale)",
        "return C * LumenScale * L * (Dir.a * max(dot(n, d), 0.0) * lerp(1.0, AO, DirectAO) + (1.0 - Dir.a) * AO);",
        "#else",
        "float3 lit = C * L * (Dir.a * max(dot(n, d), 0.0) * lerp(1.0, AO, DirectAO) * S.r + (1.0 - Dir.a) * AO * S.g);",
        "// shine: the direct light as one light from its mean direction, GGX like the engine's default lit model",
        "if (Spec > 0.0) {",
        "    float3 l = normalize(d);",
        "    float3 hv = normalize(l + V);",
        "    float nl = saturate(dot(n, l)), nv = saturate(dot(n, V)) + 1e-4, nh = saturate(dot(n, hv)), vh = saturate(dot(V, hv));",
        "    float a = Rough * Rough, a2 = a * a, k = nh * nh * (a2 - 1.0) + 1.0;",
        "    float D = a2 / (3.14159265 * k * k);",
        "    float Vis = 0.5 / (nl * (nv * (1.0 - a) + a) + nv * (nl * (1.0 - a) + a));",
        "    float F0 = 0.08 * Spec, F = F0 + (1.0 - F0) * pow(1.0 - vh, 5.0);",
        "    lit += 3.14159265 * L * Dir.a * S.r / max(dot(Ng, l), 0.05) * nl * D * Vis * F;",
        "}",
        "return lit;",
        "#endif"])


def custom_inputs(*names):
    pins = []
    for name in names:
        pin = unreal.CustomInput()
        pin.set_editor_property("input_name", name)
        pins.append(pin)
    return pins


def build_material(light, light_dir, shadow, light_info, shadow_info):
    path = FOLDER + "/M_LabBaked"
    if eal.does_asset_exist(path):
        material = unreal.load_asset(path)
        mel.delete_all_material_expressions(material)
    else:
        material = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_LabBaked", FOLDER, unreal.Material, unreal.MaterialFactoryNew())
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)

    def node(cls, x, y, **props):
        e = mel.create_material_expression(material, cls, x, y)
        for k, v in props.items():
            e.set_editor_property(k, v)
        return e

    def link(a, a_out, b, b_in):
        assert mel.connect_material_expressions(a, a_out, b, b_in), (a.get_name(), a_out, b.get_name(), b_in)

    def scalar(name, value, x, y):
        return node(unreal.MaterialExpressionScalarParameter, x, y, parameter_name=name, default_value=value)

    def texture(name, default, sampler, x, y):
        e = node(unreal.MaterialExpressionTextureSampleParameter2D, x, y, parameter_name=name, texture=unreal.load_asset(default),
                 sampler_type=sampler, mip_value_mode=unreal.TextureMipValueMode.TMVM_MIP_BIAS)
        link(uv_tiled, "", e, "UVs")
        link(softness, "", e, "Bias")
        return e

    # the surface's own textures, tiled like the original materials
    uv = node(unreal.MaterialExpressionTextureCoordinate, -1800, 0)
    tiling = scalar("Tiling", 1.0, -1800, 120)
    uv_tiled = node(unreal.MaterialExpressionMultiply, -1600, 40)
    link(uv, "", uv_tiled, "A")
    link(tiling, "", uv_tiled, "B")
    softness = scalar("Softness", 0.0, -1600, 200)   # mip bias: above 0 blurs the textures
    albedo = texture("Albedo", "/Engine/EngineResources/WhiteSquareTexture", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, -1300, 0)
    normal_map = texture("Normal", "/Engine/EngineMaterials/FlatNormal", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, -1300, 300)
    occlusion = texture("AO", "/Engine/EngineResources/WhiteSquareTexture", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, -1300, 600)
    grey = node(unreal.MaterialExpressionDesaturation, -1000, 0)
    link(albedo, "RGB", grey, "")
    link(scalar("Desaturate", 0.0, -1300, -150), "", grey, "Fraction")
    tinted = node(unreal.MaterialExpressionMultiply, -800, 40)
    link(grey, "", tinted, "A")
    link(node(unreal.MaterialExpressionVectorParameter, -1000, 150, parameter_name="Tint", default_value=unreal.LinearColor(1, 1, 1, 1)), "", tinted, "B")
    surface = node(unreal.MaterialExpressionMultiply, -600, 80)
    link(tinted, "", surface, "A")
    link(scalar("Brightness", 1.0, -800, 200), "", surface, "B")
    normal_ws = node(unreal.MaterialExpressionTransform, -1000, 300,
                     transform_source_type=unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_TANGENT,
                     transform_type=unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
    link(normal_map, "RGB", normal_ws, "")

    # the baked light, its direction and the model's shadows, found from the point's position
    position = node(unreal.MaterialExpressionWorldPosition, -1800, 900)
    vertex_normal = node(unreal.MaterialExpressionVertexNormalWS, -1800, 1050)
    shade = node(unreal.MaterialExpressionCustom, -700, 700, code=shade_code(light_info, shadow_info),
                 output_type=unreal.CustomMaterialOutputType.CMOT_FLOAT3, description="Baked light on the bumped surface",
                 inputs=custom_inputs("P", "Ng", "N", "V", "C", "AO", "Strength", "DirectAO", "Spec", "Rough", "LumenScale", "LightTex", "DirTex", "ShadowTex"))
    link(position, "", shade, "P")
    link(vertex_normal, "", shade, "Ng")
    link(normal_ws, "", shade, "N")
    link(node(unreal.MaterialExpressionCameraVectorWS, -1800, 1200), "", shade, "V")
    link(surface, "", shade, "C")
    link(occlusion, "R", shade, "AO")
    link(scalar("NormalStrength", 1.0, -1000, 800), "", shade, "Strength")
    # 1: the occlusion map dims the direct light too (the originals apply it to bounced light only, but their shine
    # brings out the surface; measured on the wall, the texture's fine contrast then matches the original)
    link(scalar("DirectAO", 1.0, -1000, 900), "", shade, "DirectAO")
    link(scalar("Specular", 0.0, -1000, 950), "", shade, "Spec")
    link(scalar("Roughness", 0.5, -1000, 1000), "", shade, "Rough")
    link(scalar("LumenScale", 1.0, -1000, 1050), "", shade, "LumenScale")
    for pin, (tex, y) in {"LightTex": (light, 1000), "DirTex": (light_dir, 1150), "ShadowTex": (shadow, 1300)}.items():
        link(node(unreal.MaterialExpressionTextureObject, -1000, y, texture=tex), "", shade, pin)
    out = node(unreal.MaterialExpressionMultiply, -200, 450)
    link(shade, "", out, "A")
    link(scalar("LightScale", 1.0, -400, 600), "", out, "B")
    mel.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    mel.recompile_material(material)
    eal.save_loaded_asset(material, False)
    print("material M_LabBaked built")
    return material


def build_instances(material):
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    for name, (colour, normal, occlusion, tiling, tint, brightness, desaturate, softness, specular) in INSTANCES.items():
        path = FOLDER + "/" + name
        if eal.does_asset_exist(path):
            instance = unreal.load_asset(path)
        else:
            instance = tools.create_asset(name, FOLDER, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        mel.set_material_instance_parent(instance, material)
        mel.clear_all_material_instance_parameters(instance)
        for param, tex in (("Albedo", colour), ("Normal", normal), ("AO", occlusion)):
            if tex:
                mel.set_material_instance_texture_parameter_value(instance, param, unreal.load_asset(tex))
        mel.set_material_instance_scalar_parameter_value(instance, "Tiling", tiling)
        mel.set_material_instance_scalar_parameter_value(instance, "Brightness", brightness)
        mel.set_material_instance_scalar_parameter_value(instance, "Desaturate", desaturate)
        mel.set_material_instance_scalar_parameter_value(instance, "Softness", softness)
        mel.set_material_instance_scalar_parameter_value(instance, "Specular", specular)
        mel.set_material_instance_scalar_parameter_value(instance, "LumenScale", LUMEN.get(name, 1.0))
        mel.set_material_instance_vector_parameter_value(instance, "Tint", unreal.LinearColor(tint, tint, tint, 1.0))
        mel.update_material_instance(instance)
        eal.save_loaded_asset(instance, False)
        print("instance set:", name)


if unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
    raise RuntimeError("stop Play first")
light_info = json.load(open(os.path.join(BAKE, "T_LabLight.json")))
shadow_info = json.load(open(os.path.join(BAKE, "T_LabShadow.json")))
build_instances(build_material(import_picture("T_LabLight"), import_picture("T_LabLightDir"),
                               import_picture("T_LabShadow", ".png", shadow=True), light_info, shadow_info))
print("unsaved now:", [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()],
      len(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()), "level packages")
