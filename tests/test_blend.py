"""Blend: layers, Edit Mode tools, edge angle, saved selections and export."""

import math
import unittest

import bmesh
import bpy
import numpy as np

import livemat
from livemat.blend import composite, data, export


def final_values(mesh, channel="R"):
    """Raw byte values (0-255) of one channel of the final mask, per corner."""
    attribute = mesh.color_attributes[data.FINAL]
    values = np.zeros(len(attribute.data) * 4, dtype=np.float32)
    attribute.data.foreach_get("color_srgb", values)
    return np.rint(values[data.CHANNELS.index(channel)::4] * 255).astype(int)


class CompositeMathTest(unittest.TestCase):
    def test_blend_modes(self):
        below = np.array([0.5], dtype=np.float32)
        value = np.array([0.8], dtype=np.float32)
        full = np.array([1.0], dtype=np.float32)
        expected = {"NORMAL": 0.8, "ADD": 1.0, "SUBTRACT": 0.0, "MULTIPLY": 0.4, "MAX": 0.8, "MIN": 0.5}
        for mode, want in expected.items():
            self.assertAlmostEqual(float(composite.blend(below, value, full, mode)[0]), want, places=5, msg=mode)

    def test_top_layer_wins_and_coverage_lets_lower_show(self):
        count = 2
        bottom = (np.array([0.2, 0.2]), np.array([1.0, 1.0]), 1.0, "NORMAL")
        top = (np.array([0.9, 0.9]), np.array([1.0, 0.0]), 1.0, "NORMAL")
        result = composite.channel(0.0, [top, bottom], count)  # listed top first
        self.assertAlmostEqual(float(result[0]), 0.9, places=5)
        self.assertAlmostEqual(float(result[1]), 0.2, places=5)


class BlendTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        livemat.register()

    @classmethod
    def tearDownClass(cls):
        livemat.unregister()

    def setUp(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)
        bpy.ops.mesh.primitive_cube_add()
        self.obj = bpy.context.active_object
        self.mesh = self.obj.data
        self.tool = bpy.context.scene.livemat_blend_tool
        self.tool.smooth = False
        self.tool.use_seed = True
        self.tool.value = 0.5
        bpy.ops.livemat.blend_start()

    def tearDown(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for collection in (bpy.data.objects, bpy.data.meshes):
            for block in list(collection):
                collection.remove(block)

    def edit_select_faces(self, indices):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bm = bmesh.from_edit_mesh(self.mesh)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face.select_set(False)
        for index in indices:
            bm.faces[index].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(self.mesh)

    def leave_edit(self):
        bpy.ops.object.mode_set(mode="OBJECT")

    def corners_of_face(self, index):
        polygon = self.mesh.polygons[index]
        return list(range(polygon.loop_start, polygon.loop_start + polygon.loop_total))


class MaskStartTest(BlendTestBase):
    def test_start_makes_the_mask_first_and_active(self):
        colors = self.mesh.color_attributes
        self.assertEqual(colors[0].name, data.FINAL)
        self.assertEqual(colors.active_color_name, data.FINAL)
        self.assertEqual((colors[0].data_type, colors[0].domain), ("BYTE_COLOR", "CORNER"))
        self.assertEqual(export.issues(self.mesh), [])


class FillTest(BlendTestBase):
    def test_set_on_faces_writes_raw_bytes_on_their_corners(self):
        self.edit_select_faces([0])
        bpy.ops.livemat.blend_fill(action="SET")
        self.leave_edit()
        values = final_values(self.mesh)
        inside = self.corners_of_face(0)
        self.assertTrue(all(values[i] == 128 for i in inside))
        self.assertEqual(int(sum(values[i] for i in range(len(values)) if i not in inside)), 0)

    def test_smooth_spreads_to_neighbor_corners(self):
        self.tool.smooth = True
        self.edit_select_faces([0])
        bpy.ops.livemat.blend_fill(action="SET")
        self.leave_edit()
        values = final_values(self.mesh)
        # The face's 4 vertices each touch 3 faces of the cube: 12 corners.
        self.assertEqual(int(np.count_nonzero(values == 128)), 12)

    def test_other_channels_are_untouched(self):
        self.edit_select_faces([0, 1])
        bpy.ops.livemat.blend_fill(action="SET")
        self.mesh.livemat_blend.channel = "G"
        bpy.ops.livemat.blend_fill(action="ERASE")
        self.leave_edit()
        self.assertEqual(int(np.count_nonzero(final_values(self.mesh, "R") == 128)), 8)
        self.assertEqual(int(final_values(self.mesh, "G").sum()), 0)
        self.assertEqual(int(final_values(self.mesh, "B").sum()), 0)

    def test_clear_lets_the_layer_below_show(self):
        self.edit_select_faces([0])
        bpy.ops.livemat.blend_fill(action="SET")
        self.leave_edit()
        bpy.ops.livemat.blend_layer_add()  # layer list changes happen in Object Mode
        self.edit_select_faces([0])
        self.tool.value = 1.0
        bpy.ops.livemat.blend_fill(action="SET")
        bpy.ops.livemat.blend_fill(action="CLEAR")
        self.leave_edit()
        values = final_values(self.mesh)
        self.assertTrue(all(values[i] == 128 for i in self.corners_of_face(0)))

    def test_randomize_per_element_is_constant_per_island_and_repeatable(self):
        self.leave_edit() if bpy.context.mode != "OBJECT" else None
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.duplicate_move(TRANSFORM_OT_translate={"value": (3, 0, 0)})
        bpy.ops.mesh.select_all(action="SELECT")
        self.tool.random_per = "ELEMENT"
        self.tool.seed = 7
        bpy.ops.livemat.blend_fill(action="RANDOMIZE")
        self.leave_edit()
        first = final_values(self.mesh)
        half = len(first) // 2
        self.assertEqual(len(set(first[:half])), 1)
        self.assertEqual(len(set(first[half:])), 1)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.livemat.blend_fill(action="RANDOMIZE")
        self.leave_edit()
        self.assertTrue(np.array_equal(first, final_values(self.mesh)))

    def test_per_edge_needs_edge_mode(self):
        self.edit_select_faces([0])
        self.tool.random_per = "EDGE"
        result = bpy.ops.livemat.blend_fill(action="RANDOMIZE")
        self.assertEqual(result, {"CANCELLED"})

    def test_layer_opacity_and_visibility_recomposite(self):
        self.edit_select_faces([0])
        self.tool.value = 1.0
        bpy.ops.livemat.blend_fill(action="SET")
        self.leave_edit()
        layer = self.mesh.livemat_blend.layers_r[0]
        layer.opacity = 0.5
        self.assertEqual(int(final_values(self.mesh)[self.corners_of_face(0)[0]]), 128)
        layer.visible = False
        self.assertEqual(int(final_values(self.mesh).sum()), 0)


class EdgeAngleTest(BlendTestBase):
    def run_angle(self, kind, target, low=30, high=180):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        self.tool.angle_kind = kind
        self.tool.angle_min = math.radians(low)
        self.tool.angle_max = math.radians(high)
        bpy.ops.livemat.blend_select_angle(target=target)
        bm = bmesh.from_edit_mesh(self.mesh)
        return bm

    def test_cube_edges_are_all_convex(self):
        bm = self.run_angle("CONVEX", "EDGE")
        self.assertEqual(sum(e.select for e in bm.edges), 12)

    def test_no_concave_edges_on_a_cube(self):
        bm = self.run_angle("CONCAVE", "EDGE")
        self.assertEqual(sum(e.select for e in bm.edges), 0)

    def test_angle_range_excludes_right_angles(self):
        bm = self.run_angle("BOTH", "EDGE", low=100, high=180)
        self.assertEqual(sum(e.select for e in bm.edges), 0)

    def test_faces_on_both_sides(self):
        bm = self.run_angle("CONVEX", "FACE")
        self.assertEqual(sum(f.select for f in bm.faces), 6)
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), (False, False, True))


