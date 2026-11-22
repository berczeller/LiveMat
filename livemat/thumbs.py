# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Thumbnails for texture files on disk.

Blender's file thumbnails cover PNG and JPEG but stay empty for formats like
TGA, which game pipelines export all the time. Those get a thumbnail made
here instead: the file is loaded once in the background, shrunk, and its
pixels copied into the preview.
"""

import os

import bpy
import bpy.utils.previews

NATIVE = {".png", ".jpg", ".jpeg"}  # formats Blender's own thumbnailer handles
IMAGE_SIZE = 128  # px, the large preview shown in the picker
ICON_SIZE = 32  # px, the small icon

_previews = None
_queue = []  # paths waiting for a thumbnail


def file_icon(path):
    """icon_value of a preview for the image file at `path`, or 0."""
    if _previews is None or not path or not os.path.isfile(path):
        return 0
    preview = _previews.get(path)
    if preview is None:
        if os.path.splitext(path)[1].lower() in NATIVE:
            preview = _previews.load(path, path, "IMAGE")
        else:
            preview = _previews.new(path)
            _queue.append(path)
            if not bpy.app.timers.is_registered(_make_next):
                bpy.app.timers.register(_make_next, first_interval=0.05)
    return preview.icon_id


def forget(paths):
    """Read thumbnails again for files that changed on disk."""
    if _previews is None:
        return
    for path in paths:
        if path not in _previews:
            continue
        if os.path.splitext(path)[1].lower() in NATIVE:
            _previews[path].reload()
        elif path not in _queue:
            _queue.append(path)
            if not bpy.app.timers.is_registered(_make_next):
                bpy.app.timers.register(_make_next, first_interval=0.05)


def _pixels(image, size):
    """The image shrunk to fit `size`, as (width, height, RGBA floats) with opaque alpha."""
    width, height = image.size
    scale = size / max(width, height, 1)
    image.scale(max(1, round(width * scale)), max(1, round(height * scale)))
    pixels = list(image.pixels)
    pixels[3::4] = [1.0] * (len(pixels) // 4)  # alpha often holds data (gloss), not transparency
    return image.size[0], image.size[1], pixels


def _make_next():
    """Make one queued thumbnail per call, so the UI stays responsive."""
    if _previews is None or not _queue:
        return None
    path = _queue.pop(0)
    preview = _previews.get(path)
    if preview is not None and os.path.isfile(path):
        try:
            image = bpy.data.images.load(path, check_existing=False)
        except RuntimeError:
            image = None
        if image is not None:
            try:
                # Keep RGB as stored; straight alpha would multiply a gloss channel into it.
                image.alpha_mode = "CHANNEL_PACKED"
                w, h, pixels = _pixels(image, IMAGE_SIZE)
                preview.image_size = (w, h)
                preview.image_pixels_float = pixels
                w, h, pixels = _pixels(image, ICON_SIZE)
                preview.icon_size = (w, h)
                preview.icon_pixels_float = pixels
            finally:
                bpy.data.images.remove(image)
            _redraw()
    return 0.01 if _queue else None


def _redraw():
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            if area.type in {"VIEW_3D", "NODE_EDITOR", "PROPERTIES"}:
                area.tag_redraw()


def register():
    global _previews
    _previews = bpy.utils.previews.new()


def unregister():
    global _previews
    if bpy.app.timers.is_registered(_make_next):
        bpy.app.timers.unregister(_make_next)
    _queue.clear()
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
