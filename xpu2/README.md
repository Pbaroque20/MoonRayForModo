# XPU2 â€” experimental runtime extension

Status: **experimental native GPU shading and queue validation; no installable
or selectable XPU2 renderer yet**.
Latest: [rough-diffuse math shortcut, image differences and timing](NATIVE_MATH_SHORTCUT.md).
Previous: [per-flight GPU record tables, version checks and timing](NATIVE_RESIDENT_RECORDS.md).
Previous: [early shared host records, lifetime checks and timing](NATIVE_PREPARED_RECORDS.md).
Previous: [host overhead and shared-data tests](NATIVE_OVERHEAD.md).
See also [integration profiling and bounded completion waits](NATIVE_INTEGRATION_PROFILE.md).
See [scoped shadow work and native queue-failure isolation](NATIVE_SHADOW_WORK.md),
[split native material sampling and rejected cross-path helping](NATIVE_MATERIAL_STAGE.md),
[native lobe lookahead and shared inputs](NATIVE_READY_WORK.md),
[grouped native shading packets](NATIVE_BATCH_GROUPS.md),
[native batches in flight](NATIVE_FLIGHTS.md),
[native neighbor scheduling and render timing](NATIVE_TILE_SCHEDULING.md),
[neighbor-first scheduling model](LOCAL_TILE_SCHEDULING.md),
[broader native diffuse shading](BROADER_DIFFUSE.md),
[native asynchronous GPU shading and early dispatch](NATIVE_GPU_SHADING.md),
[native first-bounce path restoration](NATIVE_PATH_RESTORE.md),
[owned texture-to-GPU shading-stage dispatch](SHADING_DISPATCH.md),
[native terminal-radiance suspension and film resumption](NATIVE_FILM_CONTINUATIONS.md),
[texture-ready work dispatch](TEXTURE_WORK.md),
[scene-index texture dependencies](TEXTURE_DEPENDENCIES.md),
[background texture decoding and cancellation](TEXTURE_ASYNC.md),
[hierarchical texture residency policy](TEXTURE_RESIDENCY.md),
[CUDA point/bilinear filtering checks](TEXTURE_FILTER.md),
[native OIIO mip loading and parity checks](TEXTURE_OIIO.md),
[bounded native texture-tile residency](TEXTURE_CACHE.md),
[region hierarchy and importance scheduling](REGION_PRIORITY.md),
[persistent native index updates](RDL_LIVE_INDEX.md),
[native RDL adaptation and metadata optimization](NATIVE_SCENE_INDEX.md),
[native indexed scene resources and Morton convergence checkpoints](INDEXED_SCENE.md),
[coalesced native-worker jobs and upload ordering](COALESCED_FILM.md),
[live transfer and graph replay measurements](FILM_TRANSFERS.md),
[live fused shading and contribution dispatch](LIVE_FUSED_FILM.md),
[live contribution-window batching](FILM_WINDOWS.md),
[live GPU contribution images and measured overhead](FILM_IMAGE.md),
[dedicated GPU queue during active rendering](DEDICATED_QUEUE.md),
[native scene drains and persistent-session validation](NATIVE_SCENE_DRAIN.md),
[scene lifetime and retained GPU jobs](SCENE_LIFETIME.md),
[owned shadow requests and native visibility](SHADOW_REQUESTS.md),
[live GPU environment evaluation](LIVE_ENV.md),
[fused GPU sampling and contribution validation](FUSED_CONTRIBUTION.md),
[local coordination and larger GPU batches](LOCAL_BATCHES.md),
[alternating CPU/GPU worker measurements](ALTERNATING_WORKERS.md),
[owned native contribution replay](OWNED_CONTRIBUTION.md),
[native lighting/GPU overlap](NATIVE_LIGHT_OVERLAP.md),
[independent CPU/GPU scheduling measurements](SCHEDULING_OVERLAP.md),
[combined readback and audit controls](PACKED_READBACK.md),
[pinned asynchronous transfers](ASYNC_TRANSFERS.md),
[explicit native window dispatch](WINDOW_DISPATCH.md),
[native overhead profiling](PROFILING.md),
[bounded native shading batches](BATCHED_SHADING.md),
[native deferred shading](DEFERRED_SHADING.md),
[correlated native sampler/shader capture](CORRELATED_STATE.md),
[native numeric state capture](NATIVE_SURFACE_STATE.md),
[owned CPU-resume leases](CONTINUATIONS.md) and
[nonblocking queue tickets](ASYNC_QUEUE.md) for the latest integration steps.
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

[NATIVE_INTEGRATION.md](NATIVE_INTEGRATION.md) now connects the CUDA Lambert
operation to the native XPU integrator in an isolated diagnostic DLL. Two live
replacement renders match every float32 RGBA pixel and all measured shader
outputs; an intentional color perturbation proves the bridge reaches the film.
Calls are still synchronous and retain CPU validation, so no acceleration is claimed.

[NATIVE_QUEUE.md](NATIVE_QUEUE.md) adds bounded GPU dispatch and measured CPU/GPU
overlap in the native integrator. Single-worker results remain exact; the separate
four-worker bitwise image gate is unresolved. GPU callers still wait, and no
acceleration or production lifecycle is claimed.

[NATIVE_CONTEXT.md](NATIVE_CONTEXT.md) investigates shared CUDA-context lifetime
and prepares a reusable batch packing/ownership contract. Context image controls
and standalone contract checks are distinct from timing and native integration.

