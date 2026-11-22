# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Per-vertex bitangents for Unity-style normal mapping.

Unity's built-in shaders build the bitangent on each vertex and interpolate
it. Blender rebuilds it per pixel. Maps baked for Unity look slightly off
with Blender's version, so LiveMat stores Unity's on the mesh as a hidden
corner attribute that the node group reads back.
"""

import bpy

from .nodegroup import BITANGENT_ATTRIBUTE


def mesh_users(material):
    """Meshes with `material` in one of their slots, editable ones only."""
    meshes = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data is None or obj.data.library is not None:
            continue
        if any(slot.material == material for slot in obj.material_slots):
            meshes[obj.data.name] = obj.data
    return list(meshes.values())


def write_bitangents(mesh):
    """Store MikkTSpace bitangents per face corner. Returns False when the mesh can't have them."""
    uv = mesh.uv_layers.active_render or mesh.uv_layers.active
    if uv is None or not mesh.loops:
        return False
    try:
        mesh.calc_tangents(uvmap=uv.name)
    except RuntimeError:  # n-gons: tangents need triangles or quads
        return False
    values = [0.0] * (len(mesh.loops) * 3)
    mesh.loops.foreach_get("bitangent", values)
    mesh.free_tangents()

    attribute = mesh.attributes.get(BITANGENT_ATTRIBUTE)
    if attribute is not None and (attribute.data_type != "FLOAT_VECTOR" or attribute.domain != "CORNER"):
        mesh.attributes.remove(attribute)
        attribute = None
    if attribute is None:
        attribute = mesh.attributes.new(BITANGENT_ATTRIBUTE, "FLOAT_VECTOR", "CORNER")
    attribute.data.foreach_set("vector", values)
    mesh.update()
    return True


def update_users(material):
    """Write bitangents to every mesh using `material`. Returns the names of meshes that failed."""
    return [mesh.name for mesh in mesh_users(material) if not write_bitangents(mesh)]
