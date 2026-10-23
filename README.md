# Experimental XPU2 prototype

This `codex/xpu2-foundation` branch publishes an **experimental standalone Windows CPU/GPU renderer**, developed by Raphael Tobar with AI assistance. It is not the production Modo plugin and does not replace original MoonRay XPU.

The prototype combines supported GPU traversal and shading with CPU rendering, resident scene data, progressive updates, resumable paths and pinned-reference fallback. In two synthetic textured direct-lighting scenes, fresh 12-thread comparisons measured about **33% shorter warm render times than XPU**, with the stated quality gates passing. That excludes startup/loading and is not a general performance promise.

**Limits:** static flat triangles; diffuse/emissive materials; supported image maps and a constant environment. Textured scenes are direct-only; untextured transport supports up to eight surfaces. General materials/lights, full Modo integration, dynamic device work sharing, demand-paged textures and production qualification remain unfinished.

- [Prototype, features and limitations](xpu2/interactive/README.md)
- [Build requirements and run instructions](xpu2/interactive/BUILDING.md)
- [Measurements and validation evidence](xpu2/interactive/VALIDATION.md)
- [MIT license for original prototype code](xpu2/interactive/LICENSE) and [upstream license notices](xpu2/interactive/THIRD_PARTY_NOTICES.md)

For the released **MoonRay for Modo plugin**, use [codex/native-avx-modo](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo). Plugin development continues on [MoonLightIPR](https://github.com/Pbaroque20/MoonRayForModo/tree/MoonLightIPR). Earlier XPU2 experiments elsewhere in this branch are historical; the standalone prototype is under `xpu2/interactive/`.
