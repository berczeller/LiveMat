import os
import tempfile
import unittest

import bpy

from livemat.build import material as builder
from livemat.build import nodegroup
from livemat.core import presets, scanner
from tests.fixtures import METAL_ROUGH, make_texture_set, write_png


def links_into(node, socket_name):
    return [l for l in node.id_data.links if l.to_node == node and l.to_socket.name == socket_name]


def source_of(node, socket_name):
    found = links_into(node, socket_name)
    return found[0].from_node if found else None


class BuildTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name
        self.presets = presets.load_builtin_presets()

    def tearDown(self):
        for collection in (bpy.data.materials, bpy.data.node_groups, bpy.data.images):
            for block in list(collection):
                collection.remove(block)
        self._tmp.cleanup()

    def build(self, preset_id, maps, name="crate", material=None, **kwargs):
        make_texture_set(self.folder, name, maps)
        preset = self.presets[preset_id]
        texture_set = scanner.scan_folder(self.folder, preset).sets[0]
        material = material or bpy.data.materials.new(name)
        report = builder.build_material(material, texture_set, preset, **kwargs)
        return material, report

    def livemat_group(self, material):
        return next(n for n in material.node_tree.nodes if n.get(builder.TAG) == "group")

    def inner(self, group, kind):
        return [n for n in group.nodes if n.bl_idname == kind]


class MaterialTest(BuildTestBase):
    def test_metal_rough_wiring(self):
        material, report = self.build("default_metal_rough", METAL_ROUGH)
        self.assertEqual(sorted(report.loaded), ["base_color", "metallic", "normal", "roughness"])
        self.assertIn("ao", report.missing)

        group_node = self.livemat_group(material)
        output = next(n for n in material.node_tree.nodes if n.type == "OUTPUT_MATERIAL")
        self.assertEqual(source_of(output, "Surface"), group_node)
        self.assertEqual(source_of(group_node, "Base Color").image.name, "crate_BaseColor.png")
        self.assertEqual(material["livemat_preset"], "default_metal_rough")

    def test_colorspaces(self):
        self.build("default_metal_rough", METAL_ROUGH)
        images = bpy.data.images
        self.assertEqual(images["crate_BaseColor.png"].colorspace_settings.name, "sRGB")
        for name in ("crate_Metallic.png", "crate_Roughness.png", "crate_Normal.png"):
            self.assertEqual(images[name].colorspace_settings.name, "Non-Color", name)

    def test_gloss_alpha_is_channel_packed(self):
        maps = {"_Albedo": (200, 100, 50, 255), "_MetallicSmoothness": (255, 0, 0, 191)}
        material, _ = self.build("unity_standard", maps)
        image = bpy.data.images["crate_MetallicSmoothness.png"]
        self.assertEqual(image.alpha_mode, "CHANNEL_PACKED")
        self.assertEqual(bpy.data.images["crate_Albedo.png"].alpha_mode, "STRAIGHT")
        group_node = self.livemat_group(material)
        self.assertTrue(group_node.inputs["Metallic Smoothness Alpha"].is_linked)

    def test_images_are_reused(self):
        make_texture_set(self.folder, "crate", METAL_ROUGH)
        preset = self.presets["default_metal_rough"]
        texture_set = scanner.scan_folder(self.folder, preset).sets[0]
        for name in ("a", "b"):
            builder.build_material(bpy.data.materials.new(name), texture_set, preset)
        self.assertEqual(len(bpy.data.images), 4)