class SelectionSetTest(BlendTestBase):
    def selected_faces(self):
        bm = bmesh.from_edit_mesh(self.mesh)
        return sorted(f.index for f in bm.faces if f.select)

    def test_save_and_click_to_reselect(self):
        self.edit_select_faces([0, 2])
        bpy.ops.livemat.blend_set_add()
        self.edit_select_faces([5])
        bpy.ops.livemat.blend_set_add()
        state = self.mesh.livemat_blend
        self.assertEqual([s.count for s in state.sets], [2, 1])
        state.active_set = 0  # clicking the first item in the list
        self.assertEqual(self.selected_faces(), [0, 2])
        bpy.ops.livemat.blend_set_select(index=1)
        self.assertEqual(self.selected_faces(), [5])

    def test_sets_survive_object_mode(self):
        self.edit_select_faces([3])
        bpy.ops.livemat.blend_set_add()
        self.leave_edit()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.livemat.blend_set_select(index=0)
        self.assertEqual(self.selected_faces(), [3])

    def test_combine(self):
        self.edit_select_faces([0, 1])
        bpy.ops.livemat.blend_set_add()
        self.edit_select_faces([1, 2])
        bpy.ops.livemat.blend_set_add()
        state = self.mesh.livemat_blend
        for item in state.sets:
            item.pick = True
        self.tool.combine = "INTERSECT"
        bpy.ops.livemat.blend_set_combine()
        self.assertEqual(state.sets[2].count, 1)
        bpy.ops.livemat.blend_set_select(index=2)
        self.assertEqual(self.selected_faces(), [1])


class ViewTest(BlendTestBase):
    def test_channel_view_is_grayscale_and_material_view_cleans_up(self):
        self.edit_select_faces([0])
        bpy.ops.livemat.blend_fill(action="SET")
        self.leave_edit()
        bpy.ops.livemat.blend_view(mode="CHANNEL")
        view = self.mesh.color_attributes[data.VIEW]
        self.assertEqual(self.mesh.color_attributes.active_color_name, data.VIEW)
        corner = self.corners_of_face(0)[0]
        self.assertEqual(tuple(round(v, 3) for v in view.data[corner].color_srgb), (0.502, 0.502, 0.502, 1.0))
        bpy.ops.livemat.blend_view(mode="MATERIAL")
        self.assertNotIn(data.VIEW, self.mesh.color_attributes)
        self.assertEqual(self.mesh.color_attributes.active_color_name, data.FINAL)


class ExportTest(BlendTestBase):
    def test_other_color_attribute_first_is_flagged_and_fixed(self):
        bpy.ops.object.mode_set(mode="OBJECT")
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        old = obj.data.color_attributes.new("Col", "BYTE_COLOR", "POINT")
        for item in old.data:
            item.color_srgb = (0.25, 0.5, 0.75, 1.0)
        data.composite_mesh(obj.data)  # an older color attribute stays first
        self.assertTrue(export.issues(obj.data))
        bpy.ops.livemat.blend_move_first()
        self.assertEqual(export.issues(obj.data), [])
        kept = obj.data.color_attributes["Col"]
        self.assertEqual(kept.domain, "POINT")
        self.assertEqual(tuple(round(v, 3) for v in kept.data[0].color_srgb), (0.251, 0.502, 0.749, 1.0))

    def test_round_trip_keeps_values(self):
        self.edit_select_faces([0, 3])
        bpy.ops.livemat.blend_fill(action="SET")
        self.leave_edit()
        objects = len(bpy.data.objects)
        passed, message = export.round_trip(bpy.context, self.obj)
        self.assertTrue(passed, message)
        self.assertEqual(len(bpy.data.objects), objects)


