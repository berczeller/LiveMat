# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

import os

import bpy
import bpy.utils.previews

from . import registry
from .operators import plural
from .build import material as builder
from .build import nodegroup

SEMANTIC_NAMES = {
    "base_color": "Base Color",
    "diffuse": "Diffuse",
    "specular": "Specular",
    "emission": "Emission",
    "normal": "Normal",
    "metallic": "Metallic",
    "roughness": "Roughness",
    "gloss": "Gloss",
    "ao": "AO",
    "alpha": "Alpha",
    "height": "Height",
}

# Thumbnails for files that aren't loaded as images yet (scan results).
_file_previews = None


def channel_summary(slot):
    """'R Metallic  A Gloss' for packed slots, 'Base Color' for plain ones."""
    if slot.semantic("RGB"):
        return SEMANTIC_NAMES[slot.semantic("RGB")]
    return "  ".join(f"{channel} {SEMANTIC_NAMES[semantic]}" for channel, semantic in slot.channels)


def file_icon(path):
    if _file_previews is None or not path or not os.path.isfile(path):
        return 0
    preview = _file_previews.get(path) or _file_previews.load(path, path, "IMAGE")
    return preview.icon_id


def builtin_icon(name):
    """The numeric id of a built-in icon, for calls that only take icon_value."""
    return bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items[name].value


def active_material(context):
    material = getattr(context, "material", None)
    if material is None and context.object is not None:
        material = context.object.active_material
    return material


def draw_material(layout, material):
    """The material inspector: preset, one row per slot with a thumbnail, then parameters."""
    if material is None:
        layout.label(text="No active material", icon="INFO")
        return
    preset = registry.get(material.get("livemat_preset", ""))
    if preset is None:
        layout.label(text=f"{material.name} isn't built by LiveMat", icon="INFO")
        return

    row = layout.row(align=True)
    row.context_pointer_set("material", material)
    row.menu("LIVEMAT_MT_switch_preset", text=preset.name, icon="PRESET")

    nodes = builder.livemat_texture_nodes(material)
    for slot in preset.slots:
        node = nodes.get(slot.id)
        image = node.image if node is not None else None
        box = layout.box()
        split = box.split(factor=0.28)
        thumb = split.column()
        icon = layout.icon(image) if image is not None else builtin_icon("IMAGE_DATA")
        thumb.template_icon(icon_value=icon, scale=3.0)

        info = split.column(align=True)
        info.label(text=slot.label)
        summary = channel_summary(slot)
        if summary != slot.label:
            sub = info.row()
            sub.enabled = False
            sub.label(text=summary)
        row = info.row(align=True)
        row.label(text=image.name if image else "None", icon="FILE_IMAGE" if image else "BLANK1")
        op = row.operator("livemat.load_slot", text="", icon="FILEBROWSER")
        op.material, op.slot = material.name, slot.id
        if image is not None:
            op = row.operator("livemat.clear_slot", text="", icon="X")
            op.material, op.slot = material.name, slot.id

    group_node = builder.livemat_group_node(material)
    if group_node is not None:
        col = layout.column(align=True)
        for name, *_rest in nodegroup.PARAMETERS:
            socket = group_node.inputs.get(name)
            if socket is not None and not socket.is_linked:
                col.prop(socket, "default_value", text=name)


class LIVEMAT_MT_switch_preset(bpy.types.Menu):
    bl_label = "Switch Preset"

    def draw(self, context):
        material = getattr(context, "material", None)
        if material is None:
            return
        current = material.get("livemat_preset")
        for preset in registry.all_presets().values():
            op = self.layout.operator(
                "livemat.switch_preset",
                text=preset.name,
                icon="CHECKMARK" if preset.id == current else "BLANK1",
            )
            op.material = material.name
            op.preset = preset.id


class LIVEMAT_UL_sets(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _property):
        row = layout.row(align=True)
        row.prop(item, "include", text="")
        row.label(text=item.name)
        if item.material:
            row.label(text=item.material.name, icon="MATERIAL")
        else:
            sub = row.row()
            sub.enabled = False
            sub.label(text="New", icon="ADD")


class _Sidebar:
    bl_region_type = "UI"
    bl_category = "LiveMat"


