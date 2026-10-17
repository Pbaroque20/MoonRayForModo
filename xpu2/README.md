# XPU2 â€” experimental runtime extension

Status: **foundation only; no XPU2 GPU shader or renderer is enabled**.
Started from MoonLightIPR commit `1f8e54b`. This directory is outside the
installed Modo kit and is not included by its packaging tools.

The objective is shorter scene preparation, faster updates, and less time to an
equivalent-quality final image. GPU utilization is a diagnostic, not a success
criterion. MoonLightIPR's approximate shading must not be accumulated with
MoonRay's final samples.

## Architecture contract

XPU2 is an additional, separately selectable architecture once validated.
It does not replace or remove XPU. Existing XPU remains available independently;
the experimental work here changes neither its implementation nor the installed
engine selector.

- Preserve existing XPU as the reference. Begin with whole-render fallback.
  An unsupported scene or failed candidate attempt starts an empty XPU attempt;
  old frames may remain visible but their samples cannot enter the new image.
- A render attempt owns its film, sample batches, and scene revision. Reject
  late results and duplicate batches. Asynchronous completion must not change
  random-number assignment or cause missing/duplicate contributions.
- Scene data is versioned by stable object identity. Classify topology, position,
  transform, shading, and visibility changes separately. Dependency changes
  invalidate consumers; until finer rules are proven, do this conservatively.
- Publish scene updates as transactions. Workers never read a half-updated scene.
  A future native adapter must acknowledge a revision before accepting its work.
  Modo extraction stays on Modo's main thread; only plain data goes to workers.
- RAM holds texture backing data; a bounded VRAM cache holds required mip tiles.
  Missing pages defer work. No final sample uses a coarse substitute merely
  because the required page is absent.
- Geometry demand starts from conservative bounds covering displacement and the
  shutter interval. Proxy hits are requests, not real surface hits or occlusion.
  Resume/retrace after all required geometry is available. Prefetch depth may
  limit speculation, never valid paths, shadows, or indirect light.
- Resource eviction must wait for GPU-use fences. Native queues need backpressure,
  memory budgets, cancellation, and device-loss recovery. The Python protocol
  model does not implement these CUDA responsibilities.
- Start GPU shading with one faithful, complete supported shading sequence.
  General materials, procedural DSOs, volumes, AOVs and per-path CPU fallback
  remain separate milestones. No unvalidated material may silently approximate.

## Implemented in this milestone

`control.py` is a single-coordinator model with immutable tokens:
- SceneIndex validates atomic metadata edits and transitive invalidation.
  Unchanged object records are reused; changed bindings invalidate conservatively.
- RenderGate always chooses XPU today. It rejects stale/duplicate results and
  gives every fallback/restart a new attempt identity.
- DemandQueue coalesces geometry/texture requests, distinguishes resource
  revisions and mip pages, and resumes a path only when all dependencies arrive.

These are protocol prototypes, not connected to Modo, native XPU, CUDA, or a
pixel accumulator. SceneIndex is not yet a geometry store or native upload path.

`reference.py` fingerprints runtime executables, DSOs, shared libraries, PTX and
JSON metadata, rejects inventory drift, extracts explicit renderer timing fields,
and compares corresponding finite raw channel values with supplied tolerances.

## Reproduce

From the repository root, with ordinary Python (no Modo required):

```powershell
python -m unittest discover -s tests -p test_xpu2.py -v
python tools/xpu2_baseline.py --runtime <runtime> --output test-results/xpu2-small
python tools/xpu2_baseline.py --runtime <runtime> --output test-results/xpu2-dense --segments 512
python tools/xpu2_baseline.py --runtime <runtime> --reference test-results/xpu2-small/reference.json --output test-results/xpu2-replay --repetitions 1
python tools/xpu2_compare.py --runtime <runtime> --reference <reference.exr> --actual <actual.exr> --output test-results/xpu2-compare --absolute 0 --relative 0
```

All output directories must be new. The fixture has fixed uniform sampling
(grid 4, 16 samples per pixel), 256x144 output, and no external assets. It is
generated without opening or saving any Modo scene. The baseline fails on CPU
fallback, missing GPU work, missing images, nonzero exit, timeout or runtime
inventory drift.

Runs write the exact scene, complete runtime lock, native logs/statistics and
phase timings. Inherited renderer/OCIO/DSO configuration is stripped; optional
plugin source overrides are unset in this initial reference profile. Hashing
warms caches, and OS/driver cache state is uncontrolled. **These are not cold
startup measurements.** Modo capture and first-correct-pixel times are explicitly
unknown. Log timing categories may overlap; do not sum them.

The comparison tool currently accepts simple full-frame RGBA EXRs only. It
compares decoded float values, not EXR file bytes (metadata/compression can
differ). It does not certify deep images, Cryptomatte metadata, AOV suites,
working-space equivalence or general renderer parity. Numerical tolerances are
mandatory arguments; none has been adopted as the production criterion.

## Initial evidence â€” October 16, 2026

29 control/reference checks passed. Two small and two denser native XPU renders
completed normally with GPU intersection utilization above 97%, no CPU fallback,
and output EXRs. This percentage is a fraction of intersection queries,
**not GPU hardware utilization**.

The dense fixture has 131,584 vertices and 131,072 quads. On this machine:
- Scene serialization plus writing: 3.796 seconds.
- Renderer-reported scene loading: 4.024 / 3.976 seconds.
- GPU BVH preparation: 6.485 / 0.552 seconds.
- Total render prep: 11.686 / 5.282 seconds.
- MCRT: 2.882 / 1.136 seconds.

