# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog and the project uses Semantic Versioning.

## [Unreleased]

### Added
- **Blend** tab: RGBA blend masks on meshes, exported as vertex colors. Each channel has a stack of layers with opacity and blend modes.
- Edit Mode tools to set, erase, clear or randomize a channel on the selection, per vertex, polygon, element or edge.
- Select by edge angle: convex, concave or both, within an angle range.
- Saved selections that can be selected again and combined.
- Export checks that make sure engines read the mask as the first vertex color set, with a one-click fix and an FBX round-trip test.
- Three layer kinds: Fill, Paint (painted with Blender's vertex paint brushes, with live preview) and Generator.
- Polygon Fill tool: click a polygon or drag a rectangle in the viewport to fill it, by polygon, connected mesh or UV island, with intersection or center hit-testing and visible polygons only. A highlight shows what will be filled.
- Blend materials: a base LiveMat material with one more per mask channel, mixed property by property (color, metallic, roughness, normal, height, alpha, emission) with a generic height blend, previewed live.
- Pixel masks: a Blend material can read its mask from one painted texture per channel instead of vertex colors. Convert between vertex colors and textures in both directions.
- Export mask textures in the layouts of Unity HDRP LayeredLit, Unity Terrain splatmaps, Unreal (packed or landscape layers), Godot or plain RGBA, as 8-bit PNG or TGA.
- Generators baked from the mesh: Ambient Occlusion, Thickness and Curvature with Cycles, and Edge Wear from face angles. Low, High and Invert remap them live without baking again.

### Changed
- The sidebar panel has side tabs for Build, Blend and Templates. The Material inspector moved into the Build tab.
- Preset node groups also output their surface (base color, metallic, roughness, normal, height, alpha, emission) next to the BSDF.

## [0.2.0] - 2026-11-24

### Changed
- The tangent switch is now **Baked For**, with Blender, Unreal Engine and Unity HDRP (per-pixel bitangent) and Unity Built-in/URP and xNormal (per-vertex). Materials set to Unity keep that setting.
- Per-vertex bitangents update by themselves when an object gets the material or a mesh is edited, so Refresh isn't needed for them anymore.

## [0.1.2] - 2026-11-23

### Fixed
- Build and Assign to Selected scan the folder again first, so maps exported since the last scan aren't dropped.
- Meshes with n-gons get Unity tangents too, from a triangulated copy, instead of shading wrong in Unity mode.
- Picking a texture in the thumbnail picker works even if the folder changed after the picker opened.

## [0.1.1] - 2026-11-23

### Fixed
- Textures exported again while Blender was open kept showing their old version with no hint. The panel now warns when textures changed on disk, and turning on Auto Reload reloads them.

## [0.1.0] - 2026-11-22

First release.

### Added
- Scan a folder, group textures into sets and build materials from them, matching existing materials by name.
- Presets: Default (Metal/Rough), Default (Specular), Unity Standard, Unity Standard (Specular), Unity Mask Map, Unreal, Unreal Packed, Rust Standard and Rust Standard (Spec/Gloss).
- Channel unpacking, gloss to roughness curves, spec/gloss to metal/rough conversion and DirectX normal conversion inside one node group per preset.
- UDIM tiles, and resolution suffixes like `_2k` in file names.
- Material inspector with a texture picker on each thumbnail, per-channel routing for packed maps, tint, metallic, smoothness and strength sliders, and preset switching.
- Detail normal slot on every preset, with strength and tiling.
- Unity tangents option for normal maps baked for Unity's built-in shaders.
- Refresh, Auto Reload and Neutral View.
- Thumbnails for TGA and other formats Blender doesn't preview.
- `tools/calibrate_gloss.py` to find which gloss curve an exporter uses.
