# Broader native GPU diffuse shading

Status: experimental pre-evaluation shading in an isolated runtime. XPU and the
installed plugin are unchanged; XPU2 is not a production-selectable engine.

The early native boundary now accepts Lambert reflection, Lambert diffuse
transmission, and DwaBase's ordinary FlatDiffuse lobe with roughness. DwaBase
uses FlatDiffuse even without its toon controls: the kernel therefore follows
that native formula, including its PDF and AVX angular math, rather than
substituting a generic Oren-Nayar implementation.

Version 1 packets retain the Lambert contract; version 2 contains the native
rough-diffuse coefficients. Unsupported inputs keep their unavailable marker,
so the original CPU lobe is evaluated on demand. Family counters distinguish
reflection, transmission and rough diffuse; a test cannot pass by silently
falling back for its intended family. GPU results are consumed without first
computing a CPU BSDF answer. Lighting/MIS, texture evaluation, material setup,
secondary traversal and native film accumulation remain on their existing paths.

## Validation on 2026-10-18

Nine isolated matrices passed on the RTX 3090 / driver 591.74 with native AVX1
math. Normal single-worker RGBA images are exact for DwaBase roughness 0, 0.5
and 1, diffuse transmission, mixed Lambert/DwaBase and the existing Lambert
fixture. The 0.5 roughness run consumed 1,625,058 GPU rough-diffuse samples;
the transmission fixture consumed 1,625,067 transmission and 1,625,067 rough
reflection samples. Both GPU color sentinels changed the real image. Missing-PTX,
zero-capacity, unsupported shadow-terminator and adaptive bypass images are exact.

Persistent fresh and cancelled/reloaded images are also exact against the native
persistent reference, consuming 1,622,736 GPU samples per completed candidate
frame. Retained credits, cleanup errors and shader timeouts are zero at completed
teardown. The cancelled first phase had already consumed its 6,480 accepted GPU
samples: this does not establish cancellation of deliberately held GPU work.

Initial Oren-Nayar routing was rejected by the family gate because DwaBase uses
FlatDiffuse; it was corrected before claiming GPU coverage. One maximum-roughness
run and one persistent restart exceeded their original 180-second time limits.
Their incomplete records remain; bounded 600-second retries passed without
changing image tolerances. Other renderer activity was observed, so recorded
process timings are diagnostic, not controlled benchmarks. No multiworker image
pass or production readiness is claimed.

## Boundaries

Admission remains first-scatter, fixed-sample, beauty-only and bounded to 16
sample packets per lobe. FlatDiffuse must have zero flatness/terminator shift;
Fresnel, spherical lobes and unsupported shadow-terminator modes retain CPU
shading. Pure Oren-Nayar, toon modifications, glossy/metal/glass, layered Fresnel,
AOVs and arbitrary material graphs are not newly GPU-supported.

## Reproduction

Build with `tools/xpu2_native_gpu_early_build.py`, compile the broader kernel
with `tools/xpu2_diffuse_ptx.py`, and supply that PTX to
`tools/xpu2_broader_diffuse_probe.py`. Select `--material rough|transmission|mixed|lambert`
and use `--roughness` for the DwaBase fixture. The full matrix includes a GPU
color sentinel, missing PTX and zero queue capacity. Adaptive and unsupported
modes explicitly check native fallback. The persistent cancellation runner
accepts a passed single-worker baseline from this probe.

The new-family image bound was set to 1e-6 absolute/relative before rendering;
existing Lambert and single-worker bypass cases require exact equality. Image
comparison is independent of execution counters. Runtime and input hashes are
recorded; this rebuild uses six copied native objects and retained frozen link
inputs, not a clean full build. Evidence is recorded in
`broader-diffuse-20261018.json`.

## Performance direction

No speedup is claimed. The native early queue still has blocking device
transfers and result dependencies. Earlier pinned single-stream/graph experiments
in `FILM_TRANSFERS.md` did not accelerate the larger fixture because the caller
still waited after each window. A useful next transfer design needs bounded
pinned staging slots, non-default streams, event-gated reuse and multiple batches
in flight while the CPU continues independent work. Cancellation must drain
queued transfers before freeing or reusing a slot, and only the original sample
owner may publish its result. Merely replacing transfer calls with their async
variants is insufficient. Multiworker native image repeatability and deliberately
held in-flight shader cancellation remain separate unresolved gates.
