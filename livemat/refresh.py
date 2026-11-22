# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Bring LiveMat materials up to date with the files on disk."""

import os

import bpy

from . import registry
from .build import material as builder
from .build import nodegroup
from .core import scanner

CLEARED = "livemat_cleared"  # slots the user emptied on purpose; Refresh leaves them empty


def livemat_materials():
    return [
        m
        for m in bpy.data.materials
        if m.get("livemat_preset") and m.library is None and m.node_tree is not None
    ]


def livemat_images(materials=None):
    images = {}
    for material in materials if materials is not None else livemat_materials():
        for node in builder.livemat_texture_nodes(material).values():
            if node.image is not None:
                images[node.image.name] = node.image
    return list(images.values())


def cleared_slots(material):
    return set(material.get(CLEARED, ()))


def set_cleared(material, slots):
    if slots:
        material[CLEARED] = sorted(slots)
    elif CLEARED in material:
        del material[CLEARED]


def update_material(material):
    """Pick up maps added to the material's folder, and replacements for files that are gone.

    Files the material already uses are never swapped for others, so a texture
    picked by hand stays. Returns (rebuilt, slot ids whose file is missing).
    """
    preset = registry.get(material.get("livemat_preset", ""))
    if preset is None:
        return False, []
    current = builder.texture_set_from_material(material)
    merged = builder.texture_set_from_material(material)
    folder = builder.material_folder(material)

    if folder and os.path.isdir(folder):
        recursive = material.get("livemat_recursive", True)
        found = next(
            (s for s in scanner.scan_folder(folder, preset, recursive=recursive).sets if s.key == current.key),
            None,
        )
        # Cleared slots stay empty; generated or packed images have no file but still fill their slot.
        skip = cleared_slots(material) | {
            slot_id
            for slot_id, node in builder.livemat_texture_nodes(material).items()
            if node.image is not None and not node.image.filepath
        }
        for slot_id, path in (found.files.items() if found else ()):
            if slot_id in skip:
                continue
            existing = merged.files.get(slot_id)
            if existing is None or not os.path.isfile(existing):
                merged.files[slot_id] = path
                if slot_id in found.udim_slots:
                    merged.udim_slots.add(slot_id)
                else:
                    merged.udim_slots.discard(slot_id)

    group_node = builder.livemat_group_node(material)
    outdated = group_node is None or group_node.node_tree is None or (
        group_node.node_tree.get("livemat_stamp") != nodegroup.stamp(preset)
    )
    state = getattr(material, "livemat", None)
    unsynced = state is not None and len(state.slots) != len(preset.slots)
    # A slot renamed in the preset drops this material's links when another
    # material rebuilds the shared group first.
    unlinked = any(not n.outputs["Color"].is_linked for n in builder.livemat_texture_nodes(material).values())
    # Files changed, an add-on update brought new group inputs or panel state, or links went missing.
    rebuilt = merged.files != current.files or outdated or unsynced or unlinked
    if rebuilt:
        builder.build_material(material, merged, preset, folder=folder)
    missing = sorted(s for s, path in merged.files.items() if not os.path.isfile(path))
    return rebuilt, missing


def reload_images(images):
    count = 0
    for image in images:
        if image.source not in {"FILE", "TILED"}:
            continue
        image.reload()
        if image.preview is not None:
            image.preview.reload()
        count += 1
    return count


def redraw_all():
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            area.tag_redraw()
