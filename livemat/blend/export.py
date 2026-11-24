# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Make sure engines read the Blend mask as the mesh's vertex colors.

Unity and Unreal read only the first color set in an FBX. Blender's FBX
exporter writes color attributes in mesh order unless Prioritize Active
Color is on, so the mask has to come first. With the default sRGB option it
writes each byte as stored, which is why masks are kept as raw bytes.
"""

import os
import tempfile

import bpy
import numpy as np

from . import data

_TRACKED = ("objects", "meshes", "materials", "images", "collections", "actions", "armatures", "node_groups")


def issues(mesh):
    """Plain-language problems that would keep the mask from reaching the engine."""
    colors = mesh.color_attributes
    final = colors.get(data.FINAL)
    if final is None:
        return ["This mesh has no Blend mask yet"]
    found = []
    order = [a.name for a in colors]
    if colors.get(data.VIEW) is not None:
        found.append("Channel view is on, and its temporary colors would be exported too. Switch to Material view")
    first = next(name for name in order if name != data.VIEW)
    if first != data.FINAL:
        found.append(f"{first} is exported before {data.FINAL}, so the engine would read that one")
    if final.data_type != "BYTE_COLOR" or final.domain != "CORNER":
        found.append(f"{data.FINAL} isn't a corner byte color anymore")
    return found


def move_first(mesh):
    """Recreate the other color attributes after the mask, keeping their data, so it exports first."""
    colors = mesh.color_attributes
    if colors.get(data.FINAL) is None:
        return []
    active = colors.active_color_name
    moved = []
    for attribute in [a for a in colors if a.name not in {data.FINAL, data.VIEW}]:
        name, kind, domain = attribute.name, attribute.data_type, attribute.domain
        values = np.zeros(len(attribute.data) * 4, dtype=np.float32)
        # Raw bytes for byte colors, linear floats for float colors: both round-trip exactly.
        prop = "color_srgb" if kind == "BYTE_COLOR" else "color"
        attribute.data.foreach_get(prop, values)
        colors.remove(attribute)
        copy = colors.new(name, kind, domain)
        copy.data.foreach_set(prop, values)
        moved.append(name)
    if active and colors.get(active) is not None:
        colors.active_color = colors[active]
    colors.render_color_index = list(colors).index(colors[data.FINAL])
    return moved


def round_trip(context, obj):
    """Export `obj` with the default FBX settings, import it back and compare the first color set.

    Returns (passed, message). Leaves the scene as it was.
    """
    mesh = obj.data
    if mesh.color_attributes.get(data.FINAL) is None:
        return False, "This mesh has no Blend mask yet"
    # The export applies modifiers (Triangulate, Mirror, Bevel...), so compare with the evaluated mesh.
    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get()).data
    final = evaluated.color_attributes.get(data.FINAL)
    if final is None:
        return False, f"A modifier on {obj.name} removes the {data.FINAL} attribute"
    expected = np.zeros(len(final.data) * 4, dtype=np.float32)
    final.data.foreach_get("color_srgb", expected)

    view_layer = context.view_layer
    selected = [o for o in view_layer.objects if o.select_get()]
    active = view_layer.objects.active
    before = {name: set(getattr(bpy.data, name)) for name in _TRACKED}
    folder = tempfile.mkdtemp(prefix="livemat_")
    path = os.path.join(folder, "check.fbx")
    try:
        for other in selected:
            other.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True)  # default options, as artists export
        bpy.ops.import_scene.fbx(filepath=path)
        imported = [o for o in bpy.data.objects if o not in before["objects"] and o.type == "MESH"]
        if not imported or not imported[0].data.color_attributes:
            return False, "The exported FBX has no vertex colors"
        first = imported[0].data.color_attributes[0]
        got = np.zeros(len(first.data) * 4, dtype=np.float32)
        first.data.foreach_get("color_srgb", got)
        if first.domain != "CORNER":
            got = None  # a point-domain first set can't be the corner mask
        name = first.name
    finally:
        for collection in reversed(_TRACKED):
            store = getattr(bpy.data, collection)
            for block in [b for b in store if b not in before[collection]]:
                store.remove(block)
        # Restore from the saved list: the view layer still lists the removed import for a moment.
        obj.select_set(obj in selected)
        for other in selected:
            other.select_set(True)
        view_layer.objects.active = active
        try:
            os.remove(path)
            os.rmdir(folder)
        except OSError:
            pass

    if name != data.FINAL or got is None:
        return False, f"The engine would read {name}, not {data.FINAL}"
    # Compare per channel as byte histograms: the importer may number corners differently.
    for channel in range(4):
        a = np.bincount(np.rint(expected[channel::4] * 255).astype(int), minlength=256)
        b = np.bincount(np.rint(got[channel::4] * 255).astype(int), minlength=256)
        if not np.array_equal(a, b):
            return False, f"Channel {data.CHANNELS[channel]} changes on export"
    return True, f"Unity and Unreal read {data.FINAL} as vertex colors, values unchanged"
