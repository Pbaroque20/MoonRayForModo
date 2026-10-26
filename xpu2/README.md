# XPU2: prototype and research

> **XPU2-foundation (private):** XPU2 is now the asynchronous renderer on `xpu2-async`. Start with the
> [engineer manual](manual/README.md). The page below describes the public 22 October prototype it grew from.

**Start with the [current experimental prototype](interactive/README.md).** This branch contains two distinct efforts. The October 16 tests began the **first attempt**, which is now historical. The newer standalone prototype lives in `interactive/` and has its own implementation, validation and limitations.

## Current work: standalone CPU/GPU prototype

The newer architecture combines supported CPU/GPU rendering, resident scene data, progressive output, resumable paths and pinned-reference fallback. It is experimental Windows source, not an installed Modo feature or a production replacement for XPU.

1. [Features and current limitations](interactive/README.md)
2. [Build requirements and running the preview](interactive/BUILDING.md)
3. [October 22 measurements and validation limits](interactive/VALIDATION.md)
4. [Numerical evidence and report hashes](interactive/evidence/manifest.json)
5. [Publication build and recovery checks](interactive/PUBLICATION_CHECKS.json)
6. [Original-code MIT license](interactive/LICENSE) and [upstream notices](interactive/THIRD_PARTY_NOTICES.md)

The published comparison measured about 33% shorter warm render time at 12 threads on two restricted synthetic textured direct-lighting scenes. Startup/loading are excluded; this is not a general scene or end-to-end speed claim. Native rendering uses the newer spec's statistical-equivalence gates; exact checks of particular kernels or fallback pixels do not imply universal bit-exact parity with XPU.

## First attempt: October 16 tests and subsequent bridge experiments

The first attempt explored offloading individual operations from MoonRay's native shading path. Its repeatability tests, exact-parity gates, queue experiments and overhead measurements are historical findings. They must not be read as the status or measured performance of the newer standalone prototype.

- [Historical overview of the first attempt](HISTORICAL_OVERVIEW.md): preserved original narrative and initial October 16 measurements.
- [Research index by topic](RESEARCH_INDEX.md): all first-attempt reports, including later follow-ups.
- [First-attempt repeatability investigation](REPEATABILITY.md).
- [First-attempt material-cost ceiling](NATIVE_MATERIAL_CEILING.md): the earlier bridge's cost analysis, not the newer prototype's benchmark.

## Where the code lives

- [`interactive/`](interactive/): current standalone prototype, tests, build tools and published evidence.
- Files directly in `xpu2/`: first-attempt bridge code, protocol models, probes and historical reports. Some shared dependencies remain in use; historical classification does not mean every source file is obsolete.
- [`reference/`](reference/): first-attempt pinned reference data. The current prototype uses its own [reference lock](interactive/reference-lock.json).

Reports retain their original paths so existing GitHub links continue to work. Historical acceptance criteria and unfinished plans describe their own experiment; consult the current prototype documentation for today's scope.
