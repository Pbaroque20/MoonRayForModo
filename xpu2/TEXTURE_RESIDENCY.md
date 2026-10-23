# Texture residency policy and hierarchy

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

`texture_residency.h` adds a native coordinator-side placement policy over the
owned tile cache. It records caller-supplied material -> texture/interpretation/
revision -> subimage/mip -> tile dependencies. Shared exact tiles are counted once
for each memory tier even when several materials use them. RAM and VRAM copies
may coexist; no coarser mip or different revision substitutes for a request.

## Placement and protection

The policy ranks **tile requests**, using the grouped dependency index for identity
and sharing. It does not yet traverse a native scene graph or allocate budgets to
whole material groups. Pending demand outranks speculative prefetch. Within each
class, bounded importance and estimated benefit per byte combine with caller-
supplied waiting age; resident data receives a small retention preference. Idle
pages remain if capacity permits. Speculation with no estimated net benefit is
deferred. The heuristic is deterministic, not a measured optimal cost model.

The device budget subtracts a nontexture reservation before admitting pages. RAM
and staging feasibility are checked separately. Pinned CPU/GPU pages and uploads
are retained even if a requested budget reduction would put them over target;
the plan flags that condition and defers new unpinned admissions. The caller must
wait for their work to retire rather than force eviction or oversubscribe further.

The cache now exposes coordinator-owned residency snapshots and guarded discard.
`trimTextures` applies proposed evictions but rechecks current pins/uploads. It
can partially trim and report failure if the plan became stale. The caller must
replan rather than assume an atomic reservation. Admission still goes through
`Cache::acquire`: a suggested admission is **not proof that data is ready**, and
live RAM/staging pressure or an upload in flight can still defer it. No successful
sample is manufactured on a missing page.

This policy changes neither actual sampling nor convergence. It does not choose
a CPU shader fallback; the native dispatcher must separately verify capabilities
and arrange valid replay/ownership before routing a deferred request elsewhere.

## Validation

Native policy tests passed **74,689 assertions across 5,000 deterministic randomized
plans**, plus focused checks for:

- Shared-material deduplication, distinct revisions/mips, demand-first priority,
  age, reserve subtraction, and unprofitable-prefetch rejection.
- RAM/staging infeasibility, pinned resources under a reduced budget, and malformed
  priorities, immutable sizes and memory reservations.
- CPU pins, uploads, GPU leases, stale eviction plans and clean eviction without
  device-to-host readback.
- Exact planned byte totals and deterministic keep/admit/defer/drop results.

The changed cache also passed its existing **20,000 randomized operations** and
29,532 assertions, plus four real RTX 3090 transfer consumers.

The real CUDA filter probe now plans and trims residency before each texture.
In this deliberately small pressure test, a 65,536-byte test device budget reserves
32,768 bytes for other work and caps both the texture cache and its actual CUDA
allocation arena at 32,768 bytes. This is a fixed reservation, not a claim of
reserving physical GPU memory from other applications or allocating render buffers.
Two policy-driven GPU evictions occurred.

All **234,976 lookups / 587,776 components** still match OIIO exactly; all 32
fallback checks pass. The independent 96x64 RGBA texture-space image comparison
has zero differing pixels. CUDA cleanup has zero errors. These are the same
point/bilinear base-level fixtures, not a large-scene or performance benchmark.

Compact evidence: `texture-residency-20261017.json`.
Local results: `test-results/xpu2-residency-contract-publish` and
`test-results/xpu2-residency-filter-first`.

```powershell
python tools/xpu2_texture_cache_probe.py --source <read-only-toolchain-root> --output <new-directory> --gpu
python tools/xpu2_texture_filter_probe.py --source <read-only-toolchain-root> --runtime <frozen-XPU-runtime> --fixtures <passed-OIIO-probe-directory> --output <new-directory>
```

## Remaining integration

Background worker I/O/decode is now validated separately in [TEXTURE_ASYNC.md](TEXTURE_ASYNC.md).
Native scene-index dependency ingestion, measured cost feedback, dispatcher replay, dynamic arena-budget changes
and production residency scheduling remain. Plans currently rebuild the small
request index from a snapshot; production overhead needs measurement and likely
incremental updates. OIIO's separate cache, driver overhead and probe query/output
buffers are outside the owned texture budgets. Mip/anisotropic and full-scene image
parity gates remain open. No installed kit, shared checkout or user scene changed.
