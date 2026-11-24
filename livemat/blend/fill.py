# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Set, Erase, Clear and Randomize on the Edit Mode selection.

Works like the 3ds Max Vertex Color Channel Tool it's modeled on: values go
to one channel only, per vertex, polygon, element or edge. Here they go into
the channel's active layer, which is then blended into the final mask.
"""

import random

import bmesh
import numpy as np

from . import data


class SelectionError(Exception):
    pass


def _select_mode(context):
    vert, edge, face = context.tool_settings.mesh_select_mode
    return "FACE" if face else "EDGE" if edge else "VERT"


def targets(bm, mode, smooth):
    """Corners the selection covers, and the context needed to key random values.

    Returns (corner indices, selected faces, selected edges, selected verts).
    Corners are numbered in face order, the same order data.access uses.
    """
    faces = [f for f in bm.faces if f.select]
    edges = [e for e in bm.edges if e.select]
    verts = {v for v in bm.verts if v.select}
    if mode == "FACE":
        if not faces:
            raise SelectionError("Nothing selected")
        if smooth:
            # Whole vertices: neighbors' corners at those vertices too, so values fade out.
            verts = {v for f in faces for v in f.verts}
        else:
            chosen = set(faces)
            corners = [i for i, loop in enumerate(_loops(bm)) if loop.face in chosen]
            return corners, faces, edges, {v for f in faces for v in f.verts}
    elif mode == "EDGE":
        if not edges:
            raise SelectionError("Nothing selected")
        verts = {v for e in edges for v in e.verts}
    elif not verts:
        raise SelectionError("Nothing selected")
    corners = [i for i, loop in enumerate(_loops(bm)) if loop.vert in verts]
    return corners, faces, edges, verts


def _loops(bm):
    return [loop for face in bm.faces for loop in face.loops]


def _elements(bm):
    """Face -> island number, islands being faces connected through edges."""
    island = {}
    number = 0
    for start in bm.faces:
        if start in island:
            continue
        stack = [start]
        island[start] = number
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for other in edge.link_faces:
                    if other not in island:
                        island[other] = number
                        stack.append(other)
        number += 1
    return island


def _average_at_verts(items, verts_of, low, high, rng):
    """One random value per item, then each vertex gets the average of its items' values."""
    sums, counts = {}, {}
    for item in items:
        value = rng.uniform(low, high)
        for vert in verts_of(item):
            sums[vert] = sums.get(vert, 0.0) + value
            counts[vert] = counts.get(vert, 0) + 1
    return {v: sums[v] / counts[v] for v in sums}


def random_values(bm, corners, faces, edges, per, smooth, mode, low, high, rng):
    """A value for each target corner."""
    loops = _loops(bm)
    if per == "EDGE":
        if mode != "EDGE":
            raise SelectionError("Per Edge works in Edge select mode")
        at_vert = _average_at_verts(edges, lambda e: e.verts, low, high, rng)
        return [at_vert.get(loops[i].vert, rng.uniform(low, high)) for i in corners]
    if per == "POLYGON":
        # Selected faces in Face mode, otherwise every face the target corners belong to.
        source = faces if mode == "FACE" else {loops[i].face for i in corners}
        source = sorted(source, key=lambda f: f.index)  # same order every run, for Fixed Seed
        if smooth:
            at_vert = _average_at_verts(source, lambda f: f.verts, low, high, rng)
            fallback = {}
            return [
                at_vert[loops[i].vert] if loops[i].vert in at_vert else fallback.setdefault(loops[i].vert, rng.uniform(low, high))
                for i in corners
            ]
        per_face = {}
        return [per_face.setdefault(loops[i].face, rng.uniform(low, high)) for i in corners]
    if per == "ELEMENT":
        island = _elements(bm)
        per_island = {}
        return [per_island.setdefault(island[loops[i].face], rng.uniform(low, high)) for i in corners]
    per_vert = {}
    return [per_vert.setdefault(loops[i].vert, rng.uniform(low, high)) for i in corners]


def apply(context, mesh, action, value=1.0):
    """Write into the active layer of the active channel. Returns a status message.

    action: SET (value), ERASE (0), CLEAR (back to transparent) or RANDOMIZE.
    """
    tool = context.scene.livemat_blend_tool
    state = mesh.livemat_blend
    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.index_update()
    mode = _select_mode(context)
    corners, faces, edges, _verts = targets(bm, mode, tool.smooth)
    if not corners:
        raise SelectionError("The selection has no faces to color")

    if action == "RANDOMIZE":
        low, high = sorted((tool.random_min, tool.random_max))
        rng = random.Random(tool.seed if tool.use_seed else None)
        values = random_values(bm, corners, faces, edges, tool.random_per, tool.smooth, mode, low, high, rng)
    else:
        fixed = {"SET": value, "ERASE": 0.0, "CLEAR": 0.0}[action]
        values = [fixed] * len(corners)
    coverage = 0.0 if action == "CLEAR" else 1.0

    layer = data.ensure_layer(mesh, state.channel)
    if layer.kind != "FILL":
        raise SelectionError(f"{layer.name} is a {layer.kind.title()} layer. Pick or add a Fill layer to fill selections")
    name = data.layer_attribute(layer.uid)
    with data.access(mesh, bm) as acc:
        stored = acc.read_layer(name)
        index = np.asarray(corners, dtype=np.int64)
        stored[index, 0] = values
        stored[index, 1] = coverage
        acc.write_layer(name, stored)
    data.composite_mesh(mesh, bm)
    verb = {"SET": "Set", "ERASE": "Erased", "CLEAR": "Cleared", "RANDOMIZE": "Randomized"}[action]
    return f"{verb} {state.channel} on {len(corners)} corners in {layer.name}"
