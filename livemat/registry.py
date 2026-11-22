# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""The presets the add-on offers, loaded once and shared by properties, operators and panels."""

import zlib

from .core import presets as _presets

_loaded = {}
# Blender reads enum item strings from Python without copying them, so the
# list has to stay alive between calls instead of being rebuilt each time.
_enum_items = []


def reload():
    _loaded.clear()
    _loaded.update(_presets.load_builtin_presets())
    # Blender saves the item number, not the id, so the number must not depend
    # on the order of the presets: adding one would change saved choices.
    _enum_items[:] = [(p.id, p.name, p.description, enum_number(p.id)) for p in _loaded.values()]
    numbers = [item[3] for item in _enum_items]
    if len(set(numbers)) != len(numbers):
        raise RuntimeError("Two preset ids hash to the same number; rename one of them")


def enum_number(preset_id):
    return zlib.crc32(preset_id.encode()) & 0x7FFFFFFF


def all_presets():
    if not _loaded:
        reload()
    return _loaded


def get(preset_id):
    return all_presets().get(preset_id)


def enum_items(_self=None, _context=None):
    all_presets()
    return _enum_items
