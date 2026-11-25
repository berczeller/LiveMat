# LiveMat

### A Blender add-on that turns a folder of PBR textures into ready-to-use materials.

![Blender](https://img.shields.io/badge/Blender-5.2%2B-7fd3ff?style=flat-square) ![Type](https://img.shields.io/badge/Blender-extension-ff8fa3?style=flat-square) ![Python](https://img.shields.io/badge/Python-3.13-c4a7ff?style=flat-square) ![Version](https://img.shields.io/badge/version-0.2.0-ffc36b?style=flat-square) ![License](https://img.shields.io/badge/license-GPL--3.0--or--later-6fd6a0?style=flat-square)

---

Texture sets come out of Substance 3D Painter, Designer and game pipelines in many shapes: metal/rough or spec/gloss, OpenGL or DirectX normals, packed channels or one file per map, and a different suffix for every studio (`_normal`, `_nrm`, `_n`). LiveMat reads a folder, recognizes each map from a preset, and builds Eevee-friendly materials with the right channels, color spaces and conversions, so what you see in the viewport matches the tool the textures were made in.

## Features

- Pick a folder and LiveMat finds every texture set in it, matches them to the file's materials by name and creates the rest.
- Built-in presets for common pipelines (see below).
- Correct color spaces, channel unpacking, gloss to roughness, spec/gloss to metal/rough and DirectX to OpenGL normals, all inside one shared node group per preset.
- A material inspector in the spirit of Unity's: click a slot's thumbnail to pick a texture from the folder, reroute packed channels, and tweak tint, metallic, smoothness and strengths right under each map.
- An optional detail normal slot on every preset, with its own strength and tiling.
- Unity-style tangents for normal maps baked for Unity's built-in shaders.
- **Refresh** reloads every texture from disk and picks up maps you exported later. **Auto Reload** does it for you while you paint.
- **Match Authoring View** switches to a neutral view transform for side-by-side checks with Painter, and back.
- Existing node setups are kept aside in a frame, never deleted, unless you ask for a clean rebuild.
- **Blend**: mix LiveMat materials on a mesh by an RGBA mask, like Rust's Vertex Blend and Packed Mask Blend shaders. Paint the mask as vertex colors in layers (fills, polygon fill, brushes, baked AO, thickness, curvature or edge wear) or as one packed texture with Blender's brushes, preview the result live, and export it for Rust, Unity, Unreal or Godot.

## Presets

| Preset | Maps | Normal |
|---|---|---|
| Default (Metal/Rough) | Base Color, Metallic, Roughness, Normal, Height, AO, Emissive, Opacity | OpenGL |
| Default (Specular) | Diffuse, Specular, Glossiness, Normal, Height, AO, Emissive, Opacity | OpenGL |
| Unity Standard | Albedo (+ alpha), Metallic (R) + Smoothness (A), Normal, Occlusion (G), Height (G), Emission | OpenGL |
| Unity Standard (Specular) | Albedo (+ alpha), Specular (RGB) + Smoothness (A), Normal, Occlusion (G), Height (G), Emission | OpenGL |
| Unity Mask Map (URP/HDRP) | Base Map (+ alpha), Mask Map (Metal R, AO G, Smoothness A), Normal, Height, Emission | OpenGL |
| Unreal | Base Color, Metallic, Roughness, Normal, AO, Height, Emissive, Opacity | DirectX |
| Unreal Packed | Base Color, ORM (AO R, Roughness G, Metal B), Normal, Height, Emissive, Opacity | DirectX |
| Rust Standard | `_bc`, `_mg` (Metal RGB, Gloss A), `_nrm`, `_ao`, `_disp`, `_em`, `_a` | OpenGL |
| Rust Standard (Spec/Gloss) | `_bc` (diffuse), `_sg` (Specular RGB, Gloss A), `_nrm`, `_ao`, `_disp`, `_em`, `_a` | OpenGL |

Every preset also takes a detail normal (`_detail_normal`, `_detail_nrm`, `_detail_n` or `_dnrm`), blended over the main normal the way Unity's detail layer does.

Spec/gloss sets are converted to metal/rough inside Blender using the Khronos glTF conversion, so they shade the same as their metal/rough equivalent. AO is loaded with its strength at 0 and height with a bump strength of 0, since neither belongs in a physically based material by default. Turn them up in the inspector if you want them.

## Requirements

- Blender 5.2 or newer.

## Install

1. Download `LiveMat-0.2.0.zip` from the [latest release](https://github.com/berczeller/LiveMat/releases/latest).
2. In Blender, open **Edit > Preferences > Get Extensions**, then **Install from Disk** in the top-right menu, and pick the zip.

GitHub's automatic "Source code" archives are not installable add-ons. Use the `LiveMat-0.2.0.zip` asset.

## Usage

Open the sidebar in the 3D Viewport or the Shader Editor (`N`) and go to the **LiveMat** tab. The icons on its left switch between **Build** (materials from texture folders), **Blend** (materials mixed by a mask) and **Templates** (your own presets, coming in a later version).

### Build

1. Pick the texture folder and a preset (the field stays red until you do), then press **Scan Folder**. Each texture set shows up with the material it matched, or **New** when there's none.
2. Click a set to preview its maps, change its target material, or **Assign to Selected** objects.
3. Untick sets you want to skip and press **Build Materials**.

The toggles under **Scan Folder** set how scanning and building work: **Subfolders**, **Create** (make materials for sets with no match) and **Rebuild** (clear existing nodes instead of framing them). Next to **Refresh** sit **Auto** (Auto Reload) and **Neutral View**.

The **Material** panel (in the sidebar and under **Material Properties**) shows the active material:

- Click a thumbnail to pick another texture from the material's folder, with large previews and names. Pick **None** to empty the slot. The folder button loads a file from anywhere, the cross clears the slot.
- Packed slots list each channel with a dropdown (R, G, B, A). Change it when a file stores a map in a different channel than the preset expects.
- Tint, Metallic, Smoothness and the strength sliders sit under the map they affect. Tint is white by default, like Unity's albedo color.
- The preset menu at the top rebuilds the material with another preset.

Blender never re-reads an image by itself, so after exporting from Painter again, press **Refresh**, or turn on **Auto** and keep painting. Auto Reload checks the files every second, waits until a file stops changing, and also catches up on exports made while it was off. With Auto off, the panel warns when textures changed on disk and highlights **Refresh**. New maps only show up with **Refresh**.

**Neutral View** switches to a neutral view transform and keeps Material Preview's lighting fixed in the world, as game engines do. Press it again to get your settings back.

### Blend

Blend mixes LiveMat materials on a mesh by an RGBA mask, the way Rust's Vertex Blend and Packed Mask Blend shaders do: a **Base** that's always on, then the **R**, **G** and **B** layers in that order, so B ends up on top. The alpha channel is ambient occlusion. The two buttons at the top of the **Blend** tab pick where the mask lives:

- **Vertex Blend**: the mask is the mesh's vertex colors, exported with the FBX.
- **Mask Blend**: the mask is one packed RGBA texture on the UVs, next to an optional macro normal map.

**Materials.** **Create Blend Material** replaces the active material with one that blends LiveMat materials: pick the **Base** and one material for each of R, G and B. They're mixed property by property (color, metallic, roughness, normal, height, alpha, emission) under one Principled BSDF, as engine shaders do. **AO Strength** sets how much the alpha channel darkens the result. With **Height Blend** on (its popover), a layer comes in where its mask is high and its height map shapes the edge: **Factor** is how much the height pulls the edge and **Falloff** how soft it is, per layer, like the blend factor and falloff of the engine shader. A layer with mask m and height h gets the weight `clamp(((m - 0.5) * (f + s) + (h - 0.5) * f + s / 2) / s, 0, 1)`, with f the Factor and s the Falloff. Off, the weight is simply m. The refresh button rebuilds Blend materials after their sources change.

#### Vertex Blend

Each channel is edited on its own and holds a stack of layers, like masks in Painter: a layer can be hidden, faded with **Opacity** or blended with **Add**, **Subtract**, **Multiply**, **Lighten** or **Darken**. LiveMat blends the layers into one color attribute, **LiveMat Blend**, which is what gets exported.

The **+** next to the layer list adds one of three kinds:

| Layer | What it holds |
|---|---|
| Fill | Values written on selections (Set, Randomize) or with the Polygon Fill tool |
| Paint | Brush strokes: press **Paint**, paint with Blender's vertex paint brushes (white applies the layer's **Value**, black removes it), press **Done**. The material preview follows each stroke. |
| Generator | Ambient Occlusion, Thickness or Curvature baked with Cycles, or Edge Wear from the angles between faces. **Low**, **High** and **Invert** reshape the bake live; **Rebake** after changing the mesh. |

1. Select a mesh and press **Add Blend Mask**.
2. Pick a channel with the **R**, **G**, **B**, **AO** chips. The three buttons next to them show your material, the RGBA mask, or the active channel in grayscale. **Empty Value** is what the channel holds where no layer covers it (1 for AO).
3. **Polygon Fill** works like Painter's tool: click a polygon or drag a rectangle to fill it with the **Value**. Its options (the gear) fill by **Polygon**, connected **Mesh** or **UV Island**, and pick polygons a rectangle touches (**Intersect**) or whose center is inside (**Center**), visible ones only unless you turn that off. Ctrl clears, Esc or right-click finishes, each fill is one undo step.
4. In Edit Mode the tab adds tools for the selection:
   - **Set** writes the value, **Erase** writes 0, **Clear** makes the layer transparent there so the layers below show.
   - **Randomize** writes random values between **Min** and **Max**, one per vertex, polygon, connected element or selected edge. Its options also hold a fixed seed and **Smooth Polygons**, which lets face selections fade into their neighbors.
   - **By Edge Angle** selects convex edges (ridges), concave edges (valleys) or both within an angle range, as edges, vertices or faces. Fill them for edge wear or corner dirt.
   - **Selections** keeps selections for later: **+** adds the current one, clicking an item selects it again (Shift+click adds to the current selection). Tick several and **Combine** them as a union, intersection or subtraction.

Everything is stored on the mesh, so it's saved with the .blend and shared by linked duplicates. The layers and saved selections are hidden attributes that FBX doesn't export. Adding, removing and reordering layers happens in Object Mode, where undo covers both the list and the data.

#### Mask Blend

The Blend material reads a **Packed Mask**: R, G and B are the layer masks and A is ambient occlusion, all on the **UV Map** you pick. A **Macro Normal** on the same UVs, the object's unique baked normal map, is combined with the layers' tiling normals.

- **New** makes an empty mask at the chosen resolution: no layers and no occlusion.
- The **R**, **G**, **B**, **AO** buttons open Texture Paint on that channel, in grayscale. White applies it, black removes it. **Done** writes it back into the packed mask, which is saved inside the .blend.
- **Bake from Vertex Blend** bakes the vertex mask into the packed mask through the UVs, so you can block out with Polygon Fill and Generators and refine with brushes.

A mask painted in Substance Painter works as is: load it in **Packed Mask** with the same UVs.

#### Export

**Vertex colors.** Unity and Unreal read only the first color set of an FBX, and LiveMat stores the mask so Blender's default FBX settings deliver the exact values (a value of 0.5 arrives as 128/255). The **Export** section warns when another color attribute would be exported first and fixes it with **Export the Mask First**, which keeps that attribute's data. **Check FBX Export** exports the object to a temporary file, reads it back and confirms the engine gets the same values.

**Mask textures.** **Export Mask Texture** saves the mask, from either mode, as 8-bit PNG or TGA in the layout you pick in its options, which also show the import settings it needs:

| Layout | Files |
|---|---|
| Rust Packed Mask | One RGBA mask: R, G, B layers, A ambient occlusion |
| Unity HDRP LayeredLit | One RGBA layer mask: R, G, B drive layers 1 to 3, A the main layer |
| Unity Terrain Splatmap | Base, R, G and B as four terrain layer weights that add up to 1 |
| Unreal (Packed RGBA) | One RGBA image, imported with Masks compression |
| Unreal Landscape Layers | One grayscale weight image each for Base, R, G and B |
| Godot | One RGBA image, imported Lossless |

### Normal maps and tangents

Normal maps are stored relative to the surface's tangent and bitangent. Blender, Unreal and Unity HDRP rebuild the bitangent per pixel; Unity's built-in and URP shaders and xNormal build it per vertex. A map baked for one shades slightly differently in the other, most visibly on low-poly meshes and stretched UVs.

Pick what the maps were baked for under **Normals > Baked For** in the Material panel:

| Per pixel | Per vertex |
|---|---|
| Blender, Unreal Engine, Unity HDRP | Unity (Built-in, URP), xNormal |

For per-vertex targets LiveMat stores the bitangent in a `.livemat_bitangent` attribute on the meshes using the material (FBX doesn't export it) and reads it back in the shader. It keeps that attribute current by itself: objects that get the material, and meshes whose geometry, UVs or normals change, are updated as soon as they're back in Object Mode. N-gons are triangulated on a temporary copy for this, the way Unity triangulates on import, so the meshes themselves don't change.

In Substance 3D Painter, **Compute tangent space per fragment** decides which convention a bake uses: off matches the per-vertex targets, on matches the per-pixel ones.

### Gloss curves

Tools store gloss in different ways. Each preset has a `gloss_curve` (`LINEAR`, `SQUARED` or `SQRT`). Unity's Standard shader and its descendants read smoothness as one minus perceptual roughness, which is `LINEAR`, so exporting plain glossiness (inverted roughness) matches every built-in preset. To check what a custom exporter does, export the same texture set once with a plain roughness map and once with the packed gloss map, then run:

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

The Blend tools are inspired by Damian Lazarski's Vertex Color Channel Tool for 3ds Max.

## License

Released under the [GNU General Public License v3.0 or later](LICENSE), © 2026 Tom Berczeller.
