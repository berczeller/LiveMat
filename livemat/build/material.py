# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Fill a material with a texture set: image nodes feeding the preset's node group."""

import os
import re
from dataclasses import dataclass, field

import bpy

from ..core import naming
from ..core.scanner import TextureSet
from . import nodegroup

TAG = "livemat"  # custom property marking nodes LiveMat owns
FRAME_LABEL = "Before LiveMat"


@dataclass
class BuildReport:
    material: str
    loaded: dict = field(default_factory=dict)  # slot id -> image name
    missing: list = field(default_factory=list)  # slot ids with no texture
    kept_aside: bool = False


def build_material(material, texture_set, preset, *, rebuild=False, folder=None):
    """Wire `texture_set` into `material` using `preset`.

    Existing nodes are handled in this order:
    - `rebuild=True` clears the whole tree.
    - A material LiveMat built before loses only LiveMat's nodes; tweaked
      group parameters carry over.
    - A lone Principled BSDF + Output (a fresh or imported material) is cleared.
    - Anything else is kept in a "Before LiveMat" frame, disconnected.

    `folder` is remembered on the material so it can be rescanned later,
    for example to switch presets.
    """
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    report = BuildReport(material=material.name)

    previous_values = {}
    if rebuild or _is_trivial(tree):
        nodes.clear()
    elif material.get("livemat_preset"):
        previous_values = _group_values(tree)
        for node in [n for n in nodes if n.get(TAG)]:
            nodes.remove(node)
    else:
        _set_aside(tree)
        report.kept_aside = True

    output = _material_output(tree)
    for link in [l for l in links if l.to_node == output]:
        links.remove(link)

    top = max((n.location.y for n in nodes if n != output), default=0.0) + 600 if report.kept_aside else 0.0
    output.location = (300, top)

    group_node = nodes.new("ShaderNodeGroup")
    group_node.node_tree = nodegroup.ensure_group(preset)
    group_node.name = group_node.label = "LiveMat"
    group_node.location = (0, top)
    group_node.width = 240
    group_node[TAG] = "group"
    old_stamp = previous_values.pop(_STAMP, None)
    if old_stamp != group_node.node_tree.get("livemat_stamp"):
        # A different preset or builder: slot defaults may mean something else now.
        parameters = {name for name, *_rest in nodegroup.PARAMETERS}
        previous_values = {k: v for k, v in previous_values.items() if k in parameters}
    for name, value in previous_values.items():
        socket = group_node.inputs.get(name)
        if socket is not None and not socket.is_linked:
            socket.default_value = value

    y = top
    for slot in preset.slots:
        path = texture_set.files.get(slot.id)
        if path is None:
            report.missing.append(slot.id)
            continue
        image = load_image(path, slot, udim=slot.id in texture_set.udim_slots)
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.label = slot.label
        tex.location = (-400, y)
        tex[TAG] = "texture"
        tex["livemat_slot"] = slot.id
        y -= 280
        links.new(tex.outputs["Color"], group_node.inputs[slot.label])
        if slot.uses_alpha:
            links.new(tex.outputs["Alpha"], group_node.inputs[nodegroup.alpha_socket_name(slot)])
        report.loaded[slot.id] = image.name

    links.new(group_node.outputs[nodegroup.SHADER_OUTPUT], output.inputs["Surface"])

    material["livemat_preset"] = preset.id
    material["livemat_set"] = texture_set.name
    material["livemat_key"] = texture_set.key
    if folder is not None:
        material["livemat_folder"] = folder
    alpha_slot = preset.slot_for("alpha")
    if alpha_slot is not None and alpha_slot.id in report.loaded:
        # Dithered handles cutouts and hashed transparency in Eevee without sorting issues.
        material.surface_render_method = "DITHERED"
    return report


def texture_set_from_material(material):
    """The texture set a LiveMat material was built from, read back from its image nodes."""
    texture_set = TextureSet(
        name=material.get("livemat_set", material.name),
        key=material.get("livemat_key") or naming.asset_key(material.name),
    )
    for node in material.node_tree.nodes:
        slot_id = node.get("livemat_slot")
        image = getattr(node, "image", None)
        if not slot_id or image is None or not image.filepath:
            continue
        path = bpy.path.abspath(image.filepath, library=image.library)
        if image.source == "TILED":
            first = min(tile.number for tile in image.tiles)
            path = path.replace("<UDIM>", str(first))
            texture_set.udim_slots.add(slot_id)
        texture_set.files[slot_id] = path
    return texture_set


def livemat_texture_nodes(material):
    """Slot id -> image texture node, for the nodes LiveMat added."""
    if material is None or material.node_tree is None:
        return {}
    return {n["livemat_slot"]: n for n in material.node_tree.nodes if n.get("livemat_slot")}


def livemat_group_node(material):
    if material is None or material.node_tree is None:
        return None
    return next((n for n in material.node_tree.nodes if n.get(TAG) == "group"), None)


_TILE = re.compile(r"1\d{3}(?=\D*$)")


def load_image(path, slot, *, udim=False):
    """Load (or reuse) an image with the color settings the slot needs."""
    if udim:
        folder, name = os.path.split(path)
        path = os.path.join(folder, _TILE.sub("<UDIM>", name, count=1))
    image = bpy.data.images.load(path, check_existing=True)
    if udim and image.source != "TILED":
        image.source = "TILED"
    # Tiled images report no color space until set, so don't read it first.
    if udim or image.colorspace_settings.name != slot.colorspace:
        image.colorspace_settings.name = slot.colorspace
    # Channel packed keeps Blender from mixing a data alpha (gloss, smoothness) into RGB.
    image.alpha_mode = "CHANNEL_PACKED" if slot.alpha_is_data else "STRAIGHT"
    return image


def _is_trivial(tree):
    kinds = sorted(n.type for n in tree.nodes)
    return kinds in ([], ["OUTPUT_MATERIAL"], ["BSDF_PRINCIPLED", "OUTPUT_MATERIAL"])


def _set_aside(tree):
    nodes = tree.nodes
    keep = [n for n in nodes if n.type != "OUTPUT_MATERIAL" and n.parent is None]
    if not keep:
        return
    frame = nodes.new("NodeFrame")
    frame.label = FRAME_LABEL
    for node in keep:
        node.parent = frame


def _material_output(tree):
    outputs = [n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"]
    active = next((n for n in outputs if n.is_active_output), None)
    if active or outputs:
        return active or outputs[0]
    return tree.nodes.new("ShaderNodeOutputMaterial")


_STAMP = object()  # key for the old group's stamp in _group_values' result


def _group_values(tree):
    """Unlinked input values on the current LiveMat group node, by socket name."""
    group_node = next((n for n in tree.nodes if n.get(TAG) == "group"), None)
    if group_node is None or group_node.node_tree is None:
        return {}
    values = {_STAMP: group_node.node_tree.get("livemat_stamp")}
    for socket in group_node.inputs:
        if not socket.is_linked and hasattr(socket, "default_value"):
            value = socket.default_value
            values[socket.name] = tuple(value) if hasattr(value, "__len__") else value
    return values
