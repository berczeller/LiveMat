# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog and the project uses Semantic Versioning.

## [0.1.0] - 2026-11-22

First release.

### Added
- Scan a folder, group textures into sets and build materials from them, matching existing materials by name.
- Presets: Default (Metal/Rough), Default Specular, Unity Standard, Unity Standard (Specular), Unity Mask Map, Unreal, Unreal Packed, Rust Standard and Rust Standard (Spec/Gloss).
- Channel unpacking, gloss to roughness curves, spec/gloss to metal/rough conversion and DirectX normal conversion inside one node group per preset.
- UDIM tiles, and resolution suffixes like `_2k` in file names.
- Material inspector with thumbnails, per-slot load and clear, strength sliders and preset switching.
- Refresh, Auto Reload and Match Authoring View.
- `tools/calibrate_gloss.py` to find which gloss curve an exporter uses.
