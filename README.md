# MoonRay for Modo

MoonRay for Modo integrates DreamWorks’ open-source MoonRay renderer with **Modo 16.1v9 on Windows**, running natively without WSL. Developed by Raphael Tobar w/ AI-Assistance.

The plugin includes CPU and XPU rendering, a dockable live preview, MoonShine material graphs, Shader Tree translation, AOVs, and denoising. Add a **MoonShine Material Override** layer to author native materials in the graph editor.

**Current version: 0.3.48 — experimental development build.**

[Download the packaged 0.3.48 kit and Windows runtime](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.3.48) · [Installation instructions](docs/INSTALLATION.md)

**Currently implemented**
- Native Windows rendering: CPU/AVX and NVIDIA XPU, with XPU → Vector → Scalar fallback.
- Interactive preview: dockable window, low-resolution IPR, progressive updates, persistent renderer sessions, and worker-tile/bucket overlays.
- Materials: MoonShine Material Override layers, visual node editor, integrated material preview, and native MoonRay material choices.
- Modo scene translation: support for common materials, image textures, normal/bump maps, lights, environments, subdivisions, instances, and replicators—with compatibility limits.
- Render outputs: configurable AOVs, Cryptomatte surface categories, buffer switching, and cached beauty denoising.
- Workflow tools: color/LUT controls, animation output and recovery controls, asset library, and partial editable RDL scene import.

**Missing or incomplete**
- Full Modo parity: remaining Shader Tree effects, procedurals, masks, light linking, and environment behavior.
- Arbitrary MaterialX: currently a supported subset.
- Exact geometry behavior: some instancing, motion, subdivision, UV/projection, and normal-map cases differ from Modo.
- Complete Cryptomatte: volume coverage is unfinished; ID previews aren’t an interactive matte-selection tool.
- Fully incremental preview: some edits still require full scene capture; some image/output paths use temporary files.
- Complete RDL import: not every shader, procedural, or animation converts into editable Modo content.
- Production validation: broader large-scene, recovery, color, hardware, and clean-install checks remain.
- **Production readiness:** Large-scene performance, cancellation and recovery under load, color matching, and clean-machine installation still need broader validation. Recent updates have not been tested; this is not a production-certified release.

Detailed implementation notes and recorded checks are in [docs](docs/). Plugin licensing is in [LICENSE](LICENSE); MoonRay and bundled assets retain their respective licenses.
