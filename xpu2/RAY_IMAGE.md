# Ray-traced shading migration fixture

The October 17, 2026 check passes on the RTX 3090 and the retained native AVX8
build. A custom reference path tracer now exercises real native/CUDA sampling
and Lambert shading against geometric hits, throughput and an accumulated image.
This is **not a MoonRay integrator image-parity or speed benchmark**. Traversal,
ray origins, throughput and film use shared host Python code; the CUDA callbacks
perform sampling and shading only. Original XPU remains unchanged.

## Fixture and transport

The fixed 32 x 24 image has four deterministic camera samples per pixel and at
most four scattering bounces. Two diffuse spheres sit inside a partially open
room with colored walls, a ceiling emitter and a constant environment. Analytic
sphere/rectangle intersections select the nearest positive hit. Surface normals
and ray directions feed the actual Lambert operation. Invalid geometry flags
and zero PDFs terminate paths; sampled f*cos/PDF updates float32 throughput.
Paths accumulate emitted/environment light, then the film reduces camera samples
in fixed pixel/sample order. There is no next-event light sampling or MIS.

The sampler uses unique pixel/camera-sample sequence addresses and the measured
AVX8 cache-window domain around indices 1014/1022. This is a diagnostic sequence
mapping, not MoonRay's production path-sampling convention. The AVX8 profile
must remain unchanged across device handoffs. Sampler/shader output values are
never computed by a Python RNG or uploaded as expected results to CUDA.

Each run independently traces returned directions and carries returned sampler
state. The verifier compares every hit, ray, throughput, sampler state, shader
result, contribution and final float32 RGB bit against the CPU-only baseline.
Mixed schedules alternate ownership by path and bounce; the shuffled schedule
also changes batch order. Shader-unavailability after a draw and missing-table
fallback must return the complete original state before CPU completion.

## Measured results

All five schedules pass: native with four workers, GPU-only shading, GPU with
forced CPU fallback, alternating CPU/GPU, and shuffled CPU/GPU. Compared with the
single-worker native baseline, every schedule has **zero different RGB bits and
zero different path events**. The independent earlier run produced the same
baseline film and trajectory hashes.

- 3,072 camera paths, 9,960 traced events and 6,888 sampler/shading operations.
- 1,021 emitter terminations, 1,540 environment terminations and 511 bounce caps.
- All six diffuse surfaces receive hits, including 730 secondary sphere hits.
- GPU-only performs all 6,888 shading operations on CUDA; it has no CPU fallback.
- GPU-preferred with fallback performs 6,602 CUDA and 286 native operations.
- Each mixed schedule performs 3,603 native and 3,285 CUDA operations, with
  1,776 CPU-to-GPU and 1,868 GPU-to-CPU transitions and 137 fallback operations.
- Removing spheres only from secondary visibility changes 1,066 of 2,304 RGB
  components, with maximum linear RGB difference 1.904000163. This is an expected
  negative-control mismatch; it proves secondary geometry affects this image.

Film SHA-256:
`93e7e9be2b946d7c273ef6566ad06b377cca8530efd099573d81f1c7b0cb1f73`

Canonical trajectory SHA-256:
`f00186d5dabd690033b4b35cb88094f4615f77e172ff58d6d7bb718c81732aab`

The complete evidence, hardware/compiler identities and source hashes are in
[ray-image-20261017.json](ray-image-20261017.json). The pinned trajectory is
`reference/ray-image-avx8-20261017.json.gz`; its decompressed JSON keys are
`path_id:bounce`. The pinned `.rgb32f` file is 32 x 24 x 3 little-endian float32,
row-major RGB with the top row first. The PPM in the local test output is a
clipped gamma-2.2 diagnostic display only, not a color-management reference.

The 194-test regression suite passed before the final schedule split. All nine
image checks passed afterward, including the added invalid/zero-PDF termination
check: 195 distinct unit checks passed overall. Existing CUDA window, missing
resource and 48-step continuation checks also pass in the final image run.
This physical fixture generates no invalid or zero-PDF samples; those termination
branches are covered by unit checks, not claimed as native rendered coverage.

## Limits and next step

Native shading uses the existing isolated retained-object executable and original
ISPC bodies, not a newly built production renderer. Transport still uses files,
hidden native processes and synchronous GPU transfers. The fixture's fixed
1e-4 origin offset applies only to its metre-scale geometry; it is not a proposed
production bias. There are no textures, Fresnel, volumes, multiple lobes, AOVs,
GPU traversal, asynchronous CPU/GPU execution or scene-loading measurements.
Exact agreement is evidence for this measured fixture, not arbitrary-scene parity.

Next: bridge these shading transactions into an isolated native MoonRay path
experiment and compare its geometry, contribution queues and final image against
unmodified XPU before enabling asynchronous scheduling or claiming speedup.

## Reproduce

Use a fresh output folder and the verified retained native build/table exports
from [SHADING_EXCHANGE.md](SHADING_EXCHANGE.md). Do not install either candidate.

    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/sampler-window-avx8-20261017.jsonl.gz --tables test-results/xpu2-native-tables --window test-results/xpu2-native-window-tables --shading-native test-results/xpu2-native-shading-exchange-fixed --shading-runtime test-results/xpu2-origin-build/control --shading-materials xpu2/reference/lambert-stress-avx8-20261017.jsonl.gz --shading-image --output test-results/ray-image-new
    python -m unittest discover -s tests -p "test_xpu2*.py" -q

The follow-up [NATIVE_INTEGRATION.md](NATIVE_INTEGRATION.md) connects the operation
to native MoonRay sampling/shading calls and validates real XPU images and selected
contribution queues. Asynchronous queueing remains a separate next step.
