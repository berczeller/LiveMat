# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""The Blend tab. Sections follow the work: pick a channel, manage its layers,
fill or randomize selections, find edges by angle, keep selections, export."""

import bpy

from .. import icons
from . import data, export
from .ops import current_view

CHANNEL_NAMES = {"R": "Red", "G": "Green", "B": "Blue", "A": "Alpha"}


class LIVEMAT_UL_blend_layers(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _property):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", emboss=False, icon="HIDE_OFF" if item.visible else "HIDE_ON")
        kind_icon = {"FILL": "SNAP_FACE", "PAINT": "BRUSH_DATA", "GENERATOR": "MOD_SMOOTH"}[item.kind]
        row.prop(item, "name", text="", emboss=False, icon=kind_icon)
        sub = row.row(align=True)
        sub.ui_units_x = 4.6
        sub.prop(item, "blend_mode", text="")


class LIVEMAT_UL_blend_sets(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _property):
        row = layout.row(align=True)
        row.prop(item, "pick", text="")
        icon = {"VERT": "VERTEXSEL", "EDGE": "EDGESEL", "FACE": "FACESEL"}[item.domain]
        row.prop(item, "name", text="", emboss=False, icon=icon)
        count = row.row()
        count.enabled = False
        count.label(text=str(item.count))


def draw_layer_settings(layout, context, mesh, layer):
    """Settings of the active layer, depending on its kind."""
    col = layout.column(align=True)
    col.prop(layer, "opacity", slider=True)
    if layer.kind == "PAINT":
        col.prop(layer, "paint_value", slider=True)
        row = layout.row(align=True)
        row.scale_y = 1.3
        if mesh.livemat_blend.painting == layer.uid:
            row.active_default = True
            row.operator("livemat.blend_paint_done", icon="CHECKMARK")
            hint = layout.row()
            hint.enabled = False
            hint.label(text="Paint white to apply, black to remove", icon="INFO")
        else:
            row.operator("livemat.blend_paint", icon="BRUSH_DATA")
    elif layer.kind == "GENERATOR":
        col = layout.column(align=True)
        col.prop(layer, "generator", text="")
        if layer.generator in {"AO", "THICKNESS"}:
            col.prop(layer, "distance")
            col.prop(layer, "samples")
            if layer.generator == "AO":
                col.prop(layer, "only_local")
        elif layer.generator == "CURVATURE":
            col.prop(layer, "samples")
        else:
            col.row(align=True).prop(layer, "edge_kind", expand=True)
        row = layout.row(align=True)
        row.prop(layer, "low", slider=True)
        row.prop(layer, "high", slider=True)
        row.prop(layer, "invert", text="", icon="ARROW_LEFTRIGHT", toggle=True)
        row = layout.row(align=True)
        row.scale_y = 1.3
        if not layer.baked:
            row.active_default = True
        row.operator("livemat.blend_bake", text="Rebake" if layer.baked else "Bake", icon="RENDER_STILL")


def draw(layout, context, section, end_section):
    """Draw the Blend tab with the shared section helpers from the main UI."""
    obj = context.object
    if obj is None or obj.type != "MESH":
        layout.label(text="Select a mesh to paint its Blend mask", icon="INFO")
        return
    mesh = obj.data
    state = mesh.livemat_blend
    tool = context.scene.livemat_blend_tool
    editing = context.mode == "EDIT_MESH"

    if mesh.color_attributes.get(data.FINAL) is None:
        body = section(layout, "Blend Mask", "blend")
        body.label(text=f"{mesh.name} has no Blend mask yet")
        row = body.row()
        row.scale_y = 1.4
        row.active_default = True
        row.operator("livemat.blend_start", icon="ADD")
        end_section(body)
        return

    # Channel, view and layers
    body = section(layout, "Channel", "blend")
    row = body.row(align=True)
    row.scale_y = 1.3
    row.prop(state, "channel", expand=True, icon_only=True)
    view = current_view(context, mesh)
    row = body.row(align=True)
    for mode, label, icon in (("MATERIAL", "Material", "MATERIAL"), ("COLORS", "Mask", "COLOR"), ("CHANNEL", "Channel", "IMAGE_ALPHA")):
        row.operator("livemat.blend_view", text=label, icon=icon, depress=view == mode).mode = mode

    channel = state.channel
    index = data.CHANNELS.index(channel)
    body.separator(factor=0.5)
    header = body.row(align=True)
    header.label(text=f"{CHANNEL_NAMES[channel]} Layers", icon_value=icons.get("layers"))
    row = body.row()
    row.template_list(
        "LIVEMAT_UL_blend_layers", channel, state, f"layers_{channel.lower()}", state, f"active_{channel.lower()}", rows=3
    )
    side = row.column(align=True)
    side.menu("LIVEMAT_MT_blend_add_layer", text="", icon="ADD")
    side.operator("livemat.blend_layer_remove", text="", icon="REMOVE")
    side.separator()
    side.operator("livemat.blend_layer_move", text="", icon="TRIA_UP").direction = "UP"
    side.operator("livemat.blend_layer_move", text="", icon="TRIA_DOWN").direction = "DOWN"
    layers = data.layers_of(state, channel)
    active = getattr(state, f"active_{channel.lower()}")
    col = body.column(align=True)
    if 0 <= active < len(layers):
        draw_layer_settings(body, context, mesh, layers[active])
    col = body.column(align=True)
    col.prop(state, "base", index=index, text="Base", slider=True)
    end_section(body)

    # Fill
    body = section(layout, "Fill", "fill")
    if not editing:
        hint = body.row()
        hint.enabled = False
        hint.label(text="Select vertices, edges or faces in Edit Mode", icon="EDITMODE_HLT")
    col = body.column()
    col.enabled = editing
    row = col.row(align=True)
    row.prop(tool, "value", slider=True)
    sub = row.row(align=True)
    sub.ui_units_x = 2.6
    sub.label(text=f"{round(tool.value * 255)}")
    row = col.row(align=True)
    row.scale_y = 1.2
    row.operator("livemat.blend_fill", text="Set", icon="BRUSH_DATA").action = "SET"
    row.operator("livemat.blend_fill", text="Erase", icon="X").action = "ERASE"
    row.operator("livemat.blend_fill", text="Clear", icon="GHOST_DISABLED").action = "CLEAR"
    col.separator(factor=0.6)
    col.row(align=True).prop(tool, "random_per", expand=True)
    row = col.row(align=True)
    row.prop(tool, "random_min", slider=True)
    row.prop(tool, "random_max", slider=True)
    row = col.row(align=True)
    row.prop(tool, "use_seed", toggle=True, icon="LOCKED" if tool.use_seed else "UNLOCKED")
    sub = row.row(align=True)
    sub.enabled = tool.use_seed
    sub.prop(tool, "seed", text="")
    row = col.row(align=True)
    row.scale_y = 1.2
    row.operator("livemat.blend_fill", text="Randomize", icon="RNDCURVE").action = "RANDOMIZE"
    col.prop(tool, "smooth")
    end_section(body)

    # Edge angle
    body = section(layout, "Edge Angle", "angle")
    col = body.column()
    col.enabled = editing
    col.row(align=True).prop(tool, "angle_kind", expand=True)
    row = col.row(align=True)
    row.prop(tool, "angle_min")
    row.prop(tool, "angle_max")
    col.prop(tool, "angle_open")
    row = col.row(align=True)
    for target, label, icon in (("EDGE", "Edges", "EDGESEL"), ("VERT", "Verts", "VERTEXSEL"), ("FACE", "Faces", "FACESEL")):
        row.operator("livemat.blend_select_angle", text=label, icon=icon).target = target
    end_section(body)

    # Saved selections
    body = section(layout, "Selections", "selection")
    row = body.row()
    row.template_list("LIVEMAT_UL_blend_sets", "", state, "sets", state, "active_set", rows=3)
    side = row.column(align=True)
    add = side.row(align=True)
    add.enabled = editing
    add.operator("livemat.blend_set_add", text="", icon="ADD")
    side.operator("livemat.blend_set_remove", text="", icon="REMOVE")
    if len(state.sets):
        row = body.row(align=True)
        row.enabled = editing
        row.prop(tool, "combine", text="")
        row.operator("livemat.blend_set_combine", text="Combine Ticked", icon="SELECT_EXTEND")
        if editing:
            hint = body.row()
            hint.enabled = False
            hint.label(text="Click a selection to select it again", icon="INFO")
    end_section(body)

    # Export
    body = section(layout, "Export", "export")
    problems = export.issues(mesh)
    if problems:
        for problem in problems:
            row = body.row()
            row.alert = True
            row.label(text=problem, icon="ERROR")
        body.operator("livemat.blend_move_first", icon="SORT_DESC")
    else:
        row = body.row()
        row.enabled = False
        row.label(text="Exported as vertex color set 1", icon="CHECKMARK")
    body.operator("livemat.blend_check", icon="EXPORT")
    end_section(body)


register, unregister = bpy.utils.register_classes_factory((LIVEMAT_UL_blend_layers, LIVEMAT_UL_blend_sets))
