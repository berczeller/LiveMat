"""Find which gloss curve an exporter used, from two exports of the same texture set.

Export the same material twice from Substance 3D Painter (or any tool): once
with a plain roughness map, once with the packed map that stores gloss in a
channel. A roughness ramp from 0 to 1 gives the clearest result. Then run:

    blender -b --factory-startup --python tools/calibrate_gloss.py -- ROUGHNESS PACKED [CHANNEL]

CHANNEL is where the packed map keeps gloss (default A). The script compares
every pixel and prints how well each of LiveMat's gloss curves matches.
"""

import sys

import bpy
import numpy as np

# gloss_curve -> stored gloss as a function of roughness r
CURVES = {
    "LINEAR": lambda r: 1.0 - r,
    "SQUARED": lambda r: 1.0 - np.sqrt(r),  # roughness = (1 - g)^2
    "SQRT": lambda r: (1.0 - r) ** 2,  # roughness = 1 - sqrt(g)
}


def read(path):
    image = bpy.data.images.load(path)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(height, width, 4)


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    roughness_path, packed_path = argv[:2]
    channel = "RGBA".index(argv[2].upper()) if len(argv) > 2 else 3

    roughness, packed = read(roughness_path), read(packed_path)
    if roughness.shape != packed.shape:
        sys.exit(f"sizes differ: {roughness.shape[:2]} vs {packed.shape[:2]}, export both at the same size")

    r = roughness[..., 0].ravel()
    g = packed[..., channel].ravel()
    print(f"\n{r.size} pixels, roughness {r.min():.3f} to {r.max():.3f}")
    if r.max() - r.min() < 0.5:
        print("warning: roughness covers a narrow range, use a 0 to 1 ramp for a reliable fit")

    errors = {name: float(np.sqrt(np.mean((curve(r) - g) ** 2))) for name, curve in CURVES.items()}
    for name, error in sorted(errors.items(), key=lambda item: item[1]):
        print(f"  {name:8} RMS error {error:.4f}  ({error * 255:.1f} / 255)")
    best = min(errors, key=errors.get)
    print(f"\nbest fit: \"gloss_curve\": \"{best}\"")
    if errors[best] * 255 > 3:
        print("no curve fits within 3/255; the exporter may use metallic too, so compare a metallic 0 and 1 export")

    print("\n roughness   stored gloss")
    for low in np.linspace(0, 0.9, 10):
        mask = (r >= low) & (r < low + 0.1)
        if mask.any():
            print(f"  {low:.1f}-{low + 0.1:.1f}     {g[mask].mean():.3f}")


main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
