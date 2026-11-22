"""Check the spec/gloss conversion group numerically against the reference formula.

Each case renders a flat emission plane through Cycles, which evaluates the
node group exactly, then compares the pixel with a plain Python version of
the Khronos conversion.
"""

import math
import os
import tempfile
import unittest

import bpy

from livemat.build import nodegroup

F0 = 0.04


def reference(diffuse, specular):
    """Khronos spec/gloss to metal/rough, linear colors in, (base color, metallic) out."""

    def brightness(c):
        return math.sqrt(0.299 * c[0] ** 2 + 0.587 * c[1] ** 2 + 0.114 * c[2] ** 2)

    one_minus_spec = 1 - max(specular)
    d, s = brightness(diffuse), brightness(specular)
    if s < F0:
        metallic = 0.0
    else:
        b = d * one_minus_spec / (1 - F0) + s - 2 * F0
        c = F0 - s
        metallic = (-b + math.sqrt(max(b * b - 4 * F0 * c, 0.0))) / (2 * F0)
        metallic = min(max(metallic, 0.0), 1.0)
    from_diffuse = [x * one_minus_spec / (1 - F0) / max(1 - metallic, 1e-4) for x in diffuse]
    from_specular = [(x - F0 * (1 - metallic)) / max(metallic, 1e-4) for x in specular]
    t = metallic * metallic
    base = [min(max(a + (b - a) * t, 0.0), 1.0) for a, b in zip(from_diffuse, from_specular)]
    return base, metallic


CASES = {
    "plastic": ((0.6, 0.1, 0.1), (0.04, 0.04, 0.04)),
    "dark_rubber": ((0.02, 0.02, 0.02), (0.03, 0.03, 0.03)),
    "gold": ((0.0, 0.0, 0.0), (1.0, 0.77, 0.33)),
    "iron": ((0.0, 0.0, 0.0), (0.56, 0.57, 0.58)),
    "half_metal": ((0.25, 0.25, 0.25), (0.3, 0.3, 0.3)),
}


class SpecGlossConversionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        scene = bpy.context.scene
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 1
        scene.cycles.use_denoising = False
        scene.render.resolution_x = scene.render.resolution_y = 2
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.world.color = (0, 0, 0)

        bpy.ops.mesh.primitive_plane_add(size=4)
        cls.plane = bpy.context.active_object
        bpy.ops.object.camera_add(location=(0, 0, 3))
        camera = bpy.context.active_object
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = 1
        scene.camera = camera

        cls.material = bpy.data.materials.new("probe")
        cls.plane.data.materials.append(cls.material)
        tree = cls.material.node_tree
        tree.nodes.clear()
        cls.convert = tree.nodes.new("ShaderNodeGroup")
        cls.convert.node_tree = nodegroup.ensure_specgloss_group()
        cls.emission = tree.nodes.new("ShaderNodeEmission")
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(cls.emission.outputs[0], output.inputs["Surface"])

    @classmethod
    def tearDownClass(cls):
        bpy.data.objects.remove(cls.plane)
        bpy.data.materials.remove(cls.material)
        cls._tmp.cleanup()

    def evaluate(self, output_name):
        tree = self.material.node_tree
        for link in list(self.emission.inputs["Color"].links):
            tree.links.remove(link)
        tree.links.new(self.convert.outputs[output_name], self.emission.inputs["Color"])
        path = os.path.join(self._tmp.name, "probe.exr")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(path)
        pixel = tuple(image.pixels[:3])
        bpy.data.images.remove(image)
        return pixel

    def test_matches_reference(self):
        for name, (diffuse, specular) in CASES.items():
            with self.subTest(name):
                self.convert.inputs["Diffuse"].default_value = (*diffuse, 1)
                self.convert.inputs["Specular"].default_value = (*specular, 1)
                base, metallic = reference(diffuse, specular)
                got_base = self.evaluate("Base Color")
                got_metallic = self.evaluate("Metallic")[0]
                self.assertAlmostEqual(got_metallic, metallic, places=3)
                for got, want in zip(got_base, base):
                    self.assertAlmostEqual(got, want, places=3)

    def test_reference_extremes(self):
        # Sanity checks on the formula itself: dielectrics stay dielectric, pure metals become metal.
        base, metallic = reference((0.6, 0.1, 0.1), (0.04, 0.04, 0.04))
        self.assertEqual(metallic, 0.0)
        self.assertAlmostEqual(base[0], 0.6, places=4)
        base, metallic = reference((0, 0, 0), (1.0, 0.77, 0.33))
        self.assertAlmostEqual(metallic, 1.0, places=4)
        self.assertAlmostEqual(base[1], 0.77, places=4)
