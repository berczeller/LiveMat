# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

import bpy


class _LiveMatSidebar:
    bl_region_type = "UI"
    bl_category = "LiveMat"
    bl_label = "LiveMat"

    def draw(self, context):
        self.layout.label(text="No texture folder loaded", icon="FILE_FOLDER")


class LIVEMAT_PT_view3d(_LiveMatSidebar, bpy.types.Panel):
    bl_space_type = "VIEW_3D"


class LIVEMAT_PT_shader_editor(_LiveMatSidebar, bpy.types.Panel):
    bl_space_type = "NODE_EDITOR"

    @classmethod
    def poll(cls, context):
        # The node editor also hosts geometry and compositor trees.
        return getattr(context.space_data, "tree_type", "") == "ShaderNodeTree"


register, unregister = bpy.utils.register_classes_factory(
    (LIVEMAT_PT_view3d, LIVEMAT_PT_shader_editor)
)
