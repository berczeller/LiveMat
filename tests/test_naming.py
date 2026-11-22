import unittest

from livemat.core import naming


class ParseFilenameTest(unittest.TestCase):
    def test_rejects_non_images(self):
        self.assertIsNone(naming.parse_filename("crate_BaseColor.spp"))
        self.assertIsNone(naming.parse_filename("notes.txt"))

    def test_plain_name(self):
        parsed = naming.parse_filename("Crate_BaseColor.PNG")
        self.assertEqual(parsed.base, "Crate_BaseColor")
        self.assertIsNone(parsed.udim)

    def test_udim_with_dot(self):
        parsed = naming.parse_filename("crate_BaseColor.1003.png")
        self.assertEqual((parsed.base, parsed.udim), ("crate_BaseColor", 1003))

    def test_underscore_1024_is_a_resolution(self):
        parsed = naming.parse_filename("crate_nrm_1024.tga")
        self.assertEqual((parsed.base, parsed.udim, parsed.resolution), ("crate_nrm", None, "1024"))

    def test_resolution_tag(self):
        parsed = naming.parse_filename("crate_Normal_4K.png")
        self.assertEqual((parsed.base, parsed.resolution), ("crate_Normal", "4k"))


class SplitSuffixTest(unittest.TestCase):
    def test_longest_alias_wins(self):
        result = naming.split_map_suffix("rock_mixed_AO", ["ao", "mixed_ao"])
        self.assertEqual(result, ("rock", "mixed_ao"))

    def test_separators_are_interchangeable(self):
        self.assertEqual(naming.split_map_suffix("rock-base color", ["base_color"]), ("rock", "base_color"))

    def test_needs_a_separator(self):
        # "_n" must not match the end of "iron".
        self.assertIsNone(naming.split_map_suffix("iron", ["n"]))

    def test_needs_a_set_name(self):
        self.assertIsNone(naming.split_map_suffix("_normal", ["normal"]))

    def test_resolution_before_suffix(self):
        self.assertEqual(naming.split_map_suffix("rock_2k_normal", ["normal"]), ("rock", "normal"))

    def test_keeps_original_case(self):
        self.assertEqual(naming.split_map_suffix("Big_Rock_Normal", ["normal"])[0], "Big_Rock")


class AssetKeyTest(unittest.TestCase):
    def test_engine_prefixes_and_duplicates(self):
        for name in ("T_Crate", "M_Crate", "MI_Crate", "crate", "Crate.001"):
            self.assertEqual(naming.asset_key(name), "crate", name)

    def test_short_names_keep_their_letters(self):
        self.assertEqual(naming.asset_key("M_"), "m")
