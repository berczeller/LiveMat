# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty

from . import data, export, fill, generators, paint, props, selection


def _mesh(context):
    obj = context.object
    return obj.data if obj is not None and obj.type == "MESH" and obj.data.library is None else None


class _MeshOperator:
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _mesh(context) is not None


class _EditOperator(_MeshOperator):
    @classmethod
    def poll(cls, context):
        if _mesh(context) is None or context.mode != "EDIT_MESH":
            cls.poll_message_set("Works on a selection in Edit Mode")
            return False
        return True


class LIVEMAT_OT_blend_start(_MeshOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_start"
    bl_label = "Add Blend Mask"
    bl_description = "Give this mesh a Blend mask: an RGBA vertex color the engine reads, built from layers"

    def execute(self, context):
        mesh = _mesh(context)
        data.composite_mesh(mesh)
        if not mesh.is_editmode:
            export.move_first(mesh)
        return {"FINISHED"}


class LIVEMAT_OT_blend_fill(_EditOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_fill"
    bl_label = "Fill Selection"
    bl_description = "Write into the active layer of the active channel, on the selection"

    action: EnumProperty(
        items=[
            ("SET", "Set", "Set the channel to the value on the selection"),
            ("ERASE", "Erase", "Write 0 into the active layer on the selection"),
            ("CLEAR", "Clear", "Make the active layer transparent on the selection, so layers below show"),
            ("RANDOMIZE", "Randomize", "Random values between Min and Max, per vertex, polygon, element or edge"),
        ],
        options={"SKIP_SAVE"},
    )

    @classmethod
    def description(cls, _context, properties):
        return {
            "SET": "Set the channel to the value on the selection",
            "ERASE": "Write 0 into the active layer on the selection. On a Normal layer that makes the channel 0",
            "CLEAR": "Make the active layer transparent on the selection, so the layers below show",
            "RANDOMIZE": "Random values between Min and Max on the selection, per vertex, polygon, element or edge",
        }[properties.action]

    def execute(self, context):
        mesh = _mesh(context)
        tool = context.scene.livemat_blend_tool
        try:
            message = fill.apply(context, mesh, self.action, tool.value)
        except fill.SelectionError as error:
            self.report({"WARNING"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, message)
        return {"FINISHED"}


class LIVEMAT_OT_blend_select_angle(_EditOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_select_angle"
    bl_label = "Select by Edge Angle"
    bl_description = "Find convex or concave edges in the angle range, in the selection or the whole mesh"

    target: EnumProperty(
        items=[
            ("EDGE", "Edges", "Select the matching edges", "EDGESEL", 0),
            ("VERT", "Verts", "Select the vertices of the matching edges", "VERTEXSEL", 1),
            ("FACE", "Faces", "Select the faces on both sides of the matching edges", "FACESEL", 2),
        ],
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        self.report({"INFO"}, selection.select_by_angle(context, _mesh(context), self.target))
        return {"FINISHED"}


class LIVEMAT_OT_blend_set_add(_EditOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_set_add"
    bl_label = "Save Selection"
    bl_description = "Add the current selection to the list, to select it again later"

    def execute(self, context):
        if selection.save(context, _mesh(context)) is None:
            self.report({"WARNING"}, "Nothing selected")
            return {"CANCELLED"}
        return {"FINISHED"}


class LIVEMAT_OT_blend_set_select(_EditOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_set_select"
    bl_label = "Select Saved Selection"
    bl_description = "Select this saved selection again. Shift+click adds it to the current selection"

    index: IntProperty(options={"HIDDEN", "SKIP_SAVE"})
    extend: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        mesh = _mesh(context)
        sets = mesh.livemat_blend.sets
        if not 0 <= self.index < len(sets):
            return {"CANCELLED"}
        mesh.livemat_blend["active_set"] = self.index
        if selection.restore(mesh, sets[self.index], extend=self.extend) is None:
            self.report({"WARNING"}, "This selection was undone. Remove it from the list")
            return {"CANCELLED"}
        return {"FINISHED"}


class LIVEMAT_OT_blend_set_remove(_MeshOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_set_remove"
    bl_label = "Remove Saved Selection"
    bl_description = "Remove the active saved selection from the list"

    def execute(self, context):
        mesh = _mesh(context)
        selection.remove(mesh, mesh.livemat_blend.active_set)
        return {"FINISHED"}


class LIVEMAT_OT_blend_set_combine(_EditOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_set_combine"
    bl_label = "Combine Selections"
    bl_description = "Make a new saved selection from the ticked ones: union, intersection or subtraction"

    def execute(self, context):
        mesh = _mesh(context)
        picked = [item for item in mesh.livemat_blend.sets if item.pick]
        if len(picked) < 2:
            self.report({"WARNING"}, "Tick at least two saved selections to combine")
            return {"CANCELLED"}
        if selection.combine(mesh, picked, context.scene.livemat_blend_tool.combine) is None:
            self.report({"WARNING"}, "The combination is empty")
            return {"CANCELLED"}
        return {"FINISHED"}


class _LayerOperator(_MeshOperator):
    """Layer list changes stay in Object Mode, where undo covers the list and the data together."""

    @classmethod
    def poll(cls, context):
        if _mesh(context) is None or context.mode != "OBJECT":
            cls.poll_message_set("Switch to Object Mode to change the layer list")
            return False
        return True


class LIVEMAT_OT_blend_layer_add(_LayerOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_layer_add"
    bl_label = "Add Layer"
    bl_description = "Add a layer on top of the active channel"

    kind: EnumProperty(
        items=props.LAYER_KINDS,
        default="FILL",
        options={"SKIP_SAVE"},
    )
    generator: EnumProperty(
        items=props.GENERATORS,
        default="AO",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        mesh = _mesh(context)
        if mesh.color_attributes.get(data.FINAL) is None:
            data.composite_mesh(mesh)
        names = {"FILL": "Fill", "PAINT": "Paint", "GENERATOR": dict(
            AO="AO", THICKNESS="Thickness", CURVATURE="Curvature", EDGES="Edge Wear")[self.generator]}
        layer = data.add_layer(mesh, mesh.livemat_blend.channel, names[self.kind])
        layer.kind = self.kind
        if self.kind == "GENERATOR":
            layer.generator = self.generator
            layer.low, layer.high = generators.DEFAULT_LEVELS.get(self.generator, (0.0, 1.0))
        data.composite_mesh(mesh)
        return {"FINISHED"}


class LIVEMAT_MT_blend_add_layer(bpy.types.Menu):
    bl_label = "Add Layer"

    def draw(self, _context):
        layout = self.layout
        layout.operator("livemat.blend_layer_add", text="Fill", icon="SNAP_FACE").kind = "FILL"
        layout.operator("livemat.blend_layer_add", text="Paint", icon="BRUSH_DATA").kind = "PAINT"
        layout.separator()
        for key, label, icon in (
            ("AO", "Ambient Occlusion", "SHADING_RENDERED"),
            ("THICKNESS", "Thickness", "MOD_SOLIDIFY"),
            ("CURVATURE", "Curvature", "SPHERECURVE"),
            ("EDGES", "Edge Wear", "MOD_BEVEL"),
        ):
            op = layout.operator("livemat.blend_layer_add", text=label, icon=icon)
            op.kind = "GENERATOR"
            op.generator = key


def _active_layer(mesh):
    state = mesh.livemat_blend
    layers = data.layers_of(state, state.channel)
    index = getattr(state, f"active_{state.channel.lower()}")
    return layers[index] if 0 <= index < len(layers) else None


class LIVEMAT_OT_blend_paint(_MeshOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_paint"
    bl_label = "Paint"
    bl_description = "Paint this layer with Blender's vertex paint brushes. White applies the layer's value, black removes it"

    @classmethod
    def poll(cls, context):
        mesh = _mesh(context)
        if mesh is None or context.mode not in {"OBJECT", "PAINT_VERTEX"}:
            return False
        layer = _active_layer(mesh)
        return layer is not None and layer.kind == "PAINT" and not mesh.livemat_blend.painting

    def execute(self, context):
        paint.start(context, context.object, _active_layer(_mesh(context)))
        return {"FINISHED"}


class LIVEMAT_OT_blend_paint_done(_MeshOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_paint_done"
    bl_label = "Done"
    bl_description = "Keep the strokes and go back to Object Mode"

    @classmethod
    def poll(cls, context):
        mesh = _mesh(context)
        return mesh is not None and bool(mesh.livemat_blend.painting)

    def execute(self, context):
        mesh = _mesh(context)
        if context.mode == "PAINT_VERTEX":
            bpy.ops.object.mode_set(mode="OBJECT")
        paint.finish(mesh)
        return {"FINISHED"}


class LIVEMAT_OT_blend_bake(_LayerOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_bake"
    bl_label = "Bake"
    bl_description = "Bake this generator layer from the mesh. AO, Thickness and Curvature use Cycles"

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        layer = _active_layer(_mesh(context))
        return layer is not None and layer.kind == "GENERATOR"

    def execute(self, context):
        layer = _active_layer(_mesh(context))
        try:
            low, high = generators.bake(context, context.object, layer)
        except generators.BakeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Baked {layer.name}: raw values from {low:.3f} to {high:.3f}")
        return {"FINISHED"}


class LIVEMAT_OT_blend_layer_remove(_LayerOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_layer_remove"
    bl_label = "Remove Layer"
    bl_description = "Remove the active layer of the active channel"

    def execute(self, context):
        mesh = _mesh(context)
        state = mesh.livemat_blend
        data.remove_layer(mesh, state.channel, getattr(state, f"active_{state.channel.lower()}"))
        data.composite_mesh(mesh)
        return {"FINISHED"}


class LIVEMAT_OT_blend_layer_move(_LayerOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_layer_move"
    bl_label = "Move Layer"
    bl_description = "Move the active layer up or down the stack"

    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")], options={"SKIP_SAVE"})

    def execute(self, context):
        mesh = _mesh(context)
        state = mesh.livemat_blend
        layers = data.layers_of(state, state.channel)
        key = f"active_{state.channel.lower()}"
        index = getattr(state, key)
        target = index - 1 if self.direction == "UP" else index + 1
        if not (0 <= index < len(layers) and 0 <= target < len(layers)):
            return {"CANCELLED"}
        layers.move(index, target)
        setattr(state, key, target)
        data.composite_mesh(mesh)
        return {"FINISHED"}


# Viewport display

_saved_shading = {}  # area pointer -> (shading type, color type), session only


def _space(context):
    space = context.space_data
    if space is not None and space.type == "VIEW_3D":
        return space
    for area in context.screen.areas if context.screen else ():
        if area.type == "VIEW_3D":
            return area.spaces.active
    return None


def current_view(context, mesh):
    space = _space(context)
    if space is None or space.shading.type != "SOLID" or space.shading.color_type != "VERTEX":
        return "MATERIAL"
    return "CHANNEL" if mesh.livemat_blend.view_channel else "COLORS"


def _remove_view(mesh):
    if mesh.is_editmode:
        bm = bmesh.from_edit_mesh(mesh)
        layer = bm.loops.layers.color.get(data.VIEW)
        if layer is not None:
            bm.loops.layers.color.remove(layer)
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    else:
        attribute = mesh.color_attributes.get(data.VIEW)
        if attribute is not None:
            mesh.color_attributes.remove(attribute)
        data.make_active(mesh, data.FINAL)


class LIVEMAT_OT_blend_view(_MeshOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_view"
    bl_label = "Blend View"
    bl_options = {"REGISTER"}  # display only, nothing to undo

    mode: EnumProperty(
        items=[
            ("MATERIAL", "Material", "Show the materials, as before", "MATERIAL", 0),
            ("COLORS", "Mask", "Show the RGBA mask the engine receives", "COLOR", 1),
            ("CHANNEL", "Channel", "Show only the active channel, in grayscale", "IMAGE_ALPHA", 2),
        ],
        options={"SKIP_SAVE"},
    )

    @classmethod
    def description(cls, _context, properties):
        return {
            "MATERIAL": "Show the materials, as before",
            "COLORS": "Show the RGBA mask the engine receives",
            "CHANNEL": "Show only the active channel, in grayscale, like a mask in Painter",
        }[properties.mode]

    def execute(self, context):
        mesh = _mesh(context)
        state = mesh.livemat_blend
        space = _space(context)
        key = space.as_pointer() if space else None
        if self.mode == "MATERIAL":
            state.view_channel = ""
            _remove_view(mesh)
            if space is not None:
                shading_type, color_type = _saved_shading.pop(key, ("MATERIAL", "MATERIAL"))
                space.shading.type = shading_type
                space.shading.color_type = color_type
            return {"FINISHED"}
        if space is not None:
            if current_view(context, mesh) == "MATERIAL":
                _saved_shading[key] = (space.shading.type, space.shading.color_type)
            space.shading.type = "SOLID"
            space.shading.color_type = "VERTEX"
        state.view_channel = state.channel if self.mode == "CHANNEL" else ""
        if self.mode == "COLORS":
            _remove_view(mesh)
        data.composite_mesh(mesh)
        return {"FINISHED"}


# Blend materials


class LIVEMAT_OT_blend_material_create(_MeshOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_material_create"
    bl_label = "Create Blend Material"
    bl_description = "Make a material that blends LiveMat materials by this mesh's mask, based on its current material"

    def execute(self, context):
        from . import material

        created = material.create(context.object)
        self.report({"INFO"}, f"Created {created.name}. Pick a material for each channel")
        return {"FINISHED"}


class LIVEMAT_OT_blend_material_rebuild(bpy.types.Operator):
    bl_idname = "livemat.blend_material_rebuild"
    bl_label = "Rebuild Blend Material"
    bl_description = "Rebuild this Blend material from its source materials"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        from . import material

        obj = context.object
        return obj is not None and obj.active_material is not None and obj.active_material.get(material.TAG)

    def execute(self, context):
        from . import material

        problem = material.build(context.object.active_material)
        if problem:
            self.report({"WARNING"}, problem)
        return {"FINISHED"}


# Pixel masks


def _blend_material(context):
    from . import material

    obj = context.object
    mat = obj.active_material if obj is not None else None
    return mat if mat is not None and mat.get(material.TAG) else None


class _MaskOperator:
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if _mesh(context) is None or _blend_material(context) is None:
            cls.poll_message_set("Needs a mesh whose active material is a Blend material")
            return False
        return True


class LIVEMAT_OT_blend_mask_paint(_MaskOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_mask_paint"
    bl_label = "Paint Mask Texture"
    bl_description = "Paint this channel's mask texture with Blender's texture paint brushes"

    channel: EnumProperty(items=[(c, c, "") for c in data.CHANNELS], options={"SKIP_SAVE"})

    def execute(self, context):
        from . import texture

        material = _blend_material(context)
        setup = material.livemat_blend_material
        image = texture.channel_image(material, self.channel, create=True)
        if setup.mask_source != "TEXTURE":
            setup.mask_source = "TEXTURE"  # rebuilds with an image node per channel
        if context.mode != "PAINT_TEXTURE":
            bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
        context.scene.tool_settings.image_paint.mode = "MATERIAL"
        images = list(material.texture_paint_images)
        if image in images:
            material.paint_active_slot = images.index(image)
        self.report({"INFO"}, f"Painting mask {self.channel}: white applies the channel, black removes it")
        return {"FINISHED"}


class LIVEMAT_OT_blend_mask_done(_MaskOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_mask_done"
    bl_label = "Done"
    bl_description = "Keep the painted mask textures in the .blend and go back to Object Mode"

    def execute(self, context):
        if context.mode == "PAINT_TEXTURE":
            bpy.ops.object.mode_set(mode="OBJECT")
        material = _blend_material(context)
        for channel in data.CHANNELS:
            image = getattr(material.livemat_blend_material, f"image_{channel.lower()}")
            if image is not None and image.is_dirty:
                image.pack()  # unsaved paint would be lost on reload
        return {"FINISHED"}


class LIVEMAT_OT_blend_mask_convert(_MaskOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_mask_convert"
    bl_label = "Convert Mask"
    bl_description = "Copy the mask between vertex colors and textures"

    direction: EnumProperty(
        items=[
            ("TO_TEXTURE", "Vertex Colors to Textures", "Bake the vertex mask into the mask textures, through the UVs"),
            ("TO_VERTEX", "Textures to Vertex Colors", "Sample the mask textures at each corner into new Fill layers"),
        ],
        options={"SKIP_SAVE"},
    )

    @classmethod
    def description(cls, _context, properties):
        return {
            "TO_TEXTURE": "Bake the vertex mask into the mask textures, through the UVs",
            "TO_VERTEX": "Sample the mask textures at each corner into new Fill layers",
        }[properties.direction]

    def execute(self, context):
        from . import generators, texture

        material = _blend_material(context)
        try:
            if self.direction == "TO_TEXTURE":
                done = texture.from_vertex(context, material, context.object)
                material.livemat_blend_material.mask_source = "TEXTURE"
            else:
                done = texture.to_vertex(material, context.object)
                material.livemat_blend_material.mask_source = "VERTEX"
        except generators.BakeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Converted channels {', '.join(done) or 'none'}")
        return {"FINISHED"}


class LIVEMAT_OT_blend_mask_export(_MaskOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_mask_export"
    bl_label = "Export Mask Textures"
    bl_description = "Save the mask as image files in the layout the chosen engine workflow expects"
    bl_options = {"REGISTER"}

    def execute(self, context):
        import os

        from . import generators, texture

        tool = context.scene.livemat_blend_tool
        if not tool.export_folder:
            self.report({"ERROR"}, "Pick a folder to export to")
            return {"CANCELLED"}
        folder = bpy.path.abspath(tool.export_folder)
        material = _blend_material(context)
        try:
            if material.livemat_blend_material.mask_source == "VERTEX":
                texture.from_vertex(context, material, context.object)  # textures follow the vertex mask
            paths = texture.export(material, folder, bpy.path.clean_name(material.name), tool.export_preset, tool.export_format)
        except (generators.BakeError, OSError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        names = ", ".join(os.path.basename(p) for p in paths)
        self.report({"INFO"}, f"Saved {names}. {texture.IMPORT_NOTES[tool.export_preset]}")
        return {"FINISHED"}


# Export


class LIVEMAT_OT_blend_move_first(_MeshOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_move_first"
    bl_label = "Export the Mask First"
    bl_description = "Reorder the color attributes so the Blend mask is exported first. Their data is kept"

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"WARNING"}, "Switch to Object Mode first")
            return {"CANCELLED"}
        moved = export.move_first(_mesh(context))
        self.report({"INFO"}, f"Moved {len(moved)} color attributes after the mask" if moved else "The mask was already first")
        return {"FINISHED"}


class LIVEMAT_OT_blend_check(_MeshOperator, bpy.types.Operator):
    bl_idname = "livemat.blend_check"
    bl_label = "Check FBX Export"
    bl_description = "Export this object to a temporary FBX with default settings, read it back and compare the mask"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"WARNING"}, "Switch to Object Mode first")
            return {"CANCELLED"}
        passed, message = export.round_trip(context, context.object)
        self.report({"INFO"} if passed else {"WARNING"}, message)
        return {"FINISHED"}


register, unregister = bpy.utils.register_classes_factory(
    (
        LIVEMAT_OT_blend_start,
        LIVEMAT_OT_blend_fill,
        LIVEMAT_OT_blend_select_angle,
        LIVEMAT_OT_blend_set_add,
        LIVEMAT_OT_blend_set_select,
        LIVEMAT_OT_blend_set_remove,
        LIVEMAT_OT_blend_set_combine,
        LIVEMAT_OT_blend_layer_add,
        LIVEMAT_MT_blend_add_layer,
        LIVEMAT_OT_blend_paint,
        LIVEMAT_OT_blend_paint_done,
        LIVEMAT_OT_blend_bake,
        LIVEMAT_OT_blend_layer_remove,
        LIVEMAT_OT_blend_layer_move,
        LIVEMAT_OT_blend_view,
        LIVEMAT_OT_blend_material_create,
        LIVEMAT_OT_blend_material_rebuild,
        LIVEMAT_OT_blend_mask_paint,
        LIVEMAT_OT_blend_mask_done,
        LIVEMAT_OT_blend_mask_convert,
        LIVEMAT_OT_blend_mask_export,
        LIVEMAT_OT_blend_move_first,
        LIVEMAT_OT_blend_check,
    )
)