class _MainPanel(_Sidebar):
    bl_label = "LiveMat"

    def draw(self, context):
        layout = self.layout
        props = context.scene.livemat

        col = layout.column(align=True)
        col.prop(props, "folder", text="")
        col.prop(props, "preset", text="")
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("livemat.scan", icon="FILE_REFRESH")

        if not props.sets:
            if props.scanned_folder:
                layout.label(text="No texture sets found", icon="INFO")
            return

        layout.template_list("LIVEMAT_UL_sets", "", props, "sets", props, "active_set", rows=4)
        if props.scanned_preset != props.preset:
            layout.label(text="Preset changed, scan again", icon="ERROR")
        if props.ignored or props.unmatched:
            info = layout.row()
            info.enabled = False
            info.label(text=f"{props.unmatched} unrecognized, {props.ignored} ignored files")

        if 0 <= props.active_set < len(props.sets):
            self.draw_set(layout, props, props.active_set)

        row = layout.row(align=True)
        row.scale_y = 1.3
        count = sum(1 for item in props.sets if item.include)
        row.operator("livemat.build", text=f"Build {plural(count, 'Material')}", icon="MATERIAL")

    @staticmethod
    def draw_set(layout, props, index):
        item = props.sets[index]
        preset = registry.get(props.scanned_preset)
        box = layout.box()
        box.prop(item, "material", text="")
        col = box.column(align=True)
        files = {entry.slot: entry for entry in item.files}
        for slot in preset.slots if preset else ():
            entry = files.get(slot.id)
            row = col.row()
            if entry is None:
                row.enabled = False
                row.label(text=f"{slot.label}: none", icon="BLANK1")
            else:
                name = os.path.basename(entry.path)
                row.label(text=f"{slot.label}: {name}", icon_value=file_icon(entry.path))
        if item.duplicates:
            box.label(text=f"Skipped {plural(item.duplicates, 'duplicate file')}", icon="INFO")
        row = box.row(align=True)
        row.operator("livemat.build", text="Build", icon="MATERIAL").index = index
        row.operator("livemat.assign", text="Assign to Selected", icon="RESTRICT_SELECT_OFF").index = index


class _OptionsPanel(_Sidebar):
    bl_label = "Options"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.livemat
        col = layout.column()
        col.prop(props, "recursive")
        col.prop(props, "create_missing")
        col.prop(props, "rebuild")
        layout.operator(
            "livemat.authoring_view",
            text="Restore View" if props.authoring_view else "Match Authoring View",
            icon="RESTRICT_VIEW_OFF",
            depress=props.authoring_view,
        )


class _MaterialPanel(_Sidebar):
    bl_label = "Material"

    def draw(self, context):
        draw_material(self.layout, active_material(context))


def _sidebar_panels(space, prefix, poll=None):
    """The same three sidebar panels for one editor."""
    main = type(f"LIVEMAT_PT_{prefix}", (_MainPanel, bpy.types.Panel), {"bl_space_type": space})
    children = []
    for name, base in (("material", _MaterialPanel), ("options", _OptionsPanel)):
        children.append(
            type(
                f"LIVEMAT_PT_{prefix}_{name}",
                (base, bpy.types.Panel),
                {"bl_space_type": space, "bl_parent_id": main.__name__},
            )
        )
    if poll is not None:
        for cls in (main, *children):
            cls.poll = classmethod(poll)
    return (main, *children)


def _is_shader_editor(_cls, context):
    # The node editor also hosts geometry and compositor trees.
    return getattr(context.space_data, "tree_type", "") == "ShaderNodeTree"


class LIVEMAT_PT_material(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"
    bl_label = "LiveMat"

    @classmethod
    def poll(cls, context):
        return getattr(context, "material", None) is not None

    def draw(self, context):
        draw_material(self.layout, context.material)


_classes = (
    LIVEMAT_MT_switch_preset,
    LIVEMAT_UL_sets,
    *_sidebar_panels("VIEW_3D", "view3d"),
    *_sidebar_panels("NODE_EDITOR", "shader_editor", _is_shader_editor),
    LIVEMAT_PT_material,
)

_register_classes, _unregister_classes = bpy.utils.register_classes_factory(_classes)


def register():
    global _file_previews
    _file_previews = bpy.utils.previews.new()
    _register_classes()


def unregister():
    global _file_previews
    _unregister_classes()
    bpy.utils.previews.remove(_file_previews)
    _file_previews = None
