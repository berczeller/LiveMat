# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Preset files: what each texture is called, which channel holds what, and how to read it.

A preset is JSON:

    {
      "schema": 1,
      "id": "unreal_packed",
      "name": "Unreal Packed",
      "normal_format": "DIRECTX",
      "gloss_curve": "LINEAR",
      "ignore": [],
      "slots": [
        {"id": "orm", "label": "ORM", "suffixes": ["orm", "arm"],
         "channels": {"R": "ao", "G": "roughness", "B": "metallic"}}
      ]
    }

Each channel key is `RGB` (color and normal maps) or one of `R`, `G`, `B`, `A`.
Every semantic can come from only one slot, so there's never a question of
which file wins.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .naming import normalize

SCHEMA_VERSION = 1

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "presets"

# Semantic -> kind. "color" and "vector" read RGB, "value" reads one channel.
SEMANTICS = {
    "base_color": "color",
    "diffuse": "color",
    "specular": "color",
    "emission": "color",
    "normal": "vector",
    "metallic": "value",
    "roughness": "value",
    "gloss": "value",
    "ao": "value",
    "alpha": "value",
    "height": "value",
}

COLOR_SEMANTICS = frozenset(s for s, kind in SEMANTICS.items() if kind == "color")

# What a semantic reads as when its texture is missing.
SEMANTIC_DEFAULTS = {
    "base_color": (0.8, 0.8, 0.8),
    "diffuse": (0.8, 0.8, 0.8),
    "specular": (0.04, 0.04, 0.04),  # dielectric F0
    "emission": (0.0, 0.0, 0.0),
    "normal": (0.5, 0.5, 1.0),
    "metallic": 0.0,
    "roughness": 0.5,
    "gloss": 0.5,
    "ao": 1.0,
    "alpha": 1.0,
    "height": 0.5,
}

CHANNEL_KEYS = ("RGB", "R", "G", "B", "A")
NORMAL_FORMATS = ("OPENGL", "DIRECTX")
# How stored gloss turns into roughness: LINEAR 1 - g, SQUARED (1 - g)^2, SQRT 1 - sqrt(g).
GLOSS_CURVES = ("LINEAR", "SQUARED", "SQRT")

# Spec/gloss and metal/rough describe the same surface in different terms; a preset picks one.
SPECULAR_SEMANTICS = frozenset({"diffuse", "specular"})
METALLIC_SEMANTICS = frozenset({"base_color", "metallic"})
COLORSPACES = ("sRGB", "Non-Color")

_ID = re.compile(r"^[a-z0-9_]+$")


class PresetError(ValueError):
    pass


@dataclass(frozen=True)
class Slot:
    """One texture file in a preset, such as the ORM map."""

    id: str
    label: str
    suffixes: tuple
    channels: tuple  # ((channel key, semantic), ...) in CHANNEL_KEYS order
    colorspace: str

    def semantic(self, channel):
        return dict(self.channels).get(channel)

    @property
    def semantics(self):
        return tuple(s for _, s in self.channels)

    @property
    def uses_alpha(self):
        return self.semantic("A") is not None

    @property
    def alpha_is_data(self):
        """True when the alpha channel holds a map (gloss, metal) rather than transparency."""
        return self.uses_alpha and self.semantic("A") != "alpha"

    def default_color(self):
        """RGBA the slot reads as when no texture is loaded."""
        rgb = self.semantic("RGB")
        if rgb:
            r, g, b = SEMANTIC_DEFAULTS[rgb]
        else:
            r, g, b = (SEMANTIC_DEFAULTS.get(self.semantic(c), 0.0) for c in "RGB")
        return (r, g, b, 1.0)

    def default_alpha(self):
        semantic = self.semantic("A")
        return SEMANTIC_DEFAULTS[semantic] if semantic else 1.0


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    description: str
    normal_format: str
    gloss_curve: str
    ignore: tuple
    slots: tuple
    fingerprint: str
    builtin: bool = False

    def slot(self, slot_id):
        return next((s for s in self.slots if s.id == slot_id), None)

    def slot_for(self, semantic):
        return next((s for s in self.slots if semantic in s.semantics), None)

    @property
    def semantics(self):
        return {sem for slot in self.slots for sem in slot.semantics}

    @property
    def is_specular(self):
        return bool(self.semantics & SPECULAR_SEMANTICS)


