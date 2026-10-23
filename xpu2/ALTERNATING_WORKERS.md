# Alternating CPU/GPU workers

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This is a standalone **native Lambert shading-stage experiment**, not an XPU2
path renderer or image-speed benchmark. CPU workers invoke the original AVX8 ISPC
Lambert sampler. The GPU invokes the previously validated matching CUDA sampler.
Both compute their assigned jobs; CPU workers do not return cached answers.
Original XPU and the installed Modo plugin are unchanged.

## Ownership tested

There are 64 logical patterns and 16 successive epochs, for 1,024 jobs per trial.
A job contains either 8 or 128 samples. Patterns stand in for independently owned
image regions; these are not actual film tiles. Inputs replay the existing native
capture, rather than generating new path samples for each epoch. Each SIMD packet
replicates one captured record across eight lanes, keeping reflection uniform.
This fixture does not test lane-divergent materials or an entire scene.

Four policies use the same persistent workers, inputs, work count and output check:

- CPU only: the CPU pool consumes the ready queue.
- Barrier alternation: CPU/GPU ownership is `(pattern + epoch) % 2`; all patterns
  finish an epoch before any advances.
- Completion alternation: the same ownership rule, but each pattern can advance
  immediately after its previous job finishes. In-flight owners never change.
- Shared FIFO: either device can claim the next ready pattern. Completed patterns
  return to the back of the queue, preventing repeated selection of one pattern.

The CPU pool contains one or six workers; there is one GPU submit/collect worker
and the existing CUDA queue service. They survive across trials. GPU windows
contain one or sixteen eight-lane packets. A GPU window completes before that
worker claims another job, so this is a bounded single-window baseline, not a
saturated multi-stream GPU implementation.

For each worker count and batch size, each policy runs five times in rotated
order. Initialization and warmup are excluded. Numerical checks and canonical
output hashing occur after the timer. All GPU work retains the full native audit,
including transfers and comparison. CPU jobs also copy/convert input packets.
These are end-to-end stage timings, not isolated arithmetic throughput.

## Results (RTX 3090, i7-4930K AVX)

All 80 trials passed. Every trial completed 1,024 jobs exactly once, with immutable
in-flight ownership and bitwise agreement for sampled direction, RGB, PDF and
validity. Canonical result hashes match across every policy and repetition for
each workload. Each alternating trial performed 960 ownership swaps and assigned
512 jobs to each device. Duplicate GPU collection was rejected. GPU counters
confirm 1,405,496 samples actually accepted and replaced across 20,647 batches,
including warmup: no hidden CPU fallback, invalid samples, mismatches or errors.
Queue credits drained and CUDA resources were released.

For six CPU workers and 128 samples per job (131,072 samples per trial), median
wall times were:

- CPU only: **1.2363 ms** (1.2079–1.3685 ms).
- Shared FIFO: **1.9676 ms** (1.6266–2.2138 ms).
- Barrier alternation: **136.8949 ms** (135.8720–140.8140 ms).
- Completion alternation: **138.7676 ms** (138.1784–144.0683 ms).

The shared queue assigned only 4–6 of 1,024 jobs to the GPU in those five trials.
That reflects its measured end-to-end service cost, not a GPU failure. Forcing
half the work through small CUDA windows creates hundreds of transfer/completion
round trips. Removing the global barrier does not remove that cost. GPU event
timing includes scheduling gaps and is not a pure kernel arithmetic measurement.

The first exploratory scheduler scanned pattern indices rather than using FIFO;
that could repeatedly select a pattern and lengthen the tail. It was replaced
before these final measurements. The exploratory output remains local at
`test-results/xpu2-alternating-workers`; the final report is
`test-results/xpu2-alternating-workers-fifo/report.json`. The committed aggregate
`alternating-workers-20261017.json` retains timings, checks and source/build hashes;
no new scene-derived binary is published.

## Consequence

Alternating ownership is correct for this supported stage, but is **not a useful
performance policy for the current small GPU jobs**. Retain CPU-only routing for
cheap work. Next compare substantially larger GPU batches and more complete
supported shading sequences before enforcing any CPU/GPU ratio. A shared queue
can respond to measured service rates; forcing 50/50 cannot.

This result does not establish full-path parity, film accumulation order,
adaptive stopping, scene-loading speed, GPU material coverage, cancellation of a
mixed render, or any final-render speedup. Existing multiworker native-film
repeatability limits remain unresolved.

## Reproduction

Run `tools/xpu2_alternating_workers_probe.py` with `--source` pointing to the
read-only toolchain checkout, `--native` to the retained original Lambert probe
object/link manifest, `--runtime` to the isolated native runtime, `--capture` to
the existing XCL1 native capture, `--ptx` to the validated sampler PTX, and `--output`
to a new isolated results directory. Exact input hashes are in the report.
The tool refuses output inside the shared source checkout and rejects incomplete,
unmatched, numerically different or invalid ownership evidence.

The XPU2 regression suite passes all 245 tests, including seven new checks that reject invalid alternating-worker evidence.
