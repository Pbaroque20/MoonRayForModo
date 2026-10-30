# Exact-image 64-ray native chunk qualification

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Follow-up to [wider native windows](NATIVE_WIDE_WINDOWS.md), 2026-10-18. This uses
the same isolated candidate DLL and unchanged shading PTX; no rebuild, installation,
or change to original XPU. All native changes remain opt-in.

## Result

A **64-ray native chunk with an eight-block window** retains two outstanding GPU
batches while matching original XPU exactly on the tested one-worker fixtures.
The larger 128-ray chunk's five-pixel rounding difference is not present at 64.
This is empirical qualification for these fixtures, not a guarantee of bitwise
parity for every scene, material, worker count or hardware combination.

The matrix produced **36 exact candidate/control images**, checked both by
float32 RGBA comparison and matching RGB/alpha PFM file hashes. It covers the
main reflection/transmission fixture, rough diffuse, native adaptive bypass,
missing PTX, zero queue capacity, partial upload failure, mismatched inputs,
discarded tickets, and persistent cancellation/replacement. Replacement matches
both fresh rendering and original XPU. Two intentional GPU-color sentinels change
the image, verifying real GPU contribution.

Four additional 128-ray comparison renders (warmup and three measured rounds)
retain the known five-pixel rounding difference. They remain separately labelled:
the raw mixed timing report is `image_differences`, while the evidence collector
requires every ordinary 64-ray/control image to match original XPU exactly.
No tolerance exception is used to pass the 64-ray candidate or its cancellation
baseline. All cleanup/ownership checks completed without retained work.

## Timing

One native render worker, RTX 3090, warmup plus three rotated measured rounds.
MCRT medians and observed ranges, excluding warmup:

- Original XPU: **7.601 s** (7.601-7.738).
- Frozen four-block / 32-ray candidate: **10.964 s** (10.851-11.223).
- Same-build four-block / 64-ray control: **10.837 s** (10.818-10.968).
- Eight-block / 64-ray candidate: **10.460 s** (10.086-10.484).
- Eight-block / 128-ray comparison: **10.079 s** (10.002-10.275).

The exact 64-ray candidate reduces the observed median by **4.60%** versus the
frozen previous candidate and **3.48%** versus the same-build four-block control.
It remains **37.61% slower than original XPU**. The 64-ray median is 3.78% slower
than 128 rays; their ranges overlap,
so do not claim a reliable advantage from only three rounds. Cross-session medians
also vary; use this paired comparison rather than mixing earlier runs.

Enabled cases consume the same **1,625,067 GPU lanes**, with no queue-full
fallbacks. Median peak outstanding batches increases from one to two. Queue
high-water rises from 36 to 72 packets. Median waits drop from 5,703 to **2,876**;
results ready at replay increase from 74.83% to **87.37%**. Submission count only
falls from 5,709 to 5,631: the gain primarily accompanies more work ready when
needed, not a large reduction in launches. Outstanding events do not establish
simultaneous kernel execution or GPU saturation.

Native timing categories locate the remaining cost. Median Integration is
**5.186 s**, versus **2.508 s** in original XPU. GPU intersection time is 0.191 s
versus 0.196 s, and GPU occlusion is 0.147 s versus 0.146 s. The material-shader
category excluding OIIO is 0.299 s versus 0.343 s. Integration includes waits,
preparation, validation and native calculations; this profile cannot distinguish
which internal phase dominates. Overlapping category/transport timers must not
be summed into a frame budget. Instrumenting those integration subphases is the
next useful optimization step, before enlarging the queue again.

## Reproduction

Use the retained `test-results/xpu2-chunk-build` and
`test-results/xpu2-origin-build/control`. The frozen comparison is
`test-results/xpu2-window-build`; both PTX arguments use
`test-results/xpu2-native-work-ptx/film.ptx`.

- `tools/xpu2_native_chunk64_probe.py --checks` runs strict image/failure controls.
  Use `--cases reference,native_chunk,eight,sentinel` for the rough fixture, and
  `--bypass` for the adaptive fixture.
- `tools/xpu2_native_chunk64_cancel.py` validates persistent replacement against
  the passed main baseline. Do not pass `--allow-native-roundoff` for this gate.
- `tools/xpu2_native_chunk64_timing.py --repeats 3` compares original XPU, frozen
  previous candidate, same-build four/eight blocks at 64 rays, and eight blocks
  at 128 rays. Its strict original comparison deliberately keeps the known
  128-ray difference visible.
- `tools/xpu2_native_chunk64_evidence.py` verifies the dated report directories,
  raw image hashes, native timing categories and renderer activity observations.

Each render harness requires a new `--output` directory; use `--help` for all
required paths. The exact candidate uses `XPU2_NATIVE_CHUNK_RAYS=64`,
`XPU2_WINDOW_BLOCKS=8`, queue capacity 512, batch limit 64 and two flight slots.
It retains lean transfers, paced polling and existing CPU lobe work; sampler
cache and packing/group-replay experiments remain disabled.

Evidence: [native-chunk64-20261018.json](native-chunk64-20261018.json). Source,
runtime and PTX identities were checked before/after. Periodic process monitoring
found no competing MoonRay renderer; it cannot exclude all other system load.
Multiworker repeatability, broader materials and production speed remain open.
