# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Auto Reload: poll LiveMat textures and reload the ones that change on disk."""

import os
import traceback

import bpy
from bpy.app.handlers import persistent

from . import refresh

INTERVAL = 1.0  # seconds between checks

_seen = {}  # image name -> file stamp last loaded
_pending = {}  # image name -> new stamp waiting one more check


def _file_stamp(path):
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def image_stamp(image):
    """Modification time and size of the image's file, or of every tile for UDIMs."""
    path = bpy.path.abspath(image.filepath, library=image.library)
    if image.source == "TILED":
        return tuple(_file_stamp(path.replace("<UDIM>", str(t.number))) for t in image.tiles)
    return _file_stamp(path)


def _busy():
    for job in ("RENDER", "RENDER_PREVIEW", "OBJECT_BAKE", "COMPOSITE"):
        try:
            if bpy.app.is_job_running(job):
                return True
        except (TypeError, ValueError):  # job type not known to this Blender
            continue
    return False


def check(scene):
    """One polling pass. Returns the names of the images it reloaded."""
    if scene is None or not scene.livemat.auto_reload:
        _seen.clear()
        _pending.clear()
        return []
    if _busy():
        return []  # reloading images under a running render or bake is unsafe

    reload = []
    for image in refresh.livemat_images():
        stamp = image_stamp(image)
        name = image.name
        if name not in _seen:
            _seen[name] = stamp
        elif stamp != _seen[name] and stamp is not None:
            # Exporters write big files over several moments. Wait until a
            # change looks the same on two checks in a row before reloading.
            if _pending.get(name) == stamp:
                reload.append(image)
                _seen[name] = stamp
                del _pending[name]
            else:
                _pending[name] = stamp

    if reload:
        refresh.reload_images(reload)
        refresh.redraw_all()
    return [image.name for image in reload]


def _tick():
    try:
        check(bpy.context.scene)
    except Exception:  # an exception would unregister the timer for good
        traceback.print_exc()
    return INTERVAL


@persistent
def _forget(_dummy=None):
    # A newly opened file has its own images.
    _seen.clear()
    _pending.clear()


def register():
    bpy.app.timers.register(_tick, first_interval=INTERVAL, persistent=True)
    bpy.app.handlers.load_post.append(_forget)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _forget in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_forget)
    _forget()
