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

## Bounded diagnostic drain and empty-batch validation

The queue now has an explicit `stop(deadline)` admission-close/drain handshake.
It rejects new calls to native CPU fallback, drains already accepted requests,
and signals when the worker has reached its exit path. If work is held, it
returns false after the condition-variable wait expires, leaving ownership
intact; a later call can wait again. Repeated calls after draining succeed.
The deadline applies after acquiring the queue mutex and is not a hard realtime
bound. The native hook does not yet call this method during renderer shutdown.

[Drain evidence](queue-drain-20261017.json) records six passing standalone checks
and 208 passing unit checks. Two drain runs each held one in-flight request and
32 pending requests. The requested 20-ms wait returned false after 32 and 31 ms.
Calls arriving while closing and after stopping kept native answers. Releasing
the worker delivered all 33 accepted requests correctly, with exact CUDA/native
shader results and no duplicate publications. The later stop succeeded and a
zero-duration repeated stop succeeded. Capacity and both timeout regressions
also passed. Each stress case now requests an idle drain before process exit.

The formerly review-only empty-batch edge case is now exercised. The harness
sets `coalesceUs` directly to 11,000,000 under the queue mutex, solely to keep
batch assembly open past the real ten-second caller timeout. Production
configuration remains clamped to 1000 microseconds. The request times out and
is pruned; stopping interrupts the coalescing loop. The worker observes exactly
one empty batch, performs no shader dispatch, never initializes its GPU bridge,
and reaches the exit path. A subsequent call retains its CPU answer.

**This is not a reusable renderer shutdown implementation.** The thread remains
detached and the queue/CUDA resources remain process-owned. The exit handshake
is not a thread join or permission to unload the DLL or destroy the queue;
callers and thread lifetime must be handled by a future reusable owner. CUDA
resource cleanup, device-loss recovery and Modo shutdown remain unvalidated.

    python tools/xpu2_queue_stress.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/queue-drain-new --cases shutdown,shutdown,capacity,timeout,pending_timeout,coalesce_timeout

### Native regression with drain-capable queue

[Native drain evidence](native-drain-20261017.json) records the final retained-object
build and complete 15-case normal-render matrix. Single-worker replacement,
mixed repeats and fallback cases retain exact RGBA and selected-path results;
the intentional sentinel still changes the image. Native GPU shader comparisons
remain exact. These renders do not invoke the drain method; that method is
covered by the standalone checks above.

Four-worker native controls differ in 5 pixels. Mixed runs differ from the first
control in 5 and 3 pixels, and from each other in 4. Maximum channel difference
is again 1.4901161193847656e-08; the bitwise image gate remains false. No tolerance
was relaxed. The native source hash matches the final stress candidate. No
installed kit, shared checkout source, or original XPU architecture was changed.

## Explicit worker join and CUDA cleanup

The standalone owner can now stop, join and delete a queue. The worker retains
its `std::thread` handle. After its final batch, it releases CUDA buffers, events,
module and context on the worker thread, restores the previous current context,
and releases its driver-library reference. Every driver release result is
checked; cleanup failure makes `stop()` fail. Resource/log handles are cleared
when released. Initialization failures are covered by the same cleanup path.

Only after the worker signals completion does `stop()` join it. A lifecycle
mutex serializes competing stop/join operations. A timed-out stop retains the
thread and resources for a later attempt. Owners must stop admission, quiesce
all callers, and successfully stop/join before deleting; deleting a still-joinable
queue is rejected by termination rather than implicitly blocking inside a
potential loader callback. This remains an experimental owner contract.

[Cleanup evidence](queue-cleanup-20261017.json) records eight successful standalone
processes using the final queue source. There were eight successful GPU
create/render/stop/join/delete cycles and four missing-PTX cycles. Each successful
cycle returned exact native-reference shader results. Each missing-PTX cycle
retained its CPU answer and released its partially initialized context. All
cycles reported zero cleanup errors, no joinable worker, and no remaining owned
CUDA/library handles. Repeated stop calls remained successful. Capacity,
in-flight timeout, pending cancellation, held-worker drain and forced empty-batch
checks also completed with explicit cleanup and deletion.

The first six-process matrix and the subsequent partial-initialization/control
matrix have different harness hashes, but identical queue source hashes. The
existing unit-tested Python verifier did not change; its prior 208-check result
is not represented as a new run here.

The earlier detached-thread/process-owned-only limitation is superseded **for
explicit standalone owners**. The native renderer hook still keeps a process-owned
singleton and does not invoke this owner lifecycle during Modo shutdown. DLL
unloading, renderer integration, device loss and long-running memory behavior
remain separate validation work. Release-call success is not a memory benchmark.

    python tools/xpu2_queue_stress.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/queue-cleanup-new --cases lifecycle,lifecycle_missing_ptx,shutdown,capacity,timeout,pending_timeout,coalesce_timeout

### Native regression after cleanup support

[Native cleanup evidence](native-cleanup-20261017.json) records the matching
retained-object build and full 15-case rendering matrix. Normal single-worker
GPU replacement, alternating CPU/GPU repeats and fallback controls retain exact
RGBA and selected-path results. The sentinel changes the image as intended.
All GPU/native shader comparisons match; native renders do not invoke shutdown.
The four-worker bitwise image gate remains false, including differences between
native control repeats. No tolerance or benchmark claim has changed. Installed
XPU and the shared checkout remain untouched.

In this matrix the native control repeats differ in 16 pixels, with maximum
channel difference 2.9802322387695312e-08. Mixed candidates differ from the first
control in 25 and 16 pixels (maximum 1.4901161193847656e-08), and from each other
in 17. These observations do not establish a tolerance or the cause of each
candidate difference; exact multithread parity remains an open gate.

## Windows DLL boundary validation

[DLL boundary evidence](dll-boundary-20261017.json) records a separately compiled
Windows test DLL containing the unchanged actual queue stress code, plus a host
loader. This is a diagnostic module, not the complete MoonRay shading DLL or a
Modo plugin. The queue source hash matches the last native-render candidate.

The final loader completed ten load/run/cleanup/unload cycles: four loads each
running four successful GPU owner lifecycles; four loads each running four
missing-PTX/native-fallback lifecycles; and two loads each running a held-worker
drain with 33 accepted requests. Every GPU result matched its pinned native
reference. Every lifecycle joined its worker, checked resource cleanup and
deleted its owner before returning across the exported C ABI boundary.

For every cycle, the loader verified the module was absent before loading,
confirmed that the same lookup returned the loaded module's handle, then called
`FreeLibrary` and verified absence again. A short post-unload scheduling interval
and repeated reloads completed without process failure. Held-worker scenarios
still returned false at the initial stop deadline, retained CPU answers for
closed admission, then delivered all accepted results before cleanup/unload.
No renderer operations or CUDA cleanup run from `DllMain`.

This closes the controlled diagnostic DLL-boundary gap, not general plugin
unload safety. Actual Modo admission/callback lifetime, the complete native
shading DLL, device loss and long-duration memory behavior still need testing.
The native hook remains process-owned and is not yet connected to this explicit
owner lifecycle. Existing native image tests were not repeated because the queue
implementation is unchanged; multithread bitwise image parity remains unresolved.

    python tools/xpu2_dll_probe.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/dll-boundary-new

## Nonblocking submission milestone

The queue now also exposes owned asynchronous tickets with bounded outstanding
results, revision checks and explicit cancellation. See [ASYNC_QUEUE.md](ASYNC_QUEUE.md)
for the contract and recorded stress checks. The native hook still uses `run()`;
this does not yet replace synchronous native calls with path continuations.
