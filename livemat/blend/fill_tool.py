# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Polygon Fill: click or drag in the viewport to fill polygons, like Painter's tool.

The geometry functions (picking, rectangles, islands, writing) don't depend
on the viewport and are tested on their own. The modal operator only turns
mouse events into calls to them and draws the hover highlight.
"""

import bmesh
import bpy
import gpu
import numpy as np
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import data

DRAG = 6  # pixels the mouse moves before a click becomes a rectangle


class Picker:
    """World-space ray picking and island lookups for one object's mesh (modifiers ignored)."""

    def __init__(self, obj):
        mesh = obj.data
        matrix = obj.matrix_world
        self.obj = obj
        self.verts = [matrix @ v.co for v in mesh.vertices]
        self.polygons = [tuple(p.vertices) for p in mesh.polygons]
        self.centers = [matrix @ p.center for p in mesh.polygons]
        self.tree = BVHTree.FromPolygons(self.verts, self.polygons)
        mesh.calc_loop_triangles()
        self.triangles = {}
        for tri in mesh.loop_triangles:
            self.triangles.setdefault(tri.polygon_index, []).append(tuple(tri.vertices))
        self.mesh_islands, self.uv_islands = islands(mesh)

    def ray(self, origin, direction):
        """Index of the first polygon a ray hits, or None."""
        _location, _normal, index, _distance = self.tree.ray_cast(origin, direction)
        return index

    def visible(self, origin, index, ortho_direction=None):
        """True when nothing hides polygon `index`'s center from the viewer."""
        target = self.centers[index]
        if ortho_direction is not None:
            start = target - ortho_direction * 1e4
            direction = ortho_direction
        else:
            start = origin
            direction = (target - origin).normalized()
        hit = self.ray(start, direction)
        return hit == index

    def expand(self, indices, mode):
        """The polygons a fill covers: the picked ones, or their whole islands."""
        if mode == "POLYGON":
            return set(indices)
        table = self.mesh_islands if mode == "MESH" else self.uv_islands
        wanted = {table[i] for i in indices}
        return {i for i, island in enumerate(table) if island in wanted}


def islands(mesh):
    """(island per polygon through shared edges, island per polygon through shared UV edges)."""
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.index_update()
        uv = bm.loops.layers.uv.active

        def flood(connected):
            island = [-1] * len(bm.faces)
            number = 0
            for start in bm.faces:
                if island[start.index] >= 0:
                    continue
                stack = [start]
                island[start.index] = number
                while stack:
                    face = stack.pop()
                    for loop in face.loops:
                        for other in loop.edge.link_loops:
                            if other.face is not face and island[other.face.index] < 0 and connected(loop, other):
                                island[other.face.index] = number
                                stack.append(other.face)
                number += 1
            return island

        def same_uv(loop, other):
            if uv is None:
                return True
            # Across a shared edge the two faces run in opposite directions: compare crosswise.
            a1, a2 = loop[uv].uv, loop.link_loop_next[uv].uv
            b1, b2 = other[uv].uv, other.link_loop_next[uv].uv
            return (a1 - b2).length < 1e-5 and (a2 - b1).length < 1e-5 or (a1 - b1).length < 1e-5 and (a2 - b2).length < 1e-5

        return flood(lambda _a, _b: True), flood(same_uv)
    finally:
        bm.free()


def in_rectangle(points, rect):
    """Which 2D points (None for points behind the view) lie inside rect (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = rect
    return [p is not None and x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in points]


def polygons_in_rectangle(picker, project, rect, hit_test, visible_only, view_origin, ortho_direction=None):
    """Polygons a rectangle selects. `project` turns a world point into 2D region coordinates."""
    centers_2d = [project(c) for c in picker.centers]
    chosen = set(i for i, inside in enumerate(in_rectangle(centers_2d, rect)) if inside)
    if hit_test == "INTERSECT":
        verts_2d = [project(v) for v in picker.verts]
        inside = in_rectangle(verts_2d, rect)
        for index, polygon in enumerate(picker.polygons):
            if index not in chosen and any(inside[v] for v in polygon):
                chosen.add(index)
    if visible_only:
        chosen = {i for i in chosen if picker.visible(view_origin, i, ortho_direction)}
    return chosen


def apply(mesh, polygons, value, clear=False):
    """Write `value` (or transparency, with clear) into the active Fill layer on these polygons' corners."""
    state = mesh.livemat_blend
    layer = data.ensure_layer(mesh, state.channel)
    if layer.kind != "FILL":
        raise ValueError(f"{layer.name} is a {layer.kind.title()} layer. Pick or add a Fill layer")
    corners = []
    for index in polygons:
        polygon = mesh.polygons[index]
        corners.extend(range(polygon.loop_start, polygon.loop_start + polygon.loop_total))
    if not corners:
        return 0
    name = data.layer_attribute(layer.uid)
    with data.access(mesh) as acc:
        stored = acc.read_layer(name)
        index = np.asarray(corners, dtype=np.int64)
        stored[index, 0] = 0.0 if clear else value
        stored[index, 1] = 0.0 if clear else 1.0
        acc.write_layer(name, stored)
    data.composite_mesh(mesh)
    return len(polygons)


# The modal tool

_HIGHLIGHT = (1.0, 0.56, 0.64, 0.45)  # the pastel pink used across LiveMat
_RECT = (1.0, 1.0, 1.0, 0.8)


