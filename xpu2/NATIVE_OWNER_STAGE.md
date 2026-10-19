# Rolling owner-scoped shading queue

This tests the smallest safe queue-stage change after [no-wait fallback](NATIVE_NO_WAIT.md).
It is experimental and opt-in (`XPU2_OWNER_STAGE=1` with `XPU2_NO_WAIT=1`).
Original XPU, the installed runtime and production defaults are unchanged.

## What the code actually does

The previous handler prepared two/four chunks, finished that entire group, then
prepared the next group. The candidate uses a bounded FIFO of separately owned
chunks. After finishing the oldest chunk, it prepares another chunk in the freed
slot before consuming the next result. That preparation performs native presence,
intersection conversion, material/BSDF evaluation and supported sample dispatch.
The CPU can therefore prepare later material work while earlier GPU jobs run.

There is no wait or readiness spin in this scheduler. If the queue is full or the
input ends, it integrates the oldest chunk; the existing no-wait collector uses
CPU fallback for any still-pending result. Preparation and integration remain on
the original owner thread. Child rays and film contributions publish in native
chunk order. CUDA workers retain numerical requests and publish completed results
through the existing ticket mechanism, without touching native arenas or queues.

Two/four chunk capacities retain at most 128/256 input rays in this handler's
queue (64 rays/chunk); existing GPU credits and prepared-record bounds also apply.
These are not total renderer memory limits. On cancellation, chunk owners revoke
tickets and the GPU queue retains submitted storage until retirement. The queue
contract checks FIFO identity, wraparound, full/empty rejection and exact retirement.
Frame counters check produced = resumed + canceled, queue depth and actual GPU use.

## Important boundary: not a full native asynchronous shading stage

The handler's stack, arena, intersections, BSDF closures and material context
remain alive. The worker does **not** return to arbitrary native queues or tiles
while these chunks wait. This is an owner-scoped producer/consumer queue and a
measurement of useful CPU preparation between consumption points, not the complete
Step 2 architecture. The deferred-path `gpuEnabled()` gate remains false.

A full stage needs independently owned shading continuations and a native-owner
completion pump outside this handler. Existing `defer()` captures only a restricted
post-shading numeric path; it does not retain arbitrary material closures or the
pre-shading context. Earlier recursive native-queue helping changed images even
when attribute offsets were saved. Do not rehabilitate that path by turning on
the old gate or copying arena pointers into a mailbox.

Until native context isolation is established, keep the current immediate CPU
fallback. Stable sample IDs and standalone order-independent accumulation do not
by themselves qualify native multiworker film or path regrouping. No multiworker,
adaptive sampling, arbitrary material or multibounce GPU claim is made here.

## Measured result (2026-10-19)

[Evidence, source identities and complete counters](owner-stage-20261019.json).
One native worker, fixed-sampling 384 x 216 diffuse/transmission fixture, warmup
plus three rotated rounds, profiling scopes off:

- Original XPU median: **7.720 s** (7.692–8.182).
- Previous no-wait build: **10.241 s** (9.974–10.517).
- Same candidate, rolling queue off: **9.961 s** (9.834–10.190).
- Rolling queue, two chunks: **10.069 s** (10.035–10.505).
- Rolling queue, four chunks: **10.136 s** (10.078–10.180).

There is **no demonstrated speedup**. Against the same-build queue-off control,
two-chunk paired differences are +0.315, +0.074, +0.235 seconds; four-chunk
pairs are -0.054, +0.219, +0.244 seconds. Two chunks remain 2.349 seconds slower
than original XPU by these medians. Do not promote this as a performance default.

The median consumed GPU sample-lane counter rises from 1,030,152 with the queue
off to 1,853,272 with two chunks and 1,927,664 with four. Median sampler trips fall
from 11,892 to 10,556 and 10,965 respectively. Both native collector wait counts
remain zero. Direct-light GPU consumption remains zero in all measured cases.
These are sampling-stage counters, not percentages of the whole render running
on the GPU or measurements of GPU utilization. Increased sampling coverage has
not amortized the remaining preparation, handoff and integration costs; the sweep
does not isolate the exclusive cost responsible for the remaining slowdown.

Final-candidate correctness includes both depths, explicit zero flags, held flights,
missing kernels, both queue upload failures, stale records and exhausted storage.
All normal/fallback/control images are exact float32 RGBA matches. The intentional
GPU sentinel changes the image. Held-owner cancellation/replacement passes, all
checked resources retire, and all 20 timing images match original XPU exactly.
Enabled multiworker, adaptive rendering and arbitrary material coverage remain
unqualified.

A competing renderer interrupted one check matrix. That run remains marked
incomplete; its affected frame is excluded. Only the unfinished cases were rerun
with a fresh reference, then the complete guarded timing sweep passed. Before/after
process checks do not exclude every possible brief intervening external workload.

## Cancellation checkpoint

The first held-flight test canceled the render but caught no parked owner chunks;
all local continuations had already resumed. A second checkpoint held two owner
chunks during the initial progressive sample pass. Native `TLState::isCanceled()`
intentionally ignores cancellation until `mCurrentPassIdx > 0`, so that test also
failed the stronger pending-owner assertion. Its completed replacement image was
correct, but it does not qualify pending-owner cancellation.

The corrected test holds two queued owner chunks only in a later pass, then sends
the normal persistent-session replacement command. It must observe nonzero canceled
owner chunks, balanced GPU/record lifetimes and an exact replacement image. This is
a test-only pause, disabled by explicit zero, not a production waiting policy.

The corrected run passed: 83 owner chunks were produced, 81 resumed and two were
canceled. The replacement resumed all 3,733 chunks, retained no checked resources
and matched both fresh and original-XPU images exactly.

## Reproduction

Use fresh output directories:

```text
python tools/xpu2_native_build.py --stage owner_stage --source <primary-read-only> --base <no-wait-build> --output <candidate-build>
python tools/xpu2_no_wait_probe.py --owner-stage --mode checks --build <candidate-build> --previous <no-wait-build> --reference <original-xpu-runtime> --scene <fixture.rdla> --ptx <resident-film.ptx> --light-ptx <direct-light.ptx> --output <results>
```

Use `--mode cancel` for held-flight cancellation/replacement, `--mode timing` for
warmup and three rotated rounds. Profiling scopes remain off. Lifecycle counters
remain enabled in both controls. The harness rejects competing renderers and
checks source/runtime hashes and GPU identity before/after the run.
