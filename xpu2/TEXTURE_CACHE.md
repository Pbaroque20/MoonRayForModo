# Bounded RAM / VRAM texture-tile cache

The native cache foundation is implemented in `texture_cache.h`, with an isolated
CUDA transfer backend in `texture_cuda_backend.h`. It is read-only, backed by a
loader, and is not connected to native MoonRay shading or the installed kit yet.
The follow-up [OIIO loader](TEXTURE_OIIO.md) now validates real mip texels through
this cache; GPU filtering and shader integration remain separate.

## Ownership and residency

Each immutable key includes asset identity, revision, interpretation signature,
mip, tile coordinates and layer. The interpretation signature must identify the
working space and storage format. The caller must change identity/revision when
content changes; the cache does not watch files or derive dirty revisions itself.
Different mips and revisions cannot alias. A same-key byte-size change is rejected.

RAM keeps loaded tile bytes. VRAM keeps uploaded tiles. Both can evict unleased
backed data and reload it later. Clean GPU eviction drops the GPU copy without
reading it back: the source remains available through RAM or the loader. There is
no API for GPU-generated/modified texture publication yet; such data must not be
silently treated as clean or written through the exposed read-only GPU address.

RAM, logical VRAM, in-flight staging bytes, record count, lease count and pending
upload count have separate limits. Oversized tiles fail explicitly; transient
pressure defers admission. These are cache limits, not whole-process/driver-memory
limits. Metadata and loader temporaries are additional. The CUDA backend also caps
its reserved GPU and pinned staging arenas; configure them to match cache budgets.
Validation output buffers are separate from those arenas.

CPU leases protect borrowed immutable bytes. GPU leases require a completion fence
before becoming evictable. Cache instances have retained owner tokens, preventing
stale leases from becoming valid when an object address is reused. Failed loads
and uploads do not publish a GPU page. The coordinator owns mutation; callers must
finish CPU borrows and retire GPU jobs before closing. Exceptional teardown drains
the device before allocations are dropped; a failed drain fails closed rather than
pretending cleanup succeeded. Production engine failure/fallback wiring remains
separate.

## Overhead controls

- Deduplicate uploads already in flight; never return a GPU address before upload
  completion.
- Poll only pending uploads, not every resident tile on each request.
- Protect demanded/pinned data from speculative prefetch eviction.
- Reuse bounded, exact-size GPU and pinned staging allocations. Empty pool metadata
  is removed as blocks are consumed or freed.
- Record disk loads, hits, admission stalls, eviction counts, transfer bytes, peak
  cache usage and CUDA upload-event timing.

The loader callback is synchronous in this foundation. Asynchronous disk/decode
work and region-priority prefetch submission remain to be connected. Byte-budget
pressure currently scans candidates for eviction; no production LRU-index speedup
is claimed. The CUDA backend creates an isolated context and two nonblocking
streams. A native integration must bind the renderer's context and lifetime rules.

## Validation

The native contract/stress executable passed 29,532 assertions over 20,000 mixed
operations, including budget pressure, pinned pages, old revisions, stale/foreign
leases, upload deduplication, failed loads/uploads, close rejection and record/lease/
upload caps. A populated 4,096-page CPU cache served repeat hits with zero upload
polls or reloads.

The real RTX 3090 probe passed four transfer consumers using synthetic RGBA float32
mip/revision tiles loaded from disk. Three disk loads served four uploads; the RAM
hit avoided a repeat disk read. The probe exercised three GPU evictions, revision
isolation, demand protection, and reuse of both GPU and pinned allocations.

- H2D bytes: 212,992.
- Texture eviction D2H bytes: **0**.
- D2H verification output bytes: 212,992 (the test reads results back to compare).
- Cache peak RAM: 131,072 bytes; GPU and in-flight staging: 65,536 bytes each.
- Reserved GPU/pinned arenas: at most 65,536 bytes each, excluding test outputs.
- CUDA cleanup errors: 0.

CUDA upload events totaled 0.07376 ms in this small run. That excludes allocation,
host preparation, disk work and validation output. It is not a throughput benchmark
or evidence of compute/copy overlap or rendering acceleration. These consumers use
CUDA copies, not shaders. Synthetic mip bytes do not establish equivalence with
OIIO mip generation, filtering, derivatives, wrapping, or color conversion.

```powershell
python tools/xpu2_texture_cache_probe.py --source <read-only-toolchain-root> --output <new-directory> --gpu
```

Compact evidence is `texture-cache-20261017.json`; full local results are in
`test-results/xpu2-texture-cache-publish`. No native render path, shared checkout,
installed kit or user scene was changed. The prior 368 Python regressions are
unchanged by this standalone C++ addition and were not unnecessarily repeated.

Next steps after the OIIO tile-loader checks are worker I/O/decode, exact filtering parity,
scene-index revision bindings, region-prefetch integration, and full image checks.
GPU-generated textures will need an explicit dirty-data readback/publication path.
