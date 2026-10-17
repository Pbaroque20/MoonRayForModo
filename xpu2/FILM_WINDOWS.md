# Live contribution-window batching

Status: isolated candidate; existing XPU and the installed Modo kit are unchanged.
This optimizes the contribution-to-film diagnostic described in [FILM_IMAGE.md](FILM_IMAGE.md).

## Implementation

Collect the existing GPU Lambert results for each available native sample slot,
then pack that window's contribution inputs before one CUDA submission. Up to 16
slots of eight SIMD lanes fit in resident input/output buffers. Invalid native
samples still retire their Lambert tickets, but never become contribution work.

Audit mode computes native references and compares each supported GPU result.
The CPU-skipping mode uses GPU contributions for accepted lanes and falls back
per lane for unsupported inputs or device failures. Native light labels and
clamping still run in the original sample order. No native pointer leaves the
active stack. This is a synchronous contribution boundary, not asynchronous path
resumption or a complete GPU shading backend.

`XPU2_FILM_WINDOW=1` dispatches one SIMD packet at a time using the same binary,
input packing, kernel and surrounding native control flow. The default groups
all available slots. Profiles distinguish packet count, actual GPU dispatches,
maximum window width and accepted/skipped contribution work. The comparison
rejects a reduced dispatch count if the amount of completed work changed.

## Reproduction

Build using `tools/xpu2_film_build.py` with the retained native base, then run
`tools/xpu2_film_probe.py` normally for reference, disabled, shading-only, audit,
CPU-skipping, repeat, deliberate image-change and missing-PTX fallback checks.
Add `--showcase` for the sphere/ground scene: native reference, shading-only,
audit, one-packet control, full window, and full-window repeat.

`tools/xpu2_film_window_probe.py --build <candidate> --output <new-directory>`
checks numeric CUDA windows separately at 1, 9 and 16 slots in both dispatch
modes. It covers inactive lanes, mirror/missing-light/invalid-PDF/nonfinite
fallback and output/mask boundary canaries. These synthetic checks do not stand
in for rendered-scene validation. Run them after timing the renders.

All test outputs stay local under `test-results`. This build links retained
native objects; it is not a clean-source distributable runtime. Timings are
instrumented one-thread renders on the RTX 3090 with warmed/uncontrolled caches.
Neither scene loading improvements nor production/multithread parity are claimed.

## Results — 2026-10-17

Fourteen native renders passed their intended gates. Eleven non-reference,
non-sentinel RGBA comparisons were exact at zero tolerance. The deliberate
sentinel changed 23,346 pixels, proving that returned GPU contributions still
reach the image; missing-PTX fallback accepted no GPU contribution and matched
native output. The six synthetic bounds/mask cases also passed, including the
full 128-sample window. All 319 XPU2 regression tests passed.

On the 384 by 216 sphere/ground scene, both dispatch modes completed exactly
1,997,771 supported contributions. Packet dispatch made 250,981 GPU calls;
window dispatch made 68,182, a 3.68-fold reduction. The largest actual native
window was nine slots (72 samples); later bounces produced smaller windows.
The 16-slot limit was exercised separately by the synthetic boundary check.

In the same candidate binary, render time was 56.325 seconds with one-packet
dispatch and 39.161 / 39.512 seconds with window dispatch, about 30% less time.
Contribution bridge time fell from 28.362 seconds to 12.152 / 12.216 seconds.
All normal runs had zero contribution mismatches, device errors and cleanup
errors. Audit rendering took 42.373 seconds and retained native CPU results.

Native XPU took 3.710 seconds. GPU Lambert alone took 27.822 seconds. Therefore,
the candidate is still much slower than native XPU: reducing contribution calls
is useful but does not remove the dominant shading/transfer/synchronization cost.
Window contribution wait plus readback still consumed 10.780 of its 12.152
seconds. The next target is shared resident GPU resources and a fused supported
shading/contribution path, followed by owned asynchronous continuations. Merely
increasing GPU arithmetic or utilization does not establish an acceleration.

On the small fixture, nine-slot grouping reduced 26,271 packets to 2,919 GPU
calls; CPU-skipping renders took 2.184 / 2.200 seconds versus 0.375 seconds for
native XPU. Both accepted and replaced all 210,001 supported contributions.

Local artifacts: `test-results/xpu2-film-window-build`,
`test-results/xpu2-film-window-validation`, `test-results/xpu2-film-window-showcase`
(including `gpu-image.png` and `fast/beauty.exr`), and
`test-results/xpu2-film-window-bounds`. Published [aggregate evidence](film-windows-20261017.json)
contains hashes and measurements, not renderer binaries or image/capture data.
