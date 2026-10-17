# First CUDA shading evaluation: Lambert

This is an isolated shading-component experiment for XPU2. Original XPU,
installed runtimes and Modo engine selection remain unchanged.

## Result

The CUDA implementation matches MoonRay's original C++ LambertBsdfLobe::eval,
albedo and BsdfSlice::isSampleGeometricallyInvalid outputs exactly on the
RTX 3090 for 11,520 cases. Each case checks seven float components (RGB, PDF,
albedo) plus a geometric-validity decision: 80,640 float components and 11,520
boolean decisions per dispatch.

The fixture varies five shading normals, two geometric-normal choices, eight
incoming directions, three outgoing directions, four albedos, three scales,
reflection/transmission and cosine inclusion. It includes grazing directions
on both sides of a tangent, back-facing directions, black/zero-scale cases,
colored inputs and HDR albedo components up to 8 with scale components up to 2.
All normals/directions are supplied as native-normalized float values.

Native generation repeats exactly with one worker twice and four workers once.
A second isolated build matches the pinned compressed reference. CUDA matches
all fields in three shuffled two-stream dispatches at block sizes 64/128/256.
Four valid unsupported packets are declined unchanged, and eleven invalid
packets are rejected unchanged. 161 focused Python checks pass, including
coverage validation, physical oracle invariants and deliberate result corruption.

The existing version-1 sampler and version-2 boundary/returned-state continuation
checks also pass after the shared harness changes. Native CPU/CUDA handoff code
was not changed or rerun in this milestone. Evidence is in lambert-20261017.json;
the native corpus is reference/lambert-eval-20261017.jsonl.gz.

## Scope and fallback

lambert_probe.cc invokes original native C++ shading objects; the CPU oracle is
not a Python rewrite of the Lambert formula. lambert_cuda.cu receives surface
parameters only and computes its own result. Expected native shading outputs are
never uploaded to the GPU. Native operation ordering is preserved, with floating
point contraction and fast math disabled.

The diagnostic packet explicitly represents the Lambert evaluation inputs and
controls. It is not a material graph or complete shading/path state. The kernel
supports only no-Fresnel, shadow-terminator-off Lambert evaluation, with finite
nonnegative albedo components up to 8 and scales up to 2. Higher finite ranges,
Fresnel and terminator corrections return unsupported rather than approximate
results. Nonfinite values, negative colors/scales, invalid controls, nonunit
directions, bad headers and truncated packets return invalid. Every input byte
is preserved on both supported and declined paths.

A lobe can return nonzero RGB even when geometric validity fails; this is native
behavior, not permission for the integrator to use that sample. The separate
geometric-validity result must be honored by future integration.

This verifies C++-to-CUDA lobe evaluation only. It does not establish parity with
the separate vectorized ISPC shading implementation. Generating a new direction
via BsdfLobe::sample, reference-frame transforms, Fresnel, shadow-terminator fixes,
derivatives, material graphs, textures and multiple-lobe sampling remain outside
this experiment. The new shading operation is not yet connected to the validated
sampler handoff or a renderer.

Native builds use frozen current headers with retained objects, not a clean
runtime rebuild. Transfers are synchronous. No rendered RGB/AOV parity,
production material compatibility, GPU utilization or speed gain is claimed.
Next work is to validate diffuse direction sampling and the native vector path,
then combine sampling/evaluation with path-state transport and image comparisons.

## Reproduce

Use fresh output directories:

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/lambert-native-new --lambert --reference xpu2/reference/lambert-eval-20261017.jsonl.gz
    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/lambert-eval-20261017.jsonl.gz --lambert --output test-results/lambert-cuda-new
    python -m unittest discover -s tests -p "test_xpu2*.py" -q

Follow-up: [LAMBERT_SAMPLE.md](LAMBERT_SAMPLE.md) adds direction sampling and
AVX8 comparison, corrects the CUDA dot-product association, and records the
unresolved vector migration hazard. The original evaluation corpus still passes.
