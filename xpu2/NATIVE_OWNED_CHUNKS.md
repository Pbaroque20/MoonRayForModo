# Owner-thread native chunk preparation

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Experimental extension alongside original XPU. The installed kit is unchanged.
The goal is to overlap useful CPU preparation with GPU sampling, rather than
spend additional CPU time polling completion events.

## Ownership and work

The isolated `ShadeBundleHandler` copy can retain two or four chunks from its
existing sorted input list. Each chunk keeps its own intersection, BSDF, ray-state
and presence buffers. Native shading calls and integration calls retain their
original maximum width of 64 rays. Chunk preparation advances, but integration
and radiance publication retain original chunk order.

Preparation publishes a bounded numeric GPU window and detaches its owner-thread
handle. While that GPU work is outstanding, the same native thread prepares the
next chunk. Before integration, its handle is rebound on that same thread and
consumed by the existing replay path. Replay still compares all numeric inputs;
changed or unavailable work falls back to native CPU shading. No native arena,
BSDF pointer, ray state or shader context crosses a worker thread or GPU queue.

The enclosing native arena remains alive for the handler. Separate chunk buffers
prevent later preparation from overwriting an earlier chunk. RAII owners cancel
unconsumed handles on early return, and frame counters require every detached
window to finish or cancel. Epoch and thread checks protect rebinding. GPU slot
retirement and stream-error handling remain those of the previously tested
transport; the PTX kernel is unchanged.

## Gates and controls

This experiment is opt-in, limited to fixed-sample XPU with empty AOVs, the native
64-ray chunk size, eight-block GPU windows, and DwaBaseMaterial/UsdPreviewSurface
input groups larger than one chunk. Existing GPU admission still rejects
unsupported bounces, closure features, volumes and nonopaque paths. Preparing
mixed-depth CPU groups does not make those paths eligible for GPU shading.

`XPU2_OWNED_CHUNKS=2` or `4` selects the bounded lookahead. The absent/zero flag
uses the unchanged handler path. `XPU2_OWNED_MIXED=1` permits preparation of
mixed-depth groups on their original native thread; otherwise every input ray
in a group must be primary. `XPU2_OWNED_PROFILE` records coverage and lifetime.
The lane-parallel packing and bounded-spin experiments remain off.

The conservative first version prepared only 256 chunks from one of 239 input
groups in the main fixture. Broader preparation covered 36 groups / 252,272
entries and 3,974 chunks, preserving exact original-XPU RGBA. Its first check
reduced submissions from about 5,600 to 4,500. Those initial checks are not the
repeated performance qualification.

## Reproduction

Build with `tools/xpu2_native_owned_depth_build.py` using the retained original
runtime/link manifest and a fresh isolated output directory. Run
`tools/xpu2_native_owned_depth_probe.py --checks` for same-build two/four-chunk
images, GPU sentinel and injected failures. The rough fixture uses
`--cases reference,two,four,sentinel`; adaptive bypass uses `--bypass`.

`tools/xpu2_native_owned_depth_cancel.py` interrupts a persistent frame and
compares replacement output against original XPU and a fresh candidate frame.
The probe without `--checks`, with `--repeats 3`, runs a discarded warmup plus
three rotated timing rounds. It rejects competing MoonRay processes. Periodic
process monitoring is also retained for the recorded run.

`tools/xpu2_native_owned_evidence.py` validates raw RGB/alpha hashes, source and
runtime report identities, lifetime results and paired timing. Fine integration
timers are inclusive and nested; they are enabled only in separate diagnostic
cases and must not be summed into frame time.

Qualification is limited to one native render worker and the tested material
fixtures. General material/volume/AOV coverage, multiworker repeatability and
production performance remain open. The grouping is bounded lookahead within
a native handler, not arbitrary cross-handler or cross-thread suspension.

## Recorded results (2026-10-18)

The retained evidence in `native-owned-chunks-20261018.json` verifies 72
ordinary float32 RGBA images and their raw RGB/alpha hashes against original
XPU. Four deliberate GPU-color sentinels change the image. Controls cover
rough diffuse, reflection/transmission, adaptive bypass, absent PTX, zero queue
capacity, upload failure, replay mismatch and dropped speculative work.

Three rotated timing rounds, excluding warmup, gave MCRT medians of 8.125 s
for original XPU, 11.191 s for the same-build preparation-disabled control,
10.548 s for two prepared chunks and 10.431 s for four. The four-chunk observed
median is 6.79% lower than the same-build control but still 28.38% slower than
original XPU. Its range was 10.221–10.510 s; the control range was
10.641–11.223 s. This small experiment does not establish general scene gains,
and the 7.6-second target remains unmet.

Median wait counts fell from 2,921 to 497 and submissions from 5,631 to 3,828,
with the same 1,625,067 GPU shading lanes and no queue-capacity fallback. Four
prepared CPU chunks still use only two GPU flight slots. The separately
profiled collection time of 0.240 s includes waiting and CPU bookkeeping; it
is not an isolated PCIe-transfer measurement. Inclusive timers are not additive.

Normal frame replacement matched original XPU and a fresh candidate frame.
The separate v2 diagnostic additionally holds four prepared chunks after the
native protected first pass, then receives a normal session cancellation.
All four held chunks cancel and the replacement image is exact. This checks
unconsumed owner-handle cleanup, not GPU kernel preemption. The first diagnostic
incorrectly held the protected first pass and timed out; it is retained only
for reproducing that diagnostic limitation. Use the v2 build/probe for the gate.
Neither diagnostic runtime is used for performance measurements.
