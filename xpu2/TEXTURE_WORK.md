# Texture-ready work dispatch

`texture_work.h` connects indexed texture identities, background decoding and
cache leases at an **owned-work boundary**. It can claim ready jobs while an older
job waits for a page. This is validated through native RDL metadata and an actual
CUDA texture-space image pipeline. It does **not** suspend arbitrary native
MoonRay shader calls or connect those queued jobs to native film accumulation.

## Dispatch and lifetime rules

Jobs carry a caller-supplied logical ID, owned byte payload, immutable dependency
snapshot and exact tile requirements. Submission checks material references,
unresolved sources, working-set feasibility, bounded outstanding jobs/payloads
and a bounded per-attempt ID ledger. No random numbers or sample IDs are assigned
from execution order. The caller must provide stable identities and serialize
all continuation data; a byte copy containing native pointers is not safe.

`claim` polls without waiting for disk or decoding. The oldest pending job drives
new page admission. Later jobs may bypass it using already resident resources or
no textures. Their ready-only lookups never upload or evict. This conservative
policy avoids competing partial working sets continuously evicting one another;
it does not optimize or parallelize all cold-file requests. Partial acquisitions
are released when a job cannot acquire its complete set. Only complete sets are
handed to a consumer, and pins remain until that consumer finishes.

The decoder must be exclusively owned by this queue while it runs. Shared tile
requests are deduplicated, and obsolete queued decodes are cancelled when no
pending job requires them. Active cancelled reads retain their reservation until
return. Already submitted device uploads still obey the cache's completion fences.

Consumers must call `finish` **before publishing their contribution**. Successful
current-attempt work is accepted once. Failure, repeated completion and revoked
attempts cannot pass that gate. GPU consumers supply a completion fence: an
unfinished fence returns Pending and retains both page pins and job capacity.
A newer attempt revokes claimed jobs but retains their capacity until returned;
old dependency snapshots remain readable while they drain. `close` declines to
complete until claimed work returns. Native film ordering/accumulation is not
implemented by this queue; callers must obey this gate.

The limits cover queue-owned payload and job/ID counts. Cache allocations have
separate budgets. Metadata/snapshots and copies retained by callers after finish
are outside these payload limits. Exhausting the ID ledger requires a drained
new dispatch attempt; this is not an unlimited scheduler. There is no implicit
retry or CPU shader fallback after a decode error: failed work is reported to
the caller without manufacturing a successful sample.

## Validation

- **50 queue contract assertions**: ready work bypasses a controlled blocked read,
  waiting payload/ID preservation, duplicate completion and logical-ID rejection,
  revision cancellation, bounded revoked leases, explicit decode failure, rejected
  impossible/unindexed demands, GPU completion fences, shutdown and partial-set
  memory pressure. Existing cache, policy, async-loader and dependency tests pass.
- **Eight native RDL stages / 39 assertions** now pass through the work queue.
  Three background-loaded tiles match OIIO bytes exactly; two current completions
  are accepted and one retained old-scene completion is explicitly revoked.
  These remain scene-reader checks, not native rendered validation.
- **49 actual CUDA filter jobs** pass through the queue. A first tile is warmed,
  another decode is deliberately held at a test barrier, and a ready one-tile GPU
  query completes and matches OIIO before the barrier is released. This proves
  executable ready work can bypass a waiting decode; it does not measure disk
  throughput, simultaneous hardware execution or a production performance gain.
- The 32 existing filter cases still match all **234,976 lookups / 587,776 native
  components exactly**, with all 32 missing/unsupported-input checks passing.
  The independent 96x64 RGBA texture-space image comparison remains exact. There
  are two policy-driven GPU evictions and zero CUDA cleanup errors.

The GPU probe's kernel helper still waits for its own kernel/readback to complete;
it then returns a completed fence to the queue. This establishes texture-wait
bypass, not general asynchronous GPU batch completion. Fifteen tiles decode on
the worker; the one synchronous warm-up tile is intentional test preparation.

Evidence: `texture-work-20261017.json`. Reproduce with the existing cache,
`xpu2_texture_dependencies_probe.py` and `xpu2_texture_filter_probe.py` commands
in the preceding texture documents, each with a fresh output directory.

## Remaining native-renderer integration

Native shader hooks still borrow arena/stack state, as documented in
`CONTINUATIONS.md`. Parking them without owning intersections, shader state,
sampler state, native handles and film bookkeeping would introduce use-after-free
or change samples. This queue must be wired at a supported owned packet boundary,
with validated texture sampling and publication into the native contribution path.
General GPU materials, exact native continuation replay, progressive delivery,
full-scene parity, cancellation under native rendering load and timing validation
remain. No installed kit, shared checkout, native render executable or Modo scene
was changed; XPU2 remains a draft experiment alongside unchanged stock XPU.
