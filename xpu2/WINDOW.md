# Native sampler cache-window boundary

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

XPU2 is an additional experimental architecture. This change does not modify
original XPU, install a runtime, or enable an XPU2 engine in Modo.

## Measured result

The native integrator sampler's next sample index is not sufficient to reproduce
its sequence near the precomputed-table boundary. The native AVX8 implementation
fills eight samples at a time and chooses table versus R-sequence fallback using
the window's starting index. Restarting at an index inside an existing window
can therefore choose a different distribution for that same index.

The diagnostic compares three paths: an uninterrupted native sampler, restoration
from a cache-aware snapshot, and index-only restoration as a negative control.
All paths use unchanged native sampling code.

- 324 cases cover dimensions 1/2/3, depths 0/2, three seeds, three sequence
  purposes and starting indices 0, 1, 7, 1009, 1013 and 1015. Counts are unknown,
  with pseudo-random override off. Cases record samples from max(1000, start)
  through 1047; earlier samples are consumed normally.
- Cache-aware restoration matches all 27,108 components exactly in each run.
- Index-only restoration changes 2,268 components in 270 cases, at indices
  1016 through 1022. Starting at zero happens to align the windows and conceals
  the problem; testing nonzero starting indices is necessary.
- One worker twice and four workers once produce identical ordered records.
  These runs distribute whole cases between workers; they do not measure
  transfer of a single path between CPU and GPU.
- Six native envelope guards pass. 137 focused Python checks pass, including
  tests that reject incomplete evidence and detect restoration/repeat drift.

The final isolated rebuild also matches the pinned compressed reference. Evidence
and input hashes are in window-20261017.json; raw native records are pinned in
reference/sampler-window-avx8-20261017.jsonl.gz. The earlier 648-case and expanded
CMJ corpora remain unchanged.

## State contract

sampler_window.h defines a separate 64-byte version-2 diagnostic envelope. It
preserves the existing six-word sequence identity, dimension, depth, known total,
next index and pseudo-random flag, and adds the cache-window starting index.
A checksum covers the header and fields. Version-1 readers reject this envelope;
there is no silent change to the existing CUDA or native handoff format.

The window start must be at or before the next index, at most eight samples away.
A snapshot just before a refill can still refer to the previous full window.
Restoration constructs the original sampler at that window start and consumes
at most eight samples to reconstruct the cache. The next draw then follows the
same native refill behavior. A compile-time guard requires the tested AVX8 width.

This is a correctness diagnostic, not a fast GPU implementation or a general
renderer checkpoint format. A production implementation must retain equivalent
window state (or cached values), all active samplers and their build/distribution
identity. Depth/flags/sequence changes during an existing window, other SIMD
widths, arbitrary native resume calls and other SequenceID signatures are not
validated by this corpus. The checksum detects accidental corruption, not a
semantically incorrect but structurally valid sender state.

## CUDA follow-up

The separate version-2 kernel now passes the finite boundary corpus and
returned-state GPU continuation; see [CUDA_WINDOW.md](CUDA_WINDOW.md). The
version-1 table gate remains at indices 0-64. Interleaved native CPU/GPU path
handoffs, shading, rendered RGB/AOV parity and acceleration remain unvalidated. Native builds use frozen headers and retained objects;
they are not clean source/runtime rebuilds.

## Reproduce

Use a fresh output directory:

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/window-new --window --reference xpu2/reference/sampler-window-avx8-20261017.jsonl.gz
    python -m unittest discover -s tests -p "test_xpu2*.py" -q
