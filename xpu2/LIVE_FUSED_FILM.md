# Live fused Lambert and contribution dispatch

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Status: **restricted live image path validated; still slower than native XPU**.
This follows [contribution-window batching](FILM_WINDOWS.md), bringing the
previously replay-only fused arithmetic into actual native renders.

## What changed

With `XPU2_FUSED_FILM=1` and a contribution mode enabled, the Lambert hook copies
numeric shader inputs and native reference values into bounded thread-local
slots. It does not submit the separate Lambert GPU job. The existing wrapper
guard rejects any sample whose direction, RGB or PDF changed after that hook;
multiple lobe hooks also decline replacement. Collect/take retires each slot,
including invalid samples, before the native stack continues.

One CUDA kernel then recomputes the supported Lambert sample, checks direction,
RGB, PDF and geometric validity against the native reference, and computes its
BSDF-sampled direct/indirect contributions. Intermediate shader values remain
on the GPU. One upload and one contribution readback replace the two separate
GPU stages and their two private contexts. Only accepted contribution values
reach the original native light-label/clamping/continuation/film path.

Unsupported shaders, wrapper changes and failed GPU jobs use native contribution
results. CPU Lambert sampling is still present: native light evaluation uses its
direction/PDF, and exact shader guards use its reference. This reduces transfers
and queue overhead; it does not remove all duplicated CPU shading. CPU lights,
visibility, light-sampled contributions and path continuation remain native.

The previous separate dispatch path remains available in the same build when
the fusion switch is off. The installed renderer, existing XPU and user scenes
are unchanged. This is not yet a selectable production XPU2 backend.

## Validation — 2026-10-17

Fourteen native renders passed their intended gates. Eleven non-reference,
non-sentinel linear RGBA comparisons matched exactly at zero tolerance, including
repeated fused rendering and both failure controls. The deliberate sentinel
changed 23,346 pixels, proving GPU contributions reach the film.

Normal fused renders had zero shader/contribution mismatches, device errors or
cleanup errors. The small scene accepted 210,001 GPU shader/contribution results;
the sphere/ground scene accepted 1,997,771. The separate GPU shading profile was
absent in fused cases, and the fused counters confirmed every contribution call
used the combined path. The prior separate shading job additionally handled a
small number of invalid samples that never became contribution work; fusion
skips that unnecessary GPU shading. Completed contribution counts agree exactly.

Missing PTX accepted no GPU work and rendered the exact reference through CPU
fallback. Deliberately corrupting the shader reference rejected all 210,001
contributions, accepted none, and also rendered the exact reference. Those
intentional mismatches are distinguished from normal successful renders.

Five synthetic capture checks cover copied ownership, changed wrappers, missing
lanes, multiple lobe hooks and slot reuse. Three synthetic GPU checks exercise
1, 9 and 16 slots with partial masks, shader exclusions, mirror fallback,
corrupted references and output/mask canaries. The latter deliberately produce
26 rejected shader mismatches and 52 unsupported shader results, with no device
or cleanup errors. These numeric checks supplement rendered validation.
All 325 XPU2 regression tests passed, including six new evidence-gate tests.

## Measured cost and remaining gap

Same-build sphere/ground render times with one renderer thread on the RTX 3090:

- Native XPU: **3.858 seconds**.
- Separate Lambert/contribution dispatch: **38.976 seconds**.
- Fused audit retaining CPU contributions: **11.667 seconds**.
- Fused CPU-contribution replacement: **11.880 and 16.855 seconds**.

Fusion reduced measured render time by about **57–70%** versus separate dispatch.
Both fused timings are reported because the spread is substantial; the run does
not establish a stable production speedup. Caches are warmed/uncontrolled, and
there was one separate-control timing. Native XPU remains roughly 3–4 times faster.

The first fused replacement run spent 7.080 seconds in the bridge, including
3.065 seconds waiting for GPU completion and 2.234 seconds reading results back.
The repeat spent 9.949 seconds there. These are host intervals, not arithmetic
kernel timings. Both used 68,182 dispatches; scheduling/readback overhead remains
large relative to the supported arithmetic. The next target is pinned staging
with upload, kernel and download on one stream before a single completion wait;
owned asynchronous path continuation remains necessary to release the caller.

The small fixture took 0.359 seconds natively, 2.715 seconds with separate stages,
and 1.015 / 0.920 seconds with fused replacement. No faster scene loading or
multithread parity certification is claimed.

## Reproduce

Build with `tools/xpu2_film_build.py --source <read-only-native-checkout> --base
<retained-base> --output <new-folder> --fused`. Run `tools/xpu2_film_probe.py` with
that build and `--fused`; add `--showcase` for the sphere/ground timing comparison.
Run `tools/xpu2_fused_guard_probe.py --build <candidate> --output <new-folder>`
after timed renders. The retained base is `test-results/xpu2-owned-contribution-build-v2`.

Local artifacts are `test-results/xpu2-film-fused-build`,
`test-results/xpu2-film-fused-validation`, `test-results/xpu2-film-fused-showcase`
(including `gpu-image.png` and `fast/beauty.exr`), and
`test-results/xpu2-film-fused-guards`. [Aggregate evidence](live-fused-film-20261017.json)
contains source/output hashes and measurements. Binaries, captured inputs and
rendered files remain local. This links retained native objects rather than
providing a clean-source distributable build. Production cancellation, recovery,
full material support and native asynchronous path resumption remain unproven.
