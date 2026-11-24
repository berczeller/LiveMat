# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Pixel masks: one grayscale image per channel, mapped through UVs.

A Blend material can read its mask from these images instead of the vertex
colors. They're painted with Blender's Texture Paint, converted from and to
the vertex mask, and exported packed into the layouts engines expect.
"""

import os

import bpy
import numpy as np

from . import data, generators

MASK_PREFIX = "LiveMat Mask "  # + material name + " " + channel

EXPORT_PRESETS = (
    ("GENERIC", "Generic RGBA", "One RGBA image: R, G, B, A as painted", 0),
    ("UNITY_HDRP", "Unity HDRP LayeredLit", "Layer Mask: R, G, B drive layers 1 to 3, A the main layer", 1),
    ("UNITY_TERRAIN", "Unity Terrain Splatmap", "RGBA splatmap for 4 terrain layers: R is the bottom one, weights add up to 1", 2),
    ("UNREAL", "Unreal (Packed RGBA)", "One RGBA mask for a layered material", 3),
    ("UNREAL_LANDSCAPE", "Unreal Landscape Layers", "One grayscale image per channel, for landscape layer import", 4),
    ("GODOT", "Godot", "One RGBA image, read as raw data", 5),
)

IMPORT_NOTES = {
    "GENERIC": "Import as data: no sRGB, no color compression",
    "UNITY_HDRP": "Unity: untick sRGB (Color Texture) in the import settings",
    "UNITY_TERRAIN": "Unity: untick sRGB. R is the bottom layer, G, B and A paint over it",
    "UNREAL": "Unreal: Compression Settings Masks (no sRGB)",
    "UNREAL_LANDSCAPE": "Unreal: import each file on its landscape layer, same resolution as the landscape",
    "GODOT": "Godot: import as Lossless, sample without source_color",
}


def image_name(material, channel):
    return f"{MASK_PREFIX}{material.name} {channel}"


def channel_image(material, channel, create=False):
    """The grayscale mask image of one channel, made black at the setup's resolution when asked."""
    setup = material.livemat_blend_material
    image = getattr(setup, f"image_{channel.lower()}")
    if image is None and create:
        size = int(setup.resolution)
        image = bpy.data.images.new(image_name(material, channel), size, size, alpha=False)
        image.generated_color = (0.0, 0.0, 0.0, 1.0)
        image.colorspace_settings.name = "Non-Color"
        image.pack()  # lives in the .blend until exported
        setattr(setup, f"image_{channel.lower()}", image)
    return image


