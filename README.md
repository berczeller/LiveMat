# LiveMat

### A Blender add-on that turns a folder of PBR textures into ready-to-use materials.

![Blender](https://img.shields.io/badge/Blender-5.2%2B-7fd3ff?style=flat-square) ![Type](https://img.shields.io/badge/Blender-extension-ff8fa3?style=flat-square) ![Python](https://img.shields.io/badge/Python-3.13-c4a7ff?style=flat-square) ![Version](https://img.shields.io/badge/version-0.1.0-ffc36b?style=flat-square) ![License](https://img.shields.io/badge/license-GPL--3.0--or--later-6fd6a0?style=flat-square)

---

Texture sets come out of Substance 3D Painter, Designer and game pipelines in many shapes: metal/rough or spec/gloss, OpenGL or DirectX normals, packed channels or one file per map, and a different suffix for every studio (`_normal`, `_nrm`, `_n`). LiveMat reads a folder, recognizes each map from a preset, and builds Eevee-friendly materials with the right channels, color spaces and conversions, so what you see in the viewport matches the tool the textures were made in.

## Features

- Pick a folder and LiveMat finds every texture set in it, matches them to the file's materials by name and creates the rest.
- Built-in presets for common pipelines (see below).
- Correct color spaces, channel unpacking, gloss to roughness, spec/gloss to metal/rough and DirectX to OpenGL normals, all inside one shared node group per preset.
- A material inspector with a thumbnail per texture slot, in the spirit of Unity's material inspector. Swap or clear single textures, tweak strengths, or switch the whole material to another preset.
- **Refresh** reloads every texture from disk and picks up maps you exported later. **Auto Reload** does it for you while you paint.
- **Match Authoring View** switches to a neutral view transform for side-by-side checks with Painter, and back.
- Existing node setups are kept aside in a frame, never deleted, unless you ask for a clean rebuild.

## Presets

| Preset | Maps | Normal |
|---|---|---|
| Default (Metal/Rough) | Base Color, Metallic, Roughness, Normal, Height, AO, Emissive, Opacity | OpenGL |
| Default Specular | Diffuse, Specular, Glossiness, Normal, Height, AO, Emissive, Opacity | OpenGL |
| Unity Standard | Albedo (+ alpha), Metallic (R) + Smoothness (A), Normal, Occlusion (G), Height (G), Emission | OpenGL |
| Unity Standard (Specular) | Albedo (+ alpha), Specular (RGB) + Smoothness (A), Normal, Occlusion (G), Height (G), Emission | OpenGL |
| Unity Mask Map (URP/HDRP) | Base Map (+ alpha), Mask Map (Metal R, AO G, Smoothness A), Normal, Height, Emission | OpenGL |
| Unreal | Base Color, Metallic, Roughness, Normal, AO, Height, Emissive, Opacity | DirectX |
| Unreal Packed | Base Color, ORM (AO R, Roughness G, Metal B), Normal, Height, Emissive, Opacity | DirectX |
| Rust Standard | `_bc`, `_mg` (Metal RGB, Gloss A), `_nrm`, `_ao`, `_disp`, `_em`, `_a` | OpenGL |
| Rust Standard (Spec/Gloss) | `_bc` (diffuse), `_sg` (Specular RGB, Gloss A), `_nrm`, `_ao`, `_disp`, `_em`, `_a` | OpenGL |

Spec/gloss sets are converted to metal/rough inside Blender using the Khronos glTF conversion, so they shade the same as their metal/rough equivalent. AO is loaded with its strength at 0 and height with a bump strength of 0, since neither belongs in a physically based material by default. Turn them up in the inspector if you want them.

## Requirements

- Blender 5.2 or newer.

## Install

1. Download `LiveMat-0.1.0.zip` from the [latest release](https://github.com/berczeller/LiveMat/releases/latest).
2. In Blender, open **Edit > Preferences > Get Extensions**, then **Install from Disk** in the top-right menu, and pick the zip.

GitHub's automatic "Source code" archives are not installable add-ons. Use the `LiveMat-0.1.0.zip` asset.

## Usage

Open the sidebar in the 3D Viewport or the Shader Editor (`N`) and go to the **LiveMat** tab.

1. Pick the texture folder and a preset, then press **Scan Folder**. Each texture set shows up with the material it matched, or **New** when there's none.
2. Click a set to check its files, change its target material, or **Assign to Selected** objects.
3. Untick sets you want to skip and press **Build Materials**.

The **Material** panel (in the sidebar and under **Material Properties**) shows the active material's slots. Use the folder button to load a different file into a slot, the cross to clear it, and the preset menu at the top to rebuild the material with another preset.

After exporting from Painter again, press **Refresh**, or turn on **Auto Reload** and keep painting. Auto Reload checks the files every second and waits until a file stops changing before reloading it. New maps only show up with **Refresh**.

**Options** holds **Subfolders**, **Create Missing** (create materials for unmatched sets), **Rebuild** (clear existing nodes instead of framing them) and **Match Authoring View**.

### Gloss curves

Tools store gloss in different ways. Each preset has a `gloss_curve` (`LINEAR`, `SQUARED` or `SQRT`). To find the one your exporter uses, export the same texture set once with a plain roughness map and once with the packed gloss map, then run:

    blender -b --factory-startup --python tools/calibrate_gloss.py -- Crate_Roughness.png Crate_mg.tga

It compares every pixel and prints the best-fitting curve.

## Building from source

Blender 5.2+ on your PATH (or use the full path to `blender.exe`).

    blender --command extension validate livemat
    blender --command extension build --source-dir livemat --output-dir release

The zip lands in `release/`. Run the tests in a headless Blender:

    blender -b --factory-startup --python tests/run_tests.py

## Credits

**Author:** Tom Berczeller

The spec/gloss conversion follows the [Khronos glTF](https://github.com/KhronosGroup/glTF) `KHR_materials_pbrSpecularGlossiness` conversion notes.

## License

Released under the [GNU General Public License v3.0 or later](LICENSE), © 2026 Tom Berczeller.
