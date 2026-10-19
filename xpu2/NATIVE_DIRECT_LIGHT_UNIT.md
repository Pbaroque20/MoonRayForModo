# Larger GPU direct-light unit

This experiment qualifies a larger numerical operation for the next native XPU2
handoff: diffuse BSDF evaluation, its PDF, multiple-importance weight, and the
unshadowed light contribution. It uses the original native material/light inputs,
including parent throughput, emitted light, light sample counts, lobe sample
counts, and the separate light PDF and MIS PDF. The result is ready for native
clamping, lobe accumulation and shadow handling.

This is **arithmetic qualification**, not live asynchronous offload. The isolated
capture runtime still computes and publishes CPU results. Captured records run
on CUDA separately; copies are synchronous to isolate the numerical contract.
No installed runtime, original XPU behavior, or other chat's files change.

## Contract and boundary

Each XDL1 record has 32 float-width input words and eight native output floats.
Input word zero is the integer-bit kind (1 Lambert, 2 supported FlatDiffuse).
Remaining input words carry normal, incoming/outgoing directions, albedo, scale,
parent throughput, light radiance, sample counts, PDFs, roughness coefficients and
cosine inclusion. Words 29-31 must be zero. No native pointer or mutable arena
crosses the boundary. The CUDA output adds a ninth float: an explicit acceptance
flag; callers must ignore the other words when that flag is zero.

Outputs are material RGB, PDF, unshadowed contribution RGB, and MIS weight.
The kernel retains native multiplication grouping and the existing AVX-compatible
rough-diffuse/transcendental arithmetic. Fused multiply-add and flush-to-zero are
disabled for this numerical profile. Compiler/device changes require revalidation.

Native visibility, hemisphere eligibility, light linking and valid-sample checks
run before capture. Only accepted diffuse light contributions are recorded, up
to 65,536 of each kind per scene. Fresnel, spherical lobes, shadow-terminator
corrections, modified FlatDiffuse flatness/terminator shift, and other materials
remain outside this contract. The kernel rejects unsupported kinds, flags,
nonfinite data, invalid directions, negative supported colors, and invalid
sample counts/PDFs. This is not complete material or light coverage.

Clamping, per-lobe accumulation, LPE state, shadow queries and film updates remain
native. Independent GPU units must return before these consumers execute, in the
original contribution order. The scene index must invalidate material/light
inputs together; it cannot treat previously packed contributions as reusable
merely because the mesh did not move.

## Qualification, 2026-10-18

Evidence: [native-direct-light-unit-20261018.json](native-direct-light-unit-20261018.json).

Two native fixture pairs (reflection/transmission and rough material) produced
four exact float32 RGBA images, including the reference images. Capture did not
alter those images. Each scene yielded 131,072 bounded records; total corpus:
131,072 Lambert and 131,072 FlatDiffuse contributions. These are records, not
necessarily unique material configurations or independent paths.

All 262,144 records matched the eight native outputs **bit-for-bit** with CUDA
block sizes 64, 128 and 256 and independently shuffled record orders: 786,432
successful unit evaluations, zero declined valid records, zero differing outputs.
Restoring record order gave identical output bytes across launches. Thirteen
malformed/unsupported packet controls were rejected. An intentional numerical
perturbation confirmed the comparison detects an incorrect contribution.

These are one-worker native captures on an AVX CPU and RTX 3090, not multiworker
renderer repeatability or production scene validation. No full-render performance
claim follows from the GPU unit tests. Capture timing includes diagnostic work
and must not be compared with a production renderer.

## Reproduce

1. Build `tools/xpu2_native_light_build.py` from the frozen qualified
   sample-reuse build, using `--source`, `--base`, and a fresh isolated `--output`.
2. Run `tools/xpu2_native_light_capture.py` with `--build`, `--reference`, `--scene`
   and a fresh `--output` for each fixture. The runtime enables recording only
   with `XPU2_LIGHT_CAPTURE`; its ordinary output remains native.
3. Run `tools/xpu2_direct_light_probe.py --source ... --captures ... ... --output ...`.
   It compiles the CUDA unit, checks qualified capture hashes, compares native
   outputs, varies launch order, and rejects unsupported packets.
4. Collect the reports with `tools/xpu2_direct_light_evidence.py`.

## Next integration gate

Prepare bounded groups of eligible light/lobe inputs while their owning native
continuation is alive. Submit them through the asynchronous queue, do independent
CPU work, then consume each result once. Skip the replaced CPU evaluation only
after a packet is admitted; on refusal/failure compute the native result once.
Keep native contribution order, immutable revisions, cancellation drains and
queue capacity limits. Avoid one synchronous CUDA launch per light or per lobe.

The current sampler queue uses a different 24-word input and cannot safely accept
this 32-word unit without a versioned transport and result-lifetime change.
That transport integration, live image parity, cancellation/replacement, and
paired full-render timings are still required. A 75/25 device contribution target
must be evaluated by useful work and render time, not by raw packet counts.
