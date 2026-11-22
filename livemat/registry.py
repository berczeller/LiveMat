# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""The presets the add-on offers, loaded once and shared by properties, operators and panels."""

from .core import presets as _presets

_loaded = {}
# Blender reads enum item strings from Python without copying them, so the
# list has to stay alive between calls instead of being rebuilt each time.
_enum_items = []


def reload():
    _loaded.clear()
    _loaded.update(_presets.load_builtin_presets())
    _enum_items[:] = [(p.id, p.name, p.description) for p in _loaded.values()]


def all_presets():
    if not _loaded:
        reload()
    return _loaded


def get(preset_id):
    return all_presets().get(preset_id)


def enum_items(_self=None, _context=None):
    all_presets()
    return _enum_items
