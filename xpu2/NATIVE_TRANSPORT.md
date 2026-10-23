# Native batch transport integration

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This is an isolated, opt-in integration of the batch packing/ownership contract.
It does not replace XPU, install a runtime, or implement arbitrary GPU materials.

## Integration boundary

`native_transport.py` derives the copied-source candidate from `native_context`
and substitutes `native_transport_worker.inc` for the two-flight worker. The
`XPU2_BATCH_TRANSPORT=1` flag selects the library; unset/zero retains the previous
vector-packing path in the same binary. Shading PTX, native material/light setup,
queue selection, sample identity, batch limits, transfer calls, completion queries
and CUDA math stay unchanged. Both paths receive the same per-batch timing probes.

Each enabled slot owns one reusable `transport::Batch`, allocated once at worker
startup. Packet inputs and fallback results are packed into its fixed arrays.
The adapter verifies packet owner and scene revision before packing. Legacy jobs
without that identity use the old path and increment a bypass counter. Qualified
native-frame probes require zero bypasses.

The library token marks a batch in flight before entering the backend, including
submission failures. The existing CUDA backend remains responsible for event
completion and for draining partially submitted transfers. Only afterward may
result storage be published or the slot released. Failed submissions retire the
contract as failed and retain the existing native fallback behavior.

Per-request cancellation stays under the original queue mutex. An entirely
cancelled batch revokes publication and retires only after backend completion;
a partially cancelled batch returns only the surviving requests. Shutdown checks
that all packed contracts retired and none remains active. Result-buffer access
also checks ownership and in-flight state. The original ticket credits and frame
continuation checks remain in place.

## Measurement

`XPU2_TRANSPORT_PROFILE` records packed/retired/failed/discarded/bypassed batch
counts, outstanding contracts and aggregate packing/retirement time. These are
per-batch measurements, not new per-ray timers. Existing submission, polling,
selection and GPU event diagnostics remain separate; overlapping durations must
not be summed as a wall-clock breakdown.

A same-build disabled control separates the library's effect from rebuilding and
new instrumentation. A frozen predecessor provides a second control. Private CUDA
context and shadow helping disabled are the main comparison, following the prior
shared-context regression. A primary-context case is a correctness-only control.
The initial integration makes no speed claim.

## Reproduce

Use fresh output directories:

    python tools/xpu2_native_transport_build.py --source <read-only-primary> --base test-results/xpu2-origin-build --output <build>
    python tools/xpu2_native_transport_probe.py --build <build> --reference test-results/xpu2-origin-build/control --previous test-results/xpu2-context-build --ptx test-results/xpu2-native-work-ptx/film.ptx --previous-ptx test-results/xpu2-native-work-ptx/film.ptx --scene <fixture> --output <controls> --checks

The probe requires identical PTX identities and exact float32 RGBA for normal
single-worker cases, not merely the earlier shadow-helper tolerance. A deliberate
GPU-color sentinel must differ. Missing PTX, zero queue capacity and upload failure
must exercise the required fallback and retire ownership. The profile must prove
that enabled cases actually pack batches and disabled controls do not.

Without `--checks`, the probe runs warmup plus three rotated measured rounds for
original XPU, the predecessor, same-build control and integrated transport. The
cancellation probe uses a passed control directory as its baseline. Adaptive
bypass is checked with `--checks --bypass`. Tests are limited to one native render
worker because the earlier native multiworker repeatability issue is unresolved.

## Completed correctness and recovery gates

Both ten-case matrices (transmission/reflection and mixed materials) pass.
Every normal, disabled, predecessor, control and fallback image is exact in
float32 RGBA. Both deliberately altered GPU-color sentinels differ as required.
The transmission fixture packs and retires 45,170 batches without identity
bypasses, failure or outstanding ownership. Missing PTX and injected upload
failure each retire all 45,170 failed contracts; the latter drains its partially
submitted upload before reuse. The resulting CPU fallback images remain exact.

Persistent fresh and cancel/replacement renders are exact to original XPU and
to each other, with balanced per-frame batch ownership. That cancellation landed
between completed GPU groups, so it alone does not establish in-flight retention.
A separate actual-queue test holds four CUDA streams incomplete with callback
gates, cancels all tickets, and verifies retained scene resources until the gates
open. All four contracts then retire as discarded, with zero publication,
outstanding credits or active contracts. This tests delayed stream completion;
it does not preempt an executing CUDA shader kernel.

Adaptive bypass stays exact and does not submit a material batch. Standalone
contract tests pass both normal and native AVX/fast-math compiler modes, including
guarded result storage and wrong-owner/wrong-state rejection.

    python tools/xpu2_native_transport_cancel.py --build <build> --reference test-results/xpu2-origin-build/control --baseline <passed-controls> --ptx test-results/xpu2-native-work-ptx/film.ptx --output <fresh-cancel-output>
    python tools/xpu2_native_transport_held.py --source <read-only-primary> --build <build> --ptx test-results/xpu2-native-work-ptx/film.ptx --output <fresh-held-output>

The held test compiles the exact generated queue from the candidate build, copies
its headers, and verifies source hashes. It does not substitute a model queue.

## Render-time result

Warmup plus three rotated measured rounds pass all sixteen image comparisons.
No external moonray process was present in the before/after snapshots. These
are single-native-worker measurements on RTX 3090 with the reflection/transmission
fixture; they do not qualify full CPU utilization or other production scenes.

MCRT medians and measured ranges:

- Original XPU: 7.820 s (7.750-8.206).
- Frozen predecessor: 17.572 s (15.044-19.038).
- Same-build control, transport disabled: 15.929 s (15.508-16.081).
- Integrated transport: 16.654 s (15.590-17.730).

The transport median is 4.55% slower than the same-build control. Ranges overlap;
the predecessor also varies substantially. There is no demonstrated acceleration,
and the feature stays disabled by default. A faster median than the noisy
predecessor is not evidence of a benefit from the transport library.

For transport, measured packing takes 52.3-57.2 ms and retirement takes
240.0-275.7 ms per frame. There are still 45,170 submissions, about 72 accepted
samples per batch, and 1.25-1.56 million completion queries. Submission accounts
for 4.47-4.82 s of aggregate worker time. At the first material-resume check, only
0-18 of 406,530 tickets are ready in each measured transport run. Nearly all
dependent native work still reaches the handoff before its GPU result is ready.
These overlapping measurements must not be added to reconstruct frame time.

The next optimization should reduce the existing transfer/validation round trip
and completion-query overhead while preserving batch/sample identities, then
provide more independent useful work before native continuation must resume.
Changing just the ownership wrapper or queue hierarchy does not remove these
dependencies. Broader material support and native multiworker repeatability
remain separate unfinished gates.

Full source/build identities, images, failures, recovery and measured rounds:
[native-transport-20261018.json](native-transport-20261018.json).

The next isolated transport and independent-work candidate is documented in
[NATIVE_EFFICIENCY.md](NATIVE_EFFICIENCY.md); these results remain the preceding
ownership-library measurement.
