# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

from . import blend, icons, operators, props, registry, tangent_sync, thumbs, ui, watch

# Registered in this order, unregistered in reverse.
_modules = (icons, thumbs, props, operators, blend, ui, watch, tangent_sync)


def register():
    registry.reload()
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
