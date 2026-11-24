# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Edit Mode selections: by edge angle, and saved selection sets.

Saved sets are hidden boolean attributes on the mesh, one per set, on the
domain the selection was made in. They're stored with the .blend and FBX
doesn't export them.
"""

import math

import bmesh

from . import data

_DOMAIN_ELEMENTS = {"VERT": "verts", "EDGE": "edges", "FACE": "faces"}


def _elements(bm, domain):
    return getattr(bm, _DOMAIN_ELEMENTS[domain])


def _set_select_mode(context, domain):
    context.tool_settings.mesh_select_mode = (domain == "VERT", domain == "EDGE", domain == "FACE")


def _select_only(bm, domain, chosen):
    for face in bm.faces:
        face.select_set(False)
    for edge in bm.edges:
        edge.select_set(False)
    for vert in bm.verts:
        vert.select_set(False)
    for element in chosen:
        element.select_set(True)
    bm.select_mode = {domain}
    bm.select_flush_mode()


# Edge angle


def angle_edges(bm, select_mode, kind, low, high, include_open):
    """Edges bent between `low` and `high` radians, convex, concave or both.

    Looks inside the current selection, or the whole mesh when nothing is
    selected. Returns (edges, searched the whole mesh).
    """
    if select_mode == "VERT":
        candidates = [e for e in bm.edges if e.verts[0].select and e.verts[1].select]
    elif select_mode == "EDGE":
        candidates = [e for e in bm.edges if e.select]
    else:
        candidates = list({e for f in bm.faces if f.select for e in f.edges})
    whole = not candidates
    if whole:
        candidates = list(bm.edges)

    found = []
    for edge in candidates:
        faces = len(edge.link_faces)
        if faces == 1:
            if include_open:
                found.append(edge)
        elif faces == 2:
            signed = edge.calc_face_angle_signed(0.0)  # positive for convex
            if low <= abs(signed) <= high:
                if kind == "BOTH" or (kind == "CONVEX") == (signed > 0):
                    found.append(edge)
    return found, whole


def select_by_angle(context, mesh, target):
    """Replace the selection with matching edges, their vertices or their faces."""
    tool = context.scene.livemat_blend_tool
    bm = bmesh.from_edit_mesh(mesh)
    vert, edge, face = context.tool_settings.mesh_select_mode
    mode = "FACE" if face else "EDGE" if edge else "VERT"
    low, high = sorted((tool.angle_min, tool.angle_max))
    edges, whole = angle_edges(bm, mode, tool.angle_kind, low, high, tool.angle_open)
    scope = "the whole mesh" if whole else "the selection"
    kind = {"CONVEX": "convex", "CONCAVE": "concave", "BOTH": "convex or concave"}[tool.angle_kind]
    if not edges:
        return f"No {kind} edges between {math.degrees(low):.0f} and {math.degrees(high):.0f} degrees in {scope}"
    if target == "EDGE":
        chosen = edges
    elif target == "VERT":
        chosen = list({v for e in edges for v in e.verts})
    else:
        chosen = list({f for e in edges for f in e.link_faces})
    _select_only(bm, target, chosen)
    _set_select_mode(context, target)
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    what = {"EDGE": "edges", "VERT": "vertices", "FACE": "faces"}[target]
    return f"Selected {len(chosen)} {what} from {len(edges)} {kind} edges in {scope}"


# Saved selection sets


def _layer(bm, domain, uid, create=False):
    layers = _elements(bm, domain).layers.bool
    name = data.set_attribute(uid)
    return layers.get(name) or (layers.new(name) if create else None)


def save(context, mesh):
    """Store the current selection as a new set. Returns it, or None when nothing is selected."""
    bm = bmesh.from_edit_mesh(mesh)
    vert, edge, face = context.tool_settings.mesh_select_mode
    domain = "FACE" if face else "EDGE" if edge else "VERT"
    selected = [e for e in _elements(bm, domain) if e.select]
    if not selected:
        return None
    state = mesh.livemat_blend
    item = state.sets.add()
    item.uid = data.new_uid()
    item.domain = domain
    item.count = len(selected)
    item.name = f"Selection {len(state.sets)}"
    layer = _layer(bm, domain, item.uid, create=True)
    for element in _elements(bm, domain):
        element[layer] = element.select
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    state["active_set"] = len(state.sets) - 1  # raw write: don't trigger reselecting
    return item


def members(bm, item):
    layer = _layer(bm, item.domain, item.uid)
    if layer is None:
        return []
    return [e for e in _elements(bm, item.domain) if e[layer]]


def restore(mesh, item, extend=False):
    """Select the elements of a saved set again, in the mode it was saved in.

    Returns the number selected, or None when the set's data is gone (undone).
    """
    bm = bmesh.from_edit_mesh(mesh)
    if _layer(bm, item.domain, item.uid) is None:
        return None  # leave the selection alone rather than deselect everything
    chosen = members(bm, item)
    if extend:
        chosen += [e for e in _elements(bm, item.domain) if e.select]
    _select_only(bm, item.domain, chosen)
    import bpy

    _set_select_mode(bpy.context, item.domain)
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    return len(chosen)


def remove(mesh, index):
    state = mesh.livemat_blend
    if not 0 <= index < len(state.sets):
        return
    item = state.sets[index]
    if mesh.is_editmode:
        bm = bmesh.from_edit_mesh(mesh)
        layer = _layer(bm, item.domain, item.uid)
        if layer is not None:
            _elements(bm, item.domain).layers.bool.remove(layer)
    else:
        attribute = mesh.attributes.get(data.set_attribute(item.uid))
        if attribute is not None:
            mesh.attributes.remove(attribute)
    state.sets.remove(index)
    state["active_set"] = max(0, min(index, len(state.sets) - 1))


def _as_verts(bm, item):
    """A set's members turned into vertices, for combining sets saved in different modes."""
    found = members(bm, item)
    if item.domain == "VERT":
        return set(found)
    return {v for e in found for v in e.verts}


def combine(mesh, picked, how):
    """A new set from the picked ones. Returns it, or None when the result is empty."""
    bm = bmesh.from_edit_mesh(mesh)
    domains = {item.domain for item in picked}
    domain = domains.pop() if len(domains) == 1 else "VERT"
    groups = [set(members(bm, item)) if domain != "VERT" else _as_verts(bm, item) for item in picked]
    result = set(groups[0])
    for group in groups[1:]:
        if how == "UNION":
            result |= group
        elif how == "INTERSECT":
            result &= group
        else:
            result -= group
    if not result:
        return None
    state = mesh.livemat_blend
    item = state.sets.add()
    item.uid = data.new_uid()
    item.domain = domain
    item.count = len(result)
    label = {"UNION": "Union", "INTERSECT": "Intersect", "DIFFERENCE": "Subtract"}[how]
    item.name = f"{label} of {len(picked)}"
    # Keep indices, not elements: creating the layer below invalidates element references.
    _elements(bm, domain).index_update()
    chosen = {element.index for element in result}
    layer = _layer(bm, domain, item.uid, create=True)
    for element in _elements(bm, domain):
        element[layer] = element.index in chosen
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    for other in picked:
        other.pick = False
    state["active_set"] = len(state.sets) - 1
    return item
