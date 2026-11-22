# LiveMat

### A Blender add-on that turns a folder of PBR textures into ready-to-use materials.

![Blender](https://img.shields.io/badge/Blender-5.2%2B-7fd3ff?style=flat-square) ![Type](https://img.shields.io/badge/Blender-extension-ff8fa3?style=flat-square) ![Python](https://img.shields.io/badge/Python-3.13-c4a7ff?style=flat-square) ![License](https://img.shields.io/badge/license-GPL--3.0--or--later-6fd6a0?style=flat-square) ![Status](https://img.shields.io/badge/status-in%20development-ff9f6b?style=flat-square)

---

Texture sets come out of Substance 3D Painter, Designer and game pipelines in many shapes: metal/rough or spec/gloss, OpenGL or DirectX normals, packed channels or one file per map, and a different suffix for every studio (`_normal`, `_nrm`, `_n`). LiveMat reads a folder, recognizes each map from a preset, and builds Eevee-friendly materials with the right channels, color spaces and conversions, so what you see in the viewport matches the tool the textures were made in.

> [!NOTE]
> LiveMat is in early development and there's no release yet. The first one will be 0.1.0.

## Planned for 0.1.0

- Pick a folder and LiveMat matches texture sets to the scene's materials by name, listing the rest so you can create or assign them.
- Built-in presets for common pipelines (see below).
- Correct color spaces, channel unpacking, gloss to roughness and DirectX to OpenGL normal conversion, all inside one shared node group per preset.
- A texture slot panel with thumbnails, in the spirit of Unity's material inspector.
- A **Refresh** button, plus an optional auto-watch that reloads textures when they change on disk.
- An optional **Match authoring view** button that sets a neutral view transform for comparing with Painter.

Custom presets with a template editor follow in 0.2.0.

## Presets

| Preset | Maps | Normal |
|---|---|---|
| Default (Metal/Rough) | Base Color, Metallic, Roughness, Normal, Height, AO, Emissive | OpenGL |
| Default Specular | Diffuse, Specular, Glossiness, Normal | OpenGL |
| Unity Standard | Albedo, Metallic (R) + Smoothness (A), Normal, Occlusion | OpenGL |
| Unity Mask Map (URP/HDRP) | Base Map, Mask Map (Metal R, AO G, Detail B, Smoothness A), Normal | OpenGL |
| Unreal | Base Color, Metallic, Roughness, Normal | DirectX |
| Unreal Packed | Base Color, ORM (AO R, Roughness G, Metal B), Normal | DirectX |
| Rust Standard | `_bc`, `_mg` (Metal RGB + Gloss A), `_nrm`, `_ao` | OpenGL |

## Requirements

- Blender 5.2 or newer.

## Building from source

Blender 5.2+ on your PATH (or use the full path to `blender.exe`).

    blender --command extension validate livemat
    blender --command extension build --source-dir livemat --output-dir release

The zip lands in `release/`. Install it from **Edit > Preferences > Get Extensions > Install from Disk**. GitHub's automatic "Source code" archives are not installable add-ons.

Run the tests in a headless Blender:

    blender -b --factory-startup --python tests/run_tests.py

## Credits

**Author:** Tom Berczeller

## License

Released under the [GNU General Public License v3.0 or later](LICENSE), © 2026 Tom Berczeller.
