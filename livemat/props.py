# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Settings and the last scan result, stored on the scene so they're saved with the .blend."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from . import actions, icons, registry
from .core.scanner import TextureSet

_CHANNEL_NAMES = {"R": "red", "G": "green", "B": "blue", "A": "alpha"}
# Kept alive between calls; Blender doesn't copy enum item strings.
_channel_items = []


def _channel_list(_self, _context):
    """R, G, B and A with their color-coded chips. The numbers match what files already store."""
    _channel_items[:] = [
        (key, key, f"Read the {name} channel", icons.get(f"channel_{key.lower()}"), number)
        for number, (key, name) in enumerate(_CHANNEL_NAMES.items(), start=1)
    ]
    return _channel_items


def _channel(default):
    return EnumProperty(
        name="Channel",
        items=_channel_list,
        default="RGBA".index(default) + 1,  # dynamic enums take the item number
        description="Texture channel this value is read from",
        update=actions.channels_changed,
    )


class LiveMatSlotState(bpy.types.PropertyGroup):
    """Per-material choices for one preset slot."""

    slot: StringProperty()
    src_R: _channel("R")
    src_G: _channel("G")
    src_B: _channel("B")
    src_A: _channel("A")
    texture: EnumProperty(
        name="Texture",
        description="Click to pick a texture from the material's folder",
        items=actions.picker_items,
        get=actions.picker_get,
        set=actions.picker_set,
    )


class LiveMatMaterial(bpy.types.PropertyGroup):
    slots: CollectionProperty(type=LiveMatSlotState)
    tangents: EnumProperty(
        name="Tangents",
        items=[
            ("BLENDER", "Blender", "Per-pixel bitangent, like Blender, Unreal and Unity HDRP", 0),
            ("UNITY", "Unity", "Per-vertex bitangent, like Unity's built-in shaders. Writes a hidden attribute to the meshes", 1),
        ],
        default="BLENDER",
        description="How normal maps are turned from tangent space into the surface normal",
        update=actions.tangents_changed,
    )


class LiveMatSlotFile(bpy.types.PropertyGroup):
    slot: StringProperty()
    path: StringProperty(subtype="FILE_PATH")
    udim: BoolProperty()


class LiveMatSet(bpy.types.PropertyGroup):
    # `name` comes from PropertyGroup and holds the set name.
    key: StringProperty()
    include: BoolProperty(name="Include", default=True, description="Build this set")
    material: PointerProperty(
        type=bpy.types.Material,
        name="Material",
        description="Material to build. Empty creates one named after the set",
        poll=lambda _self, material: not material.is_grease_pencil and material.library is None,
    )
    files: CollectionProperty(type=LiveMatSlotFile)
    duplicates: IntProperty(description="Files that lost to another file for the same slot")

    def texture_set(self):
        texture_set = TextureSet(name=self.name, key=self.key)
        for item in self.files:
            texture_set.files[item.slot] = item.path
            if item.udim:
                texture_set.udim_slots.add(item.slot)
        return texture_set


class LiveMatScene(bpy.types.PropertyGroup):
    folder: StringProperty(name="Folder", subtype="DIR_PATH", description="Folder with the texture files")
    preset: EnumProperty(name="Preset", items=registry.enum_items, description="How the textures are named and packed")
    recursive: BoolProperty(name="Subfolders", default=True, description="Also look inside subfolders")
    create_missing: BoolProperty(
        name="Create Missing",
        default=True,
        description="Create a material for sets that don't match one in the file",
    )
    rebuild: BoolProperty(
        name="Rebuild",
        default=False,
        description="Clear each material's nodes before building, instead of keeping existing ones aside",
    )

    auto_reload: BoolProperty(
        name="Auto Reload",
        default=False,
        description="Reload LiveMat textures when they change on disk, checking every second",
    )

    sets: CollectionProperty(type=LiveMatSet)
    active_set: IntProperty()
    scanned_folder: StringProperty()
    scanned_preset: StringProperty()
    ignored: IntProperty()
    unmatched: IntProperty()

    # View settings saved by Match Authoring View, so it can be turned off again.
    authoring_view: BoolProperty()
    saved_view: StringProperty()


_classes = (LiveMatSlotState, LiveMatMaterial, LiveMatSlotFile, LiveMatSet, LiveMatScene)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.livemat = PointerProperty(type=LiveMatScene)
    bpy.types.Material.livemat = PointerProperty(type=LiveMatMaterial)


def unregister():
    del bpy.types.Material.livemat
    del bpy.types.Scene.livemat
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
