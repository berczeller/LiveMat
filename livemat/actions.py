# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Edits on one LiveMat material, shared by operators and property callbacks."""

import os
import time

import bpy

from . import refresh, registry, thumbs
from .build import material as builder
from .build import tangents
from .core import naming

NONE = "NONE"
_FOLDER_TTL = 5.0  # seconds a folder listing is trusted before reading it again
_folder_cache = {}  # (folder, recursive) -> (time, [paths])
_picker_items = {}  # (material, slot) -> enum items; Blender needs them kept alive


def livemat_material(name):
    material = bpy.data.materials.get(name)
    if material is None or material.library is not None or not material.get("livemat_preset"):
        return None, None
    return material, registry.get(material["livemat_preset"])


def rebuild(material, preset, texture_set=None):
    """Build `material` again from its own textures (or `texture_set`), keeping its settings."""
    if texture_set is None:
        texture_set = builder.texture_set_from_material(material)
    builder.build_material(material, texture_set, preset, folder=builder.material_folder(material))
    if tangents.per_vertex(material):
        tangents.update_users(material)


def assign_file(material, preset, slot_id, path):
    """Put the image at `path` in a slot, or empty the slot when `path` is None."""
    if path is None:
        node = builder.livemat_texture_nodes(material).get(slot_id)
        if node is not None:  # removed outright, or a generated image would be kept
            material.node_tree.nodes.remove(node)
        texture_set = builder.texture_set_from_material(material)
        rebuild(material, preset, texture_set)
        refresh.set_cleared(material, refresh.cleared_slots(material) | {slot_id})
        return
    texture_set = builder.texture_set_from_material(material)
    texture_set.files[slot_id] = path
    parsed = naming.parse_filename(os.path.basename(path))
    if parsed is not None and parsed.udim is not None:
        texture_set.udim_slots.add(slot_id)
    else:
        texture_set.udim_slots.discard(slot_id)
    rebuild(material, preset, texture_set)
    refresh.set_cleared(material, refresh.cleared_slots(material) - {slot_id})


def apply_tangents(material):
    """Push the material's tangent mode to its group node, writing bitangents when needed.

    Returns the names of meshes that couldn't get Unity tangents.
    """
    group_node = builder.livemat_group_node(material)
    unity = material.livemat.tangents in tangents.PER_VERTEX
    if group_node is not None:
        from .build.nodegroup import UNITY_TANGENTS

        socket = group_node.inputs.get(UNITY_TANGENTS)
        if socket is not None:
            socket.default_value = 1.0 if unity else 0.0
    return tangents.update_users(material) if unity else []


def folder_images(folder, recursive=True):
    """Image files in `folder`, cached for a few seconds since the panel asks on every redraw."""
    if not folder or not os.path.isdir(folder):
        return []
    key = (folder, recursive)
    cached = _folder_cache.get(key)
    if cached is not None and time.monotonic() - cached[0] < _FOLDER_TTL:
        return cached[1]
    found = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        found.extend(
            os.path.join(root, name)
            for name in sorted(files)
            if os.path.splitext(name)[1].lower() in naming.IMAGE_EXTENSIONS
        )
        if not recursive:
            break
    _folder_cache[key] = (time.monotonic(), found)
    return found


def forget_folders():
    _folder_cache.clear()


def _number(path):
    import zlib

    return zlib.crc32(os.path.normcase(path).encode()) & 0x7FFFFFFF or 1


def picker_items(state, _context):
    """Texture picker entries for one slot: None, then the material folder's images.

    Files of the material's own texture set come first, like Unity's picker
    showing the most likely matches at the top.
    """
    material = state.id_data
    current = builder.texture_set_from_material(material).files.get(state.slot)
    folder = builder.material_folder(material)
    paths = list(folder_images(folder, material.get("livemat_recursive", True)))
    if current and current not in paths:
        paths.insert(0, current)
    key = material.get("livemat_key", "")

    def own_set(path):
        parsed = naming.parse_filename(os.path.basename(path))
        return parsed is not None and naming.asset_key(parsed.base).startswith(key)

    paths.sort(key=lambda p: (not own_set(p), os.path.basename(p).casefold()))
    items = [(NONE, "None", "Leave this slot empty", "BLANK1", 0)]
    items += [(p, os.path.basename(p), p, thumbs.file_icon(p), _number(p)) for p in paths]
    _picker_items[(material.name, state.slot)] = items
    return items


def picker_get(state):
    current = builder.texture_set_from_material(state.id_data).files.get(state.slot)
    return _number(current) if current else 0


def picker_set(state, value):
    material = state.id_data
    items = _picker_items.get((material.name, state.slot), ())
    path = next((item[0] for item in items if item[4] == value), None)
    if path is None:
        # The list changed since the popup was drawn (a new export, another
        # material's picker): read it again rather than drop the click.
        items = picker_items(state, None)
        path = next((item[0] for item in items if item[4] == value), None)
    if path is None:
        print(f"LiveMat: the picked texture isn't in {material.name}'s folder any more")
        return
    material, preset = livemat_material(material.name)
    if material is None or preset is None:
        return
    try:
        assign_file(material, preset, state.slot, None if path == NONE else path)
    except (RuntimeError, TypeError) as error:
        print(f"LiveMat: couldn't load {path}: {error}")


def channels_changed(state, _context):
    material, preset = livemat_material(state.id_data.name)
    if material is not None and preset is not None:
        rebuild(material, preset)


def tangents_changed(state, _context):
    material = state.id_data
    if material.get("livemat_preset"):
        failed = apply_tangents(material)
        for name in failed:
            print(f"LiveMat: {name} has no UV map, so per-vertex tangents can't be computed for it")
