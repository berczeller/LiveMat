# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""LiveMat panels. One set of draw functions feeds the 3D Viewport sidebar,
the Shader Editor sidebar and Material Properties."""

import bpy

from . import icons, registry, templates, thumbs, watch
from .blend import ui as blend_ui
from .build import material as builder
from .build import nodegroup, tangents
from .operators import plural

SEMANTIC_NAMES = {
    "base_color": "Base Color",
    "diffuse": "Diffuse",
    "specular": "Specular",
    "emission": "Emission",
    "normal": "Normal",
    "detail_normal": "Detail Normal",
    "metallic": "Metallic",
    "roughness": "Roughness",
    "gloss": "Smoothness",
    "ao": "Occlusion",
    "alpha": "Alpha",
    "height": "Height",
}

# Sliders shown under the slot that holds each semantic, like Unity's inspector.
SLOT_PARAMETERS = {
    "base_color": ((nodegroup.BASE_TINT, "Tint"),),
    "diffuse": ((nodegroup.BASE_TINT, "Tint"),),
    "metallic": ((nodegroup.METALLIC_STRENGTH, "Metallic"),),
    "gloss": ((nodegroup.SMOOTHNESS_STRENGTH, "Smoothness"),),
    "normal": ((nodegroup.NORMAL_STRENGTH, "Strength"),),
    "detail_normal": ((nodegroup.DETAIL_STRENGTH, "Strength"),),
    "ao": ((nodegroup.AO_STRENGTH, "Strength"),),
    "height": ((nodegroup.HEIGHT_STRENGTH, "Strength"),),
    "emission": ((nodegroup.EMISSION_STRENGTH, "Intensity"),),
}

TITLE_GAP = 0.6  # separator factor around section titles and box edges
SECTION_END_GAP = 0.6  # separator factor under each section's last row
THUMB_SCALE = 3.4  # slot thumbnail size, in UI units
PICKER_SCALE = 6.0  # thumbnail size inside the picker grid


def section(layout, title, icon):
    """A box with a colored icon and title. Returns the column to draw into."""
    box = layout.box()
    box.separator(factor=TITLE_GAP)
    row = box.row(align=True)
    row.separator(factor=TITLE_GAP)  # keep the icon off the box edge
    row.label(text=title, icon_value=icons.get(icon))
    inner = box.row()
    inner.separator(factor=TITLE_GAP)
    body = inner.column()
    inner.separator(factor=TITLE_GAP)
    return body


def end_section(body):
    body.separator(factor=SECTION_END_GAP)


def main_button(layout):
    """A row for the section's main action, in the theme's accent color like Blender's dialogs."""
    row = layout.row(align=True)
    row.scale_y = 1.4
    row.active_default = True
    return row


def active_material(context):
    material = getattr(context, "material", None)
    if material is None and context.object is not None:
        material = context.object.active_material
    return material


# Source and texture sets


def draw_source(layout, props):
    body = section(layout, "Source", "source")
    col = body.column(align=True)
    col.prop(props, "folder", text="")
    row = col.row(align=True)
    # Red until a preset is picked, so the empty choice can't be missed.
    row.alert = props.preset == registry.NONE
    row.prop(props, "preset", text="")

    body.separator(factor=0.5)
    main_button(body).operator("livemat.scan", icon="VIEWZOOM")

    row = body.row(align=True)
    row.prop(props, "recursive", text="Subfolders", toggle=True, icon="FILE_FOLDER")
    row.prop(props, "create_missing", text="Create", toggle=True, icon="ADD")
    row.prop(props, "rebuild", text="Rebuild", toggle=True, icon="TRASH")
    stale = watch.stale_count()
    row = body.row(align=True)
    refresh_button = row.row(align=True)
    # Point at Refresh when exports changed textures Blender still shows the old version of.
    refresh_button.active_default = bool(stale) and not props.auto_reload
    refresh_button.operator("livemat.refresh", icon="FILE_REFRESH")
    row.prop(props, "auto_reload", text="Auto", toggle=True, icon="TIME")
    row.operator(
        "livemat.authoring_view",
        text="Neutral View",
        icon="HIDE_OFF",
        depress=props.authoring_view,
    )
    if stale and not props.auto_reload:
        hint = body.row()
        hint.alert = True
        hint.label(text=f"{plural(stale, 'texture')} changed on disk", icon="ERROR")
    end_section(body)


