# Per-flight resident GPU shading records

Experimental opt-in extension of the early shared host records. Original XPU and
installed kits are unchanged. This remains a one-native-worker, fixed-sampling
candidate for the existing selected diffuse sampling operations. It does not
implement full GPU material evaluation or scene-wide texture residency.

## Ownership and wire format

Each flight owns 128 GPU record slots and its own pinned upload buffer. A record
contains a layout tag, 64-bit scene revision, 64-bit host slot generation, and the
192 invariant words for eight SIMD lanes. Sample descriptors carry a record/lane
index, expected generation and two sample-coordinate words. Inactive lanes are
explicit. A changed record is included once in the current upload; later batches
on that same flight can reference the resident copy.

The host pool lends immutable records to queued work. It cannot recycle a slot
until all window/request references retire. Per-flight cache keys include both
revision and generation. Host validation rejects conflicting views of one slot
before changing cache state. The GPU checks layout, revision and generation before
using a record; rejection leaves the existing native CPU fallback available.

Updated records are shaded directly from the upload buffer while the same kernel
writes their resident copies. Each table word has one writer. Every descriptor
for an updated slot points into that upload, so it cannot read a partially written
table entry. Unchanged descriptors reference other slots. A flight is reused only
after its completion event, including readback, retires. Separate flights have
separate tables; they need no cross-stream table lock or barrier.

Host cache tags are optimistic after encoding: the owner must retire the kernel
before using that flight again. A partial submission failure drains owned work and
permanently disables the bridge for that frame, so failed uploads cannot later be
mistaken for valid resident data. Cancellation and replacement retain the existing
flight and frame lifetime rules.

One upload and one sampling kernel per participating batch are retained. There is
no separate table-update kernel. Each flight adds 100,864 bytes of device table,
60,948 bytes of device upload space and 60,948 bytes of pinned upload space. These
are bounded extra allocations, not a total-memory reduction claim.

## What still runs on the host

The worker still reconstructs flat inputs and packs the existing transport buffer
for validation, diagnostics and fallback. Native replay also retains its original
comparison. This experiment removes GPU-upload content scanning and permits
cross-batch GPU record reuse; it does not yet remove all host reconstruction or
per-request allocation. It changes data delivery, not the amount of BSDF math
computed on the GPU. Texture records and native scene-index dispatch are separate.

## Reproduction

Build with `tools/xpu2_native_resident_build.py` from the frozen prepared-record
candidate into a new directory. Compile the additional CUDA entry point using
`tools/xpu2_native_resident_ptx.py`, preserving the existing non-fused arithmetic
flags. `XPU2_RESIDENT_RECORDS=1` opts in with prepared records enabled. Frames and
batches outside the resident path retain their existing behavior.

`tools/xpu2_resident_records_probe.py` verifies the host wire protocol with normal
and AVX/fast-math compilation. `tools/xpu2_native_resident_probe.py --checks`
compares actual raw float32 images with original XPU, including forced cache flush,
stale-generation injection, full input echo, pool pressure and GPU failures.
Without `--checks` it rotates original XPU, the disabled-cache control, residency
and forced flushing through a warmup and three timing rounds.
`tools/xpu2_native_resident_cancel.py` cancels and replaces an active persistent
render. All tools require isolated paths and preserve build/source/runtime hashes.

The first native build stopped on an
ambiguous source-patch anchor before compilation; the first contract build rejected
a test indentation warning. Both failed reports are retained, and the corrected
builds succeeded. No installed runtime was touched.

## Completed validation

Both normal and AVX/fast-math protocol tests passed. Native validation completed
41 renders: 32 exact candidate float32 RGBA images, eight original-XPU references,
and one deliberately changed GPU sentinel (45,629 pixels). Coverage includes cold
and reused records, forced flushing, stale generations, full input echoes, zero/
one-slot host pools, sample-sequence checks, missing PTX, zero queue capacity,
partial upload failure, replay mismatch and dropped results. Persistent testing
also canceled an active frame and replaced it with an exact image; no records or
native paths remained retained at frame end.

The maximum-packet fixture and the larger rough-diffuse/native-metal fixture both
passed exact input-echo and image comparisons. They do not qualify arbitrary
materials or multiple native workers. The mixed fixture exercised 1,847,664 resident
sample descriptors with no cross-batch reuse.

[Machine-readable evidence](native-resident-20261019.json) retains report hashes,
per-run counters, comparisons and failed-build provenance. Generate it with
`tools/xpu2_native_resident_evidence.py` after all six report groups pass.

## Timing and reuse (2026-10-19)

Warmup plus three rotated measured rounds, MCRT seconds (median and range):

- Original XPU: 7.971 (7.966-8.047).
- New build, residency disabled: 11.315 (11.035-11.507).
- Resident records: 11.237 (10.917-11.413).
- Forced flushing each batch: 11.034 (10.737-12.290).

Paired resident-minus-disabled differences were -0.270, +0.098 and -0.118 seconds.
Resident-minus-flush differences were +0.203, -0.877 and +0.180 seconds. The small
median change and inconsistent signs do not establish a reliable speed gain from
residency. Keep the option disabled; original XPU remains faster on this fixture.
All 16 timing images were exact, and before/after renderer snapshots were clear.
Other system load and brief intervening activity are not excluded.

Measured resident runs reused only 31-35 groups against 50,702-50,706 updates:
roughly 0.07% of distinct group lookups. Scheduled resident uploads were about
105.26 MB per frame. Descriptors include versions and are larger than the old
batch-local compact descriptors. Reuse, transfer size and elapsed time are separate
measurements; do not infer a speedup from a byte reduction. Cache counters count
encoded payloads, which can include an injected failed submission in fault tests.

The first correctness fixture reused 44 groups versus 50,692 updates. Deliberately
stale generations reduced GPU-accepted samples from 3,250,134 to 1,926 (legacy-path
samples), and native fallback preserved the exact image. Full echoed inputs also
matched. The 16-sample/32-packet fixture used 5,770,496 resident descriptors with
zero cross-batch reuse: its records were consumed in their initial batches.

## Interpretation

This is a safe per-flight residency mechanism within the tested scope, not a
successful render-speed optimization. Hit normals, view directions and related
values have short useful lifetimes. Even perfect local bookkeeping cannot create
reuse when a record is consumed once. Per-flight duplication also trades potential
reuse for simple, independent stream ownership. These measurements do not prove
that global shared tables would be faster.

The more promising next residency candidates are stable material parameters and
texture pages, with explicit scene-index identities and dirty revisions, coupled
to larger supported shading jobs. More host reconstruction can then be removed
without replacing it with repeated decoding. Full asynchronous material shading,
multiworker safety and production-scene qualification remain unfinished.
