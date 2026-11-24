# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Where Blend keeps its data, and how it reads and writes it.

Everything lives on the mesh, so it's saved with the .blend and shared by
instances:
- the final mask, a byte color attribute on face corners named FINAL. It's
  the one exported to FBX, written as raw bytes, so 0.5 reaches the engine
  as 128/255 with Blender's default FBX settings
- one hidden float vector attribute per layer, (value, coverage, unused)
  per corner. Hidden attributes (dot names) aren't exported
- one hidden boolean attribute per saved selection

In Edit Mode, mesh attributes are stale and writes to them are lost when the
mode ends, so all access goes through bmesh there.
"""

import uuid
from contextlib import contextmanager

import bmesh
import bpy
import numpy as np

from . import composite

FINAL = "LiveMat Blend"
VIEW = "LiveMat View"  # temporary attribute for viewing one channel in grayscale
LAYER_PREFIX = ".lm_layer_"
SET_PREFIX = ".lm_set_"
CHANNELS = ("R", "G", "B", "A")


def new_uid():
    return uuid.uuid4().hex[:10]


def layer_attribute(uid):
    return LAYER_PREFIX + uid


def set_attribute(uid):
    return SET_PREFIX + uid


def layers_of(state, channel):
    """Layers of one channel, top first."""
    return getattr(state, f"layers_{channel.lower()}")


def all_layers(state):
    for channel in CHANNELS:
        yield from layers_of(state, channel)


class _ObjectAccess:
    """Per-corner data through mesh attributes and numpy (Object Mode)."""

    def __init__(self, mesh):
        self.mesh = mesh
        self.count = len(mesh.loops)

    def ensure_layer(self, name):
        if name not in self.mesh.attributes:
            self.mesh.attributes.new(name, "FLOAT_VECTOR", "CORNER")

    def read_layer(self, name):
        values = np.zeros(self.count * 3, dtype=np.float32)
        attribute = self.mesh.attributes.get(name)
        if attribute is not None:
            attribute.data.foreach_get("vector", values)
        return values.reshape(-1, 3)

    def write_layer(self, name, data):
        self.ensure_layer(name)
        self.mesh.attributes[name].data.foreach_set("vector", np.ascontiguousarray(data, dtype=np.float32).ravel())

    def remove_layer(self, name):
        attribute = self.mesh.attributes.get(name)
        if attribute is not None:
            self.mesh.attributes.remove(attribute)

    def write_colors(self, name, rgba):
        attribute = self.mesh.color_attributes.get(name)
        if attribute is not None and (attribute.data_type != "BYTE_COLOR" or attribute.domain != "CORNER"):
            self.mesh.color_attributes.remove(attribute)
            attribute = None
        if attribute is None:
            attribute = self.mesh.color_attributes.new(name, "BYTE_COLOR", "CORNER")
        # color_srgb writes the byte as given: 0.5 is stored as 128.
        attribute.data.foreach_set("color_srgb", np.ascontiguousarray(rgba, dtype=np.float32).ravel())

    def finish(self):
        self.mesh.update()


class _EditAccess:
    """Per-corner data through bmesh (Edit Mode). Corners follow face order."""

    def __init__(self, mesh, bm):
        self.mesh = mesh
        self.bm = bm
        self._gather()

    def _gather(self):
        # Adding a layer reallocates corner data, which invalidates loop references, so
        # the list is rebuilt after every new layer.
        self.loops = [loop for face in self.bm.faces for loop in face.loops]
        self.count = len(self.loops)

    def ensure_layer(self, name):
        layers = self.bm.loops.layers.float_vector
        layer = layers.get(name)
        if layer is None:
            layer = layers.new(name)
            self._gather()
        return layer

    def read_layer(self, name):
        layer = self.bm.loops.layers.float_vector.get(name)
        if layer is None:
            return np.zeros((self.count, 3), dtype=np.float32)
        return np.array([loop[layer] for loop in self.loops], dtype=np.float32).reshape(-1, 3)

    def write_layer(self, name, data):
        layer = self.ensure_layer(name)
        for loop, row in zip(self.loops, data):
            loop[layer] = row

    def remove_layer(self, name):
        layer = self.bm.loops.layers.float_vector.get(name)
        if layer is not None:
            self.bm.loops.layers.float_vector.remove(layer)
            self._gather()

    def write_colors(self, name, rgba):
        layers = self.bm.loops.layers.color
        layer = layers.get(name)
        if layer is None:
            layer = layers.new(name)
            self._gather()
        for loop, row in zip(self.loops, rgba):
            loop[layer] = row  # bmesh byte colors take the raw value, like color_srgb

    def finish(self):
        bmesh.update_edit_mesh(self.mesh, loop_triangles=False, destructive=False)


@contextmanager
def access(mesh, bm=None):
    """Read and write per-corner data whatever mode the mesh is in."""
    if mesh.is_editmode:
        acc = _EditAccess(mesh, bm or bmesh.from_edit_mesh(mesh))
    else:
        acc = _ObjectAccess(mesh)
    yield acc
    acc.finish()


def composite_mesh(mesh, bm=None):
    """Blend every channel's layers into FINAL (and VIEW when it's shown)."""
    state = mesh.livemat_blend
    if not mesh.is_editmode:
        prune(mesh)
    with access(mesh, bm) as acc:
        result = np.zeros((acc.count, 4), dtype=np.float32)
        for index, channel in enumerate(CHANNELS):
            stack = []
            for layer in layers_of(state, channel):
                if not layer.visible:
                    continue
                data = acc.read_layer(layer_attribute(layer.uid))
                stack.append((data[:, 0], data[:, 1], layer.opacity, layer.blend_mode))
            result[:, index] = composite.channel(state.base[index], stack, acc.count)
        acc.write_colors(FINAL, result)
        if state.view_channel:
            column = result[:, CHANNELS.index(state.view_channel)]
            gray = np.stack([column, column, column, np.ones_like(column)], axis=1)
            acc.write_colors(VIEW, gray)
    make_active(mesh, VIEW if state.view_channel else FINAL)


def prune(mesh):
    """Remove hidden layer and selection attributes nothing refers to any more.

    Edit Mode undo restores mesh data but not the layer and selection lists,
    so an undone removal can leave data behind. Only runs in Object Mode.
    """
    state = mesh.livemat_blend
    wanted = {layer_attribute(layer.uid) for layer in all_layers(state)}
    wanted |= {set_attribute(item.uid) for item in state.sets}
    for attribute in [a for a in mesh.attributes if a.name.startswith((LAYER_PREFIX, SET_PREFIX))]:
        if attribute.name not in wanted:
            mesh.attributes.remove(attribute)


def make_active(mesh, name):
    """Show `name` in the viewport, and make it the exported (render) color."""
    colors = mesh.color_attributes
    try:
        attribute = colors.get(name)
        if attribute is None:
            return
        colors.active_color = attribute
        final = colors.get(FINAL)
        if final is not None:
            colors.render_color_index = list(colors).index(final)
    except (AttributeError, RuntimeError, TypeError):
        pass  # a layer bmesh just created isn't visible to the attribute API until Edit Mode ends


def ensure_layer(mesh, channel, name=None):
    """The active layer of `channel`, created when the channel has none."""
    state = mesh.livemat_blend
    layers = layers_of(state, channel)
    index_name = f"active_{channel.lower()}"
    if not len(layers):
        add_layer(mesh, channel, name or "Layer 1")
    index = max(0, min(getattr(state, index_name), len(layers) - 1))
    setattr(state, index_name, index)
    return layers[index]


def add_layer(mesh, channel, name=None, bm=None):
    """A new layer on top of `channel`. Returns it."""
    state = mesh.livemat_blend
    layers = layers_of(state, channel)
    layer = layers.add()
    layer.uid = new_uid()
    layer.name = name or f"Layer {len(layers)}"
    layers.move(len(layers) - 1, 0)  # top of the list is the top of the stack
    setattr(state, f"active_{channel.lower()}", 0)
    with access(mesh, bm) as acc:
        acc.ensure_layer(layer_attribute(layer.uid))
    return layers[0]


def remove_layer(mesh, channel, index, bm=None):
    state = mesh.livemat_blend
    layers = layers_of(state, channel)
    if not 0 <= index < len(layers):
        return
    with access(mesh, bm) as acc:
        acc.remove_layer(layer_attribute(layers[index].uid))
    layers.remove(index)
    setattr(state, f"active_{channel.lower()}", max(0, min(index, len(layers) - 1)))


def find_object(mesh):
    """An object using `mesh`, preferring the active one, for operators started from properties."""
    active = bpy.context.object
    if active is not None and active.data == mesh:
        return active
    return next((o for o in bpy.data.objects if o.data == mesh), None)
