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

## Follow-up: capacity and timeout stress

[Queue stress evidence](queue-stress-20261017.json) records a standalone harness
that includes the **unchanged actual queue source** and executes the real CUDA
shader against pinned native AVX8 inputs. This exercises queue behavior directly;
it does not render another scene or validate Modo shutdown.

Two capacity runs each kept one request in flight, filled all 64 pending slots,
and checked eight overflow requests retained their CPU answers. All 65 accepted
requests reached the correct callers without duplicates. The worker processed
520 samples in two batches (8 and 512), with zero shader mismatches or errors.

A separate run held the worker behind its device mutex until the real ten-second
caller timeout fired (10,010 ms observed). The caller kept its native answer,
then overwrote both input and output buffers before the worker was released.
The late result was discarded without changing those buffers. A subsequent
request completed with the expected GPU result. Both requests' CUDA results
matched the captured native inputs, confirming the worker used owned input copies.

This advances timeout evidence beyond the initial render matrix, which did not
exercise it. The test deliberately holds a mutex; it is not a device-loss or GPU
hang test. Pending-request cancellation, renderer shutdown and DLL unloading
remain separate work. The four-worker image parity gate remains unresolved.

    python tools/xpu2_queue_stress.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/queue-stress-new

The runner freezes preprocessing, records compiler/executable/source hashes,
checks the GPU identity before and after, and requires a fresh output folder.
It never starts Modo, installs a runtime, or edits the shared source build.

## Follow-up: pending timeouts mixed with a fresh request

[Pending-timeout evidence](queue-pending-timeout-20261017.json) extends the same
unchanged queue implementation to pending-request timeouts. Two standalone runs
each held one in-flight request and 63 pending requests until all 64 callers hit
the actual ten-second deadline (10,045 and 10,024 ms observed). Each caller
retained its native output, then reused its input and output buffers with unique
sentinel values.

A fresh request entered the remaining pending slot before the worker was released.
It shared a 512-sample GPU batch with the 63 cancelled pending requests. Both runs
published only request 64, preserved all reused buffers, and counted exactly
64 late discards. The fresh result matched its expected GPU output bit for bit.
All 520 shader samples per run matched their native reference, with zero errors.

The tests expose an optimization still needed: cancelled pending requests are
currently computed before publication is suppressed. The queue is bounded and
ownership checks passed, but pruning cancelled work could avoid wasted GPU work.
These controlled delays do not establish renderer shutdown, device-loss recovery,
or production cancellation. The four-worker image parity gate is unchanged.

Run just these new cases without repeating earlier checks:

    python tools/xpu2_queue_stress.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/queue-pending-timeout-new --cases pending_timeout,pending_timeout

## Cancellation pruning

The candidate now removes a timed-out request from the pending deque while
holding the queue mutex. That immediately frees its slot and avoids submitting
its samples to CUDA. If the worker has already taken the request, the existing
owned-buffer and late-publication protections still apply. A new
`cancelled_before_dispatch` counter distinguishes these cases. The worker also
skips an empty batch if timeouts remove all pending work while coalescing releases
the mutex; that race guard is reviewed, not deterministically injected here.

[Pruning stress evidence](queue-pruning-20261017.json) records the final source
identity and four passing standalone processes: capacity, in-flight timeout,
and two pending-timeout runs. The full 512-sample capacity case still matches
native shading. Pending-timeout cases now prune 63 requests, discard one late
in-flight result, and deliver the fresh request correctly. GPU samples drop
from 520 in the preceding fixture to 16, with all 64 reused caller buffers
preserved and zero shader mismatches. This measures avoided work under injected
cancellation, not rendering speed. All 208 XPU2 unit tests passed.

The preceding sections and their evidence describe earlier candidates. Their
statement that pending cancelled work is computed is superseded by this change.
Production renderer cancellation, shutdown, device loss and nonblocking path
continuations remain separate integration work.

### Native regression after pruning

[Native pruning evidence](native-pruning-20261017.json) records a rebuilt,
isolated candidate and the complete 15-case matrix. The queue source hash matches
the standalone stress candidate. Original/control/disabled, all-GPU, alternating
CPU/GPU repeats, sentinel, queue-full, missing-PTX and unsupported-state cases
completed with their expected exact-image or intentional-negative-control results.
All-GPU shading matched 93,384 native samples; mixed single-worker runs matched
46,692 GPU samples each. No timeout or cancellation occurred in these renders.

The four-worker runs matched 51,136 and 46,688 GPU shader samples with no missing
or duplicate publications. Native control repeats differed in 4 pixels; mixed
runs differed from the first control in 3 and 13 pixels, and from each other in
10. Maximum channel difference remained 1.4901161193847656e-08. The bitwise gate
is still false. One mixed run recorded no overlap observations; the other
recorded 44 CPU completions while GPU work was pending and 5 CPU observations
inside CUDA event windows. These scheduling observations are not speed metrics.

No source in the shared checkout or installed kit was changed. The native test
still uses synchronous callers and duplicate CPU reference shading. It does not
establish a production XPU2 backend or a render-time improvement.
