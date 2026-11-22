# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

import json
import os

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from . import registry
from .build import material as builder
from .core import naming, scanner

# Tried in order by Match Authoring View: a neutral tone map, then plain sRGB.
AUTHORING_TRANSFORMS = ("Khronos PBR Neutral", "Standard")
_SAVED_VIEW_KEYS = ("view_transform", "look", "exposure", "gamma", "use_curve_mapping")


def plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


class ScanError(Exception):
    pass


def scan(props):
    """Scan the scene's folder with its preset and refresh the set list.

    Choices made on a previous scan of the same folder and preset (included,
    target material) are kept, so scanning again is safe.
    """
    folder = bpy.path.abspath(props.folder)
    if not props.folder or not os.path.isdir(folder):
        raise ScanError("Pick a folder with textures first")
    preset = registry.get(props.preset)
    if preset is None:
        raise ScanError("Pick a preset first")

    result = scanner.scan_folder(folder, preset, recursive=props.recursive)
    same_source = props.scanned_folder == folder and props.scanned_preset == preset.id
    previous = {item.key: (item.include, item.material) for item in props.sets} if same_source else {}
    by_key = materials_by_key()

    props.sets.clear()
    for texture_set in result.sets:
        item = props.sets.add()
        item.name = texture_set.name
        item.key = texture_set.key
        for slot_id, path in texture_set.files.items():
            entry = item.files.add()
            entry.slot = slot_id
            entry.path = path
            entry.udim = slot_id in texture_set.udim_slots
        item.duplicates = sum(len(paths) for paths in texture_set.duplicates.values())
        if texture_set.key in previous:
            item.include, item.material = previous[texture_set.key]
        else:
            item.material = by_key.get(texture_set.key)

    props.ignored = len(result.ignored)
    props.unmatched = len(result.unmatched)
    props.scanned_folder = folder
    props.scanned_preset = preset.id
    props.active_set = max(0, min(props.active_set, len(props.sets) - 1))
    return result


def materials_by_key():
    """Editable materials by matching key, preferring ones something uses."""
    found = {}
    candidates = [m for m in bpy.data.materials if not m.is_grease_pencil and m.library is None]
    for material in sorted(candidates, key=lambda m: (m.users == 0, m.name)):
        found.setdefault(naming.asset_key(material.name), material)
    return found


def scan_is_stale(props):
    return (
        props.scanned_preset != props.preset
        or props.scanned_folder != bpy.path.abspath(props.folder)
    )


def build_item(props, item, *, create):
    """Build one scanned set into its material. Returns the material, or None when skipped."""
    material = item.material
    if material is None:
        if not create:
            return None
        material = bpy.data.materials.new(item.name)
        item.material = material
    preset = registry.get(props.scanned_preset)
    builder.build_material(
        material, item.texture_set(), preset, rebuild=props.rebuild, folder=props.scanned_folder
    )
    return material


def _livemat_material(name):
    material = bpy.data.materials.get(name)
    if material is None or not material.get("livemat_preset"):
        return None, None
    return material, registry.get(material["livemat_preset"])


class LIVEMAT_OT_scan(bpy.types.Operator):
    bl_idname = "livemat.scan"
    bl_label = "Scan Folder"
    bl_description = "Find texture sets in the folder and match them to materials by name"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.livemat
        try:
            scan(props)
        except ScanError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        matched = sum(1 for item in props.sets if item.material)
        self.report({"INFO"}, f"Found {plural(len(props.sets), 'texture set')}, {matched} match a material")
        return {"FINISHED"}


class LIVEMAT_OT_build(bpy.types.Operator):
    bl_idname = "livemat.build"
    bl_label = "Build Materials"
    bl_description = "Build materials from the scanned texture sets"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        props = context.scene.livemat
        if scan_is_stale(props) or not props.sets:
            try:
                scan(props)
            except ScanError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}

        if self.index >= 0:
            if self.index >= len(props.sets):
                return {"CANCELLED"}
            items, create = [props.sets[self.index]], True
        else:
            items, create = [i for i in props.sets if i.include], props.create_missing

        built, failed = 0, []
        for item in items:
            try:
                if build_item(props, item, create=create):
                    built += 1
            except RuntimeError as error:  # a file vanished or can't be read
                failed.append(f"{item.name}: {error}")

        for message in failed:
            self.report({"WARNING"}, message)
        self.report({"INFO"}, f"Built {plural(built, 'material')}")
        return {"FINISHED"} if built or not failed else {"CANCELLED"}


class LIVEMAT_OT_assign(bpy.types.Operator):
    bl_idname = "livemat.assign"
    bl_label = "Assign to Selected"
    bl_description = "Build this set's material and assign it to the selected objects"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return any(hasattr(o.data, "materials") for o in context.selected_objects)

    def execute(self, context):
        props = context.scene.livemat
        if not 0 <= self.index < len(props.sets):
            return {"CANCELLED"}
        try:
            material = build_item(props, props.sets[self.index], create=True)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        count = 0
        for obj in context.selected_objects:
            if not hasattr(obj.data, "materials"):
                continue
            if obj.material_slots:
                obj.active_material = material
            else:
                obj.data.materials.append(material)
            count += 1
        self.report({"INFO"}, f"Assigned {material.name} to {plural(count, 'object')}")
        return {"FINISHED"}


