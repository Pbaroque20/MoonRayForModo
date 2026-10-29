# Experimental XPU2 prototype

*XPU2: Asynchronous Monte Carlo Path Tracer designed by Raphael Tobar. Not affiliated with or endorsed by DreamWorks Animation; MoonRay and OpenMoonRay are DreamWorks Animation's.*

This `codex/xpu2-foundation` branch publishes an **experimental standalone Windows CPU/GPU renderer**, developed by Raphael Tobar with AI assistance. It is not the production Modo plugin and does not replace original MoonRay XPU.

The prototype combines supported GPU traversal and shading with CPU rendering, resident scene data, progressive updates, resumable paths and pinned-reference fallback. In two synthetic textured direct-lighting scenes, fresh 12-thread comparisons measured about **33% shorter warm render times than XPU**, with the stated quality gates passing. That excludes startup/loading and is not a general performance promise.

**Limits:** static flat triangles; diffuse/emissive materials; supported image maps and a constant environment. Textured scenes are direct-only; untextured transport supports up to eight surfaces. General materials/lights, full Modo integration, dynamic device work sharing, demand-paged textures and production qualification remain unfinished.


## How XPU2 samples

XPU2 renders a preview in **generations**. Every pixel first gets a few samples, a first look. Then each generation
looks at where the picture is still noisy and sends the next samples there, and parts that are already clean stop.
Plain areas such as a wall or the sky finish quickly; hard ones such as glossy reflections, soft shadows and glass get
more. Only where the samples go changes, not how each one is worked out, so the picture settles to MoonRay's.

The settings are in **Render Settings**, under XPU2 Sampling Generations:

| Setting | What it does | Default |
|---|---|---|
| Generation Samples | What the render is worth, in samples a pixel on average | 16 |
| Halting Rule | **Time**: stop after about the time a plain render of that many samples takes, spent where the noise is. **Exact**: every pixel gets exactly that many | Time |
| Halt at Noise | A part of the picture stops once it is this clean (lower is cleaner, and slower) | 10 |
| First Look | Samples every pixel gets before the generations choose | 4 |
| XPU2 Most Samples | The most one pixel may get | 16 times the average |
| XPU2 CPU Workers | The processor works beside the graphics card | On |

A scene set to adaptive sampling uses its own Minimum Samples, Maximum Samples and Target Error. While XPU2 renders
the preview, MoonRay's own sampling fields are greyed and show what XPU2 takes; final renders use them as always.

The line under the picture says how it samples: **XPU2 Gen. 16 ps avg (4-256), noise 10** is 16 samples a pixel on
average, 4 to 256 in any one pixel, each part stopping at noise 10. The MoonRay Terminal shows each generation as it
goes, with how much of the picture is still sampling.

## More

- [Documentation guide: current prototype versus historical first attempt](xpu2/README.md)
- [Prototype, features and limitations](xpu2/interactive/README.md)
- [Build requirements and run instructions](xpu2/interactive/BUILDING.md)
- [Measurements and validation evidence](xpu2/interactive/VALIDATION.md)
- [MIT license for original prototype code](xpu2/interactive/LICENSE) and [upstream license notices](xpu2/interactive/THIRD_PARTY_NOTICES.md)

For the released **MoonRay for Modo plugin**, use [codex/native-avx-modo](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo). Plugin development continues on [MoonLightIPR](https://github.com/Pbaroque20/MoonRayForModo/tree/MoonLightIPR). Earlier XPU2 experiments elsewhere in this branch are historical; the standalone prototype is under `xpu2/interactive/`.
