# XPU2-foundation

The private research repository for **XPU2**, an asynchronous CPU + GPU path tracer for MoonRay previews in Modo.

The CPU and the GPU render the same image at the same time, and neither waits for the other. Both run MoonRay's own
estimator and shader library, ported, so the image converges to MoonRay's. Anything XPU2 can't render yet goes to
MoonRay XPU automatically, and the Render Log says why.

> **This repository stays private.** Nothing from it goes to the public `Pbaroque20/MoonRayForModo`. Changes flow one
> way only, from the public repository into this one.

![XPU2 architecture](/xpu2/manual/xpu2_architecture.svg)

## Start here

| To | Read |
|---|---|
| Learn how XPU2 works, with the file behind each part | [Engineer manual](/xpu2/manual/README.md) |
| See which MoonRay features are ported and checked | [Feature progress](/xpu2/interactive/FEATURE_PROGRESS.md) |
| Read the design notes | [Asynchronous renderer](/xpu2/interactive/ASYNC.md), [scene indexer and scheduling](/xpu2/interactive/INDEXER.md), [path tracer and shaders](/xpu2/interactive/PATH_TRACER.md) |
| Run XPU2 inside Modo with the private kit | [Kit roadmap](/xpu2/interactive/KIT_ROADMAP.md) and [tools](/xpu2/tools/README.md) |
| Build it | [Manual: building and running](/xpu2/manual/README.md#9-building-and-running) |

## Measured so far

On one machine: an RTX 3090 and an i7-4930K (6 cores, 12 threads).

| Scene | XPU2 (CPU + GPU) | MoonRay | Picture against MoonRay |
|---|---|---|---|
| Dragon from Modo, no HDRI, 1280×720, 16 samples a pixel | 9.1 s | 46.2 s (XPU) | mean ratio 1.002 |
| Polygon test scene, 360×200, 1,024 samples | 12.2 s | 122.8 s (XPU) | block error 0.0006 |
| Dose, 640×480, 64 samples, with the kit's Source Overrides | 9.5 s | 43 s (vector mode) | mean ratio 1.0006 |
| 9 Spheres, 640×480, 64 samples, with the kit's Source Overrides | 64 s | 176 s (vector mode) | mean ratio 0.9997 |
| Interior, 512×340, 64 samples | 51 s | 193 s (vector mode) | mean ratio 1.0003 |
| Material fixtures, the first 10 of the final benchmark, 64 samples | 86–92% less time | | all pass |

The sources and conditions of each number are in the [kit roadmap](/xpu2/interactive/KIT_ROADMAP.md) and the
[indexer notes](/xpu2/interactive/INDEXER.md) (sections 14 and 15).

## What's in this repository

| Folder | What it holds |
|---|---|
| `xpu2/interactive/` | XPU2 itself: the renderer, the session program Modo talks to, the GPU programs, the build scripts, tests and design notes |
| `xpu2/manual/` | The engineer manual and the architecture diagram |
| `xpu2/tools/` | The private kit builder and installer, and the headless Modo export and comparison tools |
| `xpu2/*.md`, `xpu2/*.cc` (top level) | The first attempt (the October 16 bridge experiments). Historical, kept for its findings |
| Everything else | The MoonRay for Modo tree XPU2 builds against and talks to (`native-port/`, `kit/`, ...), as in the public repository |

## Branches

- `xpu2-async`: the main research branch. Work goes here.

## Taking in changes from the public repository

```bash
git fetch origin
git merge origin/<public branch>
git push xpu2-private xpu2-async
```

`origin` is the public repository and `xpu2-private` is this one. Never push the other way: no `git push origin`
from a checkout of this branch.
