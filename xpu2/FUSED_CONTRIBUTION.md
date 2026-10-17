# Fused Lambert sampling and contribution arithmetic

This experiment extends the supported GPU calculation beyond Lambert sampling:
GPU-computed BSDF RGB/PDF now feed native-equivalent direct and indirect tentative
contribution arithmetic in the same CUDA kernel. It is not a full path renderer.
The light sample data is supplied from a capture; no live light evaluation,
visibility query, shadowing, selective clamp or film accumulation is performed.

## Native boundary

`fused_contribution.py` joins two existing native captures using pixel, subpixel,
sequence, nonmirror depth, lobe, sample index, lane and sample-array index. It
requires exact BSDF RGB/PDF and throughput agreement at the boundary. Ambiguous
identities, duplicates, nonfinite values, invalid geometric samples and inputs
outside the supported nonmirror/valid-light domain fail closed.

Eight samples match (four for each of two diffuse surface pixels). Ten additional
contribution records lack a Lambert counterpart and are explicitly reported as
unmatched. No counterpart is fabricated. These captures came from separate
instrumented runs with different lobe sample counts; this validates their matching
numeric boundary and reuses the contribution capture's sample counts. It does not
prove a jointly captured live continuation or global path identity.

The CUDA contribution calculation reproduces the native pre-shadow throughput
and power-heuristic MIS operations with contraction disabled. It reads the actual
GPU Lambert result, not the captured BSDF result. The captured result is used only
for validation. This implementation covers nonmirror lobes with valid light hits;
other contribution branches are not advertised as supported.

## Validation

Two modes are compared: the existing GPU Lambert kernel followed by a separate
GPU contribution kernel, and one kernel performing both. Both modes receive the
same inputs and transfer/read back the same data. The split mode also keeps
intermediate values on the GPU: this comparison isolates kernel fusion rather
than claiming to remove a CPU round trip that the baseline did not have.

Four base checks (forward/reverse order and split/fused) match all native output
words: sampled direction, RGB, PDF, validity, distance, direct RGB and indirect
RGB. Thirty larger checks replay these fixtures in batches of 128, 2,048 and
8,192 samples, five repetitions per mode with rotated order; all remain exact.
This is repeated fixture coverage, not additional material or scene coverage.

Two deliberate color perturbations halve the Lambert input RGB. In each mode,
all 24 sampled RGB words and all 48 direct/indirect RGB words change, and the two
GPU modes remain identical. This confirms that GPU-calculated color propagates
through the contribution stage. All CUDA buffers, module and context are released.
Native mismatches stop the timing gate and return failure; cleanup errors also
return failure.

Median end-to-end split/fused timings, including transfers and synchronous Python
harness/driver calls, were:

- 128 samples: **0.3310 / 0.3027 ms**.
- 2,048 samples: **0.6969 / 0.7086 ms**.
- 8,192 samples: **1.3741 / 1.3285 ms**.

Ranges overlap and the middle batch regresses. These results establish numerical
correctness for the fixture, **not a reliable performance gain**, GPU arithmetic
throughput, a CPU/GPU speed comparison, or accelerated final rendering.

## Remaining integration

The next meaningful boundary is live light sampling/evaluation and its owned
state. Captured light inputs cannot be treated as available before their live
direction-dependent calculation. Shadow rays, native lifetimes, arbitrary
materials, textures and accumulation remain unimplemented in this fused path.
Original XPU and the installed kit are unchanged.

`fused-contribution-20261017.json` retains compiler flags, source/capture/PTX/device
hashes, all checks and timings. Build/PTX/logs stay under the ignored local
`test-results/xpu2-fused-contribution-final` directory. No new captured binary is
published. Reproduce using `tools/xpu2_fused_contribution_probe.py` with `--source`,
`--lambert`, `--contribution` and a fresh `--output` directory outside the shared
source checkout.

All 262 XPU2 regression tests pass, including nine new boundary-validation tests.