class ShellTest(BlendTestBase):
    def test_tabs(self):
        wm = bpy.context.window_manager
        self.assertEqual(wm.livemat_tab, "BUILD")
        wm.livemat_tab = "BLEND"
        wm.livemat_tab = "TEMPLATES"
        self.assertTrue(hasattr(bpy.types, "LIVEMAT_PT_view3d"))
        self.assertFalse(hasattr(bpy.types, "LIVEMAT_PT_view3d_material"))


class ReviewRegressionTest(BlendTestBase):
    def test_layer_list_changes_need_object_mode(self):
        self.edit_select_faces([0])
        self.assertFalse(bpy.ops.livemat.blend_layer_add.poll())
        self.leave_edit()
        self.assertTrue(bpy.ops.livemat.blend_layer_add.poll())

    def test_channel_view_follows_the_picked_channel(self):
        self.edit_select_faces([0])
        self.tool.value = 1.0
        bpy.ops.livemat.blend_fill(action="SET")
        self.leave_edit()
        bpy.ops.livemat.blend_view(mode="CHANNEL")
        self.mesh.livemat_blend.channel = "G"
        view = self.mesh.color_attributes[data.VIEW]
        self.assertEqual(round(view.data[self.corners_of_face(0)[0]].color_srgb[0], 3), 0.0)

    def test_round_trip_with_topology_modifiers(self):
        self.edit_select_faces([0])
        bpy.ops.livemat.blend_fill(action="SET")
        self.leave_edit()
        self.obj.modifiers.new("Triangulate", "TRIANGULATE")
        passed, message = export.round_trip(bpy.context, self.obj)
        self.assertTrue(passed, message)

    def test_smooth_per_polygon_gives_one_value_per_vertex(self):
        self.tool.smooth = True
        self.tool.random_per = "POLYGON"
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (True, False, False)
        bm = bmesh.from_edit_mesh(self.mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        for vert in bm.verts:
            vert.select_set(False)
        lone = next(v for v in bm.verts if v not in bm.faces[0].verts)
        for vert in list(bm.faces[0].verts) + [lone]:
            vert.select_set(True)
        bmesh.update_edit_mesh(self.mesh)
        bpy.ops.livemat.blend_fill(action="RANDOMIZE")
        self.leave_edit()
        values = final_values(self.mesh)
        per_vertex = {}
        for corner, loop in enumerate(self.mesh.loops):
            if values[corner]:
                per_vertex.setdefault(loop.vertex_index, set()).add(int(values[corner]))
        self.assertTrue(per_vertex)
        self.assertTrue(all(len(found) == 1 for found in per_vertex.values()), per_vertex)

    def test_settings_on_a_mesh_without_mask_create_nothing(self):
        bpy.ops.mesh.primitive_plane_add()
        plane = bpy.context.active_object.data
        plane.livemat_blend.base[0] = 0.5
        self.assertNotIn(data.FINAL, plane.color_attributes)

    def test_view_attribute_is_flagged_for_export(self):
        bpy.ops.livemat.blend_view(mode="CHANNEL")
        self.assertTrue(any("Channel view" in problem for problem in export.issues(self.mesh)))
        bpy.ops.livemat.blend_view(mode="MATERIAL")
        self.assertEqual(export.issues(self.mesh), [])

    def test_no_faces_is_reported(self):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (True, False, False)
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.delete(type="ONLY_FACE")
        bpy.ops.mesh.select_all(action="SELECT")
        self.assertEqual(bpy.ops.livemat.blend_fill(action="SET"), {"CANCELLED"})

    def test_undone_selection_keeps_the_current_selection(self):
        self.edit_select_faces([0])
        bpy.ops.livemat.blend_set_add()
        bm = bmesh.from_edit_mesh(self.mesh)
        bm.faces.layers.bool.remove(bm.faces.layers.bool[data.set_attribute(self.mesh.livemat_blend.sets[0].uid)])
        bmesh.update_edit_mesh(self.mesh)
        self.edit_select_faces([4])
        self.assertEqual(bpy.ops.livemat.blend_set_select(index=0), {"CANCELLED"})
        bm = bmesh.from_edit_mesh(self.mesh)
        self.assertEqual(sorted(f.index for f in bm.faces if f.select), [4])

    def test_orphaned_layer_data_is_cleaned_up(self):
        self.mesh.attributes.new(data.LAYER_PREFIX + "gone", "FLOAT_VECTOR", "CORNER")
        data.composite_mesh(self.mesh)
        self.assertNotIn(data.LAYER_PREFIX + "gone", self.mesh.attributes)


class LayerKindsTest(BlendTestBase):
    def add(self, kind, generator="AO"):
        if bpy.context.mode != "OBJECT":
            self.leave_edit()
        bpy.ops.livemat.blend_layer_add(kind=kind, generator=generator)
        return self.mesh.livemat_blend.layers_r[0]

    def test_paint_layer_strokes_become_coverage(self):
        layer = self.add("PAINT")
        layer.paint_value = 1.0
        from livemat.blend import paint

        paint.start(bpy.context, self.obj, layer)
        self.assertEqual(bpy.context.mode, "PAINT_VERTEX")
        self.assertEqual(self.mesh.color_attributes.active_color_name, data.PAINT)
        # A brush stroke: white on the corners of face 0.
        strokes = self.mesh.color_attributes[data.PAINT]
        for corner in self.corners_of_face(0):
            strokes.data[corner].color_srgb = (1.0, 1.0, 1.0, 1.0)
        self.assertTrue(paint.sync(self.mesh))
        values = final_values(self.mesh)
        self.assertTrue(all(values[i] == 255 for i in self.corners_of_face(0)))
        self.assertEqual(self.mesh.color_attributes.active_color_name, data.PAINT)  # still painting there
        bpy.ops.livemat.blend_paint_done()
        self.assertEqual(bpy.context.mode, "OBJECT")
        self.assertNotIn(data.PAINT, self.mesh.color_attributes)
        self.assertEqual(self.mesh.color_attributes.active_color_name, data.FINAL)
        self.assertTrue(all(final_values(self.mesh)[i] == 255 for i in self.corners_of_face(0)))

    def test_leaving_vertex_paint_another_way_keeps_strokes(self):
        layer = self.add("PAINT")
        from livemat.blend import paint

        paint.start(bpy.context, self.obj, layer)
        strokes = self.mesh.color_attributes[data.PAINT]
        strokes.data[0].color_srgb = (1.0, 1.0, 1.0, 1.0)
        bpy.ops.object.mode_set(mode="OBJECT")
        paint._tick()  # what the timer does after the mode change
        self.assertEqual(self.mesh.livemat_blend.painting, "")
        self.assertNotIn(data.PAINT, self.mesh.color_attributes)
        self.assertEqual(int(final_values(self.mesh)[0]), 255)

    def test_edge_wear_on_a_cube(self):
        layer = self.add("GENERATOR", "EDGES")
        self.assertTrue(bpy.ops.livemat.blend_bake.poll())
        bpy.ops.livemat.blend_bake()
        # Every cube corner touches 90 degree convex edges; levels 30..90 make that 1.
        self.assertTrue(np.all(final_values(self.mesh) == 255))
        layer.high = 1.0  # 90 degrees now sits halfway between 30 and 180 degrees
        values = final_values(self.mesh)
        self.assertTrue(np.all((values > 60) & (values < 120)), values[:4])

    def test_cycles_bakes_restore_the_scene(self):
        engine = bpy.context.scene.render.engine
        material = bpy.data.materials.new("Mine")
        self.mesh.materials.append(material)
        for generator in ("AO", "THICKNESS", "CURVATURE"):
            layer = self.add("GENERATOR", generator)
            layer.samples = 4
            self.assertEqual(bpy.ops.livemat.blend_bake(), {"FINISHED"}, generator)
            self.assertTrue(layer.baked)
        self.assertEqual(bpy.context.scene.render.engine, engine)
        self.assertEqual(self.mesh.materials[0], material)
        self.assertNotIn("LiveMat Bake", bpy.data.materials)
        self.assertNotIn("LiveMat Bake", self.mesh.color_attributes)
        self.assertEqual(self.mesh.color_attributes.active_color_name, data.FINAL)

    def test_ao_bake_is_bright_on_an_open_cube(self):
        layer = self.add("GENERATOR", "AO")
        layer.samples = 8
        bpy.ops.livemat.blend_bake()
        self.assertGreater(final_values(self.mesh).mean(), 200)  # nothing occludes a lone cube

    def test_fill_refuses_other_layer_kinds(self):
        self.add("PAINT")
        self.edit_select_faces([0])
        self.assertEqual(bpy.ops.livemat.blend_fill(action="SET"), {"CANCELLED"})


class PolygonFillTest(BlendTestBase):
    def picker(self):
        from livemat.blend import fill_tool

        return fill_tool.Picker(self.obj)

    def test_ray_picks_the_top_face(self):
        from mathutils import Vector

        picker = self.picker()
        index = picker.ray(Vector((0.2, 0.1, 5.0)), Vector((0.0, 0.0, -1.0)))
        self.assertGreater(self.mesh.polygons[index].normal.z, 0.9)

    def test_islands(self):
        from livemat.blend import fill_tool

        # Move face 0's UVs away: it becomes its own UV island, still connected in 3D.
        uv = self.mesh.uv_layers.active.data
        for corner in self.corners_of_face(0):
            uv[corner].uv = (uv[corner].uv[0] + 5.0, uv[corner].uv[1])
        mesh_islands, uv_islands = fill_tool.islands(self.mesh)
        self.assertEqual(len(set(mesh_islands)), 1)
        self.assertEqual(sum(1 for island in uv_islands if island == uv_islands[0]), 1)
        picker = self.picker()
        self.assertEqual(len(picker.expand([0], "MESH")), 6)
        self.assertEqual(picker.expand([0], "UV_ISLAND"), {0})
        self.assertEqual(len(picker.expand([1], "UV_ISLAND")), 5)
        self.assertEqual(picker.expand([0], "POLYGON"), {0})

    def test_rectangle_hit_tests_and_occlusion(self):
        from mathutils import Vector

        from livemat.blend import fill_tool

        picker = self.picker()
        # A top-down orthographic view: x, y in world units are the 2D coordinates.
        project = lambda point: (point.x, point.y)
        down = Vector((0.0, 0.0, -1.0))
        # A small rectangle around the middle holds the top and bottom face centers.
        center = fill_tool.polygons_in_rectangle(picker, project, (-0.1, -0.1, 0.1, 0.1), "CENTER", False, None, down)
        self.assertEqual(len(center), 2)
        visible = fill_tool.polygons_in_rectangle(picker, project, (-0.1, -0.1, 0.1, 0.1), "CENTER", True, None, down)
        self.assertEqual(len(visible), 1)  # the bottom face is hidden by the top one
        self.assertGreater(self.mesh.polygons[visible.pop()].normal.z, 0.9)
        # A rectangle over one corner touches the faces that meet there, but no face center.
        corner = fill_tool.polygons_in_rectangle(picker, project, (0.9, 0.9, 1.1, 1.1), "INTERSECT", False, None, down)
        self.assertEqual(len(corner), 4)
        self.assertEqual(fill_tool.polygons_in_rectangle(picker, project, (0.9, 0.9, 1.1, 1.1), "CENTER", False, None, down), set())

    def test_apply_and_clear(self):
        from livemat.blend import fill_tool

        fill_tool.apply(self.mesh, {0}, 0.5)
        values = final_values(self.mesh)
        self.assertTrue(all(values[i] == 128 for i in self.corners_of_face(0)))
        fill_tool.apply(self.mesh, {0}, 0.5, clear=True)
        self.assertEqual(int(final_values(self.mesh).sum()), 0)


class BlendMaterialTest(BlendTestBase):
    """Renders compare the Blend material with its sources, so the mask decoding and mixing are checked numerically."""

    def setUp(self):
        super().setUp()
        import tempfile

        from tests.fixtures import make_texture_set

        self._tmp = tempfile.TemporaryDirectory()
        folder = self._tmp.name
        make_texture_set(folder, "Brick", {"_BaseColor": (200, 40, 40), "_Roughness": (230,)})
        make_texture_set(folder, "Moss", {"_BaseColor": (40, 160, 60), "_Roughness": (230,)})
        props = bpy.context.scene.livemat
        props.folder = folder
        props.preset = "default_metal_rough"
        props.create_missing = True
        bpy.ops.livemat.build()
        self.brick = bpy.data.materials["Brick"]
        self.moss = bpy.data.materials["Moss"]

        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 16
        scene.cycles.use_denoising = False
        scene.render.resolution_x = scene.render.resolution_y = 2
        scene.render.image_settings.file_format = "OPEN_EXR"
        if scene.world is None:
            scene.world = bpy.data.worlds.new("World")
        scene.world.color = (1.0, 1.0, 1.0)
        bpy.ops.object.camera_add(location=(0, 0, 5))
        camera = bpy.context.active_object
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = 0.5
        scene.camera = camera
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)
        self.obj.data.materials.clear()
        self.obj.data.materials.append(self.brick)

    def tearDown(self):
        super().tearDown()
        for collection in (bpy.data.materials, bpy.data.node_groups, bpy.data.images, bpy.data.cameras):
            for block in list(collection):
                collection.remove(block)
        self._tmp.cleanup()

    def render(self):
        import os

        path = os.path.join(self._tmp.name, "probe.exr")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(path)
        pixel = tuple(image.pixels[:3])
        bpy.data.images.remove(image)
        return pixel

    def set_mask_r(self, value):
        from livemat.blend import fill_tool

        fill_tool.apply(self.mesh, range(len(self.mesh.polygons)), value)

    def assertPixel(self, got, want, delta):
        for a, b in zip(got, want):
            self.assertAlmostEqual(a, b, delta=delta)

    def test_blend_follows_the_mask(self):
        brick = self.render()
        self.obj.active_material = self.moss
        moss = self.render()
        self.obj.active_material = self.brick

        bpy.ops.livemat.blend_material_create()
        blend = self.obj.active_material
        setup = blend.livemat_blend_material
        self.assertEqual(setup.base, self.brick)
        setup.layer_r = self.moss
        setup.use_height = False

        self.set_mask_r(0.0)
        self.assertPixel(self.render(), brick, 0.02)
        self.set_mask_r(1.0)
        self.assertPixel(self.render(), moss, 0.02)
        # Byte 128 has to blend halfway: decoding the mask as linear would give 0.216 instead.
        self.set_mask_r(0.5)
        middle = tuple((a + b) / 2 for a, b in zip(brick, moss))
        self.assertPixel(self.render(), middle, 0.02)

    def test_height_blend_keeps_the_ends(self):
        bpy.ops.livemat.blend_material_create()
        blend = self.obj.active_material
        blend.livemat_blend_material.layer_r = self.moss
        self.set_mask_r(0.0)
        brick_like = self.render()
        self.obj.active_material = self.brick
        self.assertPixel(brick_like, self.render(), 0.02)

    def test_only_livemat_materials_can_be_picked(self):
        from livemat.blend import material

        self.assertTrue(material.is_source(self.brick))
        self.assertFalse(material.is_source(bpy.data.materials.new("Plain")))
        bpy.ops.livemat.blend_material_create()
        self.assertFalse(material.is_source(self.obj.active_material))


