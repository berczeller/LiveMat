# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""The Blend tab: a Vertex Blend / Mask Blend switch, the Blend material, the
mask of the current mode and its export. Secondary options live in popovers."""

import bpy

from .. import icons
from . import data, export
from .ops import current_view

LAYER_CHANNELS = ("R", "G", "B")


def _hint(layout, text, icon="INFO"):
    row = layout.row()
    row.enabled = False
    row.label(text=text, icon=icon)


def _chip(layout, channel):
    layout.label(text="", icon_value=icons.get(f"channel_{channel.lower()}"))


def _blend_material(obj):
    material = obj.active_material
    return material if material is not None and material.get("livemat_is_blend") else None


class LIVEMAT_UL_blend_layers(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _property):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", emboss=False, icon="HIDE_OFF" if item.visible else "HIDE_ON")
        kind_icon = {"FILL": "SNAP_FACE", "PAINT": "BRUSH_DATA", "GENERATOR": "MOD_SMOOTH"}[item.kind]
        row.prop(item, "name", text="", emboss=False, icon=kind_icon)
        sub = row.row(align=True)
        sub.ui_units_x = 3.4
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


# Popovers


class _Popover:
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"  # only shown when a layout opens it
    bl_ui_units_x = 11


class LIVEMAT_PT_blend_height(_Popover, bpy.types.Panel):
    bl_label = "Height Blend"

    def draw(self, context):
        setup = _blend_material(context.object).livemat_blend_material
        layout = self.layout
        layout.prop(setup, "use_height")
        col = layout.column(align=True)
        col.active = setup.use_height
        for channel in LAYER_CHANNELS:
            row = col.row(align=True)
            _chip(row, channel)
            row.prop(setup, f"factor_{channel.lower()}", slider=True)
            row.prop(setup, f"falloff_{channel.lower()}", slider=True)


class LIVEMAT_PT_blend_fill_options(_Popover, bpy.types.Panel):
    bl_label = "Polygon Fill"

    def draw(self, context):
        tool = context.scene.livemat_blend_tool
        col = self.layout.column()
        col.row(align=True).prop(tool, "fill_mode", expand=True)
        row = col.row(align=True)
        row.prop(tool, "hit_test", expand=True)
        col.prop(tool, "visible_only")


class LIVEMAT_PT_blend_random_options(_Popover, bpy.types.Panel):
    bl_label = "Randomize"

    def draw(self, context):
        tool = context.scene.livemat_blend_tool
        col = self.layout.column()
        col.row(align=True).prop(tool, "random_per", expand=True)
        row = col.row(align=True)
        row.prop(tool, "random_min", slider=True)
        row.prop(tool, "random_max", slider=True)
        row = col.row(align=True)
        row.prop(tool, "use_seed", text="Seed", toggle=True, icon="LOCKED" if tool.use_seed else "UNLOCKED")
        sub = row.row(align=True)
        sub.enabled = tool.use_seed
        sub.prop(tool, "seed", text="")
        col.prop(tool, "smooth")


class LIVEMAT_PT_blend_angle_options(_Popover, bpy.types.Panel):
    bl_label = "Edge Angle"

    def draw(self, context):
        tool = context.scene.livemat_blend_tool
        col = self.layout.column()
        col.row(align=True).prop(tool, "angle_kind", expand=True)
        row = col.row(align=True)
        row.prop(tool, "angle_min")
        row.prop(tool, "angle_max")
        col.prop(tool, "angle_open")


class LIVEMAT_PT_blend_export_options(_Popover, bpy.types.Panel):
    bl_label = "Mask Texture"

    def draw(self, context):
        from .texture import IMPORT_NOTES

        tool = context.scene.livemat_blend_tool
        col = self.layout.column()
        col.prop(tool, "export_preset", text="")
        col.row(align=True).prop(tool, "export_format", expand=True)
        col.prop(tool, "export_folder", text="")
        _hint(col, IMPORT_NOTES[tool.export_preset])


# Sections


def _draw_switch(layout, mode):
    row = layout.row(align=True)
    row.scale_y = 1.4
    row.operator("livemat.blend_mode", text="Vertex Blend", icon="VPAINT_HLT", depress=mode == "VERTEX").mode = "VERTEX"
    row.operator("livemat.blend_mode", text="Mask Blend", icon="TPAINT_HLT", depress=mode == "TEXTURE").mode = "TEXTURE"
    layout.separator(factor=0.6)


def _draw_materials(layout, material, section, end_section):
    body = section(layout, "Materials", "blend")
    if material is None:
        _hint(body, "Base, then R, G and B on top. A is AO")
        row = body.row()
        row.scale_y = 1.3
        row.operator("livemat.blend_material_create", icon="NODE_MATERIAL")
        end_section(body)
        return
    setup = material.livemat_blend_material
    col = body.column(align=True)
    row = col.row(align=True)
    row.label(text="", icon="SNAP_FACE")
    row.prop(setup, "base", text="")
    for channel in LAYER_CHANNELS:
        row = col.row(align=True)
        _chip(row, channel)
        row.prop(setup, f"layer_{channel.lower()}", text="")
    col = body.column(align=True)
    row = col.row(align=True)
    row.popover("LIVEMAT_PT_blend_height", text="Height Blend" if setup.use_height else "Linear Blend", icon="MOD_DISPLACE")
    row.operator("livemat.blend_material_rebuild", text="", icon="FILE_REFRESH")
    col.prop(setup, "ao_strength", text="AO Strength", slider=True)
    end_section(body)


def _draw_layer_settings(layout, mesh, layer):
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
            _hint(layout, "White adds, black removes")
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


def _draw_vertex(layout, context, mesh, section, end_section):
    state = mesh.livemat_blend
    tool = context.scene.livemat_blend_tool
    editing = context.mode == "EDIT_MESH"

    if mesh.color_attributes.get(data.FINAL) is None:
        body = section(layout, "Vertex Mask", "layers")
        _hint(body, f"{mesh.name} has no vertex mask yet")
        row = body.row()
        row.scale_y = 1.3
        row.active_default = True
        row.operator("livemat.blend_start", icon="ADD")
        end_section(body)
        return

    # Channel and its layers
    body = section(layout, "Vertex Mask", "layers")
    row = body.row(align=True)
    row.scale_y = 1.2
    row.prop(state, "channel", expand=True)
    row.separator()
    view = current_view(context, mesh)
    for mode, icon, tip in (("MATERIAL", "MATERIAL", "Material"), ("COLORS", "COLOR", "Mask"), ("CHANNEL", "IMAGE_ALPHA", "Channel")):
        row.operator("livemat.blend_view", text="", icon=icon, depress=view == mode).mode = mode

    channel = state.channel
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
    if 0 <= active < len(layers):
        _draw_layer_settings(body, mesh, layers[active])
    body.prop(state, "base", index=data.CHANNELS.index(channel), text="Empty Value", slider=True)
    end_section(body)

    # Painting values onto polygons
    body = section(layout, "Fill", "fill")
    row = body.row(align=True)
    row.prop(tool, "value", slider=True)
    sub = row.row(align=True)
    sub.ui_units_x = 2.2
    sub.alignment = "RIGHT"
    sub.label(text=f"{round(tool.value * 255)}")
    row = body.row(align=True)
    row.scale_y = 1.3
    row.operator("livemat.blend_polygon_fill", icon="RESTRICT_SELECT_OFF")
    row.popover("LIVEMAT_PT_blend_fill_options", text="", icon="PREFERENCES")
    if editing:
        row = body.row(align=True)
        row.operator("livemat.blend_fill", text="Set", icon="CHECKMARK").action = "SET"
        row.operator("livemat.blend_fill", text="Erase", icon="X").action = "ERASE"
        row.operator("livemat.blend_fill", text="Clear", icon="TRASH").action = "CLEAR"
        row = body.row(align=True)
        row.operator("livemat.blend_fill", text="Randomize", icon="RNDCURVE").action = "RANDOMIZE"
        row.popover("LIVEMAT_PT_blend_random_options", text="", icon="PREFERENCES")
    else:
        _hint(body, "More tools in Edit Mode", "EDITMODE_HLT")
    end_section(body)

    if editing:
        body = section(layout, "Selections", "selection")
        row = body.row(align=True)
        for target, icon in (("EDGE", "EDGESEL"), ("VERT", "VERTEXSEL"), ("FACE", "FACESEL")):
            row.operator("livemat.blend_select_angle", text="", icon=icon).target = target
        row.label(text="By Edge Angle")
        row.popover("LIVEMAT_PT_blend_angle_options", text="", icon="PREFERENCES")
        row = body.row()
        row.template_list("LIVEMAT_UL_blend_sets", "", state, "sets", state, "active_set", rows=3)
        side = row.column(align=True)
        side.operator("livemat.blend_set_add", text="", icon="ADD")
        side.operator("livemat.blend_set_remove", text="", icon="REMOVE")
        if len(state.sets):
            row = body.row(align=True)
            row.prop(tool, "combine", text="")
            row.operator("livemat.blend_set_combine", text="Combine Ticked", icon="SELECT_EXTEND")
        end_section(body)


def _draw_mask(layout, context, obj, material, section, end_section):
    body = section(layout, "Packed Mask", "layers")
    if material is None:
        _hint(body, "Create a Blend material to paint its mask")
        end_section(body)
        return
    setup = material.livemat_blend_material
    col = body.column()
    col.use_property_split = True
    col.use_property_decorate = False
    row = col.row(align=True)
    row.prop(setup, "mask_image", text="Mask")
    row.operator("livemat.blend_mask_new", text="", icon="ADD")
    col.prop(setup, "macro_normal", text="Normal")
    col.prop_search(setup, "uv_map", obj.data, "uv_layers", text="UV Map")
    col.prop(setup, "resolution", text="Size")

    body.separator(factor=0.5)
    row = body.row(align=True)
    row.scale_y = 1.3
    for channel in data.CHANNELS:
        row.operator(
            "livemat.blend_mask_paint",
            text="AO" if channel == "A" else channel,
            icon_value=icons.get(f"channel_{channel.lower()}"),
            depress=setup.painting == channel,
        ).channel = channel
    if setup.painting:
        row = body.row()
        row.scale_y = 1.3
        row.active_default = True
        row.operator("livemat.blend_mask_done", icon="CHECKMARK")
        _hint(body, "White adds, black removes")
    else:
        row = body.row()
        row.enabled = obj.data.color_attributes.get(data.FINAL) is not None
        row.operator("livemat.blend_mask_from_vertex", icon="VPAINT_HLT")
    end_section(body)


def _draw_export(layout, mesh, material, mode, tool, section, end_section):
    body = section(layout, "Export", "export")
    if mode == "VERTEX":
        problems = export.issues(mesh)
        for problem in problems:
            row = body.row()
            row.alert = True
            row.label(text=problem, icon="ERROR")
        if problems:
            body.operator("livemat.blend_move_first", icon="SORT_DESC")
        row = body.row(align=True)
        row.operator("livemat.blend_check", icon="EXPORT")
        if not problems and mesh.color_attributes.get(data.FINAL) is not None:
            row.label(text="", icon="CHECKMARK")
    if material is not None:
        row = body.row(align=True)
        row.operator("livemat.blend_mask_export", text="Export Mask Texture", icon="IMAGE_DATA")
        row.popover("LIVEMAT_PT_blend_export_options", text="", icon="PREFERENCES")
    end_section(body)


def draw(layout, context, section, end_section):
    """Draw the Blend tab with the shared section helpers from the main UI."""
    obj = context.object
    tool = context.scene.livemat_blend_tool
    if obj is None or obj.type != "MESH":
        _draw_switch(layout, tool.mode)
        _hint(layout, "Select a mesh")
        return
    material = _blend_material(obj)
    mode = material.livemat_blend_material.mask_source if material is not None else tool.mode

    _draw_switch(layout, mode)
    _draw_materials(layout, material, section, end_section)
    if mode == "VERTEX":
        _draw_vertex(layout, context, obj.data, section, end_section)
    else:
        _draw_mask(layout, context, obj, material, section, end_section)
    _draw_export(layout, obj.data, material, mode, tool, section, end_section)


register, unregister = bpy.utils.register_classes_factory(
    (
        LIVEMAT_UL_blend_layers,
        LIVEMAT_UL_blend_sets,
        LIVEMAT_PT_blend_height,
        LIVEMAT_PT_blend_fill_options,
        LIVEMAT_PT_blend_random_options,
        LIVEMAT_PT_blend_angle_options,
        LIVEMAT_PT_blend_export_options,
    )
)
