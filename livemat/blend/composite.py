# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Layer blending math, free of Blender so it can be tested on its own.

Each layer holds, per face corner, a value and a coverage. Coverage 0 means
the layer doesn't touch that corner, so the layers below show through.
"""

import numpy as np

BLEND_MODES = (
    ("NORMAL", "Normal", "Replace what's below"),
    ("ADD", "Add", "Add to what's below"),
    ("SUBTRACT", "Subtract", "Subtract from what's below"),
    ("MULTIPLY", "Multiply", "Multiply what's below"),
    ("MAX", "Lighten", "Keep the brighter of the two"),
    ("MIN", "Darken", "Keep the darker of the two"),
)


def blend(below, value, alpha, mode):
    """`below` blended with `value` by `alpha` (all arrays of the same length), clamped to 0..1."""
    if mode == "NORMAL":
        result = below + (value - below) * alpha
    elif mode == "ADD":
        result = below + value * alpha
    elif mode == "SUBTRACT":
        result = below - value * alpha
    elif mode == "MULTIPLY":
        result = below + (below * value - below) * alpha
    elif mode == "MAX":
        result = below + (np.maximum(below, value) - below) * alpha
    elif mode == "MIN":
        result = below + (np.minimum(below, value) - below) * alpha
    else:
        raise ValueError(f"unknown blend mode {mode!r}")
    return np.clip(result, 0.0, 1.0)


def levels(raw, low, high, invert=False):
    """Remap `raw` so `low` becomes 0 and `high` becomes 1, like Levels in an image editor."""
    span = max(high - low, 1e-6)
    result = np.clip((np.asarray(raw, dtype=np.float32) - low) / span, 0.0, 1.0)
    return (1.0 - result) if invert else result


def channel(base, layers, count):
    """One channel from its base value and its layers, listed top first.

    `layers` holds (values, coverage, opacity, mode) tuples, where values
    and coverage are arrays of `count` floats.
    """
    result = np.full(count, float(base), dtype=np.float32)
    for values, coverage, opacity, mode in reversed(list(layers)):
        result = blend(result, values, np.clip(coverage, 0.0, 1.0) * opacity, mode)
    return result.astype(np.float32)