class PixelMaskTest(BlendMaterialTest):
    """Texture masks: render comparisons, conversions both ways, and export layouts."""

    def make_blend(self):
        bpy.ops.livemat.blend_material_create()
        blend = self.obj.active_material
        setup = blend.livemat_blend_material
        setup.layer_r = self.moss
        setup.use_height = False
        setup.resolution = "512"
        return blend

    def fill_image(self, blend, channel, value):
        from livemat.blend import texture

        image = texture.channel_image(blend, channel, create=True)
        texture.write_gray(image, np.full((image.size[1], image.size[0]), value, dtype=np.float32))
        blend.livemat_blend_material.mask_source = "TEXTURE"
        from livemat.blend import material

        material.build(blend)

    def test_texture_mask_drives_the_blend(self):
        brick = self.render()
        self.obj.active_material = self.moss
        moss = self.render()
        self.obj.active_material = self.brick
        blend = self.make_blend()
        self.fill_image(blend, "R", 0.0)
        self.assertPixel(self.render(), brick, 0.02)
        self.fill_image(blend, "R", 1.0)
        self.assertPixel(self.render(), moss, 0.02)

    def test_vertex_to_texture(self):
        from livemat.blend import texture

        blend = self.make_blend()
        self.set_mask_r(1.0)
        bpy.ops.livemat.blend_mask_convert(direction="TO_TEXTURE")
        self.assertEqual(blend.livemat_blend_material.mask_source, "TEXTURE")
        uvs = np.zeros(len(self.mesh.loops) * 2, dtype=np.float32)
        self.mesh.uv_layers.active.data.foreach_get("uv", uvs)
        uvs = uvs.reshape(-1, 2)
        polygon = self.mesh.polygons[0]
        center = uvs[polygon.loop_start:polygon.loop_start + polygon.loop_total].mean(axis=0, keepdims=True)
        red = texture.read_gray(blend.livemat_blend_material.image_r)
        green = texture.read_gray(blend.livemat_blend_material.image_g)
        self.assertAlmostEqual(float(texture.sample(red, center)[0]), 1.0, places=2)
        self.assertAlmostEqual(float(texture.sample(green, center)[0]), 0.0, places=2)

    def test_texture_to_vertex(self):
        blend = self.make_blend()
        self.fill_image(blend, "R", 0.5)
        bpy.ops.livemat.blend_mask_convert(direction="TO_VERTEX")
        self.assertEqual(blend.livemat_blend_material.mask_source, "VERTEX")
        values = final_values(self.mesh)
        self.assertTrue(np.all(np.abs(values - 128) <= 1), values[:8])
        self.assertEqual(self.mesh.livemat_blend.layers_r[0].name, "From Texture")

    def test_export_layouts(self):
        import os

        from livemat.blend import texture

        blend = self.make_blend()
        self.fill_image(blend, "R", 1.0)
        self.fill_image(blend, "G", 1.0)
        folder = os.path.join(self._tmp.name, "out")

        paths = texture.export(blend, folder, "mask", "GENERIC", "PNG")
        self.assertEqual([os.path.basename(p) for p in paths], ["mask_mask.png"])
        image = bpy.data.images.load(paths[0])
        image.colorspace_settings.name = "Non-Color"
        pixel = tuple(round(v, 2) for v in image.pixels[:4])
        bpy.data.images.remove(image)
        self.assertEqual(pixel, (1.0, 1.0, 0.0, 0.0))

        paths = texture.export(blend, folder, "terrain", "UNITY_TERRAIN", "TARGA")
        image = bpy.data.images.load(paths[0])
        image.colorspace_settings.name = "Non-Color"
        pixel = tuple(round(v, 2) for v in image.pixels[:4])
        bpy.data.images.remove(image)
        self.assertEqual(pixel, (0.5, 0.5, 0.0, 0.0))  # weights add up to 1

        paths = texture.export(blend, folder, "land", "UNREAL_LANDSCAPE", "PNG")
        self.assertEqual(sorted(os.path.basename(p) for p in paths), ["land_A.png", "land_B.png", "land_G.png", "land_R.png"])