This is preliminary evidence of preparation cost, not a speedup or a controlled
benchmark. Runtime hashing and first/repeated executions affect cache state.

The small XPU reference repeated at zero tolerance **does not match in RGB**:
maximum red difference 0.000391066; red RMS 0.00000345915. Alpha matches exactly.
The same EXR compared against itself matches exactly in every RGBA channel.
No tolerance was relaxed to turn this into a pass. The cause of the native
repeatability difference is not established; scheduling/intersection-path
differences require investigation. XPU2 cannot claim bitwise parity yet.

See `baseline-20261016.json` for compact measurements and the pinned small-scene
`reference/reference.json` for runtime hashes. The exact small fixture is beside the lock; its recorded bytes are kept without Git newline conversion. Large EXRs/logs remain in test-results.

A fifth XPU run replayed the pinned reference successfully. Timing variability persisted; no speedup is claimed.

## Repeatability follow-up

The fixed-thread matrix and primary-hit probe now identify a repeatable single-thread XPU reference for this fixture. Both single-thread modes repeat, while multithread modes vary; vector and XPU still differ from one another. See [the investigation](REPEATABILITY.md) for measured results, limitations and reproduction. This does not enable XPU2 or certify general parity.

## Next implementation boundary

1. Measure and explain XPU reference repeatability, then establish a documented
   numerical-parity contract including alpha and production AOVs.
2. Add structured binary geometry transactions and acknowledgment to an isolated
   native session. Reuse unchanged meshes, then measure transform/deformation/
   topology updates against full RDLA parsing and rebuilding.
3. Profile intersection batching/synchronization and implement bounded
   asynchronous queues while retaining existing CPU shading.
4. Port and validate a narrow shading path, then RAM-backed mip-tile paging.
5. Experiment with whole-mesh demand loading before dense-mesh chunking.

Nothing from this milestone is installed or exposed as an XPU2 engine option.

Selected-ray diagnostics and the controlled CPU-hit replay are documented in
[SELECTED_RAYS.md](SELECTED_RAYS.md). These remain isolated native experiments,
not an enabled XPU2 rendering backend.

The shadow/contribution follow-up now isolates the larger discrepancy to a
grazing visibility decision. See [CONTRIBUTIONS.md](CONTRIBUTIONS.md) for measured
evidence, diagnostic controls and implications for the XPU2 reference contract.

The copied-ray scale/contact experiment is now measured. See
[ORIGINS.md](ORIGINS.md): larger offsets demonstrably skip the closest blocker;
smaller candidates remain experimental.

The deterministic work-assignment and accumulation model is documented in
[SCHEDULING.md](SCHEDULING.md). It preserves work identities under reordered
completion/retries and bounds the publication backlog. Native sampler/shader
integration and numerical RGB acceptance limits remain unimplemented.

Native AVX sampler splitting/resumption now has a pinned bit-pattern corpus.
See [SAMPLER.md](SAMPLER.md) for the 648-case results and the known-total-count
resume hazard. This does not enable a CUDA sampler or GPU shading.

The first real CUDA sampler subset now matches the native reference on the
RTX 3090. [CUDA_SAMPLER.md](CUDA_SAMPLER.md) distinguishes the supported random
path from the explicitly declined distribution paths. No rendering backend is
enabled.

The distribution follow-up now covers the original corpus with native tables and
an expanded known-count 2D corpus. See [DISTRIBUTIONS.md](DISTRIBUTIONS.md) for
exact GPU matches and the original version-1 capability limits.

The native table/cache transition is now measured. [WINDOW.md](WINDOW.md)
shows why index-only restoration can change samples and validates a separate
cache-aware state envelope. [CUDA_WINDOW.md](CUDA_WINDOW.md) now validates
a separate version-2 boundary kernel, including returned-state continuation.
No rendering backend or installed engine is enabled.

[EXCHANGE.md](EXCHANGE.md) validates actual native CPU/CUDA sampler handoffs,
forced fallback and cross-device retry across three schedules. This remains a
synchronous correctness diagnostic, not an asynchronous rendering backend.

[LAMBERT.md](LAMBERT.md) validates the first CUDA shading component: original
C++ Lambert RGB/PDF/albedo evaluation and geometric validity across 11,520
cases. Diffuse direction sampling, vectorized ISPC parity and renderer integration
remain separate steps.

[LAMBERT_SAMPLE.md](LAMBERT_SAMPLE.md) measures original C++ and AVX8 direction
sampling. CUDA matches the C++ corpus exactly; AVX8 differs in 96 grazing
validity decisions, so the XPU vector compatibility gate remains blocked.

[LAMBERT_VECTOR.md](LAMBERT_VECTOR.md) resolves the measured AVX8 sampling
hazard in a separate GPU math profile, matching 67,584 expanded native cases.
Math profiles must remain explicit during future handoffs; no renderer is enabled.

[SHADING_EXCHANGE.md](SHADING_EXCHANGE.md) validates combined native AVX8/CUDA
sampler and Lambert shading continuations: 108 sequences, atomic stage fallback,
cross-device retries, and exact native-reference results across three schedules.
Ray tracing, throughput and image accumulation remain outside this diagnostic.

[RAY_IMAGE.md](RAY_IMAGE.md) follows these operations into a small custom ray-traced
image: native AVX8, CUDA-only shading and mixed/fallback schedules match every
path event and RGB bit. Traversal and film remain shared host reference code;
this is not native MoonRay image parity, asynchronous execution or a speed claim.
