# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Keep per-vertex bitangents current without pressing Refresh.

Blender reports every change through the depsgraph. Meshes that changed, or
objects that just got a per-vertex material, are noted, and a moment later
their bitangents are written again. A checksum of the geometry skips meshes
that didn't really change (moving an object, say), and meshes being edited
wait until their object is back in Object Mode, when the edit is final.
"""

import traceback

import bpy
from bpy.app.handlers import persistent

from .build import tangents

DELAY = 0.25  # seconds to wait for a burst of changes to settle

_geometry = set()  # object names whose geometry changed
_touched = set()  # object names that changed in other ways (new material, new object)


@persistent
def _on_depsgraph(_scene, depsgraph):
    for update in depsgraph.updates:
        obj = update.id
        if not isinstance(obj, bpy.types.Object) or obj.type != "MESH":
            continue
        (_geometry if update.is_updated_geometry else _touched).add(obj.original.name)
    if (_geometry or _touched) and not bpy.app.timers.is_registered(_process):
        bpy.app.timers.register(_process, first_interval=DELAY)


def _needs_bitangents(obj):
    return any(tangents.per_vertex(slot.material) for slot in obj.material_slots)


def _process():
    _run()
    return None  # a timer that returns None runs once


def _run():
    """Write bitangents for the meshes noted since the last pass. Returns the mesh names it wrote."""
    written = []
    try:
        names = _geometry | _touched
        geometry = set(_geometry)
        _geometry.clear()
        _touched.clear()
        for name in sorted(names):
            obj = bpy.data.objects.get(name)
            if obj is None or obj.type != "MESH" or obj.data is None or obj.data.library is not None:
                continue
            if obj.mode != "OBJECT":
                continue  # leaving Edit or Sculpt Mode reports the final geometry again
            if not _needs_bitangents(obj):
                continue
            mesh = obj.data
            if name in geometry or tangents.BITANGENT_ATTRIBUTE not in mesh.attributes:
                if not tangents.is_current(mesh) and tangents.write_bitangents(mesh):
                    written.append(mesh.name)
    except Exception:  # an exception here would surface on every change
        traceback.print_exc()
    return written


def process_now():
    """Run the pending pass right away. Returns the names of the meshes it wrote."""
    if bpy.app.timers.is_registered(_process):
        bpy.app.timers.unregister(_process)
    return _run()


@persistent
def _forget(_dummy=None):
    _geometry.clear()
    _touched.clear()
    tangents.forget()


def register():
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.handlers.load_post.append(_forget)


def unregister():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if _forget in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_forget)
    if bpy.app.timers.is_registered(_process):
        bpy.app.timers.unregister(_process)
    _forget()
