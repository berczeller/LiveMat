# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Templates tab: the editor for your own presets.

Not built yet. The tab exists so the editor can plug in without changing the
panel layout. Presets it creates will be JSON files in the same format as
livemat/presets, loaded by core.presets.load_preset next to the built-in ones.
"""


def draw(layout, section, end_section):
    body = section(layout, "Templates", "templates")
    col = body.column()
    col.enabled = False
    col.label(text="Make your own presets here")
    col.label(text="Coming in a later version", icon="TIME")
    end_section(body)