class LIVEMAT_OT_blend_polygon_fill(bpy.types.Operator):
    bl_idname = "livemat.blend_polygon_fill"
    bl_label = "Polygon Fill"
    bl_description = (
        "Click a polygon or drag a rectangle in the viewport to fill the active channel. Ctrl clears. "
        "Esc or right-click to finish"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != "MESH" or context.mode != "OBJECT" or context.area is None or context.area.type != "VIEW_3D":
            cls.poll_message_set("Works on a mesh in Object Mode, in the 3D Viewport")
            return False
        return data.FINAL in obj.data.color_attributes

    def invoke(self, context, _event):
        # The button lives in the sidebar: work in the viewport's own region, not the panel's.
        self.area = context.area
        self.region = next((r for r in self.area.regions if r.type == "WINDOW"), None)
        self.rv3d = context.space_data.region_3d
        if self.region is None or self.rv3d is None:
            self.report({"WARNING"}, "Start Polygon Fill from a 3D Viewport")
            return {"CANCELLED"}
        self.obj = context.object
        self.picker = Picker(self.obj)
        self.hover = set()
        self.press = None
        self.mouse = None
        self.handles = (
            bpy.types.SpaceView3D.draw_handler_add(self._draw_highlight, (), "WINDOW", "POST_VIEW"),
            bpy.types.SpaceView3D.draw_handler_add(self._draw_rectangle, (), "WINDOW", "POST_PIXEL"),
        )
        context.window_manager.modal_handler_add(self)
        self._status(context)
        return {"RUNNING_MODAL"}

    def _status(self, context):
        tool = context.scene.livemat_blend_tool
        channel = self.obj.data.livemat_blend.channel
        self.area.header_text_set(
            f"Polygon Fill {channel} = {tool.value:.2f}, by {tool.fill_mode.replace('_', ' ').title()}: "
            "click or drag to fill, Ctrl clears, Esc or right-click to finish"
        )

    def _finish(self):
        for handle in getattr(self, "handles", ()):
            try:
                bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
            except ValueError:
                pass  # already removed
        self.handles = ()
        try:
            self.area.header_text_set(None)
            self.area.tag_redraw()
        except (AttributeError, ReferenceError):
            pass  # the area closed

    def cancel(self, _context):
        # Called when Blender stops the tool itself: a file load, a closed window.
        self._finish()

    def _local(self, event):
        """Mouse position in the viewport region, or None when the mouse is outside it."""
        x, y = event.mouse_x - self.region.x, event.mouse_y - self.region.y
        if 0 <= x < self.region.width and 0 <= y < self.region.height:
            return (x, y)
        return None

    def _ray(self, coord):
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, coord)
        if not self.rv3d.is_perspective:
            origin = origin - direction * 1e4  # an orthographic ray starts at the view plane: back it up
        return origin, direction

    def _under(self, context, coord):
        origin, direction = self._ray(coord)
        index = self.picker.ray(origin, direction)
        if index is None:
            return set()
        return self.picker.expand([index], context.scene.livemat_blend_tool.fill_mode)

    def _rectangle_selection(self, context):
        tool = context.scene.livemat_blend_tool
        region, rv3d = self.region, self.rv3d
        (x0, y0), (x1, y1) = self.press, self.mouse
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        project = lambda point: view3d_utils.location_3d_to_region_2d(region, rv3d, point)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (region.width / 2, region.height / 2))
        ortho = None if rv3d.is_perspective else (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0)))
        picked = polygons_in_rectangle(self.picker, project, rect, tool.hit_test, tool.visible_only, origin, ortho)
        return self.picker.expand(picked, tool.fill_mode)

    def _fill(self, context, polygons, clear):
        if not polygons:
            return
        tool = context.scene.livemat_blend_tool
        try:
            apply(self.obj.data, polygons, tool.value, clear=clear)
        except ValueError as error:
            self.report({"WARNING"}, str(error))
            return
        bpy.ops.ed.undo_push(message="Polygon Fill")

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception:
            self._finish()
            raise

    def _modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._finish()
            return {"FINISHED"}
        coord = self._local(event)
        if coord is None and self.press is None:
            self.hover = set()
            self.area.tag_redraw()
            return {"PASS_THROUGH"}  # outside the viewport: the panel and menus keep working
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM"} or event.type.startswith("NDOF"):
            return {"PASS_THROUGH"}  # keep orbiting and zooming
        if event.type == "MOUSEMOVE":
            if coord is not None:
                self.mouse = coord
            if self.press is None and coord is not None:
                self.hover = self._under(context, coord)
            self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.press = coord
            self.mouse = coord
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self.press is not None:
            end = coord or self.mouse
            dragged = (Vector(end) - Vector(self.press)).length > DRAG
            self.mouse = end
            polygons = self._rectangle_selection(context) if dragged else self._under(context, end)
            self.press = None
            self._fill(context, polygons, clear=event.ctrl)
            self.hover = self._under(context, end)
            self._status(context)
            self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"} if event.type in {"TIMER", "TIMER_REPORT"} else {"RUNNING_MODAL"}

    def _draw_highlight(self):
        if not self.hover or self.press is not None:
            return
        verts = self.picker.verts
        coords = [verts[i] for p in self.hover for tri in self.picker.triangles.get(p, ()) for i in tri]
        if not coords:
            return
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "TRIS", {"pos": coords})
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
        shader.uniform_float("color", _HIGHLIGHT)
        batch.draw(shader)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")

    def _draw_rectangle(self):
        if self.press is None or self.mouse is None:
            return
        (x0, y0), (x1, y1) = self.press, self.mouse
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        coords = [(x0, y0), (x1, y0), (x1, y0), (x1, y1), (x1, y1), (x0, y1), (x0, y1), (x0, y0)]
        batch = batch_for_shader(shader, "LINES", {"pos": coords})
        gpu.state.blend_set("ALPHA")
        shader.uniform_float("color", _RECT)
        batch.draw(shader)
        gpu.state.blend_set("NONE")


register, unregister = bpy.utils.register_classes_factory((LIVEMAT_OT_blend_polygon_fill,))
