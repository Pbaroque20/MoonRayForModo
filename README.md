# MoonRay for Modo

MoonRay for Modo integrates DreamWorks’ open-source MoonRay renderer with **Modo 16.1v9 on Windows**, running natively without WSL. Developed by Raphael Tobar w/ AI-Assistance.

The plugin includes CPU and XPU rendering, a dockable live preview, native MoonRay materials with a graph editor, Shader Tree translation, AOVs, and denoising.

**Current version: 0.3.49 — experimental development build.**

**In development: 0.3.50.1 (unreleased).** In summary:

- **MoonLight**, an approximate NVIDIA GPU preview engine, chosen in the preview window. Output renders still use MoonRay.
- **MoonRay's own items**: 30 lights, light filters, cameras, shapes and volumes as Modo items (dwEnvLight and the rest), with native controls and viewport proxies.
- **A leaner preview window**: one toolbar with a single Render/Stop button, IPR, engine, buffer, exposure, region and a focus picker; render settings on the Render item; one-click Cryptomatte; a working time estimate.
- **Native materials**: assign one to a mesh or add one from the Shader Tree's Add Layer list; each has its own properties form and opens directly in the graph editor. The separate override layer is no longer offered.
- **A redesigned graph editor**: its own window that does not block Modo, a gridded canvas, compact nodes, an add-node search, and a proper control for every property, including a UV map chooser.

[What's new in 0.3.50.1](docs/WHATS_NEW_0350.md) has the details and what has not been checked yet; [moonlight/README.md](moonlight/README.md) covers MoonLight.

[Download the packaged 0.3.49 kit and Windows runtime](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.3.49) · [Installation instructions](docs/INSTALLATION.md)

**Currently implemented**
- Native Windows rendering: CPU/AVX and NVIDIA XPU, with XPU → Vector → Scalar fallback.
- Interactive preview: dockable window, IPR, progressive updates, persistent renderer sessions, worker-tile/bucket overlays, and (in development) the MoonLight GPU engine.
- Materials: native MoonRay materials with their own forms, visual node editor, integrated material preview, and MaterialX Override layers.
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

Detailed implementation notes and recorded checks are in [docs](docs/). Plugin licensing is in [LICENSE](LICENSE); MoonRay and bundled assets retain their respective licenses. MoonLight, the GPU preview engine, was created by Raphael Tobar and is under the same MIT License; it is not a DreamWorks Animation product and is not affiliated with or endorsed by DreamWorks Animation (see [moonlight/NOTICE.md](moonlight/NOTICE.md)).
