"""Inspector features: preset picker, tint and strengths, channels, texture picker, detail and tangents."""

import os

import bpy

from livemat import actions, registry
from livemat.build import material as builder
from livemat.build import nodegroup
from livemat.core import presets, scanner
from tests.fixtures import METAL_ROUGH, RUST_STANDARD, make_texture_set, write_png
from tests.test_operators import OperatorTestBase


def group_inputs(material):
    return builder.livemat_group_node(material).inputs


class PresetListTest(OperatorTestBase):
    def test_new_scene_asks_for_a_preset(self):
        bpy.context.scene.property_unset("livemat")
        props = bpy.context.scene.livemat
        self.assertEqual(props.preset, registry.NONE)
        props.folder = self.folder
        with self.assertRaises(RuntimeError):
            bpy.ops.livemat.scan()

    def test_presets_sorted_by_name(self):
        names = [item[1] for item in registry.enum_items()[1:]]
        self.assertEqual(names, sorted(names, key=str.casefold))
        self.assertIn("Default (Specular)", names)


class DetailSlotTest(OperatorTestBase):
    def test_every_preset_has_a_detail_slot(self):
        for preset in presets.load_builtin_presets().values():
            self.assertIsNotNone(preset.slot("detail_normal"), preset.id)

    def test_detail_suffix_wins_over_normal(self):
        make_texture_set(self.folder, "rock", {"_nrm": (128, 128, 255), "_detail_nrm": (128, 128, 255)})
        rust = presets.load_builtin_presets()["rust_standard"]
        files = scanner.scan_folder(self.folder, rust).sets[0].files
        self.assertTrue(files["nrm"].endswith("rock_nrm.png"))
        self.assertTrue(files["detail_normal"].endswith("rock_detail_nrm.png"))

    def test_detail_tiling_survives_rebuild(self):
        make_texture_set(self.folder, "Crate", {**METAL_ROUGH, "_detail_normal": (128, 128, 255)})
        bpy.ops.livemat.build()
        material = bpy.data.materials["Crate"]
        mapping = builder.detail_mapping(material)
        self.assertTrue(builder.livemat_texture_nodes(material)["detail_normal"].inputs["Vector"].is_linked)
        mapping.inputs["Scale"].default_value = (8.0, 8.0, 1.0)
        bpy.ops.livemat.clear_slot(material="Crate", slot="metallic")
        self.assertEqual(tuple(builder.detail_mapping(material).inputs["Scale"].default_value)[:2], (8.0, 8.0))
        bpy.ops.livemat.clear_slot(material="Crate", slot="detail_normal")
        self.assertIsNone(builder.detail_mapping(material))


class SurfaceInputsTest(OperatorTestBase):
    def setUp(self):
        super().setUp()
        self.props.preset = "rust_standard"
        make_texture_set(self.folder, "crate", RUST_STANDARD)
        bpy.ops.livemat.build()
        self.material = bpy.data.materials["crate"]

    def test_unity_style_inputs(self):
        inputs = group_inputs(self.material)
        self.assertEqual(tuple(inputs[nodegroup.BASE_TINT].default_value), (1.0, 1.0, 1.0, 1.0))
        self.assertEqual(inputs[nodegroup.METALLIC_STRENGTH].default_value, 1.0)
        self.assertEqual(inputs[nodegroup.SMOOTHNESS_STRENGTH].default_value, 1.0)

    def test_tint_survives_preset_switch(self):
        group_inputs(self.material)[nodegroup.BASE_TINT].default_value = (1.0, 0.5, 0.5, 1.0)
        write_png(os.path.join(self.folder, "crate_BaseColor.png"), (200, 120, 60))
        bpy.ops.livemat.switch_preset(material="crate", preset="default_metal_rough")
        self.assertAlmostEqual(group_inputs(self.material)[nodegroup.BASE_TINT].default_value[1], 0.5)

    def test_channel_reroute(self):
        state = next(s for s in self.material.livemat.slots if s.slot == "mg")
        state.src_R = "G"
        metallic = group_inputs(self.material)["Metallic Gloss"]
        self.assertEqual(metallic.links[0].from_node.bl_idname, "ShaderNodeCombineColor")
        state.src_R = "R"
        metallic = group_inputs(self.material)["Metallic Gloss"]  # the rebuild made a new group node
        self.assertEqual(metallic.links[0].from_node.bl_idname, "ShaderNodeTexImage")

    def test_alpha_reroute(self):
        state = next(s for s in self.material.livemat.slots if s.slot == "mg")
        state.src_A = "B"
        gloss = group_inputs(self.material)["Metallic Gloss Alpha"]
        self.assertEqual(gloss.links[0].from_node.bl_idname, "ShaderNodeSeparateColor")