[NATIVE_TRANSPORT.md](NATIVE_TRANSPORT.md) connects the reusable packing/ownership
contract to the isolated native dispatcher. Same-build controls, exact image
gates, failure drains and held-stream cancellation distinguish correctness from
render speed. The production XPU path remains unchanged.

[NATIVE_EFFICIENCY.md](NATIVE_EFFICIENCY.md) separates lean wire transfers,
paced completion queries and deterministic CPU/GPU lobe ownership. It requires
exact images and nonzero consumed CPU work before crediting independent shading.

[NATIVE_MATERIAL_WINDOW.md](NATIVE_MATERIAL_WINDOW.md) adds bounded numeric
prefetch across already-owned native shading blocks. It preserves native
contribution order, verifies input identities before reuse, and cancels unused
tickets; it does not retain arbitrary shader stacks beyond the bundle lifetime.

The optional [native input preparation experiment](NATIVE_INPUT_PREPARATION.md)
qualifies invariant lobe packing and grouped replay checks against the bounded
material-window candidate, without removing input validation or changing XPU.

The [numeric native sampler-cache experiment](NATIVE_SAMPLER_CACHE.md) reuses
checked sampler setup within a material window, with native rebuild verification
and forced-miss controls. It remains opt-in and preserves original XPU.

The [wider native-window experiment](NATIVE_WIDE_WINDOWS.md) identifies the native
32-ray chunk limit, measures two outstanding GPU batches with larger bounded
chunks, and separately reports native rounding differences and timing gains.
It remains opt-in; strict original-XPU bitwise parity is not claimed.

The [64-ray chunk follow-up](NATIVE_CHUNK64.md) restores exact original-XPU
images on the tested one-worker fixtures while retaining two outstanding GPU
batches. It includes paired timing against the 128-ray rounding comparison.

The [owner-thread chunk preparation experiment](NATIVE_OWNED_CHUNKS.md) overlaps
CPU preparation of two/four independent native chunks with GPU work, preserving
64-ray math and original contribution order. Exact-image and cancellation
evidence is recorded alongside paired timings; original XPU remains faster.

The [coordination experiment](NATIVE_COORDINATION.md) tests earlier staging
rejection and ready-only grouped result claims. Exact images and recovery pass;
the small combined timing difference is not yet a reliable performance gain.

The [bounded local-neighbor experiment](NATIVE_LOCAL_NEIGHBOR.md) uses tile
location as a hint, with immediate nonlocal fallback and aging. Exact-image,
policy and recovery checks pass, but reduced search work has not demonstrated
a render-speed gain; the policy remains opt-in.

The [native timeline diagnostic](NATIVE_TIMELINE.md) separates host waits, CPU
preparation and CUDA shading intervals, with clock calibration and tracing-overhead
checks. It diagnoses remaining costs without changing the rendering architecture.

The [native attribution comparison](NATIVE_ATTRIBUTION.md) separates chunk-size
effects, disabled-adapter overhead, forced CPU fallback and GPU-enabled rendering
using the same frozen candidate and exact original-XPU images.

The [grouped native replay experiment](NATIVE_REPLAY.md) combines bounded packet
completion checks under one lock while retaining full input identity and fallback
checks. It remains opt-in and is measured against the same-build switch-off path.

The [native sample-coordinate reuse experiment](NATIVE_SAMPLE_REUSE.md) avoids
regenerating already-owned random coordinates during material resume. Exact
image, bit-verification and recovery checks pass on the tested fixtures; the
small measured gain is against its same-build control, not original XPU.

The [larger GPU direct-light unit](NATIVE_DIRECT_LIGHT_UNIT.md) qualifies diffuse
material evaluation, PDFs, MIS weighting and unshadowed lighting together against
captured native results. Its capture runtime still publishes native CPU results.

The [native asynchronous direct-light connection](NATIVE_DIRECT_LIGHT_ASYNC.md)
uses those GPU results in the image, with bounded numeric ownership, native-order
consumption, fallback and cancellation checks. It remains opt-in: the current
small work groups increase handoff costs and have not demonstrated acceleration.

The [grouped light-sample experiment](NATIVE_LIGHT_GROUPS.md) combines samples
already owned by one native light call into one bounded packet. It preserves
result order and lifetime and reduces submissions by 75%, but paired timings
show no speed gain: the existing queue already coalesces most of that work. Wider
cross-call batching remains pending.

The [alternating device-claim experiment](NATIVE_LIGHT_TILE_CLAIMS.md) gives
supported direct-light tasks CPU/GPU tile preferences and lets either device
claim untouched work from the other. Claims are exclusive and native output
consumption stays ordered. This is not complete independent GPU tile rendering;
it remains a default-off experiment with the qualification scope recorded there.

The [descriptor-first light scheduler](NATIVE_LIGHT_LAZY.md) reuses bounded
neighbor selection before GPU payload preparation. CPU-owned work bypasses
packing; exact-image, recovery and fault gates pass. Paired timing improves on
eager stealing, but the direct-light-off control locates most of the remaining
gap in the earlier XPU2 material pipeline. The report lists active features and
separates this render test from unmeasured scene-loading and update benefits.

The [bounded multi-lobe material experiment](NATIVE_MATERIAL_JOBS.md) lets the GPU
consume several supported material components per native submission while
preserving sample order, CPU fallback and bounded ownership. Qualification and
performance are recorded separately; it is not a general GPU material renderer.
