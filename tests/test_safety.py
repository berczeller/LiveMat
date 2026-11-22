"""LiveMat must never break or silently change what the user set up."""

import os

import bpy

from livemat import registry
from livemat.build import material as builder
from livemat.build import nodegroup
from tests.fixtures import METAL_ROUGH, make_texture_set, write_png
from tests.test_operators import OperatorTestBase


def linked_inputs(node):
    return sorted(s.name for s in node.inputs if s.is_linked)


class SharedGroupTest(OperatorTestBase):
    def test_group_rebuild_keeps_other_materials_linked(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        make_texture_set(self.folder, "Barrel", METAL_ROUGH)
        bpy.ops.livemat.build()
        barrel = bpy.data.materials["Barrel"]
        barrel_group = builder.livemat_group_node(barrel)
        barrel_group.inputs[nodegroup.NORMAL_STRENGTH].default_value = 0.7
        before = linked_inputs(barrel_group)

        nodegroup.find_group("default_metal_rough")["livemat_stamp"] = "outdated"
        bpy.ops.livemat.build(index=[s.name for s in self.props.sets].index("Crate"))

        self.assertEqual(linked_inputs(barrel_group), before)
        self.assertTrue(barrel_group.outputs[nodegroup.SHADER_OUTPUT].is_linked)
        self.assertAlmostEqual(barrel_group.inputs[nodegroup.NORMAL_STRENGTH].default_value, 0.7)

    def test_helper_rebuild_keeps_preset_groups_linked(self):
        make_texture_set(self.folder, "skin", {"_bc": (90, 60, 40), "_sg": (20, 20, 20, 160)})
        self.props.preset = "rust_standard_specular"
        bpy.ops.livemat.build()
        group = nodegroup.find_group("rust_standard_specular")
        converter = next(n for n in group.nodes if n.bl_idname == "ShaderNodeGroup")
        before = (linked_inputs(converter), sorted(s.name for s in converter.outputs if s.is_linked))

        converter.node_tree["livemat_stamp"] = -1
        nodegroup.ensure_specgloss_group()

        after = (linked_inputs(converter), sorted(s.name for s in converter.outputs if s.is_linked))
        self.assertEqual(after, before)


class UserEditsTest(OperatorTestBase):
    def setUp(self):
        super().setUp()
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.livemat.build()
        self.material = bpy.data.materials["Crate"]
        self.tree = self.material.node_tree

    def test_displacement_link_survives_rebuild(self):
        output = next(n for n in self.tree.nodes if n.type == "OUTPUT_MATERIAL")
        displacement = self.tree.nodes.new("ShaderNodeDisplacement")
        self.tree.links.new(displacement.outputs[0], output.inputs["Displacement"])
        bpy.ops.livemat.clear_slot(material="Crate", slot="metallic")
        self.assertTrue(output.inputs["Displacement"].is_linked)
        self.assertTrue(output.inputs["Surface"].is_linked)

    def test_image_node_edits_survive_rebuild(self):
        base = builder.livemat_texture_nodes(self.material)["base_color"]
        mapping = self.tree.nodes.new("ShaderNodeMapping")
        self.tree.links.new(mapping.outputs[0], base.inputs["Vector"])
        base.interpolation = "Closest"
        other = write_png(os.path.join(self.folder, "x", "Rough.png"), (5,))
        bpy.ops.livemat.load_slot(material="Crate", slot="roughness", filepath=str(other))
        base = builder.livemat_texture_nodes(self.material)["base_color"]
        self.assertTrue(base.inputs["Vector"].is_linked)
        self.assertEqual(base.interpolation, "Closest")

    def test_generated_image_is_kept_until_cleared(self):
        generated = bpy.data.images.new("painted", 4, 4)
        builder.livemat_texture_nodes(self.material)["roughness"].image = generated
        bpy.ops.livemat.refresh()
        self.assertEqual(builder.livemat_texture_nodes(self.material)["roughness"].image, generated)
        bpy.ops.livemat.clear_slot(material="Crate", slot="roughness")
        self.assertNotIn("roughness", builder.livemat_texture_nodes(self.material))

    def test_render_method_restored_without_alpha(self):
        material = bpy.data.materials.new("Glass")
        material.surface_render_method = "BLENDED"
        make_texture_set(self.folder, "Glass", {"_BaseColor": (200, 200, 200), "_Opacity": (100,)})
        bpy.ops.livemat.scan()
        bpy.ops.livemat.build(index=[s.name for s in self.props.sets].index("Glass"))
        self.assertEqual(material.surface_render_method, "DITHERED")
        bpy.ops.livemat.clear_slot(material="Glass", slot="opacity")
        self.assertEqual(material.surface_render_method, "BLENDED")


class ExistingDataTest(OperatorTestBase):
    def test_shared_image_settings_are_left_alone(self):
        paths = make_texture_set(self.folder, "Crate", METAL_ROUGH)
        mine = bpy.data.images.load(str(paths["_Normal"]))
        mine.colorspace_settings.name = "sRGB"
        bpy.ops.livemat.build()
        normal = builder.livemat_texture_nodes(bpy.data.materials["Crate"])["normal"].image
        self.assertNotEqual(normal, mine)
        self.assertEqual(mine.colorspace_settings.name, "sRGB")
        self.assertEqual(normal.colorspace_settings.name, "Non-Color")

    def test_matching_image_is_reused(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.livemat.build()
        count = len(bpy.data.images)
        bpy.ops.livemat.refresh()
        bpy.ops.livemat.build()
        self.assertEqual(len(bpy.data.images), count)

    def test_tweaked_principled_is_kept_aside(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        material = bpy.data.materials.new("Crate")
        bsdf = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Roughness"].default_value = 0.123
        bpy.ops.livemat.build()
        frames = [n for n in material.node_tree.nodes if n.type == "FRAME"]
        self.assertEqual([f.label for f in frames], [builder.FRAME_LABEL])
        self.assertIn(bsdf, list(material.node_tree.nodes))

    def test_untouched_principled_is_replaced(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        material = bpy.data.materials.new("Crate")
        bpy.ops.livemat.build()
        self.assertFalse(any(n.type in {"FRAME", "BSDF_PRINCIPLED"} for n in material.node_tree.nodes))

    def test_preset_choice_saved_by_stable_number(self):
        self.props.preset = "unreal"
        self.assertEqual(self.props["preset"], registry.enum_number("unreal"))

    def test_folder_is_remembered_absolute_when_unsaved(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.livemat.build()
        crate = bpy.data.materials["Crate"]
        self.assertEqual(builder.material_folder(crate), os.path.normpath(self.folder))
        self.assertTrue(crate["livemat_recursive"])
