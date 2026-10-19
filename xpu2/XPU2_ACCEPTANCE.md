# XPU2 architecture acceptance criteria

XPU2 remains an opt-in experimental backend. Original XPU is the fallback and
reference, not a backend being replaced. A protocol test or a selected diffuse
kernel is not proof of full GPU shading, scene residency, or a speedup.

The next backend must meet all six requirements below. These gates are cumulative;
no single successful fixture qualifies the renderer.

1. **Disabled cost.** Compare original XPU with the same candidate with every
   XPU2 option removed. Record full process, scene loading, initialization and MCRT
   separately, at one and all logical CPU threads. Rotate run order after warmup.
   Initial regression budget: median MCRT overhead below the larger of 3% and
   0.1 seconds. Report uncertainty and repeat only to resolve a failure/change.
   The old resident-off control still enabled GPU shading; its 11-second result
   was not a fully disabled baseline.
2. **Useful GPU work.** Measure input/output bytes, queue delay, transfer time,
   launch time, kernel time and useful accepted lanes separately. Aggregate jobs
   across independent native owners into bounded flights. Do not wait for an
   arbitrary hundred-thousand-ray threshold: sweep sizes under a latency/memory
   budget. Larger buffers alone are not a larger shading job. GPU material,
   texture and light evaluation must replace corresponding CPU work, not audit it.
3. **Scene residency.** Stable typed scene IDs and dependency generations refer to
   immutable geometry/material/texture/light snapshots. Publish device residency
   only after successful upload completion. Edits invalidate dependents; in-flight
   leases retain their own revision. Test unchanged-frame uploads, one-material
   edits, texture edits, geometry edits, eviction and cancellation. Per-hit
   record reuse does not satisfy this gate.
4. **GPU path segments.** Shade, sample, trace and update throughput on the GPU
   for several supported bounces. Return completed film contributions or an owned
   continuation at an unsupported boundary. Preserve RNG/sample IDs, PDFs, MIS,
   path depth, texture derivatives, light linking and AOV state. Never both commit
   GPU contributions and replay the same contribution on the CPU. This requires
   a native device scene adapter and integrator, not another diffuse-sample kernel.
5. **Image quality.** Keep bit-exact mode as a diagnostic. A separate performance
   mode may use GPU arithmetic, but must pass predeclared linear-HDR quality gates
   across independently seeded reference/candidate ensembles and a converged
   reference. Compare bias, noise/error, localized defects, alpha and AOVs. Include
   missing/black/stale contributions as negative controls. Matching total brightness
   or one image within an arbitrary tolerance is insufficient. A failed or
   inconclusive test cannot be relabeled a parity pass.
6. **Full concurrency.** Qualify 1, 2, 6 and 12 native workers on this machine,
   both fixed and adaptive sampling. Require evidence of actual GPU work, bounded
   memory, no retained credits/leases, cancellation/restart recovery and no duplicate
   film commits. Compare against original XPU at the same thread count and quality.

Target: 30–40% less elapsed rendering time on representative scenes; 50% is a
stretch target, not a promised result. Report scene-load and edit-to-first-image
latency separately. Small synthetic fixtures establish correctness only.

## Current implementation boundary

The native candidate accelerates selected diffuse sampling and direct-light
operations while native CPU code still constructs materials, accesses textures,
continues paths and integrates the film. GPU intersection remains original XPU.
The scene index, texture residency and continuation libraries have independent
experiments, but they are not a scene-wide GPU integrator. Connecting them must
preserve the ownership boundaries above rather than just enable their flags.

`tools/xpu2_disabled_baseline.py` implements the first measurement gate at one
and all CPU threads. Enabled multiworker qualification, native scene residency,
large material jobs, multibounce GPU integration and statistical image qualification
remain explicit unfinished gates. No release/install action is implied by a pass.
