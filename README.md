# MoonRay for Modo

MoonRay for Modo integrates DreamWorks’ open-source MoonRay renderer with **Modo 16.1v9 on Windows**, running natively without WSL. Developed by Raphael Tobar w/ AI-Assistance.

The plugin includes CPU and XPU rendering, a dockable live preview, MoonShine material graphs, Shader Tree translation, AOVs, and denoising. Add a **MoonShine Material Override** layer to author native materials in the graph editor.

**Current version: 0.3.49 — experimental development build.**

**In development: 0.3.49.1 (unreleased).** Adds MoonLightIPR, an approximate NVIDIA GPU preview engine chosen under **System > Preview engine**; output renders still use MoonRay. See [moonlight/README.md](moonlight/README.md) for what it shows, how closely it matches MoonRay, and how to build it.

Also unreleased: **MoonRay > Add MoonRay Item** adds MoonRay's own lights, light filters, cameras, shapes and volumes as Modo items, 30 classes in all, each with its attributes in the item properties. Unset attributes keep MoonRay's defaults. A light names its filters, a portal its environment and a shape its volume by item name; a camera item can be set to render in place of the Modo camera. MoonRay accepts all 30 in `tools/check_moonray_entities.py`; the menu, the item type and the forms have not yet been run inside Modo.

[Download the packaged 0.3.49 kit and Windows runtime](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.3.49) · [Installation instructions](docs/INSTALLATION.md)

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
