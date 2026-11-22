import os
import tempfile
import unittest

import bpy

import livemat
from livemat.build import material as builder
from livemat.build import nodegroup
from tests.fixtures import METAL_ROUGH, make_texture_set, write_png


class OperatorTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        livemat.register()

    @classmethod
    def tearDownClass(cls):
        livemat.unregister()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name
        self.props = bpy.context.scene.livemat
        self.props.folder = self.folder
        self.props.preset = "default_metal_rough"
        self.props.create_missing = True
        self.props.rebuild = False
        self.props.sets.clear()
        self.props.scanned_folder = self.props.scanned_preset = ""

    def tearDown(self):
        for collection in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.node_groups, bpy.data.images):
            for block in list(collection):
                collection.remove(block)
        self._tmp.cleanup()

    def sets(self):
        return {item.name: item for item in self.props.sets}


class ScanTest(OperatorTestBase):
    def test_matches_existing_material_by_name(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        make_texture_set(self.folder, "Barrel", METAL_ROUGH)
        crate = bpy.data.materials.new("MI_Crate")
        bpy.ops.livemat.scan()
        found = self.sets()
        self.assertEqual(sorted(found), ["Barrel", "Crate"])
        self.assertEqual(found["Crate"].material, crate)
        self.assertIsNone(found["Barrel"].material)
        self.assertEqual(len(found["Crate"].files), 4)

    def test_missing_folder_is_an_error(self):
        self.props.folder = os.path.join(self.folder, "nope")
        with self.assertRaises(RuntimeError):
            bpy.ops.livemat.scan()

    def test_rescan_keeps_choices(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.livemat.scan()
        other = bpy.data.materials.new("Something Else")
        self.sets()["Crate"].include = False
        self.sets()["Crate"].material = other
        bpy.ops.livemat.scan()
        self.assertFalse(self.sets()["Crate"].include)
        self.assertEqual(self.sets()["Crate"].material, other)


class BuildTest(OperatorTestBase):
    def test_build_all_creates_and_reuses(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        make_texture_set(self.folder, "Barrel", METAL_ROUGH)
        crate = bpy.data.materials.new("Crate")
        bpy.ops.livemat.build()  # scans first, since nothing was scanned yet
        self.assertEqual(crate["livemat_preset"], "default_metal_rough")
        self.assertEqual(crate["livemat_folder"], self.props.scanned_folder)
        self.assertIn("Barrel", bpy.data.materials)

    def test_create_missing_off_skips_new_sets(self):
        make_texture_set(self.folder, "Barrel", METAL_ROUGH)
        self.props.create_missing = False
        bpy.ops.livemat.build()
        self.assertNotIn("Barrel", bpy.data.materials)

    def test_excluded_sets_are_skipped(self):
        make_texture_set(self.folder, "Barrel", METAL_ROUGH)
        bpy.ops.livemat.scan()
        self.sets()["Barrel"].include = False
        bpy.ops.livemat.build()
        self.assertNotIn("Barrel", bpy.data.materials)

    def test_assign_to_selected(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.livemat.scan()
        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.active_object
        cube.select_set(True)
        bpy.ops.livemat.assign(index=0)
        self.assertEqual(cube.active_material.name, "Crate")
        self.assertIn("livemat_preset", cube.active_material)


class MaterialEditTest(OperatorTestBase):
    def setUp(self):
        super().setUp()
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.livemat.build()
        self.material = bpy.data.materials["Crate"]

    def group_input(self, name):
        return builder.livemat_group_node(self.material).inputs[name]

    def test_load_slot_replaces_one_texture(self):
        path = write_png(os.path.join(self.folder, "other", "Rough2.png"), (10,))
        self.group_input(nodegroup.NORMAL_STRENGTH).default_value = 2.5
        bpy.ops.livemat.load_slot(material="Crate", slot="roughness", filepath=str(path))
        nodes = builder.livemat_texture_nodes(self.material)
        self.assertEqual(nodes["roughness"].image.name, "Rough2.png")
        self.assertEqual(nodes["base_color"].image.name, "Crate_BaseColor.png")
        self.assertAlmostEqual(self.group_input(nodegroup.NORMAL_STRENGTH).default_value, 2.5)

    def test_clear_slot(self):
        bpy.ops.livemat.clear_slot(material="Crate", slot="metallic")
        self.assertNotIn("metallic", builder.livemat_texture_nodes(self.material))
        self.assertIn("roughness", builder.livemat_texture_nodes(self.material))

    def test_switch_preset_rescans_folder(self):
        self.group_input(nodegroup.NORMAL_STRENGTH).default_value = 3.0
        bpy.ops.livemat.switch_preset(material="Crate", preset="unreal")
        self.assertEqual(self.material["livemat_preset"], "unreal")
        group = builder.livemat_group_node(self.material).node_tree
        self.assertTrue(any(n.label == "DirectX to OpenGL" for n in group.nodes))
        self.assertAlmostEqual(self.group_input(nodegroup.NORMAL_STRENGTH).default_value, 3.0)

    def test_slot_defaults_carry_over_only_within_a_preset(self):
        self.group_input("Height").default_value = (0.2, 0.2, 0.2, 1.0)
        bpy.ops.livemat.clear_slot(material="Crate", slot="metallic")
        self.assertAlmostEqual(self.group_input("Height").default_value[0], 0.2)
        bpy.ops.livemat.switch_preset(material="Crate", preset="unreal")
        self.assertAlmostEqual(self.group_input("Height").default_value[0], 0.5)

    def test_switch_to_preset_without_matching_files(self):
        with self.assertRaises(RuntimeError):
            bpy.ops.livemat.switch_preset(material="Crate", preset="rust_standard")
        self.assertEqual(self.material["livemat_preset"], "default_metal_rough")

    def test_read_back_texture_set(self):
        texture_set = builder.texture_set_from_material(self.material)
        self.assertEqual(texture_set.key, "crate")
        self.assertEqual(sorted(texture_set.files), ["base_color", "metallic", "normal", "roughness"])


class AuthoringViewTest(OperatorTestBase):
    def test_toggle_restores_settings(self):
        view = bpy.context.scene.view_settings
        before = (view.view_transform, view.look, view.exposure)
        view.exposure = 1.5
        bpy.ops.livemat.authoring_view()
        self.assertIn(view.view_transform, ("Khronos PBR Neutral", "Standard"))
        self.assertEqual(view.exposure, 0.0)
        bpy.ops.livemat.authoring_view()
        self.assertEqual((view.view_transform, view.look, view.exposure), (before[0], before[1], 1.5))
