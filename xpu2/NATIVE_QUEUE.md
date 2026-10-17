# Native queued Lambert shading diagnostic

The isolated XPU2 candidate now routes native AVX8 Lambert requests through a
bounded CUDA worker queue. Four native producers can split between CPU and GPU
roles, allowing CPU shading to continue while the GPU worker processes requests.
XPU remains unchanged. This candidate is not installed or distributed as a runtime.

## Ownership and execution

Each request owns copies of its input and native reference output, a unique ID,
and completion state. The queue defaults to 32 pending requests (maximum 64),
with up to 512 shader samples per GPU batch. Full queues keep the native answer.
GPU-bound callers wait for their own result; other CPU producers keep working.
This is concurrent producer execution, not suspended integrator continuations.

A ten-second timeout marks the owned request cancelled and prevents late output
publication to the caller. That timeout path has not been exercised by these
native renders. The worker is process-owned and detached for standalone probes;
reusable renderer shutdown, DLL unload, and production recovery remain unvalidated.

Native CPU answers are still computed before dispatch and compared with GPU
answers before replacement. Unsupported shader states and missing PTX retain
native answers. Duplicate CPU work and diagnostic logging make this unsuitable
for speed claims. Single-worker coalescing is disabled; four-worker probes use a
bounded 100-microsecond coalescing opportunity.

## Measured results (2026-10-17)

The 256 x 144 diagnostic scene uses one camera sample on an RTX 3090 and AVX8 CPU.
The complete XPU2 unit suite passed 208 checks. The final native candidate then
completed the single-worker, four-worker and output-wiring checks described here.

- Single-worker GPU replacement matched 93,384 native shader results exactly,
  with identical float32 RGBA, selected surface rays and radiance contributions.
  Alternating CPU/GPU repeats also matched exactly (46,692 GPU samples each).
- Capacity-zero, missing-PTX and unsupported-state controls retained exact native
  images. No missing or duplicate queue publications occurred.
- Four-worker mixed runs delivered 5,844 and 5,932 GPU requests, containing 46,752
  and 47,456 shader samples. Every shader result matched its native reference.
  Requests merged into 3,210 and 3,347 batches, at most 16 samples per batch.
- CPU-role packets completed while GPU work was pending 113 and 142 times.
  CUDA start/end-event polling observed an active CPU interval inside the kernel
  window 6 and 16 times. These are observations, not utilization measurements;
  the CPU interval includes native shading and diagnostic packing.
- The output-wiring negative control halved returned GPU RGB after validation,
  changing 23,346 pixels. It proves queue results reach the native film.

**Four-worker bitwise image parity remains unresolved.** Native control repeats
differed in 15 pixels; mixed runs differed from the first control in 6 and 13
pixels, and from each other in 9. Maximum absolute channel difference was
1.4901161193847656e-08. Native repeatability is also imperfect at this scale, but
this does not establish the cause of every candidate difference. No tolerance
was relaxed and no full multithread parity claim is made.

The first combined run completed its ten single-worker cases, then encountered
interleaved JSON from the older single-thread selected-path trace writer during
a multithread control. Its report remains incomplete. The corrected multithread
rerun disables that writer; shader captures and full-image comparisons remain.
Selected paths were not measured for four-worker runs.

[Native queue evidence](native-queue-20261017.json) preserves completed runs,
source/build/runtime identities, report hashes, the incomplete report's error,
and separate parity gates. The all-GPU single-worker capture has the same raw
SHA-256 as the pinned capture in [NATIVE_INTEGRATION.md](NATIVE_INTEGRATION.md).
Reported timings include instrumentation and are not speed benchmarks.

## Reproduce

Use fresh output folders and the retained build prerequisites from
[NATIVE_INTEGRATION.md](NATIVE_INTEGRATION.md):

    python tools/xpu2_build_native_shading.py --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --output test-results/native-queue-build-new --queued
    python tools/xpu2_native_shading_probe.py --build test-results/native-queue-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/native-queue-new --queued

The probe supports `--only-multi` for the four-worker matrix, or
`--cases original,sentinel` for output wiring. Selected subsets must include
their reference cases. A passed queue report does not override the separate
`four_worker_bitwise_parity` gate.

## Remaining integration

Move waiting GPU paths into owned integrator continuations, accumulate larger
batches, and validate cancellation and lifecycle before enabling a reusable
backend. Preserve native fallback and shadow validation while isolating film
repeatability differences. Performance measurements must follow correctness and
remove diagnostic overhead explicitly. Other lobes, textures, scene-loading
acceleration and demand geometry streaming are not covered by this milestone.
