# XPU2-foundation

The research repository for **XPU2**, a rendering architecture in which a CPU and a GPU render the same image at the
same time, as peers. Neither device waits for the other, work moves between them sample by sample, and the result is
the image either device would have made alone.

![XPU2 architecture](/xpu2/manual/xpu2_architecture.svg)

## The core ideas

- **A sample is its identity.** A sample is (pixel, sample index, frame seed), and its random numbers come from that
  identity alone. Any device can compute any sample, and work can move between devices without carrying path state.
- **One integrator, two devices.** The path tracer is written once and compiled for the CPU and for the GPU.
- **A cellular work grid.** The image is split into cells of tiles. Each device owns cells, and workers on both
  devices move through them by local rules. Every piece of work is claimed exactly once, by one atomic in host memory.
- **The GPU is never starved and the host never blocks.** A broker thread keeps GPU launches queued, sized from the
  GPU's measured rate, and polls instead of waiting.
- **Each device does what it's suited to.** A scene indexer classifies everything in the scene by which device can
  render it. Cells start on the device suited to what they see. A GPU sample that meets something only the CPU can
  render is handed to the CPU and rendered there from its identity.
- **Memory in tiers.** Host RAM holds every texture level. VRAM holds the coarse levels plus a cache of fine tiles.
  A GPU sample missing a fine tile finishes from a coarser level, and is rendered again in full before the frame ends.
- **Sampling generations.** One generational sampler serves both uniform and adaptive sampling, and spends samples
  where the error is.
- **Audited convergence.** Each device keeps its own film. The films are merged at the end, every pixel's sample count
  is checked, and an image never mixes renderers.

## What it renders: MoonRay

XPU2's first renderer is [MoonRay](https://openmoonray.org/). XPU2 ports MoonRay's path tracer and shader library
(estimator, lights, BSDF lobes, materials, maps, volumes, subsurface, hair, cameras, outputs) to its shared
integrator, so its images converge to MoonRay's. Every port is checked against MoonRay renders. MoonRay XPU is both the
reference and the fallback for anything XPU2 doesn't render yet. [Feature progress](/xpu2/interactive/FEATURE_PROGRESS.md)
lists every feature and its check.

## The showcase: MoonRay for Modo

XPU2 runs as the preview renderer of MoonRay for Modo, through an XPU2 build of the kit. Modo is where XPU2 meets
real production scenes. On one machine (RTX 3090, i7-4930K with 6 cores and 12 threads):

| Scene | XPU2 (CPU + GPU) | MoonRay | Picture against MoonRay |
|---|---|---|---|
| Dragon from Modo, no HDRI, 1280×720, 16 samples a pixel | 9.1 s | 46.2 s (XPU) | mean ratio 1.002 |
| Polygon test scene, 360×200, 1,024 samples | 12.2 s | 122.8 s (XPU) | block error 0.0006 |
| Dose, 640×480, 64 samples, with the kit's Source Overrides | 9.5 s | 43 s (vector mode) | mean ratio 1.0006 |
| 9 Spheres, 640×480, 64 samples, with the kit's Source Overrides | 64 s | 176 s (vector mode) | mean ratio 0.9997 |
| Interior, 512×340, 64 samples | 51 s | 193 s (vector mode) | mean ratio 1.0003 |
| Material fixtures, the first 10 of the final benchmark, 64 samples | 86–92% less time | | all pass |

The conditions of each number are in the [kit roadmap](/xpu2/interactive/KIT_ROADMAP.md) and the
[indexer notes](/xpu2/interactive/INDEXER.md) (sections 14 and 15).

## Start here

| To | Read |
|---|---|
| Learn how XPU2 works, with the files behind each part | [Engineer manual](/xpu2/manual/README.md) |
| Go deeper into the core | [Asynchronous renderer](/xpu2/interactive/ASYNC.md), [indexer and scheduling](/xpu2/interactive/INDEXER.md) |
| Go deeper into the MoonRay port | [Path tracer and shaders](/xpu2/interactive/PATH_TRACER.md), [feature progress](/xpu2/interactive/FEATURE_PROGRESS.md) |
| Run XPU2 in Modo | [Kit roadmap](/xpu2/interactive/KIT_ROADMAP.md), [tools](/xpu2/tools/README.md) |
| Build it | [Manual: building and running](/xpu2/manual/README.md#14-building-and-running) |

## What's in this repository

| Layer | Where |
|---|---|
| XPU2's core | `xpu2/interactive/`: the work grid, the broker, the CPU and GPU lanes, the shared integrator's frame, sampling, texture tiers, the indexer |
| The MoonRay port | `xpu2/interactive/`: the scene plan built from MoonRay's RDL scenes, and the shading library (`shade_*.h`, `light_*.h`, `camera_core.h`, `volume_*.h`, `aov_*.h`) |
| The MoonRay for Modo host | `xpu2/interactive/xpu2_session.cc` (the session the kit starts), `xpu2/tools/` (the XPU2 kit builder and headless Modo tools), and the MoonRay for Modo tree the session talks to (`native-port/`, `kit/`, ...) |
| Documentation | `xpu2/manual/`: the engineer manual and the diagram |
| History | `xpu2/*.md`, `xpu2/*.cc` (top level): the first attempt (the October 16 bridge experiments) |

The core and the MoonRay port share one folder today. The manual's file map says which file belongs to which layer.

## Branches

- `xpu2-async`: the main research branch. Work goes here.

## Taking in changes from MoonRay for Modo

The host's code comes from the MoonRay for Modo repository. Changes flow one way, from there into this repository:

```bash
git fetch origin
git merge origin/<branch>
git push xpu2-foundation xpu2-async
```

In the development checkout, `origin` is MoonRay for Modo and `xpu2-foundation` is this repository. Don't push
`xpu2-async` to `origin`.
