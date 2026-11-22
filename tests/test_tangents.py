"""Unity tangents must agree with Blender's normal mapping wherever the two bases are the same.

On a flat plane the per-vertex and per-pixel bitangents are identical, so the
Unity path has to produce exactly the normal Blender's Normal Map node does,
and both have to match the hand-computed answer.
"""

import math
import os
import tempfile
import unittest

import bpy

from livemat.build import nodegroup, tangents
from tests.fixtures import write_png

PIXEL = (200, 90, 220)
TURN = 0.7  # plane rotation around Z, so tangents aren't axis aligned


def expected_normal():
    x, y, z = (v / 255 * 2 - 1 for v in PIXEL)
    length = math.sqrt(x * x + y * y + z * z)
    x, y, z = x / length, y / length, z / length
    t = (math.cos(TURN), math.sin(TURN), 0.0)
    b = (-math.sin(TURN), math.cos(TURN), 0.0)
    return tuple(x * t[i] + y * b[i] + z * (0.0, 0.0, 1.0)[i] for i in range(3))


class UnityNormalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 1
        scene.cycles.use_denoising = False
        scene.render.resolution_x = scene.render.resolution_y = 2
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.world.color = (0, 0, 0)

        bpy.ops.mesh.primitive_plane_add(size=2)
        cls.plane = bpy.context.active_object
        cls.plane.rotation_euler = (0, 0, TURN)
        bpy.ops.object.camera_add(location=(0, 0, 3))
        camera = bpy.context.active_object
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = 1.0
        scene.camera = camera
        tangents.write_bitangents(cls.plane.data)

        # A probe group: normal map color in, both world normals out.
        group = bpy.data.node_groups.new("Normal Probe", "ShaderNodeTree")
        group.interface.new_socket("Color", in_out="INPUT", socket_type="NodeSocketColor")
        for name in ("Unity", "Blender"):
            group.interface.new_socket(name, in_out="OUTPUT", socket_type="NodeSocketVector")
        graph = nodegroup._Graph(group)
        group_in = graph.new("NodeGroupInput", 0)
        group_out = graph.new("NodeGroupOutput", 8)
        strength = graph.new("ShaderNodeValue", 0)
        strength.outputs[0].default_value = 1.0
        unity = nodegroup._unity_normal(graph, group_in.outputs["Color"], strength.outputs[0])
        blender = graph.new("ShaderNodeNormalMap", 5)
        group.links.new(group_in.outputs["Color"], blender.inputs["Color"])
        group.links.new(unity, group_out.inputs["Unity"])
        group.links.new(blender.outputs["Normal"], group_out.inputs["Blender"])

        cls.material = bpy.data.materials.new("probe")
        cls.plane.data.materials.append(cls.material)
        tree = cls.material.node_tree
        tree.nodes.clear()
        image = tree.nodes.new("ShaderNodeTexImage")
        image.image = bpy.data.images.load(str(write_png(os.path.join(cls._tmp.name, "n.png"), PIXEL)))
        image.image.colorspace_settings.name = "Non-Color"
        cls.probe = tree.nodes.new("ShaderNodeGroup")
        cls.probe.node_tree = group
        tree.links.new(image.outputs["Color"], cls.probe.inputs["Color"])
        cls.emission = tree.nodes.new("ShaderNodeEmission")
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(cls.emission.outputs[0], output.inputs["Surface"])

    @classmethod
    def tearDownClass(cls):
        for collection in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.node_groups, bpy.data.images):
            for block in list(collection):
                collection.remove(block)
        cls._tmp.cleanup()

    def render(self, output):
        tree = self.material.node_tree
        for link in list(self.emission.inputs["Color"].links):
            tree.links.remove(link)
        tree.links.new(self.probe.outputs[output], self.emission.inputs["Color"])
        path = os.path.join(self._tmp.name, f"{output}.exr")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(path)
        pixel = tuple(image.pixels[:3])
        bpy.data.images.remove(image)
        return pixel

    def test_unity_matches_blender_on_a_flat_plane(self):
        want = expected_normal()
        for output in ("Blender", "Unity"):
            with self.subTest(output):
                for got, expected in zip(self.render(output), want):
                    self.assertAlmostEqual(got, expected, places=3)
