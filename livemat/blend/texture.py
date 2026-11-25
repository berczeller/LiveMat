# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Mask Blend: one packed RGBA mask texture on the UVs.

R, G and B are the layer masks and A is ambient occlusion, as in Rust's
Packed Mask Blend shader (import the mask with sRGB off). A channel is
painted in Blender through a temporary grayscale image the Blend material
reads while painting; Done writes it back into the packed mask.
"""

import os

import bpy
import numpy as np

from . import data, generators
from .material import PAINT_IMAGE, build

MASK_PREFIX = "LiveMat Mask "  # + material name

EXPORT_PRESETS = (
    ("RUST", "Rust Packed Mask", "RGBA: R, G, B layer masks, A ambient occlusion", 0),
    ("UNITY_HDRP", "Unity HDRP LayeredLit", "Layer Mask: R, G, B drive layers 1 to 3, A the main layer (full)", 1),
    ("UNITY_TERRAIN", "Unity Terrain Splatmap", "Base, R, G and B as four terrain layers whose weights add up to 1", 2),
    ("UNREAL", "Unreal (Packed RGBA)", "One RGBA mask for a layered material, A ambient occlusion", 3),
    ("UNREAL_LANDSCAPE", "Unreal Landscape Layers", "Base, R, G and B as one grayscale weight image each", 4),
    ("GODOT", "Godot", "One RGBA image, read as raw data", 5),
)

IMPORT_NOTES = {
    "RUST": "Unity: import with sRGB off and assign as the Packed Mask Map",
    "UNITY_HDRP": "Unity: untick sRGB (Color Texture) in the import settings",
    "UNITY_TERRAIN": "Unity: untick sRGB. Layer 1 is the Base",
    "UNREAL": "Unreal: Compression Settings Masks (no sRGB)",
    "UNREAL_LANDSCAPE": "Unreal: import each file on its landscape layer, same resolution as the landscape",
    "GODOT": "Godot: import as Lossless, sample without source_color",
}


def _set_data(image):
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"  # the alpha holds AO, not transparency


def packed_image(material, create=False):
    """The material's packed mask, made at the setup's resolution when asked: no layers, full AO."""
    setup = material.livemat_blend_material
    image = setup.mask_image
    if image is None and create:
        size = int(setup.resolution)
        image = bpy.data.images.new(f"{MASK_PREFIX}{material.name}", size, size, alpha=True)
        image.generated_color = (0.0, 0.0, 0.0, 1.0)
        _set_data(image)
        image.pack()
        setup.mask_image = image
    return image


def read_rgba(image):
    """An image's pixels as a (height, width, 4) float array."""
    width, height = image.size
    pixels = np.zeros(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(height, width, 4)


def write_rgba(image, rgba):
    height, width = rgba.shape[:2]
    if tuple(image.size) != (width, height):
        image.scale(width, height)
    image.pixels.foreach_set(np.ascontiguousarray(rgba, dtype=np.float32).ravel())
    image.update()
    image.pack()  # keep it in the .blend until exported


# Painting one channel


def paint_start(context, material, channel):
    """Paint `channel` of the packed mask: copy it into a grayscale image and open Texture Paint on it."""
    setup = material.livemat_blend_material
    image = packed_image(material, create=True)
    if setup.painting:
        paint_finish(material)
    rgba = read_rgba(image)
    gray = rgba[:, :, "RGBA".index(channel)]
    height, width = gray.shape
    old = bpy.data.images.get(PAINT_IMAGE)
    if old is not None:
        bpy.data.images.remove(old)
    paint = bpy.data.images.new(PAINT_IMAGE, width, height, alpha=False)
    _set_data(paint)
    paint.pixels.foreach_set(np.stack([gray, gray, gray, np.ones_like(gray)], axis=-1).ravel())
    paint.update()
    setup["painting"] = channel  # raw write: one rebuild below
    if setup.mask_source != "TEXTURE":
        setup["mask_source"] = 1
    build(material)
    if context.mode != "PAINT_TEXTURE":
        bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
    context.scene.tool_settings.image_paint.mode = "MATERIAL"
    images = list(material.texture_paint_images)
    if paint in images:
        material.paint_active_slot = images.index(paint)


def paint_finish(material):
    """Write the painted channel back into the packed mask and remove the paint image."""
    setup = material.livemat_blend_material
    paint = bpy.data.images.get(PAINT_IMAGE)
    channel = setup.painting
    if channel and paint is not None and setup.mask_image is not None:
        image = setup.mask_image
        rgba = read_rgba(image)
        strokes = read_rgba(paint)
        if strokes.shape[:2] != rgba.shape[:2]:
            paint.scale(rgba.shape[1], rgba.shape[0])
            strokes = read_rgba(paint)
        rgba[:, :, "RGBA".index(channel)] = strokes[:, :, :3].mean(axis=-1)
        write_rgba(image, rgba)
    if paint is not None:
        bpy.data.images.remove(paint)
    setup["painting"] = ""
    build(material)


# Vertex Blend -> Mask Blend


def bake_vertex(context, material, obj):
    """The mesh's vertex mask baked through the UVs, exactly, as a (size, size, 4) array."""
    mesh = obj.data
    if mesh.color_attributes.get(data.FINAL) is None:
        raise generators.BakeError("This mesh has no vertex mask to bake")
    if not mesh.uv_layers:
        raise generators.BakeError("The mesh needs a UV map")
    size = int(material.livemat_blend_material.resolution)
    target = bpy.data.images.new("LiveMat Mask Bake Target", size, size, alpha=False, float_buffer=True)
    target.colorspace_settings.name = "Non-Color"
    try:
        channels = [_bake_channel(context, obj, material, channel, target) for channel in data.CHANNELS]
    finally:
        bpy.data.images.remove(target)
    return np.stack(channels, axis=-1)


def from_vertex(context, material, obj):
    """Bake the vertex mask into the material's packed mask."""
    write_rgba(packed_image(material, create=True), bake_vertex(context, material, obj))


def _uv_name(material, obj):
    setup = material.livemat_blend_material
    uvs = obj.data.uv_layers
    if setup.uv_map and uvs.get(setup.uv_map) is not None:
        return setup.uv_map
    return (uvs.active_render or uvs.active).name


def _bake_channel(context, obj, material, channel, target):
    """One channel of the vertex mask, as raw bytes / 255, baked through the UVs into `target`."""
    from .material import _Graph, _srgb_encode  # the same exact decoding the Blend material uses

    bake = bpy.data.materials.new("LiveMat Mask Bake")
    tree = bake.node_tree
    tree.nodes.clear()
    g = _Graph(tree)
    attribute = g.new("ShaderNodeVertexColor", 0, layer_name=data.FINAL)
    if channel == "A":
        value = attribute.outputs["Alpha"]
    else:
        split = g.new("ShaderNodeSeparateColor", 1)
        g.links.new(attribute.outputs["Color"], split.inputs["Color"])
        value = _srgb_encode(g, split.outputs["RGB".index(channel)], 2)
    emission = g.new("ShaderNodeEmission", 6)
    g.links.new(value, emission.inputs["Color"])
    output = g.new("ShaderNodeOutputMaterial", 7)
    g.links.new(emission.outputs[0], output.inputs["Surface"])
    image_node = g.new("ShaderNodeTexImage", 5)
    image_node.image = target
    tree.nodes.active = image_node  # the bake writes into the active image node
    uv = _uv_name(material, obj)
    try:
        _with_material(
            context, obj, bake,
            lambda: bpy.ops.object.bake(
                type="EMIT", target="IMAGE_TEXTURES", margin=4, uv_layer=uv,
                use_selected_to_active=False, use_cage=False,
            ),
        )
        return read_rgba(target)[:, :, 0].copy()
    finally:
        bpy.data.materials.remove(bake)


def _with_material(context, obj, material, run):
    """Run a Cycles bake with `material` on every slot of obj, restoring everything afterwards."""
    if context.mode != "OBJECT":
        raise generators.BakeError("Switch to Object Mode first")
    scene, view_layer, mesh = context.scene, context.view_layer, obj.data
    saved = {
        "engine": scene.render.engine,
        "samples": scene.cycles.samples,
        "selected": [o for o in view_layer.objects if o.select_get()],
        "active": view_layer.objects.active,
        "slots": [(slot.link, slot.material) for slot in obj.material_slots],
        "appended": False,
    }
    try:
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 1  # emission only: one sample is exact
        if obj.material_slots:
            for slot in obj.material_slots:
                slot.material = material
        else:
            mesh.materials.append(material)
            saved["appended"] = True
        for other in saved["selected"]:
            other.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj
        try:
            run()
        except RuntimeError as error:
            raise generators.BakeError(f"Cycles couldn't bake: {error}") from error
    finally:
        if saved["appended"]:
            mesh.materials.pop()
        else:
            for slot, (link, original) in zip(obj.material_slots, saved["slots"]):
                slot.link = link
                slot.material = original
        scene.render.engine = saved["engine"]
        scene.cycles.samples = saved["samples"]
        obj.select_set(obj in saved["selected"])
        for other in saved["selected"]:
            other.select_set(True)
        view_layer.objects.active = saved["active"]


# Export


def layer_weights(rgba):
    """Base, R, G and B weights as the Blend material lays them (B on top), adding up to 1."""
    r, g, b = rgba[..., 0], rgba[..., 1], rgba[..., 2]
    weight_b = b
    weight_g = g * (1.0 - b)
    weight_r = r * (1.0 - g) * (1.0 - b)
    weight_base = (1.0 - r) * (1.0 - g) * (1.0 - b)
    return weight_base, weight_r, weight_g, weight_b


def _save(path, rgba, file_format):
    height, width = rgba.shape[:2]
    image = bpy.data.images.new("LiveMat Export", width, height, alpha=True)
    try:
        _set_data(image)
        image.pixels.foreach_set(np.ascontiguousarray(rgba, dtype=np.float32).ravel())
        image.filepath_raw = path
        image.file_format = file_format
        image.save()
    finally:
        bpy.data.images.remove(image)


def export(rgba, folder, name, preset, file_format):
    """Write a packed mask (height, width, 4) in the preset's layout. Returns the written paths."""
    extension = {"PNG": ".png", "TARGA": ".tga"}[file_format]
    os.makedirs(folder, exist_ok=True)
    if preset == "UNREAL_LANDSCAPE":
        written = []
        for label, weight in zip(("Base", "R", "G", "B"), layer_weights(rgba)):
            path = os.path.join(folder, f"{name}_{label}{extension}")
            _save(path, np.stack([weight, weight, weight, np.ones_like(weight)], axis=-1), file_format)
            written.append(path)
        return written
    out = np.array(rgba, dtype=np.float32, copy=True)
    if preset == "UNITY_TERRAIN":
        out = np.stack(layer_weights(rgba), axis=-1)
    elif preset == "UNITY_HDRP":
        out[..., 3] = 1.0  # the main layer is always present
    path = os.path.join(folder, f"{name}_mask{extension}")
    _save(path, out, file_format)
    return [path]
