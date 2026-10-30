# Native input preparation experiment

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This opt-in candidate builds on the bounded four-block material window. It keeps
original XPU and the installed Modo runtime unchanged.

## Changes

`XPU2_REUSE_PACKING=1` extracts immutable numeric material, normal and view fields
once per lobe preparation. Each sample copies those fields and inserts its own
original random sample pair. Inactive lanes keep their zero payload and invalid
pixel marker. Native sampler construction, replay input regeneration and full
input-byte/pixel comparisons remain in place.

`XPU2_GROUP_REPLAY=1` performs the existing per-packet byte and pixel comparisons
outside the queue mutex, then checks matched ticket readiness and transfers
ownership under one mutex acquisition for the group. Cancellation and fallback
submission occur outside that critical section. Queue tickets, revision checks,
input mismatch behavior, film order and the shading PTX remain unchanged.

Both switches default off. They are independent and are snapshotted at frame
reset. `XPU2_PREPARATION_PROFILE` reports flags, prepared lobes, replay groups and
reused packets. Groups remain bounded to 16 packets; material lookahead remains
bounded to four native SIMD blocks, with independent queue capacity limits.

## Qualification

The dedicated build, image and cancellation scripts are
`tools/xpu2_native_preparation_build.py`,
`tools/xpu2_native_preparation_probe.py` and
`tools/xpu2_native_preparation_cancel.py`.

Probe labels use four-block lookahead throughout: `control` disables both new
switches, `transport` enables invariant packing only, and `ahead` enables both.
Original XPU is the image reference. Missing PTX, zero capacity, upload failure,
input mismatch and discarded prefetch tickets exercise CPU fallback and cleanup.
The GPU color sentinel must differ to demonstrate GPU contribution to the image.

All checks passed: 36 ordinary images match original XPU exactly in float32 RGBA,
and two intentional GPU color sentinels differ. This includes forced failures,
rough materials, adaptive bypass with packing enabled (grouped replay disabled),
and persistent cancellation/replacement with both new switches enabled.

## Performance and decision

Warmup plus three rotated rounds used the same fixture and one native worker.
Warmup is excluded from the following MCRT medians and ranges:

- Original XPU: **7.496 s**, range 7.452-7.518.
- Four-block control: **10.704 s**, range 10.675-10.728.
- Invariant packing only: **10.662 s**, range 10.605-10.730.
- Invariant packing plus grouped replay: **10.639 s**, range 10.633-10.735.

The combined median is only **0.61% lower** than its same-run control; ranges
overlap. There is no established meaningful speedup, and this remains **41.93%
slower than original XPU**. Both new switches remain off by default. Earlier
runs on another date/time are not used to calculate a speedup.

Grouped replay checks 203,013 reused tickets under 22,578 group locks instead of
one readiness lock per ticket. Invariant packing is exercised in 45,142 lobe
preparations. These are real reductions in repeated work, but not evidence that
this work dominated the frame time. GPU submissions remain 5,709 per frame, with
peak observed in-flight batches of one in all measured combined-mode runs.

For the combined mode, median transport packing is about 0.024 s and retirement
about 0.071 s. These instrumentation scopes are not an additive breakdown of
frame time. The next useful targets remain duplicated native sampler setup and
more useful independent shader computation per handoff, rather than more minor
locking changes. This experiment does not establish that broader shaders will
be faster.

All per-render activity checks were empty. The periodic monitor recorded 42
snapshots. One snapshot had a null executable path 45 ms after a candidate render
exited; its PID matched the candidate in both preceding snapshots. The raw flag
and its resolution are retained. No unrelated renderer was detected; periodic
sampling does not prove continuous absence of other system load.

Full source/runtime identities, reports, activity observations and counters:
[native-input-preparation-20261018.json](native-input-preparation-20261018.json).

This does not broaden GPU material coverage or resolve native multiworker
repeatability. It does not remove duplicated native sampler setup.
