# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""File stamps of loaded textures, to tell when the copy in memory is out of date.

Blender never re-reads an image by itself. Remembering each file's
modification time and size when LiveMat loads it lets the panel point out
textures that were exported again since.
"""

import os

import bpy

_loaded = {}  # image name -> stamp of its file when the image was (re)loaded


def file_stamp(path):
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def image_stamp(image):
    """Modification time and size of the image's file, or of every tile for UDIMs."""
    path = bpy.path.abspath(image.filepath, library=image.library)
    if image.source == "TILED":
        return tuple(file_stamp(path.replace("<UDIM>", str(t.number))) for t in image.tiles)
    return file_stamp(path)


def remember(image):
    """Record the file as it is now, right after loading or reloading `image`."""
    _loaded[image.name] = image_stamp(image)


def baseline(image):
    """Record `image` the first time it's seen. Files open fresh, so that's the best guess."""
    if image.name not in _loaded:
        remember(image)


def changed(image):
    """True when the file on disk differs from the one `image` was loaded from."""
    stamp = image_stamp(image)
    return stamp is not None and image.name in _loaded and stamp != _loaded[image.name]


def forget_all():
    _loaded.clear()
