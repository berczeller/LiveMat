"""Synthetic texture sets for tests.

Images are tiny solid-color PNGs written with the standard library, so tests
don't depend on real artwork and run outside Blender too.
"""

import struct
import zlib
from pathlib import Path

_COLOR_TYPE = {1: 0, 3: 2, 4: 6}  # channel count -> PNG color type


def write_png(path, value, size=4):
    """Write a square PNG filled with `value`, a tuple of 1, 3 or 4 ints (0 to 255)."""
    channels = len(value)
    row = b"\x00" + bytes(value) * size  # leading 0 = no row filter
    raw = row * size

    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", size, size, 8, _COLOR_TYPE[channels], 0, 0, 0)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


def make_texture_set(folder, name, maps):
    """Write one PNG per map as `<name><suffix>.png` and return their paths.

    `maps` maps a suffix such as "_nrm" to a pixel value tuple.
    """
    return {
        suffix: write_png(Path(folder) / f"{name}{suffix}.png", value)
        for suffix, value in maps.items()
    }


# A metal/rough set with the usual Substance export names.
METAL_ROUGH = {
    "_BaseColor": (200, 120, 60),
    "_Metallic": (255,),
    "_Roughness": (64,),
    "_Normal": (128, 128, 255),
}

# Rust style: metal in RGB, gloss in alpha, OpenGL normal.
RUST_STANDARD = {
    "_bc": (200, 120, 60),
    "_mg": (255, 255, 255, 191),
    "_nrm": (128, 128, 255),
    "_ao": (230,),
}
