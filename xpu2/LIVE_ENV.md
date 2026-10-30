# Live environment evaluation on the GPU

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

The isolated GPU pipeline now computes Lambert sampling, untextured environment
intersection/evaluation, and tentative direct/indirect contribution arithmetic.
Captured light radiance/PDF/distance are no longer consumed in this path. This is
live numeric evaluation from light parameters and the newly sampled direction,
not a live Modo renderer or a complete path tracer.

## Independent native reference

`xpu2_live_env_oracle.py` builds an isolated oracle from the original
`EnvLight.ispc`, appending a small exported wrapper. It calls the original
`EnvLight_intersect` and `EnvLight_eval` functions with an explicitly initialized,
stationary, untextured light and no filters/portals. The original AVX8 Lambert
sampler supplies the direction, and the previously extracted native
`integrateBsdfSample` arithmetic consumes the newly evaluated light result.

The new EnvLight object replaces exactly one retained object in the isolated
link manifest. Shared sources, installed runtime and original XPU are unchanged.
Native headers are preprocessed twice and checked for drift; compiler flags,
objects, executable, numeric input/output and source hashes are retained locally.

The eight previously matched surface/sample fixtures are repeated across six
light variants, giving 48 native cases. Captured contribution fields for light
validity, distance, PDF and RGB are zeroed before oracle/GPU evaluation. GPU
results therefore cannot pass by returning the old captured light answers.

## Supported light boundary

This is evaluation of an environment hit **along a BSDF-sampled direction**, not
an implementation of `EnvLight_sample` or a complete direct-light strategy.
Supported evaluated parameters are radiance RGB, fallback texture color,
full-sphere/hemisphere choice, stationary hemisphere direction and maximum ray
distance. PDF and hit distance follow native constants; hemisphere misses and
short rays leave the direct contribution black while preserving valid indirect
throughput.

Textures/distributions, mip lookup, animated orientation, filters, portals,
light selection among multiple lights, other light types and general material
lobes remain unsupported. The current fixture does not exercise exactly grazing
hemisphere directions or all boundary distances. The native oracle's 48 results
are checked for finite values and explicit lit/black/miss/indirect branch coverage.

## Results

All four forward/reverse split/fused base checks match native output words exactly:
Lambert direction/RGB/PDF/validity, environment hit/distance/PDF/RGB, and tentative
direct/indirect contribution. Thirty larger checks (128, 2,048 and 8,192 samples,
five repetitions per mode) also pass. These expand batching coverage, not the
number of unique scene fixtures.

The full-sphere, tinted and upper hemisphere variants each have eight lit hits.
The black environment has eight valid hits and zero direct RGB. The lower
hemisphere and short-ray variants each have eight misses and zero direct RGB.
All cases retain nonzero indirect throughput. Two deliberate Lambert color
changes affect all 144 sampled RGB words and 216 contribution words; split and
fused GPU modes agree after those changes. CUDA resources release successfully.

Split/fused median end-to-end timings were 0.3332/0.3175 ms at 128 samples,
0.7822/0.7426 ms at 2,048, and 1.6241/1.5773 ms at 8,192. These include synchronous
Python/driver calls, transfers and readback. Small differences do not establish
renderer acceleration or GPU/CPU throughput parity.

## Shadow integration boundary

Inspection of native `XPUOcclusionRayQueue.h`, `RayHandlers.cc` and
`RayHandlerUtils.cc` shows that a compatible surface-visibility query needs more
than direction and distance: the original ray origin/near bound, shutter time,
receiver ID, query type and light identity matter. Native light identity is
currently recovered through a TLS-owned list handle and an RDL light pointer;
that pointer/handle cannot simply become an independently migrating GPU job.
The surface path initializes its auxiliary volume field separately; volume
transmittance and the later contribution/AOV processing are additional work.

Next, introduce a scene-revision-scoped light binding and an owned shadow request
that resolves to the native light while its scene is retained. Preserve origin
and bounds exactly, handle receiver/light exclusions, and compare CPU/GPU surface
visibility before connecting it to the contribution stage. The current live-env
prototype does **not** submit shadow rays, attenuate through volumes, publish film
samples or resume native paths.

`live-env-20261017.json` contains aggregate evidence. Local objects, binaries and
logs stay under `test-results/xpu2-live-env-final`; none of the new numeric binary
fixtures is published. Reproduce with `tools/xpu2_live_env_probe.py` using
`--source`, `--lambert`, `--contribution` and a fresh isolated `--output` directory.

All 270 XPU2 regression tests pass, including eight new live-light coverage checks.
