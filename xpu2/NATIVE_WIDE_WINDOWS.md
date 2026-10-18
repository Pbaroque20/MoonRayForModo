# Bounded native shading windows and chunk size

Experimental work on draft PR #130. Original XPU and the installed kit are unchanged.
All flags are opt-in. GPU shading support is unchanged; this is a scheduling experiment.

## Why larger windows alone did not help

MoonRay's RenderOptions defaults to a 32-ray shading workload chunk. The shade
handler bounds each arena-owned workload by that size before calling the bundled
integrator. On this AVX1 build, that gives at most four SIMD blocks per call.
Raising the adapter window to eight or sixteen blocks cannot expose work outside
that native call. The first isolated matrix confirmed identical submission counts
and a maximum queue of 36 packets at all three settings.

`native_wide_window.py` extends the copied adapter's bounded window from four to
sixteen blocks and its queue-capacity clamp from 64 to 512 packets. The GPU batch
limit remains 64 packets (512 lanes), with two in-flight slots in these probes.
Each block retains at most 32 numeric packets. Native shader and arena pointers
are not retained across calls. Regenerated input/pixel identity checks, native
integration order within each workload, ticket cancellation, and CPU fallback
remain in place. The larger array reserves storage for sixteen blocks, including
in the same-build four-block control.

## Native chunk experiment

`xpu2_native_chunk_build.py` changes only the copied RenderContext source to accept
`XPU2_NATIVE_CHUNK_RAYS=32`, `64`, or `128`. Missing or other values preserve the
native setting. It leaves all native ray queues and memory pool sizes unchanged.
The tests use 128 rays and compare four-, eight-, and sixteen-block windows at
identical 512-packet capacity, alongside a frozen four-block/32-ray control.
A native-only 128-ray case isolates the effect of the chunk boundary itself.
Changing workload boundaries can change native floating-point accumulation order;
the image gate still requires exact float32 RGBA against unmodified XPU.

## Results, 2026-10-18

This is a completed diagnostic, **not a strict original-XPU parity pass**. Across
both experiments, 52 ordinary rendered images stay within the existing 1e-6
absolute/relative RGBA tolerance. Of these, 29 match original XPU exactly; 23 have
five pixels with native chunk-boundary roundoff, maximum channel error
2.9802322387695312e-08. Alpha is exact. Three intentional GPU-color sentinels
change the image, confirming that GPU results actually contribute.

The native-only 128-ray control has the same five differences on the main
reflection/transmission fixture. All larger-chunk GPU cases and failure fallbacks
match their corresponding native-only 128-ray control exactly in the preserved
float32 RGB/alpha PFM files and metadata. Repeated runs preserve that match.
The rough-material and adaptive-bypass fixtures match original XPU exactly.
Missing PTX, zero queue capacity, partial upload failure, input mismatch, and
unused-ticket cancellation balance ownership and preserve the expected image.
Persistent cancellation/replacement leaves no retained work; replacement exactly
matches a fresh larger-chunk render. It still has the native five-pixel difference
from original XPU. The cancellation harness requires an explicit diagnostic flag
to accept that baseline; reports retain `image_differences`, not `passed`.

Warmup plus three rotated measured rounds, one native render worker, RTX 3090.
MCRT medians (warmup excluded):

- Original XPU: **7.983 s** (7.883-8.060).
- Frozen four-block, 32-ray chunk: **12.019 s** (11.480-12.130).
- Same-build four-block, 128-ray chunk: **11.817 s** (11.260-12.249).
- Eight-block, 128-ray chunk: **10.670 s** (10.631-10.853).
- Sixteen-block, 128-ray chunk: **10.735 s** (10.594-10.876).

Eight blocks reduce the observed median by **11.22%** versus the frozen previous
candidate and **9.71%** versus the same-build four-block control. It remains
**33.66% slower than original XPU**. Eight- and sixteen-block ranges overlap;
there is no demonstrated advantage from going to sixteen on this fixture.

Every measured enabled case consumes the same **1,625,067 GPU lanes**, with no
queue-full fallbacks. Median outstanding-batch peak increases from one to two.
Queue high-water marks are 36 / 72 / 144 packets for four / eight / sixteen blocks.
Sixteen blocks reduce submissions from 5,709 to 4,259, waits from 5,702 to 1,518,
and increase results ready at replay from 74.8% to 93.4%. Eight blocks already
reduce waits to 2,907 and raise readiness to 87.2%. Fewer waits are therefore a
real improvement, but additional batching alone does not remove the remaining
render cost. Outstanding CUDA events do not establish simultaneous kernel
execution or GPU saturation. Profile durations overlap and must not be summed
as a complete frame-time breakdown.

All timing process observations belonged to the PIDs launched by this probe;
no competing MoonRay renderer was detected. Periodic sampling cannot exclude all
other system load. Source/runtime/PTX identities were checked before and after.

## Reproduction and limits

Build with `tools/xpu2_native_wide_build.py` for the queue/window-only control or
`tools/xpu2_native_chunk_build.py` for the native chunk experiment. Both take
`--source`, the retained `--base` origin build, and a new isolated `--output`.
The matching `*_probe.py --checks` runs image/failure controls; without `--checks`
it runs warmup and rotated timing rounds. Use the existing frozen window build
as `--previous` and the unchanged film PTX for both PTX arguments. A new output
directory is required for every run. `xpu2_native_chunk_cancel.py` checks persistent
replacement; use `--allow-native-roundoff` only for this explicitly diagnosed
native-only drift. The original strict parity result remains visible.

Evidence: [native-wide-windows-20261018.json](native-wide-windows-20261018.json).
Local reports: `test-results/xpu2-wide-controls`, `xpu2-chunk-controls`,
`xpu2-chunk-rough`, `xpu2-chunk-adaptive`, `xpu2-chunk-cancel`, and
`xpu2-chunk-timing`.

Keep this opt-in. It does not establish multiworker repeatability, arbitrary
material coverage, or full asynchronous shading. The next useful investigation
is CPU-side native integration and material preparation after waits have been
reduced, using heavier shading work per transfer. If exact original-XPU bit
patterns are required, retain the native 32-ray boundary or first isolate and
preserve its contribution ordering; the larger-chunk option cannot claim that
property from these results. The installed plugin and original XPU are unchanged.
