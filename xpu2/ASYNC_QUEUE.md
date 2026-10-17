# Nonblocking GPU queue tickets

The experimental queue can now accept a shader packet and return a ticket before
GPU completion. This is the next step toward CPU workers continuing other paths
while GPU shading runs. It is not yet connected to MoonRay path continuations.
The native Lambert hook still calls the existing synchronous `run()` interface.

## Ownership contract

- `submit(input, native, count, revision)` copies 1-8 lanes of inputs and native
  reference outputs into a queue-owned request. Null means declined; the caller
  retains its native answer. Unlike `run()`, this explicit GPU submission does
  not apply the diagnostic mixed/split CPU-routing policies.
- `tryCollect(ticket, revision, output)` only writes output on `Ready`, once.
  It reports `Pending`, `Cancelled`, `Duplicate`, `WrongOwner`, or `Stale`
  without touching the destination. A revision mismatch cancels the request.
  The caller must supply the current revision; Modo changes are not wired here.
- `cancel(ticket)` prunes queued work immediately. An in-flight cancellation
  holds its credit until the worker discards the result. A completed cancellation
  releases its credit without publishing the result.
- Every accepted async request holds a capacity credit while pending, executing,
  or ready but uncollected. This prevents a slow collector from accumulating an
  unlimited number of outstanding results. It is not a total process memory cap
  or a combined admission budget for the legacy synchronous interface.
- Callers must retain accepted tickets until collection or cancellation. Dropping
  a ticket without either action does not recover its credit automatically.
  Already consumed/cancelled tickets retained by callers still own their storage.
- The opaque queue-owner token prevents accidental cross-owner collection.
  This is not a security boundary. Tickets and their fields must not be mutated
  by callers. The current C++ types are internal diagnostic interfaces.
- Quiesce API callers, collect/cancel owned tickets, and successfully stop/join
  the worker before destroying the queue. Do not let tickets outlive the module
  that allocated their C++ objects or invoke CUDA cleanup from DLL detach.

Nonblocking means no wait for GPU completion in submit/collect. These operations
still acquire a mutex, allocate/copy data and may flush diagnostic logs; they are
not lock-free or suitable for a hard real-time guarantee. Accepted async requests
have no automatic timeout; the owner controls cancellation.

## Recorded checks

[Evidence](async-tickets-20261017.json) pins source and output hashes for ten
standalone processes, plus the 208-check Python suite. On the RTX 3090:

- One producer submitted 64 requests while the GPU worker was deliberately held.
  It reused the original arrays, then collected all results in reverse order.
  GPU sentinel results matched exactly, proving that collection used the owned
  request data and that successful GPU results reached the destination.
- Capacity rejection occurred both before completion and with 64 completed but
  uncollected results. Collection released all credits; duplicate and pending
  collections left the output untouched. A foreign unowned request was rejected.
- The cancellation case accepted 66 requests by reusing two pruned slots. It
  rejected one stale revision, cancelled one pending and one in-flight request,
  delivered the other 63 exactly once, and finished with zero retained credits.
- With missing PTX, all 64 accepted requests returned the exact preserved native
  values. No GPU result was accepted or substituted.
- Existing full-capacity, timeout, pending-prune, empty-coalesced-batch, stop/drain,
  and four-cycle GPU/partial-initialization cleanup checks passed.

The first two cases preceded adding the missing-PTX case to the harness; both
reports pin the same final queue implementation. This milestone has not rerun
DLL unload with async tickets, tested concurrent async collectors, or measured a
real integrator speedup. The earlier DLL tests apply to their recorded candidate.

## Next integration boundary

An integrator adapter must own complete path continuation state independently
of an ISPC stack or temporary arena. It needs render-attempt, scene-revision,
path and sample identities, and an exactly-once handoff back to the appropriate
CPU continuation queue. A shader ticket is not a film contribution.

The diagnostic CPU reference calculation remains duplicated for correctness.
Removing it requires independently validated GPU eligibility and a fallback that
replays the same owned path state. General materials, texture residency, geometry
streaming and deterministic multithread film reduction remain separate work.
No production parity tolerance or acceleration claim follows from these tests.

## Reproduce

Use new output directories and the pinned native Lambert capture:

```powershell
python tools/xpu2_queue_stress.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/async-new --cases async,async_cancel,async_missing_ptx,shutdown,capacity,timeout,pending_timeout,coalesce_timeout,lifecycle,lifecycle_missing_ptx
python -m unittest discover -s tests -p test_xpu2*.py -q
```

## Native synchronous regression

[Native evidence](native-async-20261017.json) records the rebuilt candidate and
full 15-case rendering matrix. Normal single-worker images, selected rays and
contribution multisets remain exact. GPU shader comparisons match; deliberate
sentinel changes and CPU fallback controls behave as expected. This validates
the old synchronous entry point against the new queue implementation, not an
asynchronous integrator.

The separate four-worker bitwise gate remains false. Native repeats differ in
13 pixels; the two mixed candidates differ from the first native control in
8 and 6 pixels. Maximum channel difference is 1.4901161193847656e-08 in each
comparison. These observations do not establish a production tolerance or the
cause of every difference. No tolerance was relaxed and no speedup was measured.
