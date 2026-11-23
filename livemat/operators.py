# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

import json
import os

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from . import actions, refresh, registry, thumbs, watch
from .build import material as builder
from .build import tangents
from .core import naming, scanner

# Tried in order by Match Authoring View: a neutral tone map, then plain sRGB.
AUTHORING_TRANSFORMS = ("Khronos PBR Neutral", "Standard")
_SAVED_VIEW_KEYS = ("view_transform", "look", "exposure", "gamma", "use_curve_mapping")


def _viewport_shadings(context):
    """3D Viewport shading settings in this window, keyed by area index."""
    found = {}
    for index, area in enumerate(context.window.screen.areas if context.window else ()):
        if area.type == "VIEW_3D":
            found[str(index)] = area.spaces.active.shading
    return found


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


def rescan_for(props, index):
    """Scan again so files exported since the last scan are used, and return the set
    that was at `index` (found by name, since new sets can shift the list), or None."""
    key = props.sets[index].key if 0 <= index < len(props.sets) else None
    scan(props)
    if key is None:
        return None
    return next((item for item in props.sets if item.key == key), None)


def build_item(props, item, *, create):
    """Build one scanned set into its material. Returns the material, or None when skipped."""
    material = item.material
    if material is None:
        if not create:
            return None
        material = bpy.data.materials.new(item.name)
        item.material = material
    preset = registry.get(props.scanned_preset)
    refresh.set_cleared(material, ())
    builder.build_material(
        material, item.texture_set(), preset, rebuild=props.rebuild, folder=props.scanned_folder
    )
    material["livemat_recursive"] = props.recursive
    if material.livemat.tangents == "UNITY":
        tangents.update_users(material)
    return material


_livemat_material = actions.livemat_material


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
        # Always scan first: building from an old scan would drop maps exported since.
        try:
            item = rescan_for(props, self.index)
        except ScanError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        if self.index >= 0:
            if item is None:
                self.report({"ERROR"}, "That texture set is no longer in the folder")
                return {"CANCELLED"}
            items, create = [item], True
        else:
            items, create = [i for i in props.sets if i.include], props.create_missing

        built, failed = 0, []
        for item in items:
            try:
                if build_item(props, item, create=create):
                    built += 1
            except (RuntimeError, TypeError) as error:  # unreadable file, linked material, odd color config
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
        try:
            item = rescan_for(props, self.index)
        except ScanError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if item is None:
            self.report({"ERROR"}, "That texture set is no longer in the folder")
            return {"CANCELLED"}
        try:
            material = build_item(props, item, create=True)
        except (RuntimeError, TypeError) as error:
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
        start = current or builder.material_folder(material) or ""
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
        try:
            actions.assign_file(material, preset, self.slot, path)
        except (RuntimeError, TypeError) as error:
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
        try:
            actions.assign_file(material, preset, self.slot, None)
        except (RuntimeError, TypeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
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
        folder = builder.material_folder(material)
        if not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, f"{material.name} doesn't remember its texture folder. Build it from the LiveMat panel")
            return {"CANCELLED"}
        key = material.get("livemat_key") or naming.asset_key(material.name)
        result = scanner.scan_folder(folder, preset, recursive=material.get("livemat_recursive", True))
        texture_set = next((s for s in result.sets if s.key == key), None)
        if texture_set is None:
            self.report({"ERROR"}, f"No textures for {material.get('livemat_set', material.name)} follow {preset.name}")
            return {"CANCELLED"}
        refresh.set_cleared(material, ())
        try:
            actions.rebuild(material, preset, texture_set)
        except (RuntimeError, TypeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{material.name} now uses {preset.name}")
        return {"FINISHED"}


class LIVEMAT_OT_refresh(bpy.types.Operator):
    bl_idname = "livemat.refresh"
    bl_label = "Refresh"
    bl_description = (
        "Reload every LiveMat texture from disk and add maps that appeared in the material folders"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, _context):
        materials = refresh.livemat_materials()
        if not materials:
            self.report({"INFO"}, "No LiveMat materials in this file")
            return {"CANCELLED"}
        actions.forget_folders()
        updated, missing, no_tangents = 0, 0, set()
        for material in materials:
            try:
                rebuilt, gone = refresh.update_material(material)
            except (RuntimeError, TypeError) as error:
                self.report({"WARNING"}, f"{material.name}: {error}")
                continue
            updated += rebuilt
            missing += len(gone)
            if material.livemat.tangents == "UNITY":
                # Meshes may have been edited since their bitangents were written.
                no_tangents.update(tangents.update_users(material))
        images = refresh.livemat_images(materials)
        reloaded = refresh.reload_images(images)
        watch.clear_stale()
        thumbs.forget(bpy.path.abspath(i.filepath) for i in images)
        refresh.redraw_all()
        for name in sorted(no_tangents):
            self.report({"WARNING"}, f"{name} has no UV map, so Unity tangents can't be computed for it")
        message = f"Reloaded {plural(reloaded, 'texture')}"
        if updated:
            message += f", updated {plural(updated, 'material')}"
        if missing:
            self.report({"WARNING"}, f"{message}. {plural(missing, 'file')} missing on disk")
        else:
            self.report({"INFO"}, message)
        return {"FINISHED"}


class LIVEMAT_OT_authoring_view(bpy.types.Operator):
    bl_idname = "livemat.authoring_view"
    bl_label = "Match Authoring View"
    bl_description = (
        "Use a neutral view transform with no look or exposure, and keep the preview lighting "
        "fixed in the world like a game engine. Click again to restore your settings"
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
            shadings = _viewport_shadings(context)
            for index, value in saved.get("world_space_lighting", {}).items():
                if index in shadings:
                    shadings[index].use_world_space_lighting = value
            props.authoring_view = False
            self.report({"INFO"}, "View settings restored")
            return {"FINISHED"}

        shadings = _viewport_shadings(context)
        saved = {key: getattr(view, key) for key in _SAVED_VIEW_KEYS}
        saved["world_space_lighting"] = {i: s.use_world_space_lighting for i, s in shadings.items()}
        props.saved_view = json.dumps(saved)
        # Engines light the world, not the camera: keep the preview HDRI still while orbiting.
        for shading in shadings.values():
            shading.use_world_space_lighting = True
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
        LIVEMAT_OT_refresh,
        LIVEMAT_OT_authoring_view,
    )
)
