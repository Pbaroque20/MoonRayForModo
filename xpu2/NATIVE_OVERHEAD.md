# Host overhead and shared-data experiment

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Experimental measurements on the bounded multi-lobe candidate. Original XPU and
installed kits are unchanged. One native worker, fixed samples, selected diffuse
reflection/transmission operations; this does not qualify arbitrary materials,
multiworker rendering, or the full proposed data hierarchy.

## Diagnostic scopes

`native_overhead.py` adds opt-in `XPU2_OVERHEAD_PROFILE` scopes to an isolated
build. GPU buffers, pinned buffers, streams and events retain their existing
lifetimes. It records cold initialization, slot allocation, host request/ticket
allocation, preparation and copies, context entry/exit, driver enqueue calls,
completion queries and selected locks. Native arithmetic, packet ownership,
queue bounds and film publication are unchanged.

Times overlap. Do not add the scopes into a frame-time breakdown. CUDA API times
are host-call durations, not measured PCIe transfer durations. Request/ticket
allocation scopes exclude destruction. Queue-lock scopes cover public submit
paths, not every window-publication lock. Packet preparation excludes grouped
submission with the tested `XPU2_GROUP_PACKETS=1`; ungrouped mode is not qualified
by these measurements. The 10,000 empty scopes are a calibration observation,
not a correction applied to reported times.

The first build failed before compilation: two request-copy sites used different
source identifiers. The patch now handles both explicitly; the failed report is
retained. The second build succeeded. No installed renderer was affected.

All ten correctness/recovery cases passed with exact float32 RGBA: original XPU,
previous candidate, diagnostics off, two- and one-lobe profiling, missing PTX,
zero queue capacity, partial upload failure, replay mismatch and dropped output.

Warmup plus three rotated timing rounds, seconds (median and range):

- Original XPU: 8.265 (8.223-8.298).
- Previous candidate: 11.586 (11.490-11.785).
- New diagnostic build, profiling off: 11.350 (10.654-11.608).
- Same build, profiling on: 11.934 (11.672-11.945).

All sixteen images matched exactly. Profiling-on paired changes versus off are
+0.595, +1.280 and +0.064 seconds. Instrumentation affects scheduling and runtime;
use unprofiled comparisons for speed claims. The previous/new-off differences
are not a new rendering optimization: no numeric or scheduling policy changed.

Median profiled host scopes: cold initialization 0.167 s; reusable slot allocation
0.000871 s; request allocation 0.070692 s; ticket allocation 0.043075 s; native
record/replay packet preparation 0.099015/0.101150 s; context push/pop
0.015627/0.537006 s; upload/kernel/readback enqueue 0.062393/0.072217/0.035444 s;
event queries 0.038146 s. There are 406,530 request and ticket allocations,
7,118 launches and 122,766 context entry/exit pairs at their medians. These
measurements do not establish the critical path or exclusive GPU compute time.

## Shared records before unique sample data

The user-proposed hierarchy is CPU-coordinated: immutable shared resources first,
then small work descriptors referring to exact typed/versioned resources. Dispatch
is gated by each chunk's dependency readiness, not a scene-wide level barrier.
Old versions must remain leased until their readers finish. Data that differs per
surface hit (normals, UVs, incident direction) must not be treated as globally
constant material data. Texture interpretation, mip/page identity, revisions and
shader support are part of correctness, not optional deduplication hints.

The first native comparison deliberately reuses the existing `XPU2_SHARED_INPUTS`
option with the newer two-lobe/two-flight/two-owned-chunk configuration. The CPU
splits repeated hit/lobe inputs from per-sample coordinates and sends references
to shared records. The compact GPU entry point reconstructs the same inputs and
runs the existing numeric sampler. This is batch-local organization: a combined
payload is uploaded, and its records are rebuilt each batch. It does not yet send
scene-wide shared records in advance, retain them across batches, integrate native
scene-index dependencies into dispatch, stream textures, or reduce host request
allocation. Those remain separate extensions requiring new ownership/version and
recovery gates. No GPU arithmetic or CUDA code changes were made in this test.

## Reproduction

Build with `tools/xpu2_native_overhead_build.py`, using the frozen material-jobs
build as its base and a fresh output directory. Run
`tools/xpu2_native_overhead_probe.py --checks` for image and fault checks, then
without `--checks` for warmup plus three rotated timing rounds. The
`tools/xpu2_native_data_layers_probe.py` uses the same contracts for flat versus
shared inputs, adding a GPU sentinel and compact-transfer coverage checks.
Both accept explicit build, previous build, original runtime, sampler/direct-light
PTX, fixture and fresh output paths. Runtime/source hashes and activity snapshots
are retained. No competing renderer was detected in timing snapshots; short-lived
activity and unrelated system load are not excluded.

The CPU dependency and versioning groundwork is described in
[TEXTURE_DEPENDENCIES.md](TEXTURE_DEPENDENCIES.md) and
[NATIVE_SCENE_INDEX.md](NATIVE_SCENE_INDEX.md); those isolated adapters are not
silently treated as production GPU-residency integration here.

## Shared-record results

All ten checks passed: reference, flat inputs, shared inputs, profiled shared
inputs, deliberate GPU sentinel, missing PTX, zero capacity, partial upload
failure, replay mismatch and dropped output. All ordinary images are bitwise
exact; the sentinel changes 45,629 pixels, confirming image contribution.

Warmup plus three rotated unprofiled rounds also passed all image comparisons:

- Original XPU: median 7.942 s (7.870-7.975).
- Flat-input candidate: median 11.361 s (11.089-11.413).
- Batch-local shared records: median 11.316 s (11.272-11.373).

Paired shared-minus-flat differences are -0.045, -0.141 and +0.284 seconds.
There is **no established speed improvement**. Original XPU remains about
3.4 seconds faster on this fixture; the 30-40% speedup target is not met.

Median scheduled sampler upload bytes fall from 312,215,040 to 78,083,552
(about 75%). Total scheduled payload including readbacks falls from 429,295,680
to 195,164,192 (about 54.5%). These are this bridge's scheduled bytes, not all
renderer transfers or measured PCIe bandwidth. Shared mode still allocates
406,530 requests and ticket holders and uses additional reusable compact buffers;
this is not a reduction in allocation count or demonstrated peak memory usage.

The next implementation target is earlier shared-record preparation with typed,
versioned references carried through host queues, plus bounded reusable host
storage. Retaining records across chunks requires explicit residency readiness,
reader leases and safe reclamation. The existing batch-local comparison does
not establish those extensions, and fewer bytes alone do not justify enabling
sharing by default. Context-exit and repeated preparation costs remain relevant.

Across this round, 48 renders completed: 37 candidate images exactly matched
original XPU, ten runs supplied original-XPU references, and one sentinel was
intentionally different. The counts include diagnostic and fault cases, not
48 independent performance measurements.

[Report hashes, individual timings and measured scopes](native-overhead-20261019.json).
