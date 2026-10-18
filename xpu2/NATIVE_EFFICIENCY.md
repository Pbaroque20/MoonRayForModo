# Native transfer efficiency and independent CPU shading

This isolated experiment derives from the guarded batch transport candidate.
It is opt-in, does not install a kit, and does not replace XPU. The existing CUDA
shading PTX is unchanged.

## Independent controls

- `XPU2_LEAN_WIRE=1` uploads the invariant 512-entry input-length array once per
  slot instead of once per batch. It omits the diagnostic 96-byte input echo
  download and the corresponding host comparison. Each sample still uploads its
  original 96-byte input and downloads the same 36-byte result/status record.
  Per-sample transfer falls from 232 to 132 bytes, plus 2 KiB initial upload per
  slot. The kernel still produces the diagnostic echo in device memory.
- `XPU2_POLL_US=16` limits each slot's CUDA event queries to at most one per
  16 microseconds. A pending result is never treated as complete. Failure paths
  still drain submitted work before buffer reuse; the worker continues to check
  for newly available batches. This bounds driver queries, not host scheduling
  latency or CPU occupancy. Zero preserves the old polling behavior.
- `XPU2_CPU_LOBE_AHEAD=1` precomputes CPU-owned lobes in the same first-bounce
  material invocation. The first eligible lobe is assigned to GPU; subsequent
  lobes are assigned to CPU while those submitted diffuse packets run on the
  GPU. It stores sample validity and reuses the native sample structs when the
  original lobe loop resumes. It does not recursively process other ray queues,
  migrate arenas or change the native film accumulation order.

Lean wire is limited to native execute/sentinel modes. The full echo validation
remains available in the disabled control and the original synchronous diagnostic.
Skipping that diagnostic is explicit: tokens, scene revisions, slot lifetimes,
result status and finite-value checks remain, but the candidate no longer proves
byte-for-byte input echo equivalence for each transferred sample.

CPU lookahead recreates the original per-lane lobe seed and sample sequence.
It prepares only lobes not owned by the GPU and counts precomputed/consumed sample
packets. It does not claim arbitrary native shader side-effect compatibility;
exact image comparisons determine the tested scope. Adaptive/unsupported frames
retain their existing bypass. Tests use one native render worker because the
prior native multiworker repeatability issue is unresolved.

## Reproduce

Use fresh output directories and the retained baseline/link inputs:

    python tools/xpu2_native_efficiency_build.py --source <read-only-primary> --base test-results/xpu2-origin-build --output <build>
    python tools/xpu2_native_efficiency_probe.py --build <build> --reference test-results/xpu2-origin-build/control --previous test-results/xpu2-transport-build --ptx test-results/xpu2-native-work-ptx/film.ptx --previous-ptx test-results/xpu2-native-work-ptx/film.ptx --scene <fixture> --output <controls> --checks

`--require-cpu-ahead` requires real precomputed CPU shading in the eligible cases.
Two initial glossy fixtures did not exercise both devices together: the mixed
variant precomputed no CPU work, and the transmission variant accepted no GPU
work. Those coverage failures are retained. Explicit lobe ownership is tested on
the existing reflection/transmission fixture. Original fixtures remain unchanged.

The controls separate unchanged packing, lean wire only, paced polling only,
both transport changes, and transport plus CPU lookahead. Deliberate GPU-color,
missing PTX, zero capacity and partial-upload controls are included. Without
`--checks`, warmup and three rotated rounds compare original XPU and the five
same-build paths. Timing requires an otherwise idle renderer.

## Ownership boundary

The lookahead policy is deliberately simple and explicit: the first eligible lobe
stays GPU-owned and later lobes in that same material invocation become CPU-owned.
It is not a learned load balancer, arbitrary path migration, or a guarantee of a
50/50 split in every scene. Supported GPU lobe math stays unchanged; CPU samples
use the original native sampler. Publication still follows the original lobe loop.

The first reflection/transmission control with this policy matches every float32
RGBA value. It prepares and consumes 203,265 CPU sample packets exactly once;
accepted GPU samples fall from 3,250,134 to 1,625,067. The deliberate GPU-color
sentinel differs, proving that the smaller GPU contribution still reaches film.
Only nine of 203,265 GPU tickets are ready at the first resume check in that
control, so useful independent work does not yet hide most handoff latency.

## Completed validation

The revised candidate passes the twelve-case reflection/transmission matrix and
six-case rough-diffuse/transmission matrix. All normal and fallback outputs are
exact float32 RGBA; both deliberate GPU-color sentinels differ. Missing PTX,
zero-capacity and partial-upload fallback remain guarded and exact.

Adaptive bypass, four held in-flight cancellations, and persistent cancellation
followed by a replacement frame pass. The replacement image is exact to both
fresh rendering and original XPU. Its precomputed CPU packets are consumed once,
including the cancelled frame; no batch contracts remain active after retirement.
There are 22 normal/reference/fallback images and two intentional sentinels across
these image tests. This is single-worker validation, not a multiworker parity claim.

Lean wire reduces per-sample transfer from 232 to 132 bytes (43.10%), with a
4,096-byte one-time upload for two slots. On the reflection/transmission control
it avoids 312,215,040 echo-download bytes. Spaced event checking reduces CUDA
completion queries from 1,674,407 to 178,478 (89.34%) in the observed controls.
The host still loops and checks the clock, so fewer driver queries are not a
claim of proportionally less CPU usage or shorter rendering.

## Timing results

The correctness-run durations remain excluded because another renderer was active.
The subsequent warmup plus three rotated measurement rounds produced 24 exact
float32 RGBA images. An installed Modo renderer started at 19:32:30 UTC during
`3-control`; that measurement is excluded. All other measured render logs ended
before it started. Five-second process snapshots and final-round file timestamps
are retained. These checks identify MoonRay competition, not all system activity.

Accepted MCRT medians (seconds) and ranges:

- Original XPU: **7.704**, range 7.522-8.112 (three rounds).
- Same-build control: **17.170**, range 17.061-17.278 (two uncontaminated rounds).
- Lean transfers only: **17.275**, range 17.254-17.727 (three rounds).
- Paced completion queries only: **17.832**, range 17.287-18.743 (three rounds).
- Combined transport changes: **17.638**, range 16.567-18.282 (three rounds).
- Transport plus independent CPU lobe work: **15.066**, range 14.376-16.118
  (three rounds).

Lean transfers and fewer driver queries alone do not establish a speedup.
Independent CPU lobe work reduces the median by **14.58%** against combined
transport in the three unaffected comparisons; the individual round reductions
are 8.62%, 9.06%, and 21.37%. The candidate is still **95.56% slower** than
original XPU on this single-worker fixture. These small-sample results do not
qualify production performance or other materials/scenes.

CPU ownership halves submissions from 45,170 to 22,585 and preserves exactly-once
sample consumption. The CPU-work variant reaches only one in-flight batch here;
none of its 203,265 tickets is ready at the first resume check in any measured
round. Its median submission time is 2.028 seconds and packing is only 25.9 ms.
Those counters have overlapping scopes and must not be added as a frame-time
breakdown. The next bottleneck is the frequency of native/GPU handoffs and lack
of independent work across native material invocations, rather than bulk packing.
Reducing transfers did not remove the per-batch launch and continuation costs.

The raw report is retained unchanged, including its contaminated control summary.
Use `timing_analysis.accepted_summary` in the evidence file for accepted timings.
No optimization is enabled in the installed plugin, and XPU remains unchanged.

Complete identities, reports and the two excluded coverage attempts:
[native-efficiency-20261018.json](native-efficiency-20261018.json).
