# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""One shared shader node group per preset.

The group takes the raw texture colors as inputs and does every conversion
(channel unpacking, spec/gloss to metal/rough, gloss to roughness, DirectX
normals, AO, bump) inside, so materials only hold their image nodes and a
single group node. Rebuilding a group updates every material that uses it.
"""

import bpy

from ..core.presets import SEMANTIC_DEFAULTS

# Bump this when the generated node layout changes, so existing groups rebuild.
BUILDER_VERSION = 3

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

SPECGLOSS_NAME = "LiveMat Spec-Gloss to Metal-Rough"
SPECGLOSS_VERSION = 1
DIELECTRIC_F0 = 0.04


def alpha_socket_name(slot):
    return f"{slot.label} Alpha"


def ensure_group(preset):
    """Return the preset's node group, building or rebuilding it when it's missing or outdated."""
    stamp = f"{preset.fingerprint}:{BUILDER_VERSION}"
    group = find_group(preset.id)
    if group is not None and group.get("livemat_stamp") == stamp:
        return group
    group = _fresh_group(group, GROUP_PREFIX + preset.name, lambda g: _build(g, preset))
    group["livemat_preset"] = preset.id
    group["livemat_stamp"] = stamp
    return group


def find_group(preset_id):
    return _find(lambda g: g.get("livemat_preset") == preset_id)


def ensure_specgloss_group():
    """Shared helper that turns diffuse + specular colors into base color + metallic."""
    group = _find(lambda g: g.get("livemat_helper") == "specgloss")
    if group is not None and group.get("livemat_stamp") == SPECGLOSS_VERSION:
        return group
    group = _fresh_group(group, SPECGLOSS_NAME, _build_specgloss)
    group["livemat_helper"] = "specgloss"
    group["livemat_stamp"] = SPECGLOSS_VERSION
    return group


def _find(predicate):
    return next(
        (
            g
            for g in bpy.data.node_groups
            if g.bl_idname == "ShaderNodeTree" and g.library is None and predicate(g)
        ),
        None,
    )


def _fresh_group(group, name, build):
    """Create or rebuild `group` with `build(group)`.

    Rebuilding the interface gives every socket a new identifier, which drops
    the links on each node using the group. Those links and the parameter
    values are saved by socket name first and put back afterwards.
    """
    if group is None:
        group = bpy.data.node_groups.new(name, "ShaderNodeTree")
        build(group)
        return group
    users = _save_users(group)
    group.nodes.clear()
    group.interface.clear()
    build(group)
    _restore_users(users)
    return group


def _save_users(group):
    trees = [m.node_tree for m in bpy.data.materials if m.library is None and m.node_tree is not None]
    trees += [g for g in bpy.data.node_groups if g.library is None and g != group]
    parameters = {name for name, *_rest in PARAMETERS}
    users = []
    for tree in trees:
        for node in tree.nodes:
            if node.bl_idname != "ShaderNodeGroup" or node.node_tree != group:
                continue
            links_in = [
                (l.from_node.name, l.from_socket.identifier, l.to_socket.name)
                for l in tree.links
                if l.to_node == node
            ]
            links_out = [
                (l.from_socket.name, l.to_node.name, l.to_socket.identifier)
                for l in tree.links
                if l.from_node == node
            ]
            values = {
                s.name: s.default_value
                for s in node.inputs
                if s.name in parameters and not s.is_linked
            }
            users.append((tree, node.name, links_in, links_out, values))
    return users


def _restore_users(users):
    for tree, node_name, links_in, links_out, values in users:
        node = tree.nodes.get(node_name)
        if node is None:
            continue
        for from_name, from_id, to_name in links_in:
            source, target = tree.nodes.get(from_name), node.inputs.get(to_name)
            if source is not None and target is not None:
                tree.links.new(_socket(source.outputs, from_id), target)
        for from_name, to_name, to_id in links_out:
            source, target = node.outputs.get(from_name), tree.nodes.get(to_name)
            if source is not None and target is not None:
                tree.links.new(source, _socket(target.inputs, to_id))
        for name, value in values.items():
            socket = node.inputs.get(name)
            if socket is not None:
                socket.default_value = value


def _socket(sockets, identifier):
    # Some nodes (Mix) repeat socket names per data type; identifiers are unique.
    return next(s for s in sockets if s.identifier == identifier)


class _Graph:
    """Small helpers for building node trees in code, laid out in columns."""

    def __init__(self, tree):
        self.nodes, self.links = tree.nodes, tree.links
        self._next_y = {}

    def new(self, kind, column, step=180, **props):
        node = self.nodes.new(kind)
        y = self._next_y.get(column, 0)
        node.location = (column * 250, y)
        self._next_y[column] = y - step
        for key, value in props.items():
            setattr(node, key, value)
        return node

    def feed(self, target, value):
        """Connect a socket, or set a constant when `value` is a number or tuple."""
        if hasattr(value, "is_output"):
            self.links.new(value, target)
        elif value is not None:
            target.default_value = value

    def math(self, operation, column, a=None, b=None, clamp=False):
        node = self.new("ShaderNodeMath", column, step=150, operation=operation, use_clamp=clamp)
        self.feed(node.inputs[0], a)
        self.feed(node.inputs[1], b)
        return node.outputs[0]

    def vector(self, operation, column, a=None, b=None, scale=None):
        node = self.new("ShaderNodeVectorMath", column, step=150, operation=operation)
        self.feed(node.inputs[0], a)
        self.feed(node.inputs[1], b)
        self.feed(_socket(node.inputs, "Scale"), scale)
        return _socket(node.outputs, "Value" if operation == "DOT_PRODUCT" else "Vector")


def _new_input(iface, name, kind, default, low=None, high=None):
    socket = iface.new_socket(name, in_out="INPUT", socket_type=kind)
    socket.default_value = default
    if low is not None:
        socket.min_value, socket.max_value = low, high
    return socket


def _build(group, preset):
    iface = group.interface
    graph = _Graph(group)
    links = graph.links

    iface.new_socket(SHADER_OUTPUT, in_out="OUTPUT", socket_type="NodeSocketShader")
    for slot in preset.slots:
        _new_input(iface, slot.label, "NodeSocketColor", slot.default_color())
        if slot.uses_alpha:
            _new_input(iface, alpha_socket_name(slot), "NodeSocketFloat", slot.default_alpha(), 0.0, 1.0)

    semantics = preset.semantics
    for name, default, low, high, needs in PARAMETERS:
        if needs in semantics:
            _new_input(iface, name, "NodeSocketFloat", default, low, high)

    group_in = graph.new("NodeGroupInput", 0, step=0)
    group_out = graph.new("NodeGroupOutput", 7)
    bsdf = graph.new("ShaderNodeBsdfPrincipled", 6)

    # Semantic -> socket carrying its value.
    values = {}
    for slot in preset.slots:
        color = group_in.outputs[slot.label]
        rgb = slot.semantic("RGB")
        if rgb:
            values[rgb] = color
        singles = [(key, sem) for key, sem in slot.channels if key in ("R", "G", "B")]
        if singles:
            split = graph.new("ShaderNodeSeparateColor", 1)
            split.label = slot.label
            links.new(color, split.inputs["Color"])
            for key, sem in singles:
                values[sem] = split.outputs["RGB".index(key)]
        if slot.uses_alpha:
            values[slot.semantic("A")] = group_in.outputs[alpha_socket_name(slot)]

    if preset.is_specular:
        convert = graph.new("ShaderNodeGroup", 2, step=220)
        convert.node_tree = ensure_specgloss_group()
        convert.label = "Spec/Gloss to Metal/Rough"
        convert.width = 220
        graph.feed(convert.inputs["Diffuse"], values.get("diffuse"))
        graph.feed(convert.inputs["Specular"], values.get("specular"))
        values["base_color"] = convert.outputs["Base Color"]
        values["metallic"] = convert.outputs["Metallic"]

    base = values.get("base_color")
    if base is not None and "ao" in values:
        # Base color times AO, faded in by AO Strength (0 leaves it untouched).
        mix = graph.new("ShaderNodeMix", 4, data_type="RGBA", blend_type="MULTIPLY")
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
        gloss = values["gloss"]
        if preset.gloss_curve == "SQRT":
            gloss = graph.math("SQRT", 3, gloss)
        roughness = graph.math("SUBTRACT", 4, 1.0, gloss)
        if preset.gloss_curve == "SQUARED":
            roughness = graph.math("POWER", 5, roughness, 2.0)
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
            split = graph.new("ShaderNodeSeparateColor", 2)
            join = graph.new("ShaderNodeCombineColor", 4)
            join.label = "DirectX to OpenGL"
            links.new(normal_color, split.inputs["Color"])
            links.new(split.outputs["Red"], join.inputs["Red"])
            links.new(graph.math("SUBTRACT", 3, 1.0, split.outputs["Green"]), join.inputs["Green"])
            links.new(split.outputs["Blue"], join.inputs["Blue"])
            normal_color = join.outputs["Color"]
        normal_map = graph.new("ShaderNodeNormalMap", 5)
        links.new(normal_color, normal_map.inputs["Color"])
        links.new(group_in.outputs[NORMAL_STRENGTH], normal_map.inputs["Strength"])
        shading_normal = normal_map.outputs["Normal"]

    if "height" in values:
        bump = graph.new("ShaderNodeBump", 5)
        links.new(values["height"], bump.inputs["Height"])
        links.new(group_in.outputs[HEIGHT_STRENGTH], bump.inputs["Strength"])
        if shading_normal is not None:
            links.new(shading_normal, bump.inputs["Normal"])
        shading_normal = bump.outputs["Normal"]

    if shading_normal is not None:
        links.new(shading_normal, bsdf.inputs["Normal"])

    links.new(bsdf.outputs["BSDF"], group_out.inputs[SHADER_OUTPUT])


def _build_specgloss(group):
    """Spec/gloss to metal/rough, following the Khronos glTF conversion.

    Metallic is the value that makes a metal/rough surface reflect both the
    diffuse and the specular brightness; base color then blends between the
    color implied by diffuse and the one implied by specular.
    """
    iface = group.interface
    iface.new_socket("Base Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    iface.new_socket("Metallic", in_out="OUTPUT", socket_type="NodeSocketFloat")
    _new_input(iface, "Diffuse", "NodeSocketColor", (*SEMANTIC_DEFAULTS["diffuse"], 1.0))
    _new_input(iface, "Specular", "NodeSocketColor", (*SEMANTIC_DEFAULTS["specular"], 1.0))

    g = _Graph(group)
    f0 = DIELECTRIC_F0
    group_in = g.new("NodeGroupInput", 0, step=0)
    group_out = g.new("NodeGroupOutput", 9)
    diffuse, specular = group_in.outputs["Diffuse"], group_in.outputs["Specular"]

    def brightness(color, column):
        squared = g.vector("MULTIPLY", column, color, color)
        return g.math("SQRT", column + 1, g.vector("DOT_PRODUCT", column, squared, (0.299, 0.587, 0.114)))

    split = g.new("ShaderNodeSeparateColor", 1)
    g.links.new(specular, split.inputs["Color"])
    spec_max = g.math("MAXIMUM", 2, g.math("MAXIMUM", 1, split.outputs[0], split.outputs[1]), split.outputs[2])
    one_minus_spec = g.math("SUBTRACT", 2, 1.0, spec_max)
    d = brightness(diffuse, 1)
    s = brightness(specular, 1)

    # Solve a*m^2 + b*m + c = 0 for metallic m.
    b = g.math(
        "ADD", 4,
        g.math("DIVIDE", 3, g.math("MULTIPLY", 3, d, one_minus_spec), 1.0 - f0),
        g.math("SUBTRACT", 3, s, 2 * f0),
    )
    c = g.math("SUBTRACT", 3, f0, s)
    discriminant = g.math(
        "MAXIMUM", 5,
        g.math("SUBTRACT", 4, g.math("MULTIPLY", 4, b, b), g.math("MULTIPLY", 4, c, 4 * f0)),
        0.0,
    )
    root = g.math("DIVIDE", 5, g.math("SUBTRACT", 5, g.math("SQRT", 5, discriminant), b), 2 * f0, clamp=True)
    # Anything less reflective than a dielectric is not metal.
    is_dielectric = g.math("LESS_THAN", 4, s, f0)
    metallic = g.math("MULTIPLY", 6, root, g.math("SUBTRACT", 5, 1.0, is_dielectric))

    one_minus_metal = g.math("SUBTRACT", 6, 1.0, metallic)
    from_diffuse = g.vector(
        "SCALE", 7, diffuse,
        scale=g.math(
            "DIVIDE", 7,
            g.math("DIVIDE", 6, one_minus_spec, 1.0 - f0),
            g.math("MAXIMUM", 6, one_minus_metal, 1e-4),
        ),
    )
    from_specular = g.vector(
        "SCALE", 7,
        g.vector("SUBTRACT", 6, specular, g.math("MULTIPLY", 6, f0, one_minus_metal)),
        scale=g.math("DIVIDE", 7, 1.0, g.math("MAXIMUM", 6, metallic, 1e-4)),
    )

    blend = g.new("ShaderNodeMix", 8, data_type="RGBA", clamp_result=True)
    g.links.new(g.math("MULTIPLY", 7, metallic, metallic), _socket(blend.inputs, "Factor_Float"))
    g.links.new(from_diffuse, _socket(blend.inputs, "A_Color"))
    g.links.new(from_specular, _socket(blend.inputs, "B_Color"))

    g.links.new(_socket(blend.outputs, "Result_Color"), group_out.inputs["Base Color"])
    g.links.new(metallic, group_out.inputs["Metallic"])
