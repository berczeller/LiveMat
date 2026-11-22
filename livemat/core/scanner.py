# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Folder scanning: group texture files into sets using a preset's suffixes."""

import os
from dataclasses import dataclass, field

from . import naming


@dataclass
class TextureSet:
    name: str  # display name, original case: "Crate_Wood"
    key: str  # matching key: "crate_wood"
    files: dict = field(default_factory=dict)  # slot id -> path (first tile for UDIMs)
    udim_slots: set = field(default_factory=set)
    duplicates: dict = field(default_factory=dict)  # slot id -> paths that lost to `files`


@dataclass
class ScanResult:
    sets: list
    ignored: list  # files matched by the preset's ignore list
    unmatched: list  # images no slot recognized


def scan_folder(folder, preset, *, recursive=True):
    aliases = {naming.normalize(s): slot.id for slot in preset.slots for s in slot.suffixes}
    candidates = {}  # set key -> {"name": str, "slots": {slot id: [(depth, path, udim)]}}
    ignored, unmatched = [], []

    for root, dirs, files in os.walk(folder):
        dirs.sort()
        depth = os.path.relpath(root, folder).count(os.sep) + (root != folder)
        for filename in sorted(files):
            path = os.path.join(root, filename)
            parsed = naming.parse_filename(filename)
            if parsed is None:
                continue
            if naming.ends_with_any(parsed.base, preset.ignore):
                ignored.append(path)
                continue
            split = naming.split_map_suffix(parsed.base, aliases)
            if split is None:
                unmatched.append(path)
                continue

            set_name, alias = split
            slot_id = aliases[alias]
            entry = candidates.setdefault(naming.asset_key(set_name), {"name": set_name, "slots": {}})
            entry["slots"].setdefault(slot_id, []).append((depth, path, parsed.udim))

        if not recursive:
            break

    sets = [_resolve(key, entry) for key, entry in sorted(candidates.items())]
    return ScanResult(sets=sets, ignored=ignored, unmatched=unmatched)


def _resolve(key, entry):
    texture_set = TextureSet(name=entry["name"], key=key)
    for slot_id, found in entry["slots"].items():
        tiles = sorted((udim, path) for _, path, udim in found if udim is not None)
        if tiles:
            # Blender finds the other tiles from the first one's name.
            texture_set.files[slot_id] = tiles[0][1]
            texture_set.udim_slots.add(slot_id)
            losers = [path for _, path, udim in found if udim is None]
        else:
            # Shallowest folder wins, then the shortest path.
            ranked = sorted(found, key=lambda item: (item[0], len(item[1]), item[1]))
            texture_set.files[slot_id] = ranked[0][1]
            losers = [path for _, path, _ in ranked[1:]]
        if losers:
            texture_set.duplicates[slot_id] = losers
    return texture_set
