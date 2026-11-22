import os
import tempfile
import unittest

import bpy

from livemat.build import material as builder
from livemat.build import nodegroup
from livemat.core import presets, scanner
from tests.fixtures import RUST_STANDARD, make_texture_set, write_png


class RustScanTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name
        self.presets = presets.load_builtin_presets()

    def tearDown(self):
        for collection in (bpy.data.materials, bpy.data.node_groups, bpy.data.images):
            for block in list(collection):
                collection.remove(block)
        self._tmp.cleanup()

    def test_rust_set_maps_to_slots(self):
        make_texture_set(self.folder, "SpeedLoader", RUST_STANDARD)
        texture_set = scanner.scan_folder(self.folder, self.presets["rust_standard"]).sets[0]
        self.assertEqual(texture_set.name, "SpeedLoader")
        self.assertEqual(sorted(texture_set.files), ["ao", "bc", "mg", "nrm"])

    def test_composite_ao_maps_are_ignored(self):
        make_texture_set(self.folder, "rock", {"_bc": (1, 1, 1)})
        write_png(os.path.join(self.folder, "rock_bc_ao.png"), (1, 1, 1))
        write_png(os.path.join(self.folder, "cliff_hm_ao_gloss.png"), (1, 1, 1))
        result = scanner.scan_folder(self.folder, self.presets["rust_standard"])
        names = sorted(os.path.basename(p) for p in result.ignored)
        self.assertEqual(names, ["cliff_hm_ao_gloss.png", "rock_bc_ao.png"])
        self.assertEqual([s.name for s in result.sets], ["rock"])
        self.assertNotIn("ao", result.sets[0].files)

    def test_mg_gloss_drives_roughness(self):
        make_texture_set(self.folder, "crate", RUST_STANDARD)
        preset = self.presets["rust_standard"]
        texture_set = scanner.scan_folder(self.folder, preset).sets[0]
        material = bpy.data.materials.new("crate")
        builder.build_material(material, texture_set, preset)
        self.assertEqual(bpy.data.images["crate_mg.png"].alpha_mode, "CHANNEL_PACKED")
        group = nodegroup.find_group("rust_standard")
        bsdf = next(n for n in group.nodes if n.type == "BSDF_PRINCIPLED")
        roughness = bsdf.inputs["Roughness"].links[0].from_node
        self.assertEqual(roughness.label, "Gloss to Roughness")

    def test_sg_set_uses_the_converter(self):
        make_texture_set(self.folder, "skin", {"_bc": (90, 60, 40), "_sg": (20, 20, 20, 160), "_nrm": (128, 128, 255)})
        preset = self.presets["rust_standard_specular"]
        texture_set = scanner.scan_folder(self.folder, preset).sets[0]
        builder.build_material(bpy.data.materials.new("skin"), texture_set, preset)
        group = nodegroup.find_group("rust_standard_specular")
        converters = [n for n in group.nodes if n.bl_idname == "ShaderNodeGroup"]
        self.assertEqual(len(converters), 1)
        self.assertEqual(converters[0].node_tree.name, nodegroup.SPECGLOSS_NAME)
        bsdf = next(n for n in group.nodes if n.type == "BSDF_PRINCIPLED")
        self.assertEqual(bsdf.inputs["Metallic"].links[0].from_node, converters[0])
        self.assertEqual(bpy.data.images["skin_bc.png"].colorspace_settings.name, "sRGB")
        self.assertEqual(bpy.data.images["skin_sg.png"].colorspace_settings.name, "sRGB")


class GlossCurveTest(unittest.TestCase):
    def tearDown(self):
        for group in list(bpy.data.node_groups):
            bpy.data.node_groups.remove(group)

    def chain(self, curve):
        data = {
            "schema": 1, "id": f"curve_{curve.lower()}", "name": f"Curve {curve}", "gloss_curve": curve,
            "slots": [{"id": "mg", "suffixes": ["mg"], "channels": {"R": "metallic", "A": "gloss"}}],
        }
        group = nodegroup.ensure_group(presets.preset_from_dict(data))
        bsdf = next(n for n in group.nodes if n.type == "BSDF_PRINCIPLED")
        node = bsdf.inputs["Roughness"].links[0].from_node
        ops = []  # math operations from the BSDF back towards the gloss input
        while node is not None and node.bl_idname == "ShaderNodeMath":
            ops.append(node.operation)
            linked = [s.links[0].from_node for s in node.inputs if s.is_linked]
            node = linked[0] if linked else None
        return ops

    def test_curves(self):
        self.assertEqual(self.chain("LINEAR"), ["SUBTRACT"])
        self.assertEqual(self.chain("SQUARED"), ["POWER", "SUBTRACT"])
        self.assertEqual(self.chain("SQRT"), ["SUBTRACT", "SQRT"])
