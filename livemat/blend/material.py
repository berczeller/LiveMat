# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Blend materials: a base LiveMat material with up to four more blended over it,
one per mask channel, previewed live in the viewport.

Each source material's LiveMat nodes are copied into a "layer" node group
that outputs its surface (base color, metallic, roughness, normal, height,
alpha, emission). The Blend material mixes those properties channel by
channel, then feeds one Principled BSDF, as engine shaders do.

Height blend (generic): a layer with mask m and height h (0 to 1) covers the
surface with weight
    w = clamp(((m - 0.5) * (i + t) + (h - 0.5) * i + t / 2) / t, 0, 1)
i being Height Influence and t the Transition width. Where the mask is 0 the
layer never shows and where it's 1 it always does, whatever the height; in
between, the height map decides where the edge falls. With i = 0, or height
off, w is simply m.
"""

import bpy

from ..build import nodegroup
from . import data

TAG = "livemat_is_blend"  # not livemat_blend_material: that name holds the settings
LAYER_GROUP_PREFIX = "LiveMat Layer "
SURFACE = [name for name, *_rest in nodegroup.SURFACE_OUTPUTS]
SOURCE_TAGS = {"texture", "group", "channels", "detail_uv", "detail_mapping"}


def is_source(material):
    """Materials LiveMat built that aren't Blend materials themselves."""
    return material is not None and material.get("livemat_preset") is not None and not material.get(TAG)


# Layer groups


def layer_group(source):
    """A node group holding `source`'s LiveMat nodes, outputting its surface. Rebuilt each time."""
    name = LAYER_GROUP_PREFIX + source.name
    group = bpy.data.node_groups.get(name)
    if group is None or group.library is not None:
        group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    group.nodes.clear()
    outputs = [i.name for i in group.interface.items_tree if i.item_type == "SOCKET" and i.in_out == "OUTPUT"]
    if outputs != SURFACE:
        # Only when the outputs differ: recreating them gives them new identifiers, which
        # would unlink this group in every other Blend material that uses it.
        group.interface.clear()
        for out_name, kind, _input, default in nodegroup.SURFACE_OUTPUTS:
            socket = group.interface.new_socket(out_name, in_out="OUTPUT", socket_type=kind)
            socket.default_value = default
    group["livemat_layer_of"] = source.name
    output = group.nodes.new("NodeGroupOutput")
    output.location = (600, 0)

    copies = {}
    for node in source.node_tree.nodes:
        if node.get("livemat") not in SOURCE_TAGS:
            continue
        copy = group.nodes.new(node.bl_idname)
        copy.location = node.location
        copy.label = node.label
        copy.hide = node.hide
        if node.bl_idname == "ShaderNodeTexImage":
            for prop in ("image", "interpolation", "projection", "extension"):
                setattr(copy, prop, getattr(node, prop))
        elif node.bl_idname == "ShaderNodeGroup":
            copy.node_tree = node.node_tree
        elif node.bl_idname == "ShaderNodeMapping":
            copy.vector_type = node.vector_type
        for target, original in zip(copy.inputs, node.inputs):
            if hasattr(original, "default_value") and not original.is_linked:
                try:
                    target.default_value = original.default_value
                except (AttributeError, TypeError, ValueError):
                    pass
        copies[node.name] = copy
    for link in source.node_tree.links:
        a, b = copies.get(link.from_node.name), copies.get(link.to_node.name)
        if a is None or b is None:
            continue
        group.links.new(
            next(s for s in a.outputs if s.identifier == link.from_socket.identifier),
            next(s for s in b.inputs if s.identifier == link.to_socket.identifier),
        )
    preset_node = next((c for n, c in copies.items() if source.node_tree.nodes[n].get("livemat") == "group"), None)
    if preset_node is not None:
        for name in SURFACE:
            socket = preset_node.outputs.get(name)
            if socket is not None:
                group.links.new(socket, output.inputs[name])
    return group


# The Blend material


class _Graph:
    def __init__(self, tree):
        self.tree = tree
        self.nodes, self.links = tree.nodes, tree.links
        self.y = {}

    def new(self, kind, column, **props):
        node = self.nodes.new(kind)
        y = self.y.get(column, 0)
        node.location = (column * 220, y)
        self.y[column] = y - 170
        for key, value in props.items():
            setattr(node, key, value)
        return node

    def feed(self, socket, value):
        if hasattr(value, "is_output"):
            self.links.new(value, socket)
        else:
            socket.default_value = value

    def math(self, operation, column, a, b=None, clamp=False):
        node = self.new("ShaderNodeMath", column, operation=operation, use_clamp=clamp)
        self.feed(node.inputs[0], a)
        if b is not None:
            self.feed(node.inputs[1], b)
        return node.outputs[0]


def _srgb_encode(g, value, column):
    """Linear to sRGB, exactly: the Color Attribute node decodes the stored bytes, the engine doesn't."""
    low = g.math("MULTIPLY", column, value, 12.92)
    power = g.math("POWER", column, value, 1.0 / 2.4)
    high = g.math("SUBTRACT", column + 1, g.math("MULTIPLY", column + 1, power, 1.055), 0.055)
    above = g.math("GREATER_THAN", column, value, 0.0031308)
    mix = g.new("ShaderNodeMix", column + 2, data_type="FLOAT")
    g.links.new(above, mix.inputs["Factor"])
    g.links.new(low, mix.inputs[2])
    g.links.new(high, mix.inputs[3])
    return mix.outputs[0]


