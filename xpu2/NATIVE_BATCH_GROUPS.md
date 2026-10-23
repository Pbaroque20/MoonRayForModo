# Grouped native shading packets

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Experimental extension of the [multi-flight candidate](NATIVE_FLIGHTS.md).
Original XPU and the installed kit are unchanged. This still covers early native
Lambert reflection/transmission and ordinary DwaBase diffuse roughness, not full
material evaluation or whole-path device ownership.

## Change

Previously, each eight-lane sample packet was published separately. The queue
worker could wake between packets belonging to the same lobe, dispatching a thin
batch before the producer finished preparing its remaining work.

`XPU2_GROUP_PACKETS=1` prepares the same bounded set of 1-16 packets and publishes
it under one queue lock. It sends one notification after publication. There is no
coalescing sleep, changed random sequence, new sample, lane rearrangement or
native arena migration. The native integrator already asserts a positive sample
count, and the existing early path only accepts at most sixteen packets per lobe.
The original individual-publication path remains available with the flag off.

Each packet keeps its own ticket, revision and capacity credit. Partial admission
returns empty tickets for the refused suffix, so the original CPU fallback still
handles those lanes. Caller handles are allocated before publication; an exception
while admitting a group cancels its already-admitted tickets before releasing the
lock. GPU event retirement, cancellation suppression and film publication are
unchanged. The producer remains dependent on the first required result; this is
not integration of the separate owned-child continuation prototype.

The comparison keeps two flight slots and tests dispatch limits of 8 or 16 packets
(64 or 128 lanes). The rough fixture supplies nine packets per eligible lobe.
A sixteen-packet limit can therefore send the whole lobe in one dispatch, while an
eight-packet limit still needs two. Fewer occupied slots can be faster if dispatch
cost dominates the shader operation. Slot occupancy alone is not the objective.

## Validation

- `tools/xpu2_native_batch_build.py` builds copied source objects against frozen
  native link inputs, leaving earlier builds and shared source untouched.
- `tools/xpu2_native_batch_groups.py` tests the actual queue with zero, partial and
  full capacity, copied caller storage, reverse collection, stale/foreign/duplicate
  rejection, pending/in-flight cancellation, missing PTX, closed admission and
  credit/resource cleanup.
- `tools/xpu2_native_batch_stress.py` reruns existing actual-CUDA lifetime cases
  against the extended queue.
- `tools/xpu2_native_batch_benchmark.py --checks` checks original XPU, disabled
  hooks, both group limits, deliberate GPU color perturbation and CPU fallbacks.
- `tools/xpu2_native_batch_timing.py` compares original XPU, the previous two-slot
  runtime, the new runtime with grouping off at both limits, and grouping on at
  both limits. One warmup plus three rotated measured rounds per configuration;
  identical scene, shader PTX, samples, thread count and capacity. Raw float RGBA
  comparison is outside timing; absolute and relative tolerances stay at 1e-6,
  with exactness recorded separately. Build, runtime, source and PTX hashes are
  verified before and after. Transfer bytes and GPU consumption must be compared
  alongside timings to distinguish reduced dispatch count from CPU fallback.
- `tools/xpu2_native_batch_cancel.py` checks a fresh persistent frame and native
  cancel/reload with grouped packets, two slots and a sixteen-packet limit.

Single-worker validation does not resolve the previously observed multiworker
repeatability failure, including unchanged original XPU repetitions. Queue tests
and native renders have distinct coverage. Production device-loss recovery and
cancellation specifically during an executing shader kernel are not claimed.

## Measurements (RTX 3090 / native AVX1, 2026-10-18)

The 384 x 216 rough-diffuse fixture uses one CPU render worker. All 24 timing
images, including warmups and original-XPU repetitions, match exactly in float32
RGBA. The strict image gate is unchanged.

- Previous two-slot candidate, eight-packet limit: median MCRT **11.461 s**
  (11.243-11.771), process **13.190 s**.
- New build, grouping off, eight-packet limit: **11.539 s** MCRT (11.362-12.240).
- Grouping off, sixteen-packet limit: **9.317 s** MCRT (9.005-10.410), process
  **11.770 s**. Increasing the limit supplies most of the measured improvement.
- Grouping on, eight-packet limit: **11.701 s** MCRT (11.524-12.910). Grouping
  alone does not speed this fixture up.
- Grouping on, sixteen-packet limit: **9.328 s** MCRT (9.105-9.443), process
  **10.641 s**. This is **18.6% shorter MCRT / 19.3% shorter process time** than
  the previous two-slot candidate in this paired run. Its MCRT is effectively tied
  with ungrouped sixteen-packet dispatch; three repetitions do not establish a
  separate render-speed benefit from grouped publication.
- Original XPU: **3.818 s** MCRT (3.742-3.824), process **5.351 s**. The candidate
  is still slower than XPU; there is no production acceleration claim.

Every enabled timing run consumes exactly **1,625,058 GPU lanes**, retains **990
fallback lanes**, transfers **377,243,136 bytes**, and has zero queue-capacity
refusals. Median dispatch count falls from **45,172** to **24,548** with the larger
ungrouped limit, then to **22,584** with grouping. The grouped path processes all
nine packets of a lobe together (72 scheduled lanes), rather than dropping GPU
work. Median submission intervals fall from 4.535 s to 2.103 s, while polling
intervals rise from 0.680 s to 0.855 s. These are worker CPU intervals, not exclusive
GPU utilization or additive components of render wall time.

The grouped sixteen-packet path reaches only one occupied slot with this single
producer, despite two slots being available. The ungrouped path reaches two.
This demonstrates why occupying more slots is not itself a speed objective:
reducing thin dispatches wins here. More independent native work is still needed
to combine larger batches with useful overlap. No waiting timer was introduced,
and default settings remain unchanged; grouping is explicitly opt-in.

Use the isolated candidate with `XPU2_GROUP_PACKETS=1`,
`XPU2_INFLIGHT_BATCHES=2` and `XPU2_TILE_BATCH_LIMIT=16` to reproduce the grouped
configuration. Leave these flags out for the existing default behavior. Do not
install this diagnostic DLL into the Modo kit.

The five group-admission cases and three existing real-CUDA ownership cases pass.
Eight rough-fixture image controls pass, including the intentionally different
GPU sentinel and exact normal/fallback images. Persistent fresh and cancel/reload
checks pass with exact final RGBA and no retained requests or cleanup errors.

Full reports and hashes: [batch-group evidence](native-batch-groups-20261018.json).
The supplementary mixed-material matrix was interrupted after another chat's
CPU-heavy glass render started. Its original/disabled images matched; its grouped
image was unfinished, so that matrix is explicitly **deferred, not passed**. Only
our isolated child process was stopped. The external render started at 02:51:58,
after the timing report completed at 02:50:42 (local time), so it did not overlap
the measurements above. No four-worker timing/parity claim is added.
