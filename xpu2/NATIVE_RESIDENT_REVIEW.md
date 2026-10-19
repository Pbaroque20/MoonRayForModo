# Resident record review fixes

Original XPU and the installed kit are unchanged. These fixes apply to the
experimental native resident-record candidate in PR #130.

- Eligible lean-wire resident batches now skip host record expansion, transport
  input copying and pinned full-input copying. Full-echo diagnostics, record dumps
  and nonresident paths retain their required inputs. Native replay is unchanged.
- Cache tags remain pending until the flight's upload, kernel and readback complete.
  Upload failure or a rejected record aborts the transaction and invalidates tags.
- Explicit `0` disables resident flush/stale/mixed-injection options.
- The host encoder and CUDA kernel share `resident_wire.h` and layout assertions.
- Stale records now produce an explicit rejected status, warning and counter. The
  CPU uses its existing fallback instead of accepting a black result. The previous
  implementation already rejected stale zero inputs via its sampler-invalid
  status; the earlier claim of silent successful black output was not reproduced.
- Mixed revisions are rejected locally before entering CUDA error handling. Later
  batches continue using the GPU, rather than disabling it for the frame.
- Forty-four duplicated build scripts were replaced by `tools/xpu2_native_build.py`
  and stage-specific patch modules. `legacy-builders.json` pins their historical
  source hashes and revision. Use that revision for old experimental commands.
  The current pipeline supports resident/prepared/overhead/material_jobs/
  material_admission stages; only resident was rebuilt in this review.

## Validation

The host protocol passed normal and native AVX/fast-math builds. The consolidated
builder produced equivalent generated source, apart from the intentional layout
assertion and rejection warning. All 17 native regression cases passed: 16 matched
original XPU exactly, while the deliberate sentinel changed the image as required.
Stale records, mixed revisions, upload failure, pool pressure, missing kernels,
full echoes, replay mismatches and cancellation were exercised. Cancellation and
replacement matched fresh/original images, with no pending transactions left.

Three rotated timing rounds on the fixed diffuse/transmission fixture gave median
MCRT times of 8.290 s for original XPU, 11.448 s for resident-records-off (GPU
shading still enabled), 11.676 s with old input copies retained, and 11.353 s with
those copies removed. The ranges overlap; this is not a demonstrated speedup.

A separate truly-disabled comparison removed every XPU2 option. At one thread,
original XPU measured 7.920 s versus 8.652 s for the disabled candidate: 9.2%
overhead, failing the declared regression budget. At 12 threads, medians were
1.754 s and 1.691 s, respectively. Both original and disabled multiworker images
varied between repetitions; these measurements do not establish statistical
image parity or qualify the enabled multiworker path.

The first mixed-version test run stopped because the harness expected zero failed
transport batches. It was corrected to require exactly one local rejected batch,
zero GPU errors and subsequent accepted GPU work. The failed report was retained;
it was not counted as a pass.

Compact results and report hashes: [resident-review-20261019.json](resident-review-20261019.json).
Next architecture gates: [XPU2_ACCEPTANCE.md](XPU2_ACCEPTANCE.md).

## Reproduction

Use a fresh output directory for each command. Build the resident stage with
`tools/xpu2_native_build.py --stage resident --source <primary-source> --base
<qualified-prepared-build> --output <isolated-build>`. Compile its kernel with
`tools/xpu2_native_resident_ptx.py`. Run `tools/xpu2_native_resident_probe.py --checks`
for the fault matrix and `tools/xpu2_native_resident_cancel.py` for recovery.
`tools/xpu2_disabled_baseline.py` compares a true disabled candidate at one and
all configured CPU threads. Frozen base/runtime hashes are checked throughout.

Full scene residency, large GPU material jobs, multibounce GPU integration and
production statistical qualification remain unfinished. These corrections do not
claim to complete those requirements.
