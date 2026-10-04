# MoonRay for Modo

MoonRay for Modo integrates DreamWorks’ open-source MoonRay renderer with **Modo 16.1v9 on Windows**, running natively without WSL. Developed by Raphael Tobar.

The plugin includes CPU and XPU rendering, a dockable live preview, MoonShine material graphs, Shader Tree translation, AOVs, and denoising. Add a **MoonShine Material Override** layer to author native materials in the graph editor.

**Current version: 0.3.39 — experimental development build.**

## Current limitations

- **Modo compatibility:** Full scene parity is unfinished. Some procedural textures, layer effects, masks, light links, and environment behaviors are unsupported or approximate.
- **MaterialX:** Supports a translated subset, not arbitrary MaterialX graphs or custom shader implementations.
- **Geometry and import:** Some motion, instancing, projection, and subdivision behavior differs from Modo. Editable RDL import supports selected objects and materials; it cannot preserve every procedural, shader, or animation.
- **Cryptomatte:** Simultaneous surface categories are supported, but volume coverage remains incomplete. Preview ID colors are not a matte-selection tool.
- **Preview:** Uses a custom dockable viewport, not Modo’s built-in Render View or render slots. Some edits require full scene capture, and some output paths still use temporary files. Post-render preview denoising requires a pass generated with 0.3.39 or later.
- **Production readiness:** Large-scene performance, cancellation and recovery under load, color matching, and clean-machine installation still need broader validation. Recent updates have not been tested; this is not a production-certified release.

Detailed implementation notes and recorded checks are in [docs](docs/). Plugin licensing is in [LICENSE](LICENSE); MoonRay and bundled assets retain their respective licenses.
