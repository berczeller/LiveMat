import copy
import unittest

from livemat.core import presets

VALID = {
    "schema": 1,
    "id": "test",
    "name": "Test",
    "slots": [
        {"id": "base", "suffixes": ["bc"], "channels": {"RGB": "base_color"}},
        {"id": "mg", "suffixes": ["mg"], "channels": {"R": "metallic", "A": "gloss"}},
    ],
}


def variant(**changes):
    data = copy.deepcopy(VALID)
    data.update(changes)
    return data


class BuiltinPresetTest(unittest.TestCase):
    def test_all_builtins_load(self):
        loaded = presets.load_builtin_presets()
        self.assertEqual(
            list(loaded),
            [
                "default_metal_rough",
                "default_specular",
                "unity_standard",
                "unity_standard_specular",
                "unity_mask_map",
                "unreal",
                "unreal_packed",
                "rust_standard",
                "rust_standard_specular",
            ],
        )
        for preset in loaded.values():
            self.assertTrue(preset.builtin)

    def test_unreal_uses_directx(self):
        loaded = presets.load_builtin_presets()
        self.assertEqual(loaded["unreal"].normal_format, "DIRECTX")
        self.assertEqual(loaded["default_metal_rough"].normal_format, "OPENGL")


class ValidationTest(unittest.TestCase):
    def test_valid_preset(self):
        preset = presets.preset_from_dict(VALID)
        mg = preset.slot("mg")
        self.assertEqual(mg.colorspace, "Non-Color")
        self.assertTrue(mg.alpha_is_data)
        self.assertEqual(preset.slot("base").colorspace, "sRGB")
        self.assertEqual(preset.slot("base").label, "Base")

    def test_defaults_follow_channels(self):
        mg = presets.preset_from_dict(VALID).slot("mg")
        self.assertEqual(mg.default_color(), (0.0, 0.0, 0.0, 1.0))
        self.assertEqual(mg.default_alpha(), 0.5)

    def test_single_channel_default_is_gray(self):
        height = presets.load_builtin_presets()["default_metal_rough"].slot("height")
        self.assertEqual(height.default_color(), (0.5, 0.5, 0.5, 1.0))

    def test_fingerprint_changes_with_content(self):
        a = presets.preset_from_dict(VALID)
        b = presets.preset_from_dict(variant(normal_format="DIRECTX"))
        self.assertNotEqual(a.fingerprint, b.fingerprint)

    def assertRejects(self, data, fragment):
        with self.assertRaises(presets.PresetError) as caught:
            presets.preset_from_dict(data)
        self.assertIn(fragment, str(caught.exception))

    def test_rejects_wrong_schema(self):
        self.assertRejects(variant(schema=2), "schema")

    def test_rejects_semantic_from_two_slots(self):
        slots = VALID["slots"] + [{"id": "m", "suffixes": ["m"], "channels": {"R": "metallic"}}]
        self.assertRejects(variant(slots=slots), "more than one slot")

    def test_rejects_shared_suffix(self):
        slots = VALID["slots"] + [{"id": "x", "suffixes": ["BC"], "channels": {"R": "ao"}}]
        self.assertRejects(variant(slots=slots), "suffix")

    def test_rejects_color_from_single_channel(self):
        slots = [{"id": "c", "suffixes": ["c"], "channels": {"R": "base_color"}}]
        self.assertRejects(variant(slots=slots), "can't be read")

    def test_rejects_rgb_mixed_with_single_channels(self):
        slots = [{"id": "c", "suffixes": ["c"], "channels": {"RGB": "base_color", "R": "ao"}}]
        self.assertRejects(variant(slots=slots), "mixes RGB")

    def test_rejects_mixed_workflows(self):
        slots = VALID["slots"] + [{"id": "s", "suffixes": ["s"], "channels": {"RGB": "specular"}}]
        self.assertRejects(variant(slots=slots), "mixes spec/gloss")

    def test_specular_preset_flag(self):
        loaded = presets.load_builtin_presets()
        self.assertTrue(loaded["rust_standard_specular"].is_specular)
        self.assertFalse(loaded["rust_standard"].is_specular)

    def test_rejects_unknown_gloss_curve(self):
        self.assertRejects(variant(gloss_curve="CUBIC"), "gloss_curve")

    def test_rejects_repeated_label(self):
        slots = [
            {"id": "a", "label": "Map", "suffixes": ["a"], "channels": {"R": "ao"}},
            {"id": "b", "label": "Map", "suffixes": ["b"], "channels": {"R": "metallic"}},
        ]
        self.assertRejects(variant(slots=slots), "label")
