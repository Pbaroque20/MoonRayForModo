# Numeric native sampler cache

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This isolated experiment reuses native sampler setup inside the existing bounded
four-block material window. Original XPU and the installed kit remain unchanged.
`XPU2_SAMPLER_CACHE=1` opts in; the default is off.

## Lifetime and identity

The cache stores only numeric sampler output: lobe indices and offsets, per-lane
sample counts and reciprocals, and total counts. It stores no native pointer.
Actual shading rebinds the current BSDF, slice and indirect-lighting setting and
copies cached arrays into fresh allocations in that call's own native arena.
Prefetch temporary arena allocations still rewind immediately after preparation.

Each cache belongs to one block in one owner-thread window and frame revision.
The key checks the source lobe count, every lobe's type and active mask, current
sample limits and slice flags. Partial execution masks bypass reuse. This key is
specific to the pinned native initializer, whose active sample-count branch does
not use albedo. The builder checks exact source hashes for the initializer, its
layout and BSDF flag/mask semantics, failing closed if those dependencies change.

Storage is aligned to 64 bytes, capped at 32 KiB per block and four blocks per
window. Window cleanup accounts for consumed, rejected and discarded caches;
frame completion requires stored = reused + rejected + discarded. Existing
prefetched GPU inputs still undergo full byte/pixel comparison. Queue and film
publication ordering are unchanged.

## Qualification controls

`XPU2_SAMPLER_VERIFY=1` rebuilds the actual native sampler at each cache hit and
compares all live output fields, including reciprocal float bit patterns. A
mismatch fails explicitly. This diagnostic uses the rebuilt native sampler.
`XPU2_SAMPLER_MISS=1` forces key rejection and normal initialization.
`XPU2_SAMPLER_PROFILE` records storage and lifetime counters per frame.

The dedicated scripts are `tools/xpu2_native_sampler_build.py`,
`tools/xpu2_native_sampler_probe.py` and `tools/xpu2_native_sampler_cancel.py`.
All enabled probe variants use four-block lookahead. `control` disables caching,
`transport` verifies by rebuilding, and `ahead` restores the numeric cache. The
previous packing/grouped-readiness experiment is not enabled. Each probe records
the actual renderer PID to resolve monitor observations at process teardown.

## Results and decision

All validation passed: **37 ordinary images exactly match original XPU in float32
RGBA**, plus two intentional GPU-color sentinels. The twelve-case main matrix
includes native rebuild verification, true reuse, forced sampler misses, missing
PTX, zero capacity, partial upload failure, GPU-input mismatch and discarded GPU
tickets. Rough materials, adaptive bypass with verification enabled, and persistent
cancellation/replacement also pass. Every reported cache balances its lifetime.

On the main fixture, verification checks **22,557** cached initializations against
the real native initializer. Reuse avoids the same number of initializations.
Forced misses reject all 22,557 entries and preserve the image. The numeric cache
payload is 1,376 bytes per block (1,408 bytes of aligned allocation); the general
storage cap remains 32 KiB per block. The cancellation run balanced both frames;
it did not leave unused cache entries at the observed cancellation point.

Warmup plus three rotated measured rounds produced 16 of the exact images above.
Warmup is excluded from MCRT medians and ranges:

- Original XPU: **7.449 s**, range 7.340-7.561.
- Four-block control, cache off: **10.736 s**, range 10.708-11.216.
- Native rebuild verification: **10.740 s**, range 10.577-11.088.
- Numeric sampler reuse: **10.754 s**, range 10.741-11.180.

Reuse is **0.17% slower** by the observed median, with overlapping ranges. There is
**no demonstrated speed benefit**, so the cache remains disabled by default. It is
still **44.37% slower than original XPU** on this one-worker fixture. The comparison
supports correctness of numeric reuse, not a claim that setup was the dominant
bottleneck. Further optimization should measure remaining waits and increase useful
independent GPU shading work; avoiding this initializer alone is insufficient.

All per-render activity snapshots were empty, and all renderer processes seen in
43 periodic observations matched the PIDs launched by this probe. No competing
renderer was detected. Sampling does not establish continuous absence of other
system load. Source/runtime identities and unchanged PTX were verified.

Reproducible reports and monitoring evidence:
[native-sampler-cache-20261018.json](native-sampler-cache-20261018.json).

 This experiment retains fresh
arena allocation and GPU input regeneration; it does not yet cache generated
random samples, expand shader support or establish multiworker repeatability.
