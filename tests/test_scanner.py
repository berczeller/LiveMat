import os
import tempfile
import unittest

from livemat.core import presets, scanner
from tests.fixtures import METAL_ROUGH, make_texture_set, write_png


class ScannerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name
        self.presets = presets.load_builtin_presets()

    def tearDown(self):
        self._tmp.cleanup()

    def scan(self, preset_id, **kwargs):
        return scanner.scan_folder(self.folder, self.presets[preset_id], **kwargs)

    def test_groups_maps_into_sets(self):
        make_texture_set(self.folder, "Crate", METAL_ROUGH)
        make_texture_set(self.folder, "Barrel", METAL_ROUGH)
        result = self.scan("default_metal_rough")
        self.assertEqual([s.name for s in result.sets], ["Barrel", "Crate"])
        self.assertEqual(
            sorted(result.sets[1].files), ["base_color", "metallic", "normal", "roughness"]
        )
        self.assertEqual(result.unmatched, [])

    def test_reports_unmatched_images(self):
        write_png(os.path.join(self.folder, "readme_banner.png"), (0, 0, 0))
        result = self.scan("default_metal_rough")
        self.assertEqual(len(result.unmatched), 1)

    def test_unreal_prefix_and_short_suffixes(self):
        make_texture_set(self.folder, "T_Crate", {"_BC": (1, 1, 1), "_ORM": (1, 1, 1), "_N": (1, 1, 1)})
        result = self.scan("unreal_packed")
        self.assertEqual(len(result.sets), 1)
        self.assertEqual(result.sets[0].key, "crate")
        self.assertEqual(sorted(result.sets[0].files), ["base_color", "normal", "orm"])

    def test_shallowest_file_wins(self):
        deep = os.path.join(self.folder, "old")
        write_png(os.path.join(deep, "crate_Normal.png"), (1, 1, 1))
        top = write_png(os.path.join(self.folder, "crate_Normal.png"), (1, 1, 1))
        texture_set = self.scan("default_metal_rough").sets[0]
        self.assertEqual(texture_set.files["normal"], str(top))
        self.assertEqual(len(texture_set.duplicates["normal"]), 1)

    def test_non_recursive_skips_subfolders(self):
        write_png(os.path.join(self.folder, "sub", "crate_Normal.png"), (1, 1, 1))
        self.assertEqual(self.scan("default_metal_rough", recursive=False).sets, [])

    def test_udim_tiles_form_one_slot(self):
        for tile in (1001, 1002):
            write_png(os.path.join(self.folder, f"crate_BaseColor.{tile}.png"), (1, 1, 1))
        texture_set = self.scan("default_metal_rough").sets[0]
        self.assertIn("base_color", texture_set.udim_slots)
        self.assertTrue(texture_set.files["base_color"].endswith("1001.png"))