class PickerTest(OperatorTestBase):
    def setUp(self):
        super().setUp()
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        write_png(os.path.join(self.folder, "Scratches.png"), (90, 90, 90))
        bpy.ops.livemat.build()
        self.material = bpy.data.materials["Crate"]
        self.state = next(s for s in self.material.livemat.slots if s.slot == "base_color")
        actions.forget_folders()

    def test_items_list_folder_images(self):
        items = actions.picker_items(self.state, bpy.context)
        names = [item[1] for item in items]
        self.assertEqual(names[0], "None")
        self.assertIn("Scratches.png", names)
        # The material's own set comes first.
        self.assertTrue(names[1].startswith("Crate_"))

    def test_picking_loads_and_none_clears(self):
        items = actions.picker_items(self.state, bpy.context)
        scratches = next(item[0] for item in items if item[1] == "Scratches.png")
        self.state.texture = scratches
        self.assertEqual(builder.livemat_texture_nodes(self.material)["base_color"].image.name, "Scratches.png")
        self.state.texture = actions.NONE
        self.assertNotIn("base_color", builder.livemat_texture_nodes(self.material))


class UnityTangentsTest(OperatorTestBase):
    def test_unity_mode_writes_bitangents(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.active_object
        cube.select_set(True)
        bpy.ops.livemat.scan()
        bpy.ops.livemat.assign(index=0)
        material = cube.active_material

        material.livemat.tangents = "UNITY"
        attribute = cube.data.attributes.get(nodegroup.BITANGENT_ATTRIBUTE)
        self.assertIsNotNone(attribute)
        self.assertEqual(len(attribute.data), len(cube.data.loops))
        self.assertGreater(max(abs(v) for d in attribute.data for v in d.vector), 0.5)
        self.assertEqual(group_inputs(material)[nodegroup.UNITY_TANGENTS].default_value, 1.0)

        material.livemat.tangents = "BLENDER"
        self.assertEqual(group_inputs(material)[nodegroup.UNITY_TANGENTS].default_value, 0.0)


class TgaThumbnailTest(OperatorTestBase):
    def test_tga_gets_a_thumbnail(self):
        from livemat import thumbs

        # Uncompressed 32-bit TGA, written by hand: red with alpha 128 (a gloss value).
        path = os.path.join(self.folder, "red_bc.tga")
        header = bytes([0, 0, 2]) + bytes(9) + (256).to_bytes(2, "little") + (128).to_bytes(2, "little") + bytes([32, 8])
        with open(path, "wb") as f:
            f.write(header + bytes([0, 0, 255, 128]) * (256 * 128))  # BGRA

        thumbs.file_icon(path)
        thumbs._make_next()  # the timer's job, run by hand since timers don't tick here
        preview = thumbs._previews[path]
        self.assertEqual(tuple(preview.image_size), (thumbs.IMAGE_SIZE, thumbs.IMAGE_SIZE // 2))
        self.assertEqual(tuple(preview.image_pixels_float[:4]), (1.0, 0.0, 0.0, 1.0))
        self.assertFalse(any("red_bc" in i.name for i in bpy.data.images))