def preset_from_dict(data, *, builtin=False):
    def fail(message):
        raise PresetError(f"preset {data.get('id', '?')!r}: {message}")

    if data.get("schema") != SCHEMA_VERSION:
        fail(f"unsupported schema {data.get('schema')!r}, expected {SCHEMA_VERSION}")

    preset_id = data.get("id", "")
    if not _ID.match(preset_id):
        fail("id must use lowercase letters, digits and underscores")

    name = data.get("name") or fail("name is missing")

    normal_format = data.get("normal_format", "OPENGL")
    if normal_format not in NORMAL_FORMATS:
        fail(f"normal_format must be one of {NORMAL_FORMATS}")

    gloss_curve = data.get("gloss_curve", "LINEAR")
    if gloss_curve not in GLOSS_CURVES:
        fail(f"gloss_curve must be one of {GLOSS_CURVES}")

    slots = []
    seen_slots, seen_semantics, seen_suffixes = set(), set(), {}
    for raw in data.get("slots") or fail("needs at least one slot"):
        slot_id = raw.get("id", "")
        if not _ID.match(slot_id) or slot_id in seen_slots:
            fail(f"slot id {slot_id!r} is invalid or repeated")
        seen_slots.add(slot_id)

        suffixes = tuple(raw.get("suffixes") or fail(f"slot {slot_id!r} has no suffixes"))
        for suffix in suffixes:
            key = normalize(suffix)
            if key in seen_suffixes:
                fail(f"suffix {suffix!r} is used by both {seen_suffixes[key]!r} and {slot_id!r}")
            seen_suffixes[key] = slot_id

        raw_channels = raw.get("channels") or fail(f"slot {slot_id!r} has no channels")
        if "RGB" in raw_channels and set(raw_channels) & {"R", "G", "B"}:
            fail(f"slot {slot_id!r} mixes RGB with single color channels")

        channels = []
        for key in CHANNEL_KEYS:
            semantic = raw_channels.get(key)
            if semantic is None:
                continue
            kind = SEMANTICS.get(semantic) or fail(f"unknown semantic {semantic!r}")
            if (key == "RGB") != (kind in ("color", "vector")):
                fail(f"{semantic!r} can't be read from channel {key}")
            if semantic in seen_semantics:
                fail(f"{semantic!r} comes from more than one slot")
            seen_semantics.add(semantic)
            channels.append((key, semantic))
        unknown = set(raw_channels) - set(CHANNEL_KEYS)
        if unknown:
            fail(f"slot {slot_id!r} has unknown channel keys {sorted(unknown)}")

        colorspace = raw.get("colorspace") or (
            "sRGB" if any(s in COLOR_SEMANTICS for _, s in channels) else "Non-Color"
        )
        if colorspace not in COLORSPACES:
            fail(f"colorspace must be one of {COLORSPACES}")

        label = raw.get("label") or slot_id.replace("_", " ").title()
        # Labels become node socket names, so they have to be unique.
        if any(s.label == label for s in slots):
            fail(f"slot label {label!r} is repeated")

        slots.append(
            Slot(
                id=slot_id,
                label=label,
                suffixes=suffixes,
                channels=tuple(channels),
                colorspace=colorspace,
            )
        )

    if seen_semantics & SPECULAR_SEMANTICS and seen_semantics & METALLIC_SEMANTICS:
        fail("mixes spec/gloss maps (diffuse, specular) with metal/rough ones (base_color, metallic)")

    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return Preset(
        id=preset_id,
        name=name,
        description=data.get("description", ""),
        normal_format=normal_format,
        gloss_curve=gloss_curve,
        ignore=tuple(data.get("ignore", ())),
        slots=tuple(slots),
        fingerprint=hashlib.sha1(canonical.encode()).hexdigest()[:12],
        builtin=builtin,
    )


def load_preset(path, *, builtin=False):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PresetError(f"{path.name}: {error}") from error
    return preset_from_dict(data, builtin=builtin)


def load_builtin_presets():
    """Built-in presets by id, in file name order."""
    presets = {}
    for path in sorted(BUILTIN_DIR.glob("*.json")):
        preset = load_preset(path, builtin=True)
        presets[preset.id] = preset
    return presets
