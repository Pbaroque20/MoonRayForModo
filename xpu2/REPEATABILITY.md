# XPU reference repeatability â€” October 16, 2026

This investigation extends the XPU2 foundation in PR #130. No production runtime,
Modo kit, user scene or shared source checkout was modified.

## Controlled experiment

Pinned runtime and source fixture from `reference/reference.json`. The matrix
uses a separate diagnostic scene with frame/min-frame/max-frame explicitly 0
and lock_frame_noise true. Pixel sampling stays uniform at grid 4 (16 spp),
light sampling uniform, with no adaptive stopping or denoising. Source overrides
remain unset. Runtime fingerprints are verified before and after; GPU/driver
identity is checked for changes. Requested thread counts are checked against the
renderer statistics, not assumed from command arguments.

Three repetitions of each case were interleaved: vectorized with 1 and 12
threads, XPU with 1 and 12 threads. All 12 processes exited normally. All XPU
runs confirmed GPU work without mode fallback. This is one fixture on one
RTX 3090 (driver 591.74), not a general determinism guarantee or performance test.

All pairwise comparisons within each case use zero numerical tolerance:
- Vectorized, 1 thread: exact RGBA equality across all three repetitions.
- Vectorized, 12 threads: RGB differs; largest red difference across pairs
  1.6391277313232422e-7. Alpha identical.
- XPU, 1 thread: exact RGBA equality across all three repetitions. Logged GPU
  bundled-intersection utilization is 100.00% in each run.
- XPU, 12 threads: RGB differs; largest red difference across pairs
  0.0003151148557662964. Alpha identical. Logged GPU intersection fractions
  change from 99.03% to 97.59% to 95.30%.

Numerical equality is not a claim about EXR file-byte equality, signed-zero bit
patterns, other machines, or all scene features.

## Cross-mode difference

Single-thread vector and single-thread XPU each repeat, but they do not match
each other exactly. Their largest red difference is 0.0006597638130187988 at
pixel (132, 96), coordinates counted from the bottom left.

This distinguishes repeatability (one mode reproduces itself) from parity
(two different modes produce equivalent results). No tolerance has been adopted
or relaxed to turn the comparisons into passes.

## Primary-hit diagnostic

A separate full-frame experiment used one sample per pixel, one thread, locked
frame/seed controls, and float P, Ng and N state outputs alongside beauty/alpha.
It used full-frame rendering because -debug_pixel restricts work to one pixel;
that changes batching and can make an XPU investigation use only CPU queries.

Both native renders exited normally; XPU reported 100.00% bundled GPU
intersection work. Measured zero-tolerance differences:
- P (camera-space hit position): maximum absolute component difference
  3.337860107421875e-6.
- Ng (geometric normal): exactly identical.
- N (interpolated shading normal): maximum absolute component difference
  3.3676624298095703e-6.

At the largest beauty difference, pixel (96,77), red is
0.21528181433677673 in vector mode and 0.21118733286857605 in XPU.
At that same pixel, camera-space P.z differs by roughly 4.77e-7;
N.z differs by roughly 5.96e-8; Ng matches.

Thus an observable difference already exists in intersection-derived state
before the material response. This experiment does NOT prove that this tiny
primary-state difference alone explains the entire beauty discrepancy. Secondary
intersections, self-occlusion, BSDF choices and summation still require tracing.
These are primary-surface outputs, not a complete per-bounce ray trace.

## Relevant source observations (read-only)

- `RenderContext.cc::getInitialSeed` returns 0 when lock_frame_noise is true;
  otherwise it combines frame and stereo view. This control is not a general
  deterministic-scheduling switch.
- `XPURayQueue.h::flushInternal` routes batches above 1024 rays to GPU only when
  fewer than five threads are using it; otherwise it uses the CPU handler.
- `XPURayHandlers.cc` copies GPU hit distance, barycentrics and geometric normal
  into the ray state. It also contains disabled CPU/Embree cross-check code.
- `Film.cc` contains atomic floating-point accumulation. Different addition
  order can change rounding; this is a plausible explanation of the smaller
  vector multithread differences, not a measured attribution.

The route fractions and state differences make scheduling-sensitive CPU/GPU
intersection differences a strong investigation target for the larger XPU
variation. They do not establish a complete causal trace.

## Decision for XPU2 development

Use single-thread XPU with this pinned runtime, scene and fixed sampling profile
as the current repeatable diagnostic reference. Keep the single-thread vector
result as a second reference that detects device-path changes. Retain production
multithread XPU as a separate observed-variation baseline.

Do not use one CPU thread as a production speed recommendation. The eventual
XPU2 diagnostic mode needs device-independent sample identities and ordered
accumulation without making its normal asynchronous mode single-threaded.

Before claiming broader parity:
1. Instrument selected rays during full-frame execution, keyed by pixel, camera
   sample, path branch and bounce. Record incoming ray, selected device, hit
   primitive/distance/barycentrics and then shading contributions.
2. Replay identical incoming rays through Embree and OptiX to separate geometric
   precision from earlier path changes. Do not allow diagnostic routing to alter
   which primary samples exist.
3. Compare contribution multisets before film accumulation; replay them in a
   canonical order to isolate summation effects.
4. Expand fixtures to textures, silhouettes, shadows, glass, motion, volumes and
   production AOVs before defining numerical acceptance bounds.

## Reproduce

```powershell
python -m unittest discover -s tests -p "test_xpu2*.py" -q
python tools/xpu2_repeatability.py --runtime <pinned-runtime> --output test-results/repeatability-new --threads 12 --repetitions 3
python tools/xpu2_surface_probe.py --runtime <pinned-runtime> --output test-results/surface-new
```

Use fresh output directories. Both diagnostic tools return 2 when differences
are measured, 1 on an invalid/incomplete experiment, and 0 on an exact observed
match under their documented scope. A successful process run is not relabeled
as a passing parity check.

43 unit checks pass. A generated 2x2 float PFM independently confirmed that the
reported row-zero coordinates start at the bottom. Compact measured evidence is
in `repeatability-20261016.json`; EXRs, converted buffers and full logs are local
under test-results. No images were regenerated to change an unfavorable result.
