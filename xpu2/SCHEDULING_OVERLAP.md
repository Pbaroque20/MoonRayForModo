# Independent CPU work during GPU dispatch

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This is a **standalone scheduling feasibility test**, not a native MoonRay render
benchmark. It uses the current packed, pinned asynchronous CUDA queue with full
shader auditing enabled. No runtime, installed kit, or original XPU behavior changes.

## What is measured

Each iteration publishes exactly nine owned packets (72 native captured Lambert
samples) as one GPU batch. Publication is held until the complete batch is ready,
so serial and overlapped schedules have identical batch counts and sizes. The
correlated native capture is repeated; these are not newly generated image samples.

The serial control collects the GPU results, then performs independent CPU work.
The overlapped schedule performs that same CPU work before collecting GPU results.
CPU work is a deterministic eight-lane AVX numerical recurrence, with its result
consumed in the final digest. It is synthetic and does not estimate native shading
cost. There is one CPU coordinator and one GPU service thread, not a multi-worker
native path scheduler. There remains only one GPU batch in flight.

The probe retains owned identity/state, verifies every GPU output word against the
native capture, claims leases in reverse order, rejects duplicate completion, and
compares ordered result digests across every schedule/repetition. A separate
nonzero RGB sentinel run proves GPU answers reach the consumed results. All GPU
samples must be accepted/replaced; CPU fallback cannot pass as GPU execution.
Shutdown must drain all tickets/leases and release CUDA resources.

## Retained measurement

Evidence: `scheduling-overlap-20261017.json`, generated from
`test-results/xpu2-scheduling-measured/report.json`. On the RTX 3090 and AVX1
CPU, the measured replacement run executed 1,476,864 shader samples in 20,512
batches, including warmup. Initialization and 32 warmup batches are excluded
from timing. Each CPU-work setting has five alternating-order repetitions of
512 iterations per schedule. No regression test process ran alongside this
retained timing run; other machine load, caches and clock states were not fixed.

Median total times for serial versus overlap:

- Zero recurrence steps: 119.35 versus 114.53 ms (1.04x; overlapping timing ranges).
- 128 steps: 118.81 versus 120.72 ms (0.98x; no benefit).
- 1,024 steps: 143.72 versus 118.62 ms (1.21x; substantial timing variation).
- 8,192 steps: 233.92 versus 120.73 ms (1.94x). Serial repetitions ranged
  228.84-253.75 ms; overlapped repetitions ranged 119.07-131.83 ms.

At the largest CPU workload, CPU computation itself stayed nearly unchanged:
85.47 versus 84.72 ms. Median collection time fell from 137.88 to 25.66 ms.
Every overlapped iteration started its CPU work while its GPU result was still
pending; 2,489 of 2,560 also finished CPU work before that result completed.
Pending includes queueing/transfers/driver work, so these observations do not
prove simultaneous GPU-kernel and CPU arithmetic or GPU occupancy.

Both the 40 replacement measurements and eight sentinel measurements passed
numeric, ownership, accounting and cleanup checks. The XPU2 regression suite
passed 235 tests; the four new evidence checks also passed after adding timing
ranges to the final summary. Source, compiler, executable, PTX, GPU and log
identities are retained. Earlier exploratory runs are not the timing evidence.

## Decision and remaining work

Independent useful CPU work can hide the measured handoff latency. Small CPU
jobs do not provide enough work to hide it, and overlap does not remove dispatch
cost. This supports testing an owned native work boundary next, not enabling
XPU2 or advertising a 1.94x rendering speedup.

The next adapter must dispatch ready independent native paths while shader
requests are pending, then resume them under valid CPU TLS/arena ownership.
The current integrator's stack/arena-backed BSDF, intersection, sampler and light
state cannot simply be retained as pointers after return. A restricted Lambert
boundary needs complete owned state, bounded backpressure, unchanged logical
sample identities, and ordered contribution publication before a rendered
comparison is meaningful. See CONTINUATIONS.md for the lifetime hazards.

This test does not resolve native multi-worker film parity, device-loss recovery,
texture residency, scene loading, or general material support. Existing XPU
remains the reference and independent fallback architecture.

## Reproduce

Use a new output directory outside the shared source checkout:

    python tools/xpu2_scheduling_probe.py --source <shared-source-read-only> --capture test-results/xpu2-correlated-capture-final/capture/correlated.bin --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/scheduling-new

Do not run CPU regression suites concurrently with a timing measurement.
