# Shared-context diagnostic and batch-layer preparation

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

XPU2 remains opt-in and separate from XPU. This candidate is not installed and
is not full asynchronous material shading.

## Why investigate the slowdown

The previous accepted shadow-helper comparison takes 18.679 s median MCRT,
versus 16.251 s for the split stage and 7.277 s for original XPU. In its first
measured round, native GPU occlusion accounting rises from 0.27896 s (stage) to
7.44398 s (helper). Both consume 3,250,134 supported GPU material samples and
submit 45,170 material batches, about 72 samples per batch. This points to the cost of early shadow submissions, without separating transfer,
launch, driver waiting and traversal costs. It is not additional material work. GPU event intervals,
CPU submit/poll intervals and native task timings overlap; do not add them.

At the tested 16-packet limit, an individual launch contains at most 128 samples,
with 64 CUDA threads per block. Two in-flight batches therefore supply at most
four shading blocks at a time. This is a work-supply limitation, not evidence of
high hardware occupancy. Native shadow dispatch uploads, launches, downloads and
then calls cudaStreamSynchronize before returning. A pending material flight does
not make that native call nonblocking.

## Context comparison

The earlier bridge creates a private CUDA context. Native OptiX initializes the
CUDA runtime and uses its current context. `native_context.py` adds the opt-in
`XPU2_CUDA_CONTEXT=primary` mode, retaining the already-active device-0 primary
context. NVIDIA documents the primary context as shared with the runtime:
https://docs.nvidia.com/cuda/archive/12.8.0/cuda-driver-api/group__CUDA__PRIMARY__CTX.html

The comparison uses unchanged shading PTX, batch limits, samples and queue policy.
Private/shared context and shadow helping off/on form four configurations, with
unchanged XPU as the reference. A context being shared does not prove concurrent
kernel execution or improved end-to-end speed.

Primary mode requires nonblocking flight streams and an already-active primary
context. It never resets or destroys that context. Cleanup and partial-upload
failure drain only the bridge's own streams before releasing its allocations and
primary reference. The profile verifies retain/release balance and that the
primary context remains active after cleanup. Default mode remains private.

Reproduce with fresh directories:

    python tools/xpu2_native_context_build.py --source <read-only-primary> --base test-results/xpu2-origin-build --output <build>
    python tools/xpu2_native_context_probe.py --build <build> --reference test-results/xpu2-origin-build/control --ptx test-results/xpu2-native-work-ptx/film.ptx --previous test-results/xpu2-native-work-build --previous-ptx test-results/xpu2-native-work-ptx/film.ptx --scene <fixture> --output <controls> --checks

Without `--checks`, the probe runs warmup and three rotated timing rounds. Do not
accept timing while another renderer is active. Missing PTX, zero admission
capacity, a deliberate color sentinel, and failure after upload are explicit
controls. Cancellation/replacement and unsupported adaptive frames are separate.

## Preparatory abstraction

`batch_transport.h` is a small backend-independent foundation, not yet connected
to the native renderer. It centralizes the existing 96-byte input / 32-byte
fallback / 232-byte transfer layout, packs up to 64 eight-lane packets into
reusable fixed-capacity storage, and records packet offsets without changing
numerical bits or sample order.

Each batch has a slot identity, monotonic generation and scene revision. State
transitions reject foreign, stale and duplicate completions, including reuse of the same slot address
by a new object. Cancellation revokes
publication but leaves submitted storage owned until the backend confirms event
completion or drains a failed upload. Only the owning dispatch worker uses this
class; existing queues/mailboxes still provide cross-thread synchronization.

This deliberately does not add another scene hierarchy, scheduling policy,
allocator per sample or virtual call per ray. CUDA allocation, submission,
completion events, numerical validation and film publication still belong to the
existing adapter. It is not a new GPU renderer or a demonstrated optimization.

The next integration should replace duplicated packing/slot bookkeeping with this
contract, keep backend behavior unchanged, and add per-batch pack/submit/poll/
retire timing. Only after image and recovery gates pass should polling frequency,
batch readiness or scheduling change. More independent native work remains needed
to amortize the current tiny shader launches.

    python tools/xpu2_batch_transport_probe.py --compiler <g++.exe> --output <fresh-output>

The standalone contract checks cover full-capacity packing, NaN payload and signed
zero bit preservation, invalid admission, foreign ownership, stale revisions,
slot-address reuse, cancellation before and after submission, failed completion and
exactly-once publication. They run with both standard and native AVX/fast-math
compiler flags. They do not validate real CUDA execution or renderer integration.

## Completed results

The two ten-case material matrices pass. All eighteen normal/reference/fallback
images meet the unchanged 1e-6 absolute/relative gate; both deliberate GPU-color
sentinels fail the image comparison as expected. Primary stage-only images are
bitwise exact; primary shadow-help maximum RGB errors are 2.08616257e-7 and
3.57627869e-7, with exact alpha. Persistent fresh and cancel/replacement images
pass, with balanced primary retain/release in both interrupted and replacement
frames. The primary context stays active after each bridge closes. Adaptive
bypass is exact and never retains a context or submits a material batch.

The first timing attempt was interrupted when an installed Modo renderer appeared.
It is retained as excluded evidence. After the user paused rendering, a fresh
warmup plus three rotated measured rounds passed all twenty image comparisons.
No external moonray process was present in the before/after activity snapshots.

MCRT medians (single render worker, RTX 3090, this fixture only):

- Original XPU: 7.295 s (range 7.265-7.315).
- Private context, stage only: 16.561 s (16.142-16.770).
- Shared primary context, stage only: 16.217 s (16.023-16.329).
- Private context, shadow helping: 18.850 s (18.711-19.203).
- Shared primary context, shadow helping: 19.911 s (19.786-20.090).

The stage-only difference is about 2.1%, with overlapping ranges; it does not
establish a consistent speed improvement. Shared-context shadow helping is about
5.6% slower in this sweep. The context change is therefore not promoted as an
optimization, and original XPU remains substantially faster.

In measured round one, shared-context helping reduces completion queries from
3,889,181 to 2,780,464, but cumulative poll time rises from 1.975 to 3.034 s.
Native GPU-shadow accounting rises from 7.516 to 10.348 s. Submission takes
about 4.9 s in either helper. This does not isolate driver locking versus device
contention, but rules out fewer polls or shorter GPU event intervals as sufficient
proof of lower frame time. These timings overlap and must not be summed.

Stage-only batch selection is only about 80 ms, while 45,170 small submissions
and millions of checks dominate the transport investigation. This supports a
small batch-handling library rather than a more expensive scheduling hierarchy.
No accelerated arbitrary-material renderer or multiworker qualification is claimed.

The preparatory batch contract passes both compiler modes, including a stale-token
check after reconstructing a slot at the same address. Native integration remains
a separate step. Full identities, controls, excluded timing and accepted timing:
[native-context-20261018.json](native-context-20261018.json).

The subsequent opt-in native integration and its recovery/image gates are tracked
in [NATIVE_TRANSPORT.md](NATIVE_TRANSPORT.md). The measurements above remain the
historical context-sharing experiment, before that integration.
