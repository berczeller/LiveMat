import os
import time

import bpy

from livemat import watch
from livemat.build import material as builder
from tests.fixtures import METAL_ROUGH, make_texture_set, write_png
from tests.test_operators import OperatorTestBase


class RefreshTestBase(OperatorTestBase):
    def setUp(self):
        super().setUp()
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        bpy.ops.livemat.build()
        self.material = bpy.data.materials["Crate"]

    def slots(self):
        return builder.livemat_texture_nodes(self.material)

    def base_color_red(self):
        return round(self.slots()["base_color"].image.pixels[0], 3)

    def repaint_base_color(self, value):
        path = os.path.join(self.folder, "Crate_BaseColor.png")
        write_png(path, value)
        later = time.time() + 5  # make sure the timestamp moves even on coarse file systems
        os.utime(path, (later, later))


class RefreshTest(RefreshTestBase):
    def test_reloads_changed_textures(self):
        before = self.base_color_red()
        self.repaint_base_color((20, 120, 60))
        bpy.ops.livemat.refresh()
        self.assertNotEqual(self.base_color_red(), before)

    def test_adds_new_maps(self):
        write_png(os.path.join(self.folder, "Crate_AO.png"), (200,))
        bpy.ops.livemat.refresh()
        self.assertIn("ao", self.slots())

    def test_cleared_slot_stays_empty(self):
        bpy.ops.livemat.clear_slot(material="Crate", slot="metallic")
        bpy.ops.livemat.refresh()
        self.assertNotIn("metallic", self.slots())

    def test_hand_picked_texture_is_kept(self):
        other = write_png(os.path.join(self.folder, "elsewhere", "Rusty.png"), (90, 40, 20))
        bpy.ops.livemat.load_slot(material="Crate", slot="base_color", filepath=str(other))
        bpy.ops.livemat.refresh()
        self.assertEqual(self.slots()["base_color"].image.name, "Rusty.png")

    def test_build_forgets_cleared_slots(self):
        bpy.ops.livemat.clear_slot(material="Crate", slot="metallic")
        bpy.ops.livemat.build()
        self.assertIn("metallic", self.slots())


class AutoReloadTest(RefreshTestBase):
    def setUp(self):
        super().setUp()
        watch._forget()
        self.scene = bpy.context.scene

    def tearDown(self):
        self.props.auto_reload = False
        watch._forget()
        super().tearDown()

    def test_off_does_nothing(self):
        self.props.auto_reload = False
        watch.check(self.scene)
        self.repaint_base_color((20, 120, 60))
        self.assertEqual(watch.check(self.scene), [])
        self.assertEqual(watch.check(self.scene), [])

    def test_reloads_after_change_settles(self):
        self.props.auto_reload = True
        before = self.base_color_red()
        self.assertEqual(watch.check(self.scene), [])  # first pass only records stamps
        self.repaint_base_color((20, 120, 60))
        self.assertEqual(watch.check(self.scene), [])  # change seen, waiting for it to settle
        self.assertEqual(watch.check(self.scene), ["Crate_BaseColor.png"])
        self.assertNotEqual(self.base_color_red(), before)
        self.assertEqual(watch.check(self.scene), [])
