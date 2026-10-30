# Early shared host shading records

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Experimental, opt-in XPU2 candidate. Original XPU and installed kits are unchanged.
This qualifies one native worker, fixed sampling and the existing selected diffuse
sampler operations. It does not deliver a general GPU material evaluator.

## Change

The CPU extracts invariant hit/lobe values once for up to 16 sample packets instead
of repeating that extraction inside every sample loop. Sample coordinates, active
lane masks and pixel IDs remain explicit. Each immutable record has a frame
revision and a per-slot generation. Window packets and queued requests retain strong
references until their consumers retire.

A bounded host pool preallocates 128 records (244,736 bytes of record storage,
excluding shared-pointer control blocks and the slot vector). Only a slot with no
external references can be overwritten. Exhaustion uses the original flat path;
it never overwrites a retained record or stalls waiting for space. The GPU worker
reconstructs the existing flat CUDA payload. Sample collection reads the immutable
record directly, so it cannot race that reconstruction.

The original native replay comparison, sampler arithmetic, sample sequence, GPU
input layout and film publication remain. Replay reconstructs the complete original
input for comparison. The existing compact GPU upload option can be combined with
this earlier host preparation, but it still rebuilds shared data inside each GPU
batch. No CUDA kernels change here.

## Scope of memory savings

`record_bytes` counts logical shared record payload, and `equivalent_bytes` counts
the corresponding repeated flat records. Neither measures total memory traffic or
peak resident memory. The existing request/window flat arrays remain allocated;
request and ticket allocation counts are not reduced. This change reduces repeated
main-thread preparation and input copying, adds a bounded reusable record pool,
and moves flat expansion to the worker. It does not yet retain shared records in
VRAM, remove replay reconstruction, or integrate native scene-index dependencies.

## Validation and reproduction

Build with `tools/xpu2_native_prepared_build.py`, using the frozen material-jobs
candidate as base and a fresh output directory. `tools/xpu2_prepared_records_probe.py`
checks masked bit-exact reconstruction, sample coordinates, invalid shapes,
exhaustion, reuse, concurrent retention and safe references after pool destruction,
both normally and with the native AVX/fast-math flags.

`tools/xpu2_native_prepared_probe.py --checks` compares raw float32 RGBA with original
XPU, the previous candidate, disabled/enabled prepared records, combined compact
uploads, zero/one-slot pools, sample-reuse verification, a GPU sentinel, missing
PTX, zero queue capacity, partial upload failure, replay mismatch and dropped
results. Without `--checks` it runs a warmup plus three rotated timing rounds.
`tools/xpu2_native_prepared_cancel.py` cancels an active persistent render and
replaces it, checking record retirement and the replacement image.

All tools take explicit isolated runtimes, fixture/PTX paths and fresh output
folders. Builds, sources and runtime inventories are pinned. No Modo instance or
installed kit is used. Timing probes reject competing renderer snapshots; these
snapshots cannot exclude every brief process or other system load.

## Recorded results (2026-10-19)

Both standalone contract variants passed. There were 36 completed native renders:
28 candidate images exactly matching float32 RGBA, seven original-XPU reference
runs, and one deliberately changed GPU sentinel (45,629 changed pixels). The
persistent recovery check also canceled an active frame, then replaced it with an
exact image. All frame-end record retention counts were zero. Missing PTX, zero
queue capacity, partial upload failure, replay mismatch and dropped-result checks
preserved the image.

The main fixture acquired 45,114 records, reused slots 44,986 times, and expanded
406,026 queued sample packets without exhausting the 128-slot pool. Logical record
payload was 63,700,968 bytes versus 324,820,800 equivalent flat bytes (80.4% less).
This is not a total memory or transfer measurement. An empty pool fell back for
all 45,114 acquisitions; a one-slot pool exhausted 43,670 times while still
producing the exact image. The 16-sample fixture reached 32 packets per job and
721,344 queued/expanded packets, again with exact output and no retained records.

Warmup plus three rotated measured rounds, MCRT seconds (median and range):

- Original XPU: 8.177 (7.672-8.380).
- New build, prepared records disabled: 11.039 (10.991-11.451).
- Prepared host records: 11.223 (10.817-11.261).
- Prepared records plus compact GPU uploads: 11.481 (11.199-11.549).

Paired prepared-minus-control differences were -0.222, +0.232 and -0.190 seconds.
Combined-minus-control differences were +0.442, +0.558 and -0.252 seconds. The
mixed signs and run spread do not establish a repeatable performance gain. Keep
this experiment opt-in; original XPU remains faster on this fixture. All timing
images were exact and before/after snapshots found no competing renderers.

[Machine-readable evidence](native-prepared-20261019.json) retains report hashes,
per-run results and ownership counters. Generate it with
`tools/xpu2_native_prepared_evidence.py` after all five report groups pass.

## Next decision

The host lifetime mechanism is validated within this scope, but the route still
reconstructs flat inputs for replay and worker dispatch and retains per-request
allocation. It is not yet a measured optimization. A follow-up should remove
redundant reconstruction using a typed/versioned resident GPU table and small
sample references, measuring each change separately. Broader GPU shading remains
necessary before claiming that a GPU-oriented architecture beats original XPU;
this test changes preparation, not the fraction of shading executed on the GPU.
