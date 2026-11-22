# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

"""Render LiveMat's UI icons to livemat/icons/*.png.

Standard library only. Each icon is a few anti-aliased strokes drawn from
distance functions, in the same pastel palette as the README badges.
Run: python tools/make_icons.py
"""

import math
import pathlib
import struct
import zlib

SIZE = 32
SAMPLES = 4  # supersampling per axis
MARGIN = 1.0  # px left around each glyph after scaling it to fill the icon
OUT = pathlib.Path(__file__).resolve().parents[1] / "livemat" / "icons"

SKY = (0x7F, 0xD3, 0xFF)
PINK = (0xFF, 0x8F, 0xA3)
LILAC = (0xC4, 0xA7, 0xFF)
AMBER = (0xFF, 0xC3, 0x6B)
MINT = (0x6F, 0xD6, 0xA0)


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def polyline(points, width):
    segs = list(zip(points, points[1:]))

    def dist(x, y):
        return min(_seg_dist(x, y, *a, *b) for a, b in segs) - width / 2

    return dist


def rect(x0, y0, x1, y1, width):
    return polyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], width)


def circle(cx, cy, r, width=None):
    def dist(x, y):
        d = math.hypot(x - cx, y - cy) - r
        return abs(d) - width / 2 if width else d

    return dist


def union(*shapes):
    return lambda x, y: min(s(x, y) for s in shapes)


def _bounds(shape, step=0.25):
    xs, ys = [], []
    grid = [-4.0 + i * step for i in range(int((SIZE + 8) / step) + 1)]
    for y in grid:
        for x in grid:
            if shape(x, y) <= 0.0:
                xs.append(x)
                ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def render(shape, color):
    x0, y0, x1, y1 = _bounds(shape)
    scale = (SIZE - 2 * MARGIN) / max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    c = SIZE / 2.0
    rows = []
    n = SAMPLES
    for py in range(SIZE):
        row = bytearray([0])  # PNG filter byte
        for px in range(SIZE):
            cover = 0
            for sy in range(n):
                for sx in range(n):
                    x = cx + (px + (sx + 0.5) / n - c) / scale
                    y = cy + (py + (sy + 0.5) / n - c) / scale
                    if shape(x, y) <= 0.0:
                        cover += 1
            row += bytes((*color, round(255 * cover / (n * n))))
        rows.append(bytes(row))
    return b"".join(rows)


def write_png(path, raw):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    )


def icons():
    # Material ball: a sphere with a highlight arc.
    yield "livemat", SKY, union(
        circle(16, 16, 12, width=3.0),
        polyline([(9.5, 13), (11, 10), (13.5, 8)], 2.6),
    )
    # Folder.
    yield "source", SKY, polyline([(4, 9), (12, 9), (15, 12), (28, 12), (28, 25), (4, 25), (4, 9)], 2.8)
    # Stacked texture sets.
    yield "sets", PINK, union(rect(4, 10, 20, 26, 2.8), polyline([(9, 10), (9, 5), (27, 5), (27, 21), (20, 21)], 2.8))
    # Image frame with a mountain.
    yield "textures", AMBER, union(
        rect(4, 6, 28, 26, 2.8),
        polyline([(7, 23), (13, 15), (18, 20), (21, 17), (26, 23)], 2.6),
        circle(21, 11, 2.2),
    )
    # Sliders.
    yield "surface", MINT, union(
        polyline([(4, 10), (28, 10)], 2.4),
        polyline([(4, 22), (28, 22)], 2.4),
        circle(11, 10, 3.6),
        circle(21, 22, 3.6),
    )
    # A normal arrow rising from a curved surface.
    yield "normals", LILAC, union(
        polyline([(3 + i * 26 / 16, 26 - 4 * math.sin(i / 16 * math.pi)) for i in range(17)], 2.6),
        polyline([(16, 21), (16, 5)], 2.6),
        polyline([(11, 10), (16, 5), (21, 10)], 2.6),
    )
    # Fine detail: a grid of dots.
    yield "detail", LILAC, union(*(circle(x, y, 2.4) for x in (7, 16, 25) for y in (7, 16, 25)))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, color, shape in icons():
        write_png(OUT / f"{name}.png", render(shape, color))
        print("wrote", OUT / f"{name}.png")


if __name__ == "__main__":
    main()
