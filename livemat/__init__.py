# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

from . import icons, operators, props, registry, thumbs, ui, watch

# Registered in this order, unregistered in reverse.
_modules = (icons, thumbs, props, operators, ui, watch)


def register():
    registry.reload()
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
