# Native CPU shading cost versus bridge cost

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Diagnostic measurements on an RTX 3090 / i7-4930K, with one native worker.
This adds isolated profiling builds and reproducible fixtures; it changes no
installed runtime, production defaults, GPU shading policy or material behavior.

## Finding

The existing GPU handoff happens after native `shading::shadev` has constructed
materials and evaluated maps. Offloading the following small sample operation
cannot recover that earlier CPU cost. The measured targets are larger jobs:

- Simple native Lambert/flat-diffuse sampling: **0.032-0.034 microseconds per
  active sample lane**, about 0.18 seconds total on the simple fixture.
- Eight-layer material construction without image maps: **3.17-3.26 microseconds
  per material point**.
- Eight-layer construction with 32 image-map nodes: **12.46-13.14 microseconds
  per material point** on the two-light fixture.
- Complete all-lobe BSDF evaluation and MIS contribution: about **0.43-0.45
  microseconds per light sample** on the textured fixture, and **0.27** in the
  many-light case. This excludes constructing the material, sampling the light,
  and tracing its shadow ray; it is not a complete bounce.
- Adaptive selection among 64 additional area lights: about **0.67-0.68
  microseconds per shading point** for the light-tree operation alone.
- Selected-light processing as a larger job is about **19 microseconds per
  material point** in the many-light fixture. This estimate sums disjoint light
  selection, light sample/evaluation, and all-lobe/MIS CPU work and divides by
  material points. It includes many light samples per point, excludes shadow
  visibility, and is not a separately timed contiguous function.

These are observed estimates from two sampling rates/seeds, not confidence
intervals or measured GPU speedups. Individual lobe and light operations remain
below the proposed bridge budget. Whole material/map evaluation and grouped
selected-light work exceed it; their larger payloads and GPU implementations
still require separate measurement.

## What the 1.5-microsecond bridge model means

The previous exclusive profile gives 0.546 microseconds of sampler queue host
plumbing and 0.616 microseconds of GPU service per consumed sampler lane.
Charging all native admission/replay plumbing to those sampler lanes produces
about 1.45 microseconds. That model excludes the separate light queue.

The sparse light queue instead costs about 28.9 microseconds of host plumbing
plus 19.9 microseconds of GPU service per consumed light lane. Its low useful
occupancy makes the sampler's 1.5-microsecond budget inappropriate for that queue.
Pooled host-plus-GPU service is about 2.08 microseconds per used lane, mixing two
work types. None of these sums is frame elapsed time or a causal asynchronous
break-even threshold: threads/streams overlap, and the old profile added 14.7%
to render time. Explicit waits are not included in these service models.

## Method and limits

The `cpu_cost` and `cpu_cost_full` stages patch only copied native sources.
Their scopes are disjoint: Lambert/flat-diffuse sampling, other sampling, lobe
(or all-lobe/MIS) evaluation, light sample/evaluation, light-tree selection, and
material construction including maps. The full-BSDF build removes the inner
lobe scope, avoiding double counting. Unsupported overlapping scopes fail the
accounting check. Active SIMD lanes are counted, not padded vector width.

The simple fixture is the existing diffuse/transmission sphere and ground.
The heavier fixtures contain nine indexed spheres plus ground, eight DwaBase
materials combined through seven DwaLayer materials, with glossy/metallic and
clearcoat parameters. Texture variants bind 32 ImageMap nodes to one generated
512-square tiled, mipmapped image, with different layer scales. They perform
about 90 million texture queries. This is a cache-resident texture-evaluation
stress case, not a large working-set, disk-I/O or paging benchmark. The many-light
case adds 64 RectLights and uses adaptive light selection at quality 0.5.
All use 384x216, fixed 16 camera samples per pixel and the same bounce limits.

Each fixture has original-XPU and same-binary unprofiled controls, then sampled
runs at probabilities 1/64 and 1/16 with independent deterministic seeds, and a
final unprofiled control. Every operation counts calls/active lanes, but only
selected calls read the clock. The minimum empty timestamp pair is 16-20 ns;
no optimistic subtraction is applied. Timings are exclusive elapsed intervals
on the native CPU thread, including any preemption or internal stalls, not a
hardware-cycle attribution. The two sampled runs must retain identical work
counts. Profiling-off controls measure perturbation; they cannot provide a
per-operation timestamp with instrumentation absent.

Material construction is measured as one operation; pure texture lookup time
is not separated from closure construction. A complete bounce through the next
trace is deliberately unmeasured: native queues and the GPU require correlated
ownership to account for that without overlapping scopes. Multiworker behavior
and enabled-XPU2 performance are not qualified by these CPU-only measurements.

Raw comparisons, timing perturbation, per-lane counts, and artifact hashes are
recorded in `cpu-cost-20261019.json`. The sampled runtime retains existing
compiled XPU2 hooks even with GPU shading disabled, so its difference from
original XPU is not attributable solely to the new profiling hooks.

## Next implementation target

Move a bounded, supported material job before `shading::shadev`, with resident
material/texture data, and avoid evaluating the same graph on the CPU when the
GPU owns it. Then evaluate combining selected-light work and visibility into
that job, measuring the new payload and service cost directly. Keep unsupported
materials on the original CPU path. Continue reducing disabled-route overhead;
these larger CPU costs do not excuse that baseline regression.

## Reproduce

Build through `tools/xpu2_native_build.py --stage cpu_cost` or `cpu_cost_full`
against the frozen owner-stage candidate. Run `tools/xpu2_cpu_cost_probe.py`
with `--build`, `--reference`, `--scene` and a new `--output` directory. Its default
fixtures are diffuse, layered, textured and many_adaptive. `--fixtures` narrows
the matrix; `--resume` reads an interrupted report and skips only qualified
completed cases after validating source snapshots and scene hashes.

The probe refuses competing renderers and uses lightweight Windows process
snapshots during frames. An earlier boundary WMI query timed out after a frame;
that diagnostic is preserved and the affected sample was rerendered. An earlier
matrix stopped when another renderer started, preserving completed fixtures.
The tests neither stop another renderer nor install the kit or modify a Modo scene.

## Qualification outcome

Twenty accepted original/control/sampled renders are float32 RGBA bit-exact.
The native sampled-accounting contract passes under O3/native/fast-math, and five
Python evidence contracts pass. Both sampled runs retain identical native work
counts within each fixture. The inspected images contain the intended nine
layered spheres and visible area-light reflections in the many-light variant.

Relative to the mean of the bracketing same-binary controls, sampled render-time
changes range from -3.49% to +2.79%. The negative value reflects run variation,
not a sampling speedup. Off-control spreads range from 2.67% to 6.21%, so these
runs support the large operation-cost differences, not sub-percent precision.
The many-light frame takes 148.272 s in original XPU, 162.231/158.009 s with the
candidate probe disabled, and 164.284/161.404 s sampled. Existing candidate
overhead remains; there is no enabled-XPU2 speed qualification in this report.

The post-capture CSV reader cleanup closes file handles and validates counters;
it does not alter native timing code. Exact earlier probe/builder snapshots and
hashes are retained alongside the interrupted reports for reproducibility.
