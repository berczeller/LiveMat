# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Paint layers with Blender's own vertex paint brushes.

Brushes can't be limited to one channel, so they paint a temporary
grayscale attribute (PAINT) instead. While painting, the strokes are copied
into the layer and the mask recomposited a moment after each change, so the
material preview follows the brush. Leaving Vertex Paint (with Done or any
other way) stores the strokes and removes the temporary attribute.
"""

import zlib

import bpy
import numpy as np
from bpy.app.handlers import persistent

from . import data

DELAY = 0.1  # seconds after a stroke before the mask is recomposited

_last = {}  # mesh name -> checksum of the strokes last copied, to skip our own updates


def painting_layer(mesh):
    state = mesh.livemat_blend
    if not state.painting:
        return None, None
    for channel in data.CHANNELS:
        for layer in data.layers_of(state, channel):
            if layer.uid == state.painting:
                return channel, layer
    return None, None


def start(context, obj, layer):
    """Open `layer` for painting: fill PAINT with its strokes so far and enter Vertex Paint."""
    mesh = obj.data
    state = mesh.livemat_blend
    with data.access(mesh) as acc:
        stored = acc.read_layer(data.layer_attribute(layer.uid))
        gray = stored[:, 0]
        acc.write_colors(data.PAINT, np.stack([gray, gray, gray, np.ones_like(gray)], axis=1))
    state.painting = layer.uid
    data.make_active(mesh, data.PAINT)
    _last[mesh.name] = _checksum(mesh)
    if context.mode != "PAINT_VERTEX":
        bpy.ops.object.mode_set(mode="VERTEX_PAINT")


def _strokes(mesh):
    attribute = mesh.color_attributes.get(data.PAINT)
    if attribute is None:
        return None
    values = np.zeros(len(attribute.data) * 4, dtype=np.float32)
    attribute.data.foreach_get("color_srgb", values)
    # The brush paints colors; its brightness is what counts.
    return values.reshape(-1, 4)[:, :3].mean(axis=1)


def _checksum(mesh):
    strokes = _strokes(mesh)
    return None if strokes is None else zlib.crc32(strokes.tobytes())


def sync(mesh):
    """Copy the strokes into the painting layer and recomposite. Returns True when something changed."""
    channel, layer = painting_layer(mesh)
    if layer is None:
        return False
    strokes = _strokes(mesh)
    if strokes is None:
        return False
    checksum = zlib.crc32(strokes.tobytes())
    if _last.get(mesh.name) == checksum:
        return False
    _last[mesh.name] = checksum
    with data.access(mesh) as acc:
        stored = acc.read_layer(data.layer_attribute(layer.uid))
        stored[:, 0] = strokes
        acc.write_layer(data.layer_attribute(layer.uid), stored)
    data.composite_mesh(mesh)
    return True


def finish(mesh):
    """Store the strokes, remove PAINT and stop painting. Doesn't change modes."""
    sync(mesh)
    mesh.livemat_blend.painting = ""
    attribute = mesh.color_attributes.get(data.PAINT)
    if attribute is not None:
        mesh.color_attributes.remove(attribute)
    _last.pop(mesh.name, None)
    data.composite_mesh(mesh)


def _painting_meshes():
    return [m for m in bpy.data.meshes if m.library is None and getattr(m, "livemat_blend", None) and m.livemat_blend.painting]


def _tick():
    try:
        for mesh in _painting_meshes():
            users = [o for o in bpy.data.objects if o.data == mesh]
            if any(o.mode == "VERTEX_PAINT" for o in users):
                sync(mesh)
            else:
                finish(mesh)  # left Vertex Paint some other way: keep the strokes, clean up
    except Exception:  # a failing timer would silently stop syncing
        import traceback

        traceback.print_exc()
    return None


@persistent
def _on_depsgraph(_scene, _depsgraph):
    if _painting_meshes() and not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=DELAY)


def register():
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def unregister():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _last.clear()
