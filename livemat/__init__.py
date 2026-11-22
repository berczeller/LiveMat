# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

from . import operators, props, registry, ui

# Registered in this order, unregistered in reverse.
_modules = (props, operators, ui)


def register():
    registry.reload()
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
