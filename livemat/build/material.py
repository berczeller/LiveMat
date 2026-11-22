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
_RENDER_METHOD = "livemat_render_method"  # the user's setting before LiveMat switched it

# Names the same color spaces go by in other OCIO configs (ACES and friends).
COLORSPACE_ALIASES = {
    "sRGB": ("sRGB", "sRGB - Texture", "Utility - sRGB - Texture", "srgb_tx"),
    "Non-Color": ("Non-Color", "Raw", "Utility - Raw", "raw", "data"),
}


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
    - A material LiveMat built before keeps its image nodes (and whatever
      feeds their Vector input); only the images are swapped, and tweaked
      group parameters carry over.
    - An untouched Principled BSDF + Output (a fresh material) is cleared.
    - Anything else is kept in a "Before LiveMat" frame, disconnected.

    `folder` is remembered on the material so it can be rescanned later,
    for example to switch presets.
    """
    if material.library is not None:
        raise RuntimeError(f"{material.name} is linked from another file and can't be edited")
    tree = material.node_tree
    if tree is None:
        raise RuntimeError(f"{material.name} has no node tree")
    nodes, links = tree.nodes, tree.links
    report = BuildReport(material=material.name)

    previous_values = {}
    kept = {}  # slot id -> image node reused from the last build
    if rebuild or _is_trivial(tree):
        nodes.clear()
    elif material.get("livemat_preset"):
        previous_values = _group_values(tree)
        for node in [n for n in nodes if n.get(TAG)]:
            slot_id = node.get("livemat_slot")
            if node.bl_idname == "ShaderNodeTexImage" and preset.slot(slot_id) and slot_id not in kept:
                kept[slot_id] = node
            else:
                nodes.remove(node)
    else:
        _set_aside(tree)
        report.kept_aside = True

    output = _material_output(tree)
    # Only the surface: links into Displacement or Volume are the user's.
    for link in list(output.inputs["Surface"].links):
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
        tex = kept.pop(slot.id, None)
        path = texture_set.files.get(slot.id)
        if path is not None:
            image = load_image(path, slot, udim=slot.id in texture_set.udim_slots)
        elif tex is not None and tex.image is not None and not tex.image.filepath:
            image = tex.image  # generated or packed without a file: nothing on disk, keep it
        else:
            if tex is not None:
                nodes.remove(tex)
            report.missing.append(slot.id)
            continue
        if tex is None:
            tex = nodes.new("ShaderNodeTexImage")
            tex.location = (-400, y)
            tex[TAG] = "texture"
            tex["livemat_slot"] = slot.id
        tex.image = image
        tex.label = slot.label
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
        store_folder(material, folder)
    alpha_slot = preset.slot_for("alpha")
    if alpha_slot is not None and alpha_slot.id in report.loaded:
        # Dithered handles cutouts and hashed transparency in Eevee without sorting issues.
        if _RENDER_METHOD not in material:
            material[_RENDER_METHOD] = material.surface_render_method
        material.surface_render_method = "DITHERED"
    elif _RENDER_METHOD in material:
        try:
            material.surface_render_method = material[_RENDER_METHOD]
        except TypeError:
            pass
        del material[_RENDER_METHOD]
    return report


def store_folder(material, folder):
    """Remember the texture folder, relative to the .blend when it's saved, so projects can move."""
    value = folder
    if bpy.data.filepath:
        try:
            value = bpy.path.relpath(folder)
        except ValueError:  # another drive
            pass
    material["livemat_folder"] = value


def material_folder(material):
    value = material.get("livemat_folder") if material is not None else None
    return os.path.normpath(bpy.path.abspath(value)) if value else None


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
    """Load an image with the color settings the slot needs.

    An image already loaded from the same file is reused only when its settings
    already match, so images used elsewhere in the file are never changed.
    """
    if udim:
        folder, name = os.path.split(path)
        path = os.path.join(folder, _TILE.sub("<UDIM>", name, count=1))
    alpha_mode = "CHANNEL_PACKED" if slot.alpha_is_data else "STRAIGHT"
    wanted = _normalized(path)
    for image in bpy.data.images:
        if (
            image.library is None
            and image.filepath
            and _normalized(bpy.path.abspath(image.filepath)) == wanted
            and (image.source == "TILED") == udim
            and image.alpha_mode == alpha_mode
            and _colorspace_matches(image, slot.colorspace)
        ):
            return image

    image = bpy.data.images.load(path, check_existing=False)
    if udim:
        image.source = "TILED"
    _set_colorspace(image, slot.colorspace)
    # Channel packed keeps Blender from mixing a data alpha (gloss, smoothness) into RGB.
    image.alpha_mode = alpha_mode
    return image


def _normalized(path):
    return os.path.normcase(os.path.normpath(path))


def _colorspace_matches(image, colorspace):
    settings = image.colorspace_settings
    try:
        name = settings.name
    except (TypeError, ValueError):  # freshly loaded tiles may report none
        return False
    if colorspace == "Non-Color" and settings.is_data:
        return True
    return name in COLORSPACE_ALIASES[colorspace]


def _set_colorspace(image, colorspace):
    settings = image.colorspace_settings
    for name in COLORSPACE_ALIASES[colorspace]:
        try:
            settings.name = name
            return
        except TypeError:
            continue
    if colorspace == "Non-Color":
        settings.is_data = True  # no raw space in this config, but data still skips conversion


def _is_trivial(tree):
    """True for an empty tree, or a Principled BSDF + Output nobody has touched."""
    kinds = sorted(n.type for n in tree.nodes)
    if kinds in ([], ["OUTPUT_MATERIAL"]):
        return True
    if kinds != ["BSDF_PRINCIPLED", "OUTPUT_MATERIAL"] or len(tree.links) > 1:
        return False
    bsdf = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
    fresh = tree.nodes.new("ShaderNodeBsdfPrincipled")
    try:
        if (bsdf.distribution, bsdf.subsurface_method) != (fresh.distribution, fresh.subsurface_method):
            return False
        for used, default in zip(bsdf.inputs, fresh.inputs):
            if used.is_linked:
                return False
            if hasattr(used, "default_value") and not _same(used.default_value, default.default_value):
                return False
        return True
    finally:
        tree.nodes.remove(fresh)


def _same(a, b):
    if hasattr(a, "__len__"):
        return len(a) == len(b) and all(abs(x - y) < 1e-6 for x, y in zip(a, b))
    if isinstance(a, float):
        return abs(a - b) < 1e-6
    return a == b


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
