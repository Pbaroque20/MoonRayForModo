# Descriptor-first direct-light scheduling

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This opt-in XPU2 candidate chooses CPU/GPU ownership before preparing GPU
payloads. It reuses the existing bounded neighbor policy. Original XPU and the
installed Modo kit are unchanged; the new policy defaults to off.

## Native integration

A native `drawLightSamples` call publishes a fixed array of at most 32 small
records: lane masks, tile hints, device preference and eligibility. CPU claims
stay in native shading and do not allocate or pack a GPU job. The GPU worker
reserves eligible records; their native owner then packs immutable numeric
inputs and submits them through the existing CUDA queue. The GPU worker never
reads native scene or arena pointers.

Each record has exclusive ownership. Either device can steal only untouched
records. Submitted work drains before its window closes, and the native owner
integrates GPU results before returning. Sample identities, per-lane lobe
summation, native shadows and film publication retain their existing behavior.

`XPU2_LIGHT_LAZY=shared` uses bounded descriptors without locality preference.
`XPU2_LIGHT_LAZY=neighbor` uses the existing neighbor policy with a separate
cursor for each device, shared fallback and aging. Both use
`XPU2_LIGHT_TILES=steal`; leaving lazy mode off preserves the eager control.
Eligibility filtering examines at most 32 descriptors; neighbor selection
examines at most 16 candidates per claim. These are separate bounds.

At most 512 lanes are reserved per window. GPU eligibility is conservative;
per-light packing can still reject a reservation, in which case the native
owner evaluates it on CPU. The `packed` counter measures preparation attempts,
not allocations: `packed = submitted + fallback`. CPU-owned descriptors never
enter that packing path.

This schedules supported primary diffuse direct-light tasks within one native
call. It does not create independently rendered GPU image tiles, arbitrary GPU
materials, or a cross-call work pool. Qualification uses one native worker,
fixed sampling and empty AOVs; adaptive frames bypass the offload. Wider native
worker coverage and production performance remain unqualified.

## Validation tools

- `tools/xpu2_light_window_contract.py`: fixed metadata, no heap allocation in
  the scheduler, stale/duplicate rejection, reservation bounds and concurrent
  exclusive claims. Its allocation check does not cover native shading.
- `tools/xpu2_native_light_lazy_build.py`: creates an isolated runtime from the
  frozen light-tiles-v3 build and verifies source/object identities.
- `tools/xpu2_native_light_lazy_probe.py`: exact float32 RGBA, numerical GPU
  verification, deliberate result perturbation, both steal directions, fault
  fallback, shared/neighbor controls and repeated timing.
- `tools/xpu2_native_light_lazy_cancel.py`: active cancellation and same-process
  replacement, compared with fresh and reference images.
- `tools/xpu2_native_light_lazy_evidence.py`: checks build identity and collects
  the qualified reports with paired timing differences.

The initial run was interrupted by an activity-query timeout after an unusually
slow reference render. Its results are retained separately and excluded from
qualification. The retry uses the unchanged frozen v2 build.

## What the combined benchmark enables

The candidate timing includes two GPU flight slots, grouped packets, lean wire
transfers, 16-microsecond completion-query pacing, CPU lobe lookahead, sample
coordinate reuse, an eight-block material window, four owned 64-ray chunks,
mixed-chunk handling, early staging rejection and ready-only result claims.
It then varies only the direct-light policy: off, eager stealing, descriptor-first
shared selection, or descriptor-first neighbor selection. GPU intersections
remain active in XPU execution mode. This is not a standalone scheduler toy.

The earlier sample-packet queue uses FIFO in these timings. Its bounded neighbor
variant was qualified separately but did not demonstrate a speed gain. Numeric
sampler caching, optional invariant packing and optional grouped replay are also
not credited as enabled improvements here: their prior experiments did not
establish meaningful render acceleration. A correctness or ownership breakthrough
is not automatically a speed improvement, and separately measured percentages
must not be added together.

Scene indexing, incremental scene updates, asynchronous texture residency and
geometry streaming are not exercised by this small fixed scene. Consequently,
these results cannot evaluate their loading/update benefits or establish the
fastest complete XPU2 configuration. Future end-to-end comparisons must record
active features and use large/textured scenes, repeated edits and measured scene
preparation as well as render time. Wider material offload and multiworker
qualification remain unfinished; enabling every experimental switch is not a
validated shortcut to that combined result.

## Qualification: 2026-10-19

The frozen v2 runtime passes 37 non-reference ordinary float32 RGBA comparisons
exactly, plus ten reference rows and a deliberate GPU-result sentinel changing
1,275 pixels. Three verification renders compare 45,282 GPU contributions with
zero bit mismatches. Rough diffuse, one/sixteen light samples, adaptive bypass,
missing PTX, zero capacity and injected upload failure pass. The one-sample
unforced attempt did not exercise GPU shading because CPU claims won the race;
its unqualified report is preserved. A separate forced GPU-claim correctness
case passes and is excluded from timings.

Active cancellation retires all 403 submitted jobs, including seven canceled
jobs. All descriptor windows close, no credits remain, and same-process
replacement is exact to fresh and reference images. The metadata contract also
passes 32,000 raced exclusive claims and the CPU-only allocation check.

After warmup and three rotated rounds, median MCRT is 8.062 s original XPU,
10.635 s same-build direct-light off, 11.587 s eager stealing, 10.785 s lazy shared,
and 10.603 s lazy neighbor (10.584-11.231). Neighbor-minus-eager paired differences
are -2.229, -0.508 and -0.356 s. Neighbor-minus-shared differences change sign
(-0.201, -0.145, +0.362 s), so locality itself has no established speed advantage.
Neighbor-minus-light-off differences also change sign (+0.108, -0.104, +0.596 s).
Median process wall time is 12.095 s neighbor versus 9.480 s original XPU.

Each neighbor frame packs only 927-1,346 of 253,544 descriptors, with 3,858-5,535
GPU direct-light contributions out of 1,438,792. Both CUDA slots are exercised;
242-320 direct-light waits remain. Packing reduction is real, but these counts
are not the GPU's share of the whole render. Original GPU intersections remain.

The paired gap against original XPU is 2.021-3.169 s (median 2.593 s), with a
median native Integration increase of 2.503 s. The light-off control shows most
of the gap remains in the earlier XPU2 pipeline. The next candidate is admission
before material preparation, followed by measurement of repeated setup/replay.
This is an attribution lead, not a promise that all 2.5 seconds can be removed.
There was no competing MoonRay process at the before/after timing checks; brief
intervening activity and other applications are not excluded.

[Retained evidence](native-light-lazy-20261019.json) includes source/build hashes,
paired timings and qualified reports. No merge, installation or default change.
