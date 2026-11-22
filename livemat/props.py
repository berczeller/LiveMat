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

from . import registry
from .core.scanner import TextureSet


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
        poll=lambda _self, material: not material.is_grease_pencil,
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

    sets: CollectionProperty(type=LiveMatSet)
    active_set: IntProperty()
    scanned_folder: StringProperty()
    scanned_preset: StringProperty()
    ignored: IntProperty()
    unmatched: IntProperty()

    # View settings saved by Match Authoring View, so it can be turned off again.
    authoring_view: BoolProperty()
    saved_view: StringProperty()


_classes = (LiveMatSlotFile, LiveMatSet, LiveMatScene)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.livemat = PointerProperty(type=LiveMatScene)


def unregister():
    del bpy.types.Scene.livemat
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
