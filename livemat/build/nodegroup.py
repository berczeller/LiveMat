# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""One shared shader node group per preset.

The group takes the raw texture colors as inputs and does every conversion
(channel unpacking, gloss to roughness, DirectX normals, AO, bump) inside, so
materials only hold their image nodes and a single group node. Rebuilding a
group updates every material that uses it.
"""

import bpy

# Bump this when the generated node layout changes, so existing groups rebuild.
BUILDER_VERSION = 1

GROUP_PREFIX = "LiveMat "
SHADER_OUTPUT = "BSDF"

AO_STRENGTH = "AO Strength"
NORMAL_STRENGTH = "Normal Strength"
HEIGHT_STRENGTH = "Height Strength"
EMISSION_STRENGTH = "Emission Strength"

# name, default, min, max, semantic that makes the parameter useful
PARAMETERS = (
    (AO_STRENGTH, 0.0, 0.0, 1.0, "ao"),
    (NORMAL_STRENGTH, 1.0, 0.0, 10.0, "normal"),
    (HEIGHT_STRENGTH, 0.0, 0.0, 10.0, "height"),
    (EMISSION_STRENGTH, 1.0, 0.0, 100.0, "emission"),
)


def alpha_socket_name(slot):
    return f"{slot.label} Alpha"


def ensure_group(preset):
    """Return the preset's node group, building or rebuilding it when it's missing or outdated."""
    stamp = f"{preset.fingerprint}:{BUILDER_VERSION}"
    group = find_group(preset.id)
    if group is not None and group.get("livemat_stamp") == stamp:
        return group

    if group is None:
        group = bpy.data.node_groups.new(GROUP_PREFIX + preset.name, "ShaderNodeTree")
    else:
        group.nodes.clear()
        group.interface.clear()

    _build(group, preset)
    group["livemat_preset"] = preset.id
    group["livemat_stamp"] = stamp
    return group


def find_group(preset_id):
    return next(
        (
            g
            for g in bpy.data.node_groups
            if g.bl_idname == "ShaderNodeTree"
            and g.library is None
            and g.get("livemat_preset") == preset_id
        ),
        None,
    )


def _socket(sockets, identifier):
    # Some nodes (Mix) repeat socket names per data type; identifiers are unique.
    return next(s for s in sockets if s.identifier == identifier)


class _Layout:
    """Places nodes in columns so the generated group is readable."""

    def __init__(self):
        self._next_y = {}

    def place(self, node, column, step=180):
        x = column * 250
        y = self._next_y.get(column, 0)
        node.location = (x, y)
        self._next_y[column] = y - step
        return node


def _build(group, preset):
    nodes, links, iface = group.nodes, group.links, group.interface
    layout = _Layout()

    def new(kind, column, step=180, **props):
        node = layout.place(nodes.new(kind), column, step)
        for key, value in props.items():
            setattr(node, key, value)
        return node

    def math(operation, column, first=None, second=None):
        node = new("ShaderNodeMath", column, operation=operation)
        for index, value in enumerate((first, second)):
            if isinstance(value, (int, float)):
                node.inputs[index].default_value = value
            elif value is not None:
                links.new(value, node.inputs[index])
        return node.outputs[0]

    iface.new_socket(SHADER_OUTPUT, in_out="OUTPUT", socket_type="NodeSocketShader")
    for slot in preset.slots:
        socket = iface.new_socket(slot.label, in_out="INPUT", socket_type="NodeSocketColor")
        socket.default_value = slot.default_color()
        if slot.uses_alpha:
            alpha = iface.new_socket(
                alpha_socket_name(slot), in_out="INPUT", socket_type="NodeSocketFloat"
            )
            alpha.default_value = slot.default_alpha()
            alpha.min_value, alpha.max_value = 0.0, 1.0

    semantics = preset.semantics
    for name, default, low, high, needs in PARAMETERS:
        if needs in semantics:
            param = iface.new_socket(name, in_out="INPUT", socket_type="NodeSocketFloat")
            param.default_value = default
            param.min_value, param.max_value = low, high

    group_in = new("NodeGroupInput", 0, step=0)
    group_out = new("NodeGroupOutput", 6)
    bsdf = new("ShaderNodeBsdfPrincipled", 5)

    # Semantic -> socket carrying its value.
    values = {}
    for slot in preset.slots:
        color = group_in.outputs[slot.label]
        rgb = slot.semantic("RGB")
        if rgb:
            values[rgb] = color
        singles = [(key, sem) for key, sem in slot.channels if key in ("R", "G", "B")]
        if singles:
            split = new("ShaderNodeSeparateColor", 1)
            split.label = slot.label
            links.new(color, split.inputs["Color"])
            for key, sem in singles:
                values[sem] = split.outputs["RGB".index(key)]
        if slot.uses_alpha:
            values[slot.semantic("A")] = group_in.outputs[alpha_socket_name(slot)]

    base = values.get("base_color")
    if base is not None and "ao" in values:
        # Base color times AO, faded in by AO Strength (0 leaves it untouched).
        mix = new("ShaderNodeMix", 3, data_type="RGBA", blend_type="MULTIPLY")
        mix.label = "AO"
        links.new(group_in.outputs[AO_STRENGTH], _socket(mix.inputs, "Factor_Float"))
        links.new(base, _socket(mix.inputs, "A_Color"))
        links.new(values["ao"], _socket(mix.inputs, "B_Color"))
        base = _socket(mix.outputs, "Result_Color")
    if base is not None:
        links.new(base, bsdf.inputs["Base Color"])

    if "metallic" in values:
        links.new(values["metallic"], bsdf.inputs["Metallic"])

    if "roughness" in values:
        links.new(values["roughness"], bsdf.inputs["Roughness"])
    elif "gloss" in values:
        roughness = math("SUBTRACT", 3, 1.0, values["gloss"])
        if preset.gloss_curve == "SQUARED":
            roughness = math("POWER", 4, roughness, 2.0)
        roughness.node.label = "Gloss to Roughness"
        links.new(roughness, bsdf.inputs["Roughness"])

    if "alpha" in values:
        links.new(values["alpha"], bsdf.inputs["Alpha"])

    if "emission" in values:
        links.new(values["emission"], bsdf.inputs["Emission Color"])
        links.new(group_in.outputs[EMISSION_STRENGTH], bsdf.inputs["Emission Strength"])

    shading_normal = None
    if "normal" in values:
        normal_color = values["normal"]
        if preset.normal_format == "DIRECTX":
            # Blender expects OpenGL (Y up): flip the green channel.
            split = new("ShaderNodeSeparateColor", 2)
            join = new("ShaderNodeCombineColor", 3)
            join.label = "DirectX to OpenGL"
            links.new(normal_color, split.inputs["Color"])
            links.new(split.outputs["Red"], join.inputs["Red"])
            links.new(math("SUBTRACT", 2, 1.0, split.outputs["Green"]), join.inputs["Green"])
            links.new(split.outputs["Blue"], join.inputs["Blue"])
            normal_color = join.outputs["Color"]
        normal_map = new("ShaderNodeNormalMap", 4)
        links.new(normal_color, normal_map.inputs["Color"])
        links.new(group_in.outputs[NORMAL_STRENGTH], normal_map.inputs["Strength"])
        shading_normal = normal_map.outputs["Normal"]

    if "height" in values:
        bump = new("ShaderNodeBump", 4)
        links.new(values["height"], bump.inputs["Height"])
        links.new(group_in.outputs[HEIGHT_STRENGTH], bump.inputs["Strength"])
        if shading_normal is not None:
            links.new(shading_normal, bump.inputs["Normal"])
        shading_normal = bump.outputs["Normal"]

    if shading_normal is not None:
        links.new(shading_normal, bsdf.inputs["Normal"])

    links.new(bsdf.outputs["BSDF"], group_out.inputs[SHADER_OUTPUT])
