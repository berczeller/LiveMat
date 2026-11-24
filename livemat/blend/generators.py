# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Generator layers: values baked from the mesh's shape.

AO, Thickness and Curvature are baked with Cycles straight into a corner
color attribute (an Emission shader showing the AO or Pointiness node).
Edge Wear is computed from the angles between faces, no render needed.
Each bake stores raw values; the layer's Low/High/Invert remap them live.
"""

import math

import bmesh
import bpy
import numpy as np

from . import data

_BAKE = "LiveMat Bake"  # temporary attribute Cycles bakes into


class BakeError(Exception):
    pass


def edge_wear(mesh, kind):
    """Per-corner bend angle of the sharpest convex (or concave) edge at each vertex, 0..1 for 0..180 degrees."""
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.verts.index_update()
        per_vert = np.zeros(len(bm.verts), dtype=np.float32)
        for edge in bm.edges:
            if len(edge.link_faces) != 2:
                continue
            signed = edge.calc_face_angle_signed(0.0)  # positive for convex
            if kind == "CONVEX" and signed <= 0 or kind == "CONCAVE" and signed >= 0:
                continue
            value = abs(signed) / math.pi
            for vert in edge.verts:
                per_vert[vert.index] = max(per_vert[vert.index], value)
    finally:
        bm.free()
    corner_vert = np.zeros(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", corner_vert)
    return per_vert[corner_vert]


def _bake_material(generator, distance, only_local, samples):
    material = bpy.data.materials.new("LiveMat Bake")
    tree = material.node_tree
    tree.nodes.clear()
    emission = tree.nodes.new("ShaderNodeEmission")
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(emission.outputs[0], output.inputs["Surface"])
    if generator == "CURVATURE":
        geometry = tree.nodes.new("ShaderNodeNewGeometry")
        tree.links.new(geometry.outputs["Pointiness"], emission.inputs["Color"])
    else:
        ao = tree.nodes.new("ShaderNodeAmbientOcclusion")
        ao.samples = min(samples, 128)
        ao.inside = generator == "THICKNESS"  # occlusion seen from inside the surface: thin parts get dark
        ao.only_local = only_local or generator == "THICKNESS"
        ao.inputs["Distance"].default_value = distance
        tree.links.new(ao.outputs["AO"], emission.inputs["Color"])
    return material


def cycles_bake(context, obj, generator, distance, samples, only_local):
    """Raw per-corner values baked by Cycles. Leaves the scene as it was."""
    if context.mode != "OBJECT":
        raise BakeError("Switch to Object Mode to bake")
    mesh = obj.data
    if not mesh.polygons:
        raise BakeError("The mesh has no faces to bake")
    scene = context.scene
    view_layer = context.view_layer
    saved = {
        "engine": scene.render.engine,
        "samples": scene.cycles.samples if hasattr(scene, "cycles") else None,
        "selected": [o for o in view_layer.objects if o.select_get()],
        "active": view_layer.objects.active,
        "color": mesh.color_attributes.active_color_name,
        "slots": [(slot.link, slot.material) for slot in obj.material_slots],
        "appended": False,
    }
    material = _bake_material(generator, distance, only_local, samples)
    attribute = None
    try:
        try:
            scene.render.engine = "CYCLES"
        except TypeError as error:
            raise BakeError("Cycles isn't available, so this bake can't run") from error
        scene.cycles.samples = samples
        if obj.material_slots:
            for slot in obj.material_slots:
                slot.material = material
        else:
            mesh.materials.append(material)
            saved["appended"] = True
        attribute = mesh.color_attributes.new(_BAKE, "FLOAT_COLOR", "CORNER")
        mesh.color_attributes.active_color = attribute
        for other in saved["selected"]:
            other.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj
        try:
            bpy.ops.object.bake(type="EMIT", target="VERTEX_COLORS", use_selected_to_active=False, use_cage=False)
        except RuntimeError as error:
            raise BakeError(f"Cycles couldn't bake this mesh: {error}") from error
        values = np.zeros(len(attribute.data) * 4, dtype=np.float32)
        attribute.data.foreach_get("color", values)
        return values[0::4].copy()
    finally:
        if attribute is not None and mesh.color_attributes.get(_BAKE) is not None:
            mesh.color_attributes.remove(mesh.color_attributes[_BAKE])
        if saved["appended"]:
            mesh.materials.pop()
        else:
            for slot, (link, original) in zip(obj.material_slots, saved["slots"]):
                slot.link = link
                slot.material = original
        bpy.data.materials.remove(material)
        if saved["color"] and mesh.color_attributes.get(saved["color"]) is not None:
            mesh.color_attributes.active_color = mesh.color_attributes[saved["color"]]
        scene.render.engine = saved["engine"]
        if saved["samples"] is not None and hasattr(scene, "cycles"):
            scene.cycles.samples = saved["samples"]
        obj.select_set(obj in saved["selected"])
        for other in saved["selected"]:
            other.select_set(True)
        view_layer.objects.active = saved["active"]


DEFAULT_LEVELS = {
    # Pointiness sits close to 0.5 on most meshes, so a narrow window shows its detail.
    "CURVATURE": (0.45, 0.55),
    # Edge Wear stores angle/180: 30 to 90 degrees maps to 0..1.
    "EDGES": (30.0 / 180.0, 90.0 / 180.0),
}


def bake(context, obj, layer):
    """Bake `layer` (a Generator layer of obj's mesh) and recomposite."""
    mesh = obj.data
    if layer.generator == "EDGES":
        raw = edge_wear(mesh, layer.edge_kind)
    else:
        raw = cycles_bake(context, obj, layer.generator, layer.distance, layer.samples, layer.only_local)
    with data.access(mesh) as acc:
        stored = acc.read_layer(data.layer_attribute(layer.uid))
        stored[:, 2] = raw
        acc.write_layer(data.layer_attribute(layer.uid), stored)
    layer.baked = True
    data.composite_mesh(mesh)
    return float(raw.min()), float(raw.max())
