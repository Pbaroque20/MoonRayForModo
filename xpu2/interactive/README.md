# Experimental XPU2 prototype

XPU2 is an experimental standalone Windows CPU/GPU renderer developed by Raphael Tobar with AI assistance. It explores indexed immutable scenes, resident GPU data and asynchronous path continuation alongside a pinned MoonRay XPU fallback. **It is not a production renderer, a replacement for MoonRay XPU, or an installed Modo feature.**

## What works

- CPU and OptiX/CUDA lanes perform supported traversal and shading, with fixed 50/50 checkerboard sample ownership and up to 12 CPU workers.
- Static flat-shaded triangles, opaque diffuse/emissive USD Preview materials, supported RGB image maps, software mip/filter evaluation and a constant environment.
- Bounded progressive batches preserve unfinished paths across frame deadlines. A missing texture can resume after a bounded whole-mip refill or migrate to the CPU.
- Immutable scene data and GPU resources persist between requests. The host receives progressive float32 images through pipes.
- Cancellation, stale-result rejection and whole-scene fallback to a pinned Windows MoonRay XPU build. Native and reference pixels are never blended. Reference rendering remains the default; native mode is opt-in.

## Measured results, not a general promise

On an RTX 3090 and an i7-4930K (6 cores / 12 logical threads), two synthetic textured direct-lighting scenes passed frozen image-quality gates. At 12 threads their fresh warm render-phase medians fell from **4.095 to 2.763 seconds** and **6.882 to 4.605 seconds**, about **33% less time than original XPU**. At one thread the reductions were about 45% and 40%.

Those comparisons use original XPU's reported MCRT time versus XPU2 render-window wall time. They exclude startup, loading and output. One native gallery run was slower than the reference median and is retained in the evidence. They do not prove an end-to-end or arbitrary-scene speedup.

The subsequent shared-table update cut cold OptiX module compilation from **14.461 to 10.311 seconds** (29%) in three private-empty-cache runs per build. Its 1/12-thread images remain byte-identical to the preceding native images and warm-speed gates passed. This is a comparison against the previous XPU2 build, not another fresh XPU timing comparison.

See [validation and numerical evidence](VALIDATION.md).

## Important limitations

- Textured 3D scenes support **direct lighting only**. Untextured diffuse/emissive transport supports up to eight surface interactions.
- No native glass, metal, glossy BSDFs, SSS, arbitrary material graphs, general light types, curves, hair, volumes, motion blur or complete Modo scene parity.
- Flat geometric normals and a restricted camera/material/geometry admission domain; unsupported scenes require the reference path, not silent approximation.
- Fixed device ownership; no dynamic CPU/GPU donation, production SIMD/NUMA scheduler or measured 30 ms interactive guarantee.
- Texture residency uses bounded whole-mip uploads. Selective demand paging, LRU eviction and RAM/VRAM spill tiers are unfinished. Fine refill uses a 64 MiB texel budget; existing device/pinned staging limits remain.
- Native preview/decode is capped at **1,048,576 pixels**, below 1920×1080.
- Frozen RDLB packages are the input. There is no Modo change-tracking adapter or kit installation in this prototype.
- Native/reference outputs remain globally unqualified. Reference multiworker variation is measured on finite fixtures; a clean source-to-reference-binary rebuild is not established.
- Source publication only: no portable installer, runtime bundle or SDK redistribution. Building requires the existing Windows MoonRay development toolchain; clean-machine build/install validation remains open.

## Build, run, and licensing

Read [BUILDING.md](BUILDING.md) before running. Original code is [MIT-licensed](LICENSE), copyright Raphael Tobar. Upstream-derived portions retain Apache-2.0/BSD terms and notices; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Earlier experiments elsewhere under `xpu2/` are historical. This directory is the current standalone prototype; comments describing its former private development do not restrict the licenses above. Local historical reports and generated assets are not all included. Source snapshots and scripts retain experimental guards rather than silently relaxing them for publication.