class ExistingNodesTest(BuildTestBase):
    def test_default_material_is_replaced(self):
        material, report = self.build("default_metal_rough", METAL_ROUGH)
        self.assertFalse(report.kept_aside)
        self.assertEqual(
            [n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"], []
        )

    def test_custom_nodes_are_kept_in_a_frame(self):
        material = bpy.data.materials.new("crate")
        custom = material.node_tree.nodes.new("ShaderNodeTexNoise")
        material, report = self.build("default_metal_rough", METAL_ROUGH, material=material)
        self.assertTrue(report.kept_aside)
        self.assertEqual(custom.parent.label, builder.FRAME_LABEL)
        output = next(n for n in material.node_tree.nodes if n.type == "OUTPUT_MATERIAL")
        self.assertEqual(source_of(output, "Surface"), self.livemat_group(material))

    def test_rebuild_clears_everything(self):
        material = bpy.data.materials.new("crate")
        material.node_tree.nodes.new("ShaderNodeTexNoise")
        material, _ = self.build("default_metal_rough", METAL_ROUGH, material=material, rebuild=True)
        self.assertEqual([n for n in material.node_tree.nodes if n.type == "TEX_NOISE"], [])

    def test_second_build_keeps_tweaks_and_no_duplicates(self):
        material, _ = self.build("default_metal_rough", METAL_ROUGH)
        self.livemat_group(material).inputs["Normal Strength"].default_value = 0.3
        preset = self.presets["default_metal_rough"]
        texture_set = scanner.scan_folder(self.folder, preset).sets[0]
        builder.build_material(material, texture_set, preset)

        groups = [n for n in material.node_tree.nodes if n.get(builder.TAG) == "group"]
        self.assertEqual(len(groups), 1)
        self.assertAlmostEqual(groups[0].inputs["Normal Strength"].default_value, 0.3, places=5)
        textures = [n for n in material.node_tree.nodes if n.type == "TEX_IMAGE"]
        self.assertEqual(len(textures), 4)


class NodeGroupTest(BuildTestBase):
    def test_one_group_per_preset_and_reused(self):
        preset = self.presets["unreal_packed"]
        first = nodegroup.ensure_group(preset)
        self.assertIs(nodegroup.ensure_group(preset), first)
        self.assertEqual(first.name, "LiveMat Unreal Packed")

    def test_directx_flips_green(self):
        group = nodegroup.ensure_group(self.presets["unreal"])
        # One flip for the normal map, one for the detail normal.
        self.assertEqual(len(self.inner(group, "ShaderNodeCombineColor")), 2)
        group = nodegroup.ensure_group(self.presets["default_metal_rough"])
        self.assertEqual(self.inner(group, "ShaderNodeCombineColor"), [])

    def test_gloss_becomes_roughness(self):
        group = nodegroup.ensure_group(self.presets["unity_mask_map"])
        bsdf = self.inner(group, "ShaderNodeBsdfPrincipled")[0]
        math = source_of(bsdf, "Roughness")
        self.assertEqual((math.bl_idname, math.operation), ("ShaderNodeMath", "SUBTRACT"))
        self.assertEqual(math.inputs[0].default_value, 1.0)

    def test_ao_and_height_start_disabled(self):
        group = nodegroup.ensure_group(self.presets["default_metal_rough"])
        defaults = {item.name: item.default_value for item in group.interface.items_tree
                    if item.item_type == "SOCKET" and item.in_out == "INPUT"
                    and item.socket_type == "NodeSocketFloat"}
        self.assertEqual(defaults[nodegroup.AO_STRENGTH], 0.0)
        self.assertEqual(defaults[nodegroup.HEIGHT_STRENGTH], 0.0)

    def test_outdated_group_rebuilds_in_place(self):
        preset = self.presets["unreal"]
        group = nodegroup.ensure_group(preset)
        group["livemat_stamp"] = "old"
        self.assertIs(nodegroup.ensure_group(preset), group)
        self.assertNotEqual(group["livemat_stamp"], "old")


class UdimTest(BuildTestBase):
    def test_udim_set_loads_as_tiled(self):
        for tile in (1001, 1002):
            write_png(os.path.join(self.folder, f"crate_BaseColor.{tile}.png"), (200, 100, 50))
        preset = self.presets["default_metal_rough"]
        texture_set = scanner.scan_folder(self.folder, preset).sets[0]
        builder.build_material(bpy.data.materials.new("crate"), texture_set, preset)
        image = next(iter(bpy.data.images))
        self.assertEqual(image.source, "TILED")
        self.assertEqual(sorted(t.number for t in image.tiles), [1001, 1002])
