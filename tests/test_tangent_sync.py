"""Per-vertex bitangents stay current on their own: new objects, edits, no Refresh needed."""

import bpy

from livemat import tangent_sync
from livemat.build import material as builder
from livemat.build import nodegroup, tangents
from tests.fixtures import METAL_ROUGH, make_texture_set
from tests.test_operators import OperatorTestBase


def bitangents(mesh):
    return [tuple(round(v, 4) for v in item.vector) for item in mesh.attributes[nodegroup.BITANGENT_ATTRIBUTE].data]


class TangentSyncTest(OperatorTestBase):
    def setUp(self):
        super().setUp()
        tangent_sync._forget()
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.mesh.primitive_cube_add()
        self.cube = bpy.context.active_object
        self.cube.select_set(True)
        bpy.ops.livemat.scan()
        bpy.ops.livemat.assign(index=0)
        self.material = self.cube.active_material
        self.material.livemat.tangents = "UNITY"
        self.settle()

    def settle(self):
        """Let the depsgraph report changes, then run the pending pass."""
        bpy.context.view_layer.update()
        return tangent_sync.process_now()

    def test_new_object_gets_bitangents(self):
        bpy.ops.mesh.primitive_uv_sphere_add()
        sphere = bpy.context.active_object
        sphere.data.materials.append(self.material)
        self.assertIn(sphere.data.name, self.settle())
        self.assertIn(nodegroup.BITANGENT_ATTRIBUTE, sphere.data.attributes)

    def test_geometry_edit_rewrites(self):
        mesh = self.cube.data
        before = bitangents(mesh)
        # Rotate the UVs of the whole cube a quarter turn: tangents and bitangents change.
        for item in mesh.uv_layers.active.data:
            u, v = item.uv
            item.uv = (v, 1.0 - u)
        mesh.update()
        self.assertIn(mesh.name, self.settle())
        self.assertNotEqual(bitangents(mesh), before)

    def test_moving_an_object_does_not_rewrite(self):
        self.cube.location.x += 3.0
        self.assertEqual(self.settle(), [])

    def test_edit_mode_waits_for_object_mode(self):
        bpy.context.view_layer.objects.active = self.cube
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.transform.resize(value=(2.0, 1.0, 1.0))
        self.assertEqual(self.settle(), [])
        bpy.ops.object.mode_set(mode="OBJECT")
        self.assertIn(self.cube.data.name, self.settle())

    def test_per_pixel_material_is_left_alone(self):
        self.material.livemat.tangents = "UNREAL"
        bpy.ops.mesh.primitive_uv_sphere_add()
        sphere = bpy.context.active_object
        sphere.data.materials.append(self.material)
        self.assertEqual(self.settle(), [])
        self.assertNotIn(nodegroup.BITANGENT_ATTRIBUTE, sphere.data.attributes)


class TangentTargetTest(OperatorTestBase):
    def test_targets_pick_the_bitangent_method(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.livemat.build()
        material = bpy.data.materials["Crate"]
        socket = lambda: builder.livemat_group_node(material).inputs[nodegroup.UNITY_TANGENTS].default_value
        for target, expected in (("UNREAL", 0.0), ("XNORMAL", 1.0), ("UNITY_HDRP", 0.0), ("UNITY", 1.0), ("BLENDER", 0.0)):
            material.livemat.tangents = target
            self.assertEqual(socket(), expected, target)
            self.assertEqual(tangents.per_vertex(material), bool(expected), target)
