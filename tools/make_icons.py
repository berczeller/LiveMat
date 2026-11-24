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


def rounded_square(size, radius):
    def dist(x, y):
        qx = abs(x - size / 2) - (size / 2 - radius)
        qy = abs(y - size / 2) - (size / 2 - radius)
        outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
        return outside + min(max(qx, qy), 0.0) - radius

    return dist


def render_layers(layers):
    """Draw (shape, color) layers back to front at icon scale, without fitting them."""
    rows = []
    n = SAMPLES
    for py in range(SIZE):
        row = bytearray([0])
        for px in range(SIZE):
            r = g = b = a = 0.0
            for shape, color in layers:
                cover = sum(
                    1
                    for sy in range(n)
                    for sx in range(n)
                    if shape(px + (sx + 0.5) / n, py + (sy + 0.5) / n) <= 0.0
                ) / (n * n)
                # "Over" compositing of this layer onto what's below.
                r = color[0] * cover + r * (1 - cover)
                g = color[1] * cover + g * (1 - cover)
                b = color[2] * cover + b * (1 - cover)
                a = cover + a * (1 - cover)
            if a > 0:
                r, g, b = r / a if a < 1 else r, g / a if a < 1 else g, b / a if a < 1 else b
            row += bytes((round(min(r, 255)), round(min(g, 255)), round(min(b, 255)), round(255 * a)))
        rows.append(bytes(row))
    return b"".join(rows)


WHITE = (0xFF, 0xFF, 0xFF)
# Channel chips: a colored square with the channel's letter.
CHANNEL_COLORS = {
    "r": (0xE0, 0x4F, 0x5F),
    "g": (0x3F, 0xAE, 0x6A),
    "b": (0x3D, 0x7F, 0xE0),
    "a": (0x80, 0x80, 0x88),
}


def _arc(cx, cy, r, start, end, steps=20):
    return [
        (cx + r * math.cos(math.radians(start + (end - start) * i / steps)),
         cy - r * math.sin(math.radians(start + (end - start) * i / steps)))
        for i in range(steps + 1)
    ]


LETTERS = {
    "r": union(
        polyline([(11, 24), (11, 8), (17.5, 8)] + _arc(17.5, 12.25, 4.25, 90, -90)[1:] + [(11, 16.5)], 3.0),
        polyline([(16, 16.5), (21.5, 24)], 3.0),
    ),
    "g": union(
        polyline(_arc(16, 16, 8, 40, 320), 3.0),
        polyline([(22.1, 21.1), (22.1, 16.5), (17, 16.5)], 3.0),
    ),
    "b": union(
        polyline([(11, 24), (11, 8), (17, 8)] + _arc(17, 11.75, 3.75, 90, -90)[1:] + [(11, 15.5)], 3.0),
        polyline([(17, 15.5)] + _arc(17.5, 19.75, 4.25, 90, -90)[1:] + [(11, 24)], 3.0),
    ),
    "a": union(
        polyline([(9, 24.5), (16, 7.5), (23, 24.5)], 3.0),
        polyline([(12, 19), (20, 19)], 2.8),
    ),
}


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
    # Build: stacked blocks.
    yield "build", SKY, union(rect(4, 17, 15, 28, 2.6), rect(17, 17, 28, 28, 2.6), rect(10.5, 5, 21.5, 15, 2.6))
    # Blend: two overlapping circles.
    yield "blend", PINK, union(circle(12, 16, 8.5, width=2.8), circle(20, 16, 8.5, width=2.8))
    # Templates: a page with a folded corner and lines.
    yield "templates", LILAC, union(
        polyline([(7, 4), (19, 4), (25, 10), (25, 28), (7, 28), (7, 4)], 2.6),
        polyline([(19, 4), (19, 10), (25, 10)], 2.2),
        polyline([(11, 17), (21, 17)], 2.2),
        polyline([(11, 22), (21, 22)], 2.2),
    )
    # Layers: stacked diamonds.
    def diamond(y):
        return polyline([(4, y), (16, y - 6), (28, y), (16, y + 6), (4, y)], 2.4)

    yield "layers", AMBER, union(diamond(10), diamond(16), diamond(22))
    # Fill: a droplet.
    yield "fill", MINT, union(
        polyline([(16, 3), (9, 15)], 2.8),
        polyline([(16, 3), (23, 15)], 2.8),
        circle(16, 19, 8, width=2.8),
    )
    # Edge angle: two edges meeting, with an arc.
    yield "angle", SKY, union(
        polyline([(4, 26), (28, 26)], 2.6),
        polyline([(4, 26), (22, 6)], 2.6),
        polyline([(4 + 12 * math.cos(math.radians(a)), 26 - 12 * math.sin(math.radians(a))) for a in range(0, 49, 6)], 2.2),
    )
    # Saved selections: a list with checks.
    yield "selection", LILAC, union(
        *(rect(4, y - 3, 10, y + 3, 2.0) for y in (7, 16, 25)),
        *(polyline([(14, y), (28, y)], 2.4) for y in (7, 16, 25)),
    )
    # Export: an arrow leaving a tray.
    yield "export", SKY, union(
        polyline([(5, 18), (5, 27), (27, 27), (27, 18)], 2.6),
        polyline([(16, 21), (16, 4)], 2.6),
        polyline([(10, 10), (16, 4), (22, 10)], 2.6),
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, color, shape in icons():
        write_png(OUT / f"{name}.png", render(shape, color))
        print("wrote", OUT / f"{name}.png")
    for key, color in CHANNEL_COLORS.items():
        layers = [(rounded_square(SIZE, 6.0), color), (LETTERS[key], WHITE)]
        write_png(OUT / f"channel_{key}.png", render_layers(layers))
        print("wrote", OUT / f"channel_{key}.png")


if __name__ == "__main__":
    main()
