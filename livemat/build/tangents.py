# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Per-vertex bitangents for Unity-style normal mapping.

Unity's built-in shaders build the bitangent on each vertex and interpolate
it. Blender rebuilds it per pixel. Maps baked for Unity look slightly off
with Blender's version, so LiveMat stores Unity's on the mesh as a hidden
corner attribute that the node group reads back.
"""

import bmesh
import bpy

from .nodegroup import BITANGENT_ATTRIBUTE

_CORNER = "livemat_corner"  # temporary: each triangulated corner's original corner index


def mesh_users(material):
    """Meshes with `material` in one of their slots, editable ones only."""
    meshes = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data is None or obj.data.library is not None:
            continue
        if any(slot.material == material for slot in obj.material_slots):
            meshes[obj.data.name] = obj.data
    return list(meshes.values())


def _bitangents(mesh, uv_name):
    """Flat list of MikkTSpace bitangents (x, y, z per corner) for a mesh of triangles and quads."""
    mesh.calc_tangents(uvmap=uv_name)
    values = [0.0] * (len(mesh.loops) * 3)
    mesh.loops.foreach_get("bitangent", values)
    mesh.free_tangents()
    return values


def _bitangents_via_triangles(mesh, uv_name):
    """Bitangents for a mesh with n-gons, computed on a triangulated copy.

    Tangents need triangles or quads. Unity triangulates every mesh on import
    anyway, so a triangulated copy gives the bitangents Unity would use. Each
    triangle corner remembers which corner of the original it came from.
    """
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        layer = bm.loops.layers.int.new(_CORNER)
        index = 0
        for face in bm.faces:
            for loop in face.loops:
                loop[layer] = index
                index += 1
        ngons = [face for face in bm.faces if len(face.verts) > 4]
        bmesh.ops.triangulate(bm, faces=ngons)
        temp = bpy.data.meshes.new("LiveMat Tangents")
        bm.to_mesh(temp)
    finally:
        bm.free()
    try:
        temp.uv_layers.active = temp.uv_layers[uv_name]
        values = _bitangents(temp, uv_name)
        origins = [0] * len(temp.loops)
        temp.attributes[_CORNER].data.foreach_get("value", origins)
    finally:
        bpy.data.meshes.remove(temp)
    result = [0.0] * (len(mesh.loops) * 3)
    for corner, origin in enumerate(origins):
        # An n-gon corner can appear in several triangles; they share a vertex and UV, so any will do.
        result[origin * 3:origin * 3 + 3] = values[corner * 3:corner * 3 + 3]
    return result


def write_bitangents(mesh):
    """Store MikkTSpace bitangents per face corner. Returns False when the mesh has no UVs."""
    uv = mesh.uv_layers.active_render or mesh.uv_layers.active
    if uv is None or not mesh.loops:
        return False
    try:
        values = _bitangents(mesh, uv.name)
    except RuntimeError:  # n-gons: tangents need triangles or quads
        values = _bitangents_via_triangles(mesh, uv.name)

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
