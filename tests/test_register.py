import unittest

import bpy

import livemat

PANELS = ("LIVEMAT_PT_view3d", "LIVEMAT_PT_shader_editor", "LIVEMAT_PT_material", "LIVEMAT_OT_scan")


class RegisterTest(unittest.TestCase):
    def test_register_and_unregister(self):
        livemat.register()
        try:
            for name in PANELS:
                self.assertTrue(hasattr(bpy.types, name), name)
        finally:
            livemat.unregister()

        for name in PANELS:
            self.assertFalse(hasattr(bpy.types, name), name)

    def test_register_twice_in_a_row(self):
        # Reloading scripts disables and re-enables the add-on.
        for _ in range(2):
            livemat.register()
            livemat.unregister()
