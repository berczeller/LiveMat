# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Texture file name parsing.

Names are compared in a normalized form: lowercase, with every separator
(`_`, `-`, `.`, space) turned into `_`. Normalizing keeps the string length,
so positions found in the normalized name can slice the original one and
keep its case for display.
"""

import os
import re
from dataclasses import dataclass

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr", ".bmp", ".webp", ".hdr"}
)

_SEPARATORS = re.compile(r"[-. ]")

# `.1001` is the usual UDIM form. `_1001` also counts, except `_1024`, which is
# far more often a resolution tag than tile 1024.
_UDIM = re.compile(r"(?:\.(1\d{3})|_(1\d{3}))$")

_RESOLUTION = re.compile(r"_(\d{1,2}k|256|512|1024|2048|4096|8192)$")

# Prefixes engines put on asset names (T_Crate, M_Crate, MI_Crate).
_ASSET_PREFIXES = ("mi_", "mat_", "m_", "t_")

# Blender's duplicate suffix: Crate.001
_BLENDER_DUPLICATE = re.compile(r"\.\d{3}$")


def normalize(text):
    return _SEPARATORS.sub("_", text.lower())


@dataclass(frozen=True)
class ParsedName:
    """A texture file name with UDIM and resolution tags split off."""

    stem: str
    base: str
    udim: int | None = None
    resolution: str | None = None


def parse_filename(filename):
    """Return a ParsedName, or None when the file isn't a supported image."""
    stem, ext = os.path.splitext(os.path.basename(filename))
    if ext.lower() not in IMAGE_EXTENSIONS or not stem:
        return None

    base = stem
    udim = None
    match = _UDIM.search(base)
    if match and match.group(0) != "_1024":
        udim = int(match.group(1) or match.group(2))
        base = base[: match.start()]

    base, resolution = _strip_resolution(base)
    return ParsedName(stem=stem, base=base, udim=udim, resolution=resolution)


def _strip_resolution(text):
    match = _RESOLUTION.search(normalize(text))
    if not match:
        return text, None
    return text[: match.start()], match.group(1)


def split_map_suffix(base, aliases):
    """Split `crate_BaseColor` into (`crate`, `basecolor`) using the longest matching alias.

    Aliases are given without a leading separator. Returns None when no alias
    matches or nothing would be left for the set name.
    """
    norm = normalize(base)
    for alias in sorted({normalize(a) for a in aliases}, key=len, reverse=True):
        if norm.endswith("_" + alias):
            set_name = base[: len(base) - len(alias) - 1]
            set_name, _ = _strip_resolution(set_name)
            if set_name.strip("_-. "):
                return set_name, alias
    return None


def ends_with_any(base, patterns):
    norm = normalize(base)
    return any(norm.endswith("_" + normalize(p)) for p in patterns)


def asset_key(name):
    """Key used to match a texture set to a material: `T_Crate` and `M_Crate.001` both give `crate`."""
    key = normalize(_BLENDER_DUPLICATE.sub("", name)).strip("_")
    for prefix in _ASSET_PREFIXES:
        if key.startswith(prefix) and len(key) > len(prefix):
            key = key[len(prefix):]
            break
    return key
