# Native XPU shading integration diagnostic

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

On October 17, 2026, a live CUDA Lambert operation was connected to the native
MoonRay XPU integrator in an isolated diagnostic build. The normal replacement
runs reproduce all 36,864 pixels of the reference image bit-for-bit. This advances
beyond the custom host tracer in [RAY_IMAGE.md](RAY_IMAGE.md); it does **not** yet
provide an asynchronous or accelerated production XPU2 backend.

## What runs inside MoonRay

An instrumented copy of `LambertBsdfLobe_sample` packs active AVX8 lanes, calls a
C++ bridge, and consumes returned direction, RGB and PDF values. The bridge loads
the already validated AVX8-profile CUDA shader through the NVIDIA driver API.
Its dedicated CUDA context is pushed for the call and popped afterward, preserving
the context used by MoonRay's OptiX traversal. Up to eight active lanes are sent
per batch. No expected CPU answers are sent to CUDA.

The original native answer is deliberately computed too. Every returned GPU
packet must preserve its inputs and match the native direction, RGB, PDF and
validity flag exactly before replacement. Unsupported or invalid packets,
GPU errors and mismatches retain the native answer. The verifier rejects a normal
run with any error, invalid record or mismatch, so silent fallback cannot turn a
failed parity check into a pass. This is validation overhead, not acceleration.

The diagnostic has explicit environment modes: disabled, audit, replace and a
sentinel negative control. The sentinel first validates the GPU result, then
halves its returned RGB before passing it to the native integrator. This intentional
wrong answer proves the bridge output is connected to the rendered image.

## Validated fixture and results

The fixture is the retained 256 x 144 mesh-sphere scene with one camera sample,
a constant environment and native light/BSDF sampling. UsdPreviewSurface is set
to specular workflow with black specular color, and shadow-terminator correction
is off. Thus the tested lobe is diffuse Lambert without Fresnel attenuation.
Rendering uses one CPU worker and native XPU traversal on the RTX 3090.

Ten isolated renders pass their respective positive/negative controls:

- Original retained runtime; relinked control; instrumented hook disabled.
- Audit: 93,384 CUDA shader samples in 11,680 batches, all exact native matches.
- Replacement and repeat: all 93,384 samples replaced with CUDA results each time;
  zero mismatches, invalid records, unsupported samples or driver errors.
- Sentinel: 23,346 pixels change, and selected radiance contributions change as
  expected. These differences are intentional, not a normal parity result.
- Missing PTX: GPU shading is refused; all shading stays native and the image
  remains exact. Expected initialization/unavailable errors are reported rather
  than hidden; this control is not counted as a successful GPU shading run.
- Unsupported shadow-terminator fixture and its control: all 93,384 shader samples
  decline to native shading, with zero replacements and the exact control image.

For normal replacement, 653,688 direction/RGB/PDF float components and 93,384
validity flags match bit-for-bit. The complete float32 RGBA image also matches,
including signed-zero bits. Ten selected surface-ray records (two primary and
eight depth-one) match, as do radiance contribution multisets and matched shadow
visibility at the two diagnostic pixels. This is selected-path evidence, not a
trace of every path or a claim of full AOV parity. Native statistics report 100%
GPU intersection routing for every run; GPU shading counters are measured
separately by the bridge. All 202 XPU2 unit checks pass.

Normal RGBA SHA-256, channel-planar R/G/B/A float32 in bottom-first row order:
`e7e22ff0727e386d5715aa399c18148d1448214f1cc9601972b43a089ee516a3`

The audit, replacement and repeat capture hashes are identical:
`39715df807458a8da5746fd8133f5a552ae5dd6116738f2d57010c66401b5ee3`

[Evidence](native-integration-20261017.json) records build/compiler/PTX hashes,
source hashes, runtime inventories, render checks, sample counters, selected
path comparisons and image metrics. The audit capture is pinned in
`reference/native-lambert-avx8-cuda-20261017.bin.gz`. After decompression it begins
with `XNI1`, followed by 164-byte records: 96-byte shader input, eight uint32 native
output words, and nine uint32 CUDA result words (status followed by output).
Float values are stored as their original float32 bits; the final validity word
is an integer Boolean. The raw capture contains 93,384 records.

## Boundaries and next integration step

This is a retained-object diagnostic shading DLL linked against copied build
inputs, with frozen preprocessing and drift checks; it is not a clean runtime
rebuild or a distributable plugin update. The primary checkout, installed kit
and original selectable XPU architecture remain untouched.

Calls are synchronous, retain duplicate CPU shading for validation, and transfer
small AVX8 batches. The CUDA context is process-owned for these bounded standalone
runs; reusable renderer lifecycle/cleanup and asynchronous cancellation are not
implemented here. Multiple native workers, other GPUs, textures, Fresnel, other
lobes, volumes, adaptive sampling, denoising, full AOVs, scene loading and demand
geometry streaming are outside this validation. Native sampling remains native;
this step specifically migrates the Lambert sampling/shading operation, using
random inputs already generated by the native integrator.

Next is a queued native shading stage that can batch work and preserve path
ownership without blocking the CPU at each shader call. Keep this exact-answer
shadow-validation mode while comparing contributions and final images, then
measure CPU/GPU overlap and speed. XPU2 remains separate and experimental.

## Reproduce

Use fresh output folders and the retained builds described by the earlier probe
documents. Neither command modifies the source build or installs a runtime.

    python tools/xpu2_build_native_shading.py --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --output test-results/native-shading-build-new
    python tools/xpu2_native_shading_probe.py --build test-results/native-shading-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/native-shading-new
    python -m unittest discover -s tests -p "test_xpu2*.py" -q

[NATIVE_QUEUE.md](NATIVE_QUEUE.md) adds bounded GPU dispatch and measured CPU/GPU
overlap in the native integrator. Single-worker results remain exact; the separate
four-worker bitwise image gate is unresolved. GPU callers still wait, and no
acceleration or production lifecycle is claimed.
