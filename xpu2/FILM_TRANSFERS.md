# Live film transfers and CUDA graph replay

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Status: **image and fallback checks passed; neither candidate improves the larger fixture. Blocking transfers remain the default.**

Follow-up: [larger concurrent batches](COALESCED_FILM.md) exposed a pageable-upload
ordering race in the experimental blocking path. It now waits explicitly before
kernel launch. The historical timings below predate that correction.

This follows [live fused Lambert/contribution dispatch](LIVE_FUSED_FILM.md).
Two opt-in paths now use pinned host staging: upload, fused kernel and readback
on one stream, followed by one completion wait; or a cached CUDA graph replaying
those operations. Graphs are cached by slot count and kernel, with a maximum of
32 executables. Staging remains owned until completion. Failed queued work is
drained before reuse; rejected results return to native CPU contributions.

These are asynchronous CUDA commands, not asynchronous path continuation. The
native caller still waits for every window while holding the bridge lock. CPU
Lambert reference evaluation, lighting, visibility and film remain native. The
CUDA arithmetic/PTX is byte-identical to the preceding fused candidate.

## Measured result — 2026-10-17

The final candidate ran all three transfer paths in the same binary on the
384 by 216 sphere/ground fixture, one renderer thread, RTX 3090:

- Native XPU reference: **3.643 seconds**.
- Blocking fused transfers: **13.092 / 14.442 seconds**.
- Pinned stream transfers: **18.313 / 19.398 seconds**.
- Cached graph replay: **17.776 / 19.240 seconds**.
- Graph replay retaining CPU contribution arithmetic for audit: **18.409 seconds**.

Each normal candidate processed exactly 1,997,771 supported contributions in
68,182 dispatches. All corresponding linear RGBA images matched the reference
exactly. Graph replay built only two graphs on this fixture; repeated graph
construction is therefore not the source of the observed per-window cost.
The first graph run spent 12.625 seconds inside the bridge, including 11.155
seconds in completion waits. A graph wait covers its transfers and kernel;
zero host upload/download timers do not mean transfers cost nothing.

Small-scene blocking took 1.042 seconds and graph replay 0.987 / 0.990 seconds,
against a 0.371-second native reference. This small difference does not establish
a general speedup. Timings are sequential observations with uncontrolled cache
warmth and system load, not statistical certification. Both larger-scene repeats
favor blocking. No new transfer mode is enabled by default.

## Correctness and failure evidence

The final graph-capable build completed 19 native renders across two fixtures.
Sixteen non-reference, non-sentinel comparisons matched linear RGBA at zero
tolerance. The sentinel changed 23,346 pixels, confirming GPU work reaches film.
Normal runs had zero shader mismatches, device errors and cleanup errors.

Missing PTX, a corrupted shader reference, partial pinned allocation, captured
graph failure and enqueued graph failure all produced the exact CPU-fallback
image. Captured source graphs and executable graphs were balanced at teardown.
Every enqueued graph failure was drained with no result accepted. The earlier
pinned-only build additionally exercised failure immediately after upload:
2,919 queued uploads were drained, no kernel dispatched, both pinned allocations
freed, and the fallback image matched exactly. That historical check is recorded
separately from final-binary validation.

Both final transfer modes passed five synthetic capture-ownership checks and
three CUDA window checks (1, 9 and 16 slots). Deliberately invalid lanes were
rejected, output canaries remained intact, and pinned/graph resources were freed.
These numeric checks supplement the actual rendered comparisons. All **336**
XPU2 regression tests passed, including 11 new evidence-validation tests.

Device loss or a failed CUDA drain, production cancellation, multithread image
parity, complete material support and faster scene loading are not certified by
these checks. Failed-driver cleanup remains an unresolved production concern.

## Reproduce and next boundary

Build with `tools/xpu2_film_build.py --source <read-only-native-checkout> --base
<retained-base> --output <fresh-folder> --fused`. Run `tools/xpu2_film_probe.py`
with `--build`, `--base`, `--output`, and `--fused --streamed --graphs`; add
`--showcase` for the three-way larger-scene comparison. Without `--graphs`,
`--streamed` exercises the pinned upload failure as well. Runtime opt-ins are
`XPU2_FILM_ASYNC_TRANSFERS=1` and, additionally, `XPU2_FILM_GRAPH=1`.

After timed renders, run `tools/xpu2_fused_guard_probe.py` with `--streamed`,
then with `--streamed --graphs`, each in a fresh output directory. The retained
base is `test-results/xpu2-owned-contribution-build-v2`. Final local artifacts
are `test-results/xpu2-film-graph-build`, `xpu2-film-graph-validation`,
`xpu2-film-graph-showcase`, `xpu2-film-stream-guards` and `xpu2-film-graph-guards`
(all under `test-results`). This still links retained native objects, not a
clean-source distributable runtime. No kit installation was performed.

[Aggregate evidence](film-transfers-20261017.json) records hashes, counters and
measurements; binaries, captures and rendered files remain local. The next
experiment should amortize GPU submission across larger owned jobs and let the
CPU advance independent work before waiting. Changing copy APIs alone has not
removed the synchronization cost; sharing the native GPU context is another
untested hypothesis, not an established fix.
