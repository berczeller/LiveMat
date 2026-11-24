# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Blend: per-channel RGBA masks on meshes, exported as vertex colors."""

from . import ops, props, ui

_modules = (props, ops, ui)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
