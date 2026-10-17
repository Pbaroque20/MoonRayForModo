# Deterministic XPU2 work scheduling

Status: executable coordinator model, not a native rendering backend.
Original XPU remains the reference/fallback. No installed runtime changes.

## Target accepted for XPU2

Reduce scene-ready time, first correct preview time and time to equivalent final
quality on complex scenes. Retain vectorized CPU shading while adding faithful
GPU shading and overlapping work. Retain RAM-backed texture data with bounded
GPU mip residency, revision-based updates and conservative geometry demands.

Final acceptance is numerical linear-HDR RGB parity, not necessarily identical
bits. Alpha and production AOVs require separate checks. Absolute and relative
limits, maximum pixel error and aggregate error must be specified from controlled
reference evidence before accepting a backend. No numerical tolerance is chosen
or relaxed by this change. A shadow visibility mismatch is not automatically
acceptable rounding.

Keep two separate goals:
- scheduling repeatability given identical sample contributions;
- native contribution/image parity across CPU/GPU execution.

The protocol model validates the first only.

## Implemented model

scheduling.py provides immutable sample addresses, fixed sample blocks,
revocable worker leases and ordered film publication. The model accepts cpu/gpu
worker labels only to exercise the protocol; these labels approve no real device
or shading capability.

Addresses contain seed, frame key, pixel and absolute sample index. Attempt IDs
and scene revisions gate ownership but do not reseed samples. Fixed-size blocks
are generated lazily, in sample-major then pixel order. A faster worker can claim
more blocks, but block contents never depend on device speed or completion order.

The publication window bounds all issued and completed-but-unpublished blocks.
A stalled earliest block applies backpressure. This is intentional: producers
cannot keep allocating results forever while a texture tile is unavailable.
The film itself is proportional to image size. Payloads additionally have a
per-sample contribution limit; the future native protocol must enforce byte limits
before allocating/deserializing them.

Each sample result contains stable path/branch/event contribution identities,
weighted RGB contributions, weighted alpha and one sample weight. Contributions
are sorted by identity and reduced with explicit float32 rounding. Complete
samples enter the film in fixed order. Payload and accumulation errors do not
partially publish a block. Nonfinite values, overflow, missing/duplicate samples,
duplicate contributions and stale or revoked leases are rejected.

A retry keeps sampling addresses but changes lease ownership. Old work can finish
but cannot contribute. An attempt change invalidates the old scheduler; its
owner must discard it and allocate a fresh scheduler/film. Sample weights are
counted once even for multiple light/BSDF contributions or a black sample.

Only the coordinator mutates this model. It is not a concurrent Python queue,
native worker pool, CUDA stream implementation or real film/AOV implementation.
The scheduler's reduction order defines a new diagnostic order and is not claimed
to match MoonRay's current film order bit for bit.

## Native integration requirements

1. Carry MoonRay's SequenceID arguments, IntegratorSample sample number, total
   sample count where used, dimension, depth and sampling mode across suspension.
   Preserve BSDF/light/roulette/volume sequence purposes and stable branch IDs.
   Do not substitute a new RNG, seed from worker/attempt IDs, or use block size as
   the sampler's total sample count. The current Sample address is a work identity,
   not a replacement for those native sampler inputs.
2. Capture a native sampler reference corpus, including resumed sampling, and
   compare CPU/ISPC/CUDA values before enabling GPU shading. Validate integer
   width, rounding, tables and conversion semantics.
3. Retain the CPU vector/AVX path. Pack eligible work into coherent SIMD batches;
   lane occupancy, thread count and device scheduling must not alter sample IDs.
   Capability checks must precede dispatch. Use whole-render XPU fallback until
   per-path migration is separately validated.
4. Preserve required resource versions and exact mip selection. Page faults
   suspend/retry the same work; proxy geometry and coarse texture substitutes
   cannot contribute to the final film. Enforce device fences and byte budgets.
5. Initially use fixed uniform sampling. Adaptive convergence and adaptive light
   distributions require deterministic epoch boundaries and consistent statistics
   across all affected pixels. No adaptive stopping rule is implemented here.
6. Keep a fixed numerical contract for shading, intersection reconstruction,
   texture filtering and film/AOV handling. Identical RNG output does not resolve
   the grazing-shadow discrepancy measured in ORIGINS.md.

Do not claim speedup from this Python model. Worker throughput estimation,
hardware reservations, scene preparation overlap, checkpoint serialization and
native end-to-end image comparisons remain future work.

## Validation

Run:
    python -m unittest discover -s tests -p "test_xpu2*.py" -q

100 focused checks passed on 2026-10-16, including 18 new scheduling checks.
One check exercises 100 randomized schedules with mixed worker assignments,
completion order, contribution order and lease retries. All produce the same
21 unique sample addresses, seven samples per pixel, and exactly equal synthetic
RGBA values. Other checks cover different window sizes, slow-first-block
backpressure, missing mesh/mip dependencies, cancellation/fallback, duplicate
results, numeric overflow, partial blocks and weighted accumulation.

These are synthetic protocol results. No actual CPU/GPU sampler comparison,
native rendering speedup, production RGB parity, or installed XPU2 mode is
established by them.