def draw_sets(layout, props):
    if not props.sets:
        if props.scanned_folder:
            body = section(layout, "Texture Sets", "sets")
            body.label(text="No texture sets found", icon="INFO")
            end_section(body)
        return

    body = section(layout, "Texture Sets", "sets")
    body.template_list("LIVEMAT_UL_sets", "", props, "sets", props, "active_set", rows=4)
    if props.scanned_preset != props.preset:
        body.label(text="Preset changed, scan again", icon="ERROR")
    if props.ignored or props.unmatched:
        info = body.row()
        info.enabled = False
        info.label(text=f"{props.unmatched} unrecognized, {props.ignored} ignored files")

    if 0 <= props.active_set < len(props.sets):
        draw_set(body, props, props.active_set)

    body.separator(factor=0.5)
    count = sum(1 for item in props.sets if item.include)
    main_button(body).operator("livemat.build", text=f"Build {plural(count, 'Material')}", icon="MATERIAL")
    end_section(body)


def draw_set(layout, props, index):
    item = props.sets[index]
    preset = registry.get(props.scanned_preset)
    col = layout.column()
    col.prop(item, "material", text="")
    built_with = registry.get(item.material.get("livemat_preset", "")) if item.material else None
    if built_with is not None:
        # Its textures show in the Material panel; repeating them here is noise.
        info = col.row()
        info.enabled = False
        info.label(text=f"Built with {built_with.name}", icon="CHECKMARK")
    elif preset is not None:
        # Not built yet: a preview of what the build will load.
        files = {entry.slot: entry.path for entry in item.files}
        grid = col.grid_flow(row_major=True, columns=4, even_columns=True, align=True)
        for slot in preset.slots:
            if slot.id in files:
                cell = grid.column(align=True)
                cell.template_icon(icon_value=thumbs.file_icon(files[slot.id]), scale=2.4)
                label = cell.row()
                label.alignment = "CENTER"
                label.label(text=slot.label)
    if item.duplicates:
        col.label(text=f"Skipped {plural(item.duplicates, 'duplicate file')}", icon="INFO")
    row = col.row(align=True)
    row.operator("livemat.build", text="Build", icon="MATERIAL").index = index
    row.operator("livemat.assign", text="Assign to Selected", icon="RESTRICT_SELECT_OFF").index = index


# Material inspector


def draw_material(layout, material):
    """The material inspector: preset, one card per slot, then normal settings."""
    if material is None:
        layout.label(text="No active material", icon="INFO")
        return
    preset = registry.get(material.get("livemat_preset", ""))
    if preset is None:
        layout.label(text=f"{material.name} isn't built by LiveMat", icon="INFO")
        return

    row = layout.row(align=True)
    row.label(text=material.name, icon="MATERIAL")
    sub = row.row(align=True)
    sub.context_pointer_set("material", material)
    sub.menu("LIVEMAT_MT_switch_preset", text=preset.name, icon="PRESET")

    state = getattr(material, "livemat", None)
    items = {item.slot: item for item in state.slots} if state else {}
    nodes = builder.livemat_texture_nodes(material)
    group_node = builder.livemat_group_node(material)

    body = section(layout, "Textures", "textures")
    for index, slot in enumerate(preset.slots):
        if index:
            body.separator(factor=0.8)
        draw_slot(body, material, slot, nodes.get(slot.id), items.get(slot.id), group_node)
    if not items:
        hint = body.row()
        hint.enabled = False
        hint.label(text="Press Refresh to enable the texture picker", icon="INFO")
    end_section(body)

    if state is not None:
        body = section(layout, "Normals", "normals")
        row = body.split(factor=0.34)
        row.label(text="Baked For")
        row.prop(state, "tangents", text="")
        hint = body.row()
        hint.enabled = False
        per_vertex = state.tangents in tangents.PER_VERTEX
        hint.label(text="Per-vertex bitangent" if per_vertex else "Per-pixel bitangent", icon="INFO")
        end_section(body)