def _mix(g, column, kind, factor, a, b):
    data_type = {"NodeSocketColor": "RGBA", "NodeSocketVector": "VECTOR", "NodeSocketFloat": "FLOAT"}[kind]
    node = g.new("ShaderNodeMix", column, data_type=data_type)
    sockets = {"RGBA": ("A_Color", "B_Color", "Result_Color"), "VECTOR": ("A_Vector", "B_Vector", "Result_Vector"), "FLOAT": ("A_Float", "B_Float", "Result_Float")}[data_type]
    factor_socket = next(s for s in node.inputs if s.identifier == "Factor_Float")
    g.links.new(factor, factor_socket)
    g.links.new(a, next(s for s in node.inputs if s.identifier == sockets[0]))
    g.links.new(b, next(s for s in node.inputs if s.identifier == sockets[1]))
    return next(s for s in node.outputs if s.identifier == sockets[2])


def build(material):
    """Rebuild a Blend material's nodes from its setup."""
    setup = material.livemat_blend_material
    tree = material.node_tree
    tree.nodes.clear()
    g = _Graph(tree)
    output = g.new("ShaderNodeOutputMaterial", 12)
    bsdf = g.new("ShaderNodeBsdfPrincipled", 11)
    g.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    material[TAG] = True

    base = setup.base
    if not is_source(base):
        return "Pick a LiveMat material as the base"

    # One layer group per source material, built once: rebuilding a group recreates
    # its sockets, which would invalidate every socket reference taken before.
    groups = {}

    def source_node(source, column):
        if source.name not in groups:
            groups[source.name] = layer_group(source)
        node = g.new("ShaderNodeGroup", column)
        node.node_tree = groups[source.name]
        node.label = source.name
        node.width = 200
        return node

    base_node = source_node(base, 0)
    surface = {name: base_node.outputs[name] for name in SURFACE}

    if setup.mask_source == "TEXTURE":
        channels = {}
        for channel in data.CHANNELS:
            image = getattr(setup, f"image_{channel.lower()}")
            if image is None:
                zero = g.new("ShaderNodeValue", 1)
                zero.outputs[0].default_value = 0.0
                channels[channel] = zero.outputs[0]
                continue
            node = g.new("ShaderNodeTexImage", 1)
            node.image = image
            node.label = f"Mask {channel}"
            node.interpolation = "Linear"
            channels[channel] = node.outputs["Color"]  # grayscale, Non-Color: the value as painted
    else:
        mask = g.new("ShaderNodeVertexColor", 0, layer_name=data.FINAL)
        mask.label = "Blend Mask"
        split = g.new("ShaderNodeSeparateColor", 1)
        g.links.new(mask.outputs["Color"], split.inputs["Color"])
        channels = {
            "R": _srgb_encode(g, split.outputs["Red"], 2),
            "G": _srgb_encode(g, split.outputs["Green"], 2),
            "B": _srgb_encode(g, split.outputs["Blue"], 2),
            "A": mask.outputs["Alpha"],  # alpha is stored linear
        }

    column = 5
    for channel in data.CHANNELS:
        source = getattr(setup, f"layer_{channel.lower()}")
        if not is_source(source):
            continue
        layer = source_node(source, column - 2)
        m = channels[channel]
        if setup.use_height:
            influence, transition = setup.height_influence, max(setup.transition, 1e-4)
            mask_part = g.math("MULTIPLY_ADD", column, g.math("SUBTRACT", column, m, 0.5), influence + transition)
            g.feed(mask_part.node.inputs[2], transition / 2.0)
            height = g.math("SUBTRACT", column, layer.outputs["Height"], 0.5)
            total = g.math("MULTIPLY_ADD", column + 1, height, influence)
            g.feed(total.node.inputs[2], mask_part)
            weight = g.math("DIVIDE", column + 1, total, transition, clamp=True)
        else:
            weight = m
        for name, kind, *_rest in nodegroup.SURFACE_OUTPUTS:
            surface[name] = _mix(g, column + 2, kind, weight, surface[name], layer.outputs[name])
        column += 3

    normal = g.new("ShaderNodeVectorMath", column, operation="NORMALIZE")
    g.links.new(surface["Normal"], normal.inputs[0])
    g.links.new(surface["Base Color"], bsdf.inputs["Base Color"])
    g.links.new(surface["Metallic"], bsdf.inputs["Metallic"])
    g.links.new(surface["Roughness"], bsdf.inputs["Roughness"])
    g.links.new(normal.outputs[0], bsdf.inputs["Normal"])
    g.links.new(surface["Alpha"], bsdf.inputs["Alpha"])
    g.links.new(surface["Emission"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0
    output.location = (column * 220 + 440, 0)
    bsdf.location = (column * 220 + 200, 0)
    return None


def create(obj):
    """A Blend material based on obj's active material, assigned in its place."""
    base = obj.active_material
    material = bpy.data.materials.new(f"{base.name} Blend" if base else "Blend")
    material[TAG] = True
    material.livemat_blend_material.base = base if is_source(base) else None  # builds through its update
    build(material)
    if obj.material_slots:
        obj.active_material = material
    else:
        obj.data.materials.append(material)
    return material


def rebuild_all():
    for material in bpy.data.materials:
        if material.get(TAG) and material.library is None:
            build(material)
