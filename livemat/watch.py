# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Poll LiveMat textures for changes on disk.

With Auto Reload on, changed textures reload by themselves. With it off,
the panel lists how many are out of date so Refresh can be pressed.
"""

import traceback

import bpy
from bpy.app.handlers import persistent

from . import refresh, stamps

INTERVAL = 1.0  # seconds between checks

_pending = {}  # image name -> new stamp waiting one more check
_stale = []  # names of images whose file changed since they were loaded


def stale_count():
    return len(_stale)


def clear_stale():
    """After a Refresh everything is current again; don't wait for the next check to say so."""
    _stale.clear()
    _pending.clear()


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
    if scene is None:
        return []
    images = refresh.livemat_images()
    for image in images:
        stamps.baseline(image)
    changed = [image for image in images if stamps.changed(image)]

    before = list(_stale)
    _stale[:] = [image.name for image in changed]
    if _stale != before:
        refresh.redraw_all()

    if not scene.livemat.auto_reload:
        _pending.clear()
        return []
    if _busy():
        return []  # reloading images under a running render or bake is unsafe

    # Exporters write big files over several moments. Wait until a change
    # looks the same on two checks in a row before reloading. This also
    # catches files that changed while Auto Reload was off.
    reload = []
    for image in changed:
        stamp = stamps.image_stamp(image)
        if _pending.get(image.name) == stamp:
            reload.append(image)
            del _pending[image.name]
        else:
            _pending[image.name] = stamp

    if reload:
        refresh.reload_images(reload)
        _stale[:] = [name for name in _stale if name not in {i.name for i in reload}]
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
    # A newly opened file loads its images fresh from disk.
    stamps.forget_all()
    _pending.clear()
    _stale.clear()


def register():
    bpy.app.timers.register(_tick, first_interval=INTERVAL, persistent=True)
    bpy.app.handlers.load_post.append(_forget)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _forget in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_forget)
    _forget()