def draw_slot(layout, material, slot, node, item, group_node):
    image = node.image if node is not None else None
    split = layout.split(factor=0.34)

    thumb = split.column()
    if item is not None:
        # Click the thumbnail to pick a texture, like Unity's object picker.
        thumb.template_icon_view(item, "texture", show_labels=True, scale=THUMB_SCALE, scale_popup=PICKER_SCALE)
    else:
        thumb.template_icon(icon_value=layout.icon(image) if image is not None else 0, scale=THUMB_SCALE)

    info = split.column(align=True)
    row = info.row(align=True)
    row.label(text=slot.label)
    op = row.operator("livemat.load_slot", text="", icon="FILEBROWSER", emboss=False)
    op.material, op.slot = material.name, slot.id
    if image is not None:
        op = row.operator("livemat.clear_slot", text="", icon="X", emboss=False)
        op.material, op.slot = material.name, slot.id

    name = info.row()
    name.enabled = False
    # The file name, not the datablock name (which can carry a .001 suffix).
    shown = bpy.path.basename(image.filepath) if image is not None and image.filepath else None
    name.label(text=shown or (image.name if image is not None else "None"))

    if not slot.semantic("RGB"):
        # One channel: the slot name already says what it holds. Packed maps
        # name each channel so you know which dropdown routes which value.
        single = len(slot.channels) == 1
        for channel, semantic in slot.channels:
            row = info.row(align=True)
            row.label(text="Active Channel" if single else SEMANTIC_NAMES[semantic])
            if item is not None:
                sub = row.row(align=True)
                sub.ui_units_x = 2.2
                sub.prop(item, f"src_{channel}", text="", icon_only=True)
            else:
                row.label(text="", icon_value=icons.get(f"channel_{channel.lower()}"))

    if group_node is None:
        return
    col = layout.column(align=True)
    for semantic in slot.semantics:
        for socket_name, label in SLOT_PARAMETERS.get(semantic, ()):
            socket = group_node.inputs.get(socket_name)
            if socket is None or socket.is_linked:
                continue
            if socket_name == nodegroup.BASE_TINT:
                # Same column as the slot name, label above the color field.
                row = col.split(factor=0.34)
                row.column()
                tint = row.column(align=True)
                tint.label(text=label)
                tint.prop(socket, "default_value", text="")
            else:
                col.prop(socket, "default_value", text=label, slider=True)
    if slot.id == "detail_normal" and image is not None:
        mapping = builder.detail_mapping(material)
        if mapping is not None:
            row = col.row(align=True)
            row.prop(mapping.inputs["Scale"], "default_value", index=0, text="Tiling X")
            row.prop(mapping.inputs["Scale"], "default_value", index=1, text="Y")


class LIVEMAT_MT_switch_preset(bpy.types.Menu):
    bl_label = "Switch Preset"

    def draw(self, context):
        material = getattr(context, "material", None)
        if material is None:
            return
        current = material.get("livemat_preset")
        for preset in registry.sorted_presets():
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


# Panels

# Side tabs, like Zen UV: an icon column on the left picks the section on the right.
TABS = (
    ("BUILD", "Build", "Build materials from texture folders", "build"),
    ("BLEND", "Blend", "Paint RGBA blend masks the engine reads as vertex colors", "blend"),
    ("TEMPLATES", "Templates", "Your own presets. Coming in a later version", "templates"),
)
_tab_items = []  # kept alive: Blender doesn't copy enum item strings


def _tabs(_self, _context):
    _tab_items[:] = [(key, label, tip, icons.get(icon), number) for number, (key, label, tip, icon) in enumerate(TABS)]
    return _tab_items


class _Sidebar:
    bl_region_type = "UI"
    bl_category = "LiveMat"


class _MainPanel(_Sidebar):
    bl_label = "LiveMat"

    def draw_header(self, _context):
        self.layout.label(icon_value=icons.get("livemat"))

    def draw(self, context):
        wm = context.window_manager
        row = self.layout.row()
        tabs = row.column(align=True)
        tabs.ui_units_x = 1.6
        tabs.scale_y = 1.4
        for key, _label, _tip, icon in TABS:
            tabs.prop_enum(wm, "livemat_tab", key, text="", icon_value=icons.get(icon))
        content = row.column()
        if wm.livemat_tab == "BLEND":
            blend_ui.draw(content, context, section, end_section)
        elif wm.livemat_tab == "TEMPLATES":
            templates.draw(content, section, end_section)
        else:
            props = context.scene.livemat
            draw_source(content, props)
            draw_sets(content, props)
            draw_material(content, active_material(context))


def _sidebar_panels(space, prefix, poll=None):
    """The tabbed LiveMat panel for one editor."""
    main = type(f"LIVEMAT_PT_{prefix}", (_MainPanel, bpy.types.Panel), {"bl_space_type": space})
    if poll is not None:
        main.poll = classmethod(poll)
    return (main,)


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

    def draw_header(self, _context):
        self.layout.label(icon_value=icons.get("livemat"))

    def draw(self, context):
        draw_material(self.layout, context.material)


_register_classes, _unregister_classes = bpy.utils.register_classes_factory(
    (
        LIVEMAT_MT_switch_preset,
        LIVEMAT_UL_sets,
        *_sidebar_panels("VIEW_3D", "view3d"),
        *_sidebar_panels("NODE_EDITOR", "shader_editor", _is_shader_editor),
        LIVEMAT_PT_material,
    )
)


def register():
    # Which tab is open is a view choice: on the window manager, so it isn't saved or undone.
    bpy.types.WindowManager.livemat_tab = bpy.props.EnumProperty(name="LiveMat Section", items=_tabs, default=0)
    _register_classes()


def unregister():
    _unregister_classes()
    del bpy.types.WindowManager.livemat_tab
