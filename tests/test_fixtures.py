import tempfile
import unittest

import bpy

from tests.fixtures import METAL_ROUGH, RUST_STANDARD, make_texture_set


class FixtureTest(unittest.TestCase):
    """Blender must read the synthetic PNGs with the expected channels and values."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        for image in list(bpy.data.images):
            bpy.data.images.remove(image)
        self._tmp.cleanup()

    def _load(self, path):
        image = bpy.data.images.load(str(path))
        image.colorspace_settings.name = "Non-Color"
        return image

    def test_metal_rough_set_loads(self):
        paths = make_texture_set(self.folder, "crate", METAL_ROUGH)
        for suffix, path in paths.items():
            image = self._load(path)
            self.assertEqual(tuple(image.size), (4, 4), suffix)

    def test_rust_gloss_survives_in_alpha(self):
        paths = make_texture_set(self.folder, "crate", RUST_STANDARD)
        image = self._load(paths["_mg"])
        red, alpha = image.pixels[0], image.pixels[3]
        self.assertAlmostEqual(red, 1.0, places=3)
        self.assertAlmostEqual(alpha, 191 / 255, places=3)