class LIVEMAT_OT_load_slot(bpy.types.Operator):
    bl_idname = "livemat.load_slot"
    bl_label = "Load Texture"
    bl_description = "Pick the texture file for this slot"
    bl_options = {"REGISTER", "UNDO"}

    material: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    slot: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    filepath: StringProperty(subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, _event):
        material, _preset = _livemat_material(self.material)
        if material is None:
            return {"CANCELLED"}
        current = builder.texture_set_from_material(material).files.get(self.slot)
        start = current or material.get("livemat_folder", "")
        if start:
            self.filepath = start if current else os.path.join(start, "")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, _context):
        material, preset = _livemat_material(self.material)
        if material is None or preset is None or preset.slot(self.slot) is None:
            return {"CANCELLED"}
        path = bpy.path.abspath(self.filepath)
        if not os.path.isfile(path):
            self.report({"ERROR"}, "Pick an image file")
            return {"CANCELLED"}
        texture_set = builder.texture_set_from_material(material)
        texture_set.files[self.slot] = path
        parsed = naming.parse_filename(os.path.basename(path))
        if parsed is not None and parsed.udim is not None:
            texture_set.udim_slots.add(self.slot)
        else:
            texture_set.udim_slots.discard(self.slot)
        try:
            builder.build_material(material, texture_set, preset, folder=material.get("livemat_folder"))
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class LIVEMAT_OT_clear_slot(bpy.types.Operator):
    bl_idname = "livemat.clear_slot"
    bl_label = "Clear Texture"
    bl_description = "Remove this slot's texture; the slot falls back to its default value"
    bl_options = {"REGISTER", "UNDO"}

    material: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    slot: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, _context):
        material, preset = _livemat_material(self.material)
        if material is None or preset is None:
            return {"CANCELLED"}
        texture_set = builder.texture_set_from_material(material)
        texture_set.files.pop(self.slot, None)
        texture_set.udim_slots.discard(self.slot)
        builder.build_material(material, texture_set, preset, folder=material.get("livemat_folder"))
        return {"FINISHED"}


class LIVEMAT_OT_switch_preset(bpy.types.Operator):
    bl_idname = "livemat.switch_preset"
    bl_label = "Switch Preset"
    bl_description = "Rebuild this material with another preset, rescanning its folder"
    bl_options = {"REGISTER", "UNDO"}

    material: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    preset: EnumProperty(items=registry.enum_items, options={"SKIP_SAVE"})

    def execute(self, _context):
        material, _old = _livemat_material(self.material)
        preset = registry.get(self.preset)
        if material is None or preset is None:
            return {"CANCELLED"}
        folder = material.get("livemat_folder")
        if not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, f"{material.name} doesn't remember its texture folder. Build it from the LiveMat panel")
            return {"CANCELLED"}
        key = material.get("livemat_key") or naming.asset_key(material.name)
        result = scanner.scan_folder(folder, preset)
        texture_set = next((s for s in result.sets if s.key == key), None)
        if texture_set is None:
            self.report({"ERROR"}, f"No textures for {material.get('livemat_set', material.name)} follow {preset.name}")
            return {"CANCELLED"}
        builder.build_material(material, texture_set, preset, folder=folder)
        self.report({"INFO"}, f"{material.name} now uses {preset.name}")
        return {"FINISHED"}


class LIVEMAT_OT_authoring_view(bpy.types.Operator):
    bl_idname = "livemat.authoring_view"
    bl_label = "Match Authoring View"
    bl_description = (
        "Use a neutral view transform with no look or exposure, closer to how Substance Painter "
        "displays textures. Click again to restore your settings"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.livemat
        view = context.scene.view_settings
        if props.authoring_view:
            saved = json.loads(props.saved_view or "{}")
            for key in _SAVED_VIEW_KEYS:  # transform first: looks depend on it
                if key in saved:
                    try:
                        setattr(view, key, saved[key])
                    except (TypeError, ValueError):
                        pass  # the config no longer has that transform or look
            props.authoring_view = False
            self.report({"INFO"}, "View settings restored")
            return {"FINISHED"}

        props.saved_view = json.dumps({key: getattr(view, key) for key in _SAVED_VIEW_KEYS})
        for name in AUTHORING_TRANSFORMS:
            try:
                view.view_transform = name
                break
            except TypeError:
                continue
        view.look = "None"
        view.exposure = 0.0
        view.gamma = 1.0
        view.use_curve_mapping = False
        props.authoring_view = True
        self.report({"INFO"}, f"View transform set to {view.view_transform}")
        return {"FINISHED"}


register, unregister = bpy.utils.register_classes_factory(
    (
        LIVEMAT_OT_scan,
        LIVEMAT_OT_build,
        LIVEMAT_OT_assign,
        LIVEMAT_OT_load_slot,
        LIVEMAT_OT_clear_slot,
        LIVEMAT_OT_switch_preset,
        LIVEMAT_OT_authoring_view,
    )
)
