# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog and the project uses Semantic Versioning.

## [Unreleased]

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