def read_gray(image):
    """An image's red channel as a (height, width) float array."""
    width, height = image.size
    pixels = np.zeros(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(height, width, 4)[:, :, 0]


def write_gray(image, values):
    height, width = values.shape
    if tuple(image.size) != (width, height):
        image.scale(width, height)  # the Resolution setting changed since the image was made
    rgba = np.ones((height, width, 4), dtype=np.float32)
    rgba[:, :, 0] = rgba[:, :, 1] = rgba[:, :, 2] = values
    image.pixels.foreach_set(rgba.ravel())
    image.update()
    if image.packed_file is not None or not image.filepath:
        image.pack()


# Texture -> vertex colors


def sample(image_values, uvs):
    """Bilinear samples of a (height, width) array at UV coordinates (n, 2), wrapping like a tiling texture."""
    height, width = image_values.shape
    x = (uvs[:, 0] % 1.0) * width - 0.5
    y = (uvs[:, 1] % 1.0) * height - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx, fy = x - x0, y - y0
    x0 %= width
    y0 %= height
    x1, y1 = (x0 + 1) % width, (y0 + 1) % height
    top = image_values[y0, x0] * (1 - fx) + image_values[y0, x1] * fx
    bottom = image_values[y1, x0] * (1 - fx) + image_values[y1, x1] * fx
    return (top * (1 - fy) + bottom * fy).astype(np.float32)


def to_vertex(material, obj):
    """Sample each channel image at the mesh's corners into a new Fill layer per channel. Returns the channels done."""
    mesh = obj.data
    uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active
    if uv_layer is None:
        raise generators.BakeError("The mesh needs a UV map")
    uvs = np.zeros(len(mesh.loops) * 2, dtype=np.float32)
    uv_layer.data.foreach_get("uv", uvs)
    uvs = uvs.reshape(-1, 2)
    done = []
    if mesh.color_attributes.get(data.FINAL) is None:
        data.composite_mesh(mesh)
    for channel in data.CHANNELS:
        image = channel_image(material, channel)
        if image is None:
            continue
        values = sample(read_gray(image), uvs)
        layer = data.add_layer(mesh, channel, "From Texture")
        with data.access(mesh) as acc:
            stored = np.zeros((acc.count, 3), dtype=np.float32)
            stored[:, 0] = values
            stored[:, 1] = 1.0
            acc.write_layer(data.layer_attribute(layer.uid), stored)
        done.append(channel)
    data.composite_mesh(mesh)
    return done


# Vertex colors -> texture



def bake_vertex(context, material, obj):
    """The mesh's vertex mask baked through the UVs, exactly, as {channel: (size, size) array}."""
    mesh = obj.data
    if mesh.color_attributes.get(data.FINAL) is None:
        raise generators.BakeError("This mesh has no Blend mask to convert")
    if not mesh.uv_layers:
        raise generators.BakeError("The mesh needs a UV map")
    size = int(material.livemat_blend_material.resolution)
    target = bpy.data.images.new("LiveMat Mask Bake Target", size, size, alpha=False, float_buffer=True)
    target.colorspace_settings.name = "Non-Color"
    try:
        return {channel: _bake_channel(context, obj, channel, target) for channel in data.CHANNELS}
    finally:
        bpy.data.images.remove(target)


def from_vertex(context, material, obj):
    """Bake the mesh's vertex mask into the material's channel images."""
    results = bake_vertex(context, material, obj)
    for channel, values in results.items():
        write_gray(channel_image(material, channel, create=True), values)
    return list(results)


def _bake_channel(context, obj, channel, target):
    """One channel of the vertex mask, as raw bytes / 255, baked through the UVs into `target`."""
    from .material import _srgb_encode, _Graph  # the same exact decoding the Blend material uses

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
    uv = obj.data.uv_layers.active_render or obj.data.uv_layers.active
    try:
        _with_material(
            context, obj, bake,
            lambda: bpy.ops.object.bake(
                type="EMIT", target="IMAGE_TEXTURES", margin=4, uv_layer=uv.name,
                use_selected_to_active=False, use_cage=False,
            ),
        )
        return read_gray(target).copy()
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


def channels_for_export(material):
    """The four channel arrays (black where a channel has no image), all at the setup's resolution."""
    size = int(material.livemat_blend_material.resolution)
    arrays = {}
    for channel in data.CHANNELS:
        image = channel_image(material, channel)
        if image is None:
            arrays[channel] = np.zeros((size, size), dtype=np.float32)
            continue
        values = read_gray(image)
        if values.shape != (size, size):
            scaled = image.copy()
            scaled.scale(size, size)
            values = read_gray(scaled)
            bpy.data.images.remove(scaled)
        arrays[channel] = values
    return arrays


def _terrain_weights(arrays):
    """Splatmap weights that match the Blend preview with height off, adding up to 1.

    The preview lays R, then G, B and A over the base, each covering what's
    below by its mask. A terrain has no separate base, so layer 1 (R) plays
    the base: it gets whatever the layers above leave uncovered.
    """
    g, b, a = arrays["G"], arrays["B"], arrays["A"]
    weight_a = a
    weight_b = b * (1.0 - a)
    weight_g = g * (1.0 - b) * (1.0 - a)
    weight_r = (1.0 - g) * (1.0 - b) * (1.0 - a)
    return {"R": weight_r, "G": weight_g, "B": weight_b, "A": weight_a}


def _save(path, rgba, file_format):
    height, width = rgba.shape[:2]
    image = bpy.data.images.new("LiveMat Export", width, height, alpha=True)
    try:
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        image.pixels.foreach_set(np.ascontiguousarray(rgba, dtype=np.float32).ravel())
        image.filepath_raw = path
        image.file_format = file_format
        image.save()
    finally:
        bpy.data.images.remove(image)


def export(material, folder, name, preset, file_format, arrays=None):
    """Write the mask in the preset's layout. Returns the written paths.

    `arrays` overrides the material's mask images (for a vertex mask baked on the fly).
    """
    extension = {"PNG": ".png", "TARGA": ".tga"}[file_format]
    if arrays is None:
        arrays = channels_for_export(material)
    if preset == "UNITY_TERRAIN":
        arrays = _terrain_weights(arrays)
    os.makedirs(folder, exist_ok=True)
    written = []
    if preset == "UNREAL_LANDSCAPE":
        for channel in data.CHANNELS:
            gray = arrays[channel]
            rgba = np.stack([gray, gray, gray, np.ones_like(gray)], axis=-1)
            path = os.path.join(folder, f"{name}_{channel}{extension}")
            _save(path, rgba, file_format)
            written.append(path)
        return written
    rgba = np.stack([arrays[c] for c in data.CHANNELS], axis=-1)
    path = os.path.join(folder, f"{name}_mask{extension}")
    _save(path, rgba, file_format)
    return [path]
