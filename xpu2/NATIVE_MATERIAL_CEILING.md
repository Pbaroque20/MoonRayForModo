# Native material frame-cost ceilings

GPU shading remained disabled throughout this study. The new pre-shading material job is **not implemented or qualified** by these results. Original XPU remains the reference and fallback. No installed kit, production default or merge was changed.

## Frame-time ceilings

For each fixture, original frame time is MoonRay's reported `Total time` (median of five originals at 12 workers). Material/maps and selected-light values are estimated **summed worker elapsed seconds**, shown as the range from independent 1/64 and 1/16 sampled calls. At one worker they are potential work budgets; at 12 they overlap and must not be subtracted from frame time. They include internal waits/preemption. The reference and profiled candidate use the same scene and settings, but the scopes live in the experimental CPU-cost build.

### 1 worker

- **diffuse:** original frame **8.352 s**; material/maps **0.366-0.373 worker-s**; selected light **0.362-0.366 worker-s**.
- **layered:** original frame **36.275 s**; material/maps **9.837-9.941 worker-s**; selected light **2.864-2.917 worker-s**.
- **textured:** original frame **63.890 s**; material/maps **38.733-39.794 worker-s**; selected light **2.339-2.417 worker-s**.
- **many_adaptive:** original frame **148.842 s**; material/maps **37.656-38.860 worker-s**; selected light **59.602-60.163 worker-s**.

### 12 workers

- **diffuse:** original frame **2.287 s**; material/maps **0.640-0.668 worker-s**; selected light **0.591-0.606 worker-s**.
- **layered:** original frame **6.726 s**; material/maps **19.463-19.925 worker-s**; selected light **5.625-6.589 worker-s**.
- **textured:** original frame **12.178 s**; material/maps **80.548-83.334 worker-s**; selected light **4.164-4.660 worker-s**.
- **many_adaptive:** original frame **26.435 s**; material/maps **76.176-76.333 worker-s**; selected light **109.990-110.218 worker-s**.

Material/maps includes graph evaluation and closure construction. Selected-light work sums disjoint light-tree selection, light sampling/evaluation, and complete all-lobe BSDF/MIS contributions; it excludes shadow tracing. The two sampled estimates are sensitivity checks, not confidence bounds. The estimator expands measured call time by its inverse inclusion probability, avoiding a single pooled per-lane estimate across differently occupied workers. Raw lane-weighted costs are also retained.

On the textured one-worker fixture, material work accounts for roughly 39 of 64 seconds, making the pre-shading boundary worth investigating. The many-light fixture spends roughly 60 seconds in selected-light work and 38 in material/maps; a material-only job will leave substantial CPU work. These are eight-layer Dwa stress fixtures, not a performance prediction for the first narrow UsdPreviewSurface port.

## Image and measurement gates

- **One worker: passed.** All 20 images used in the report were decoded again from their EXRs and compared as finite float32 RGBA words, including signed zero. Ten earlier accepted textured/many-light renders were reused with previously committed artifact hashes; ten new diffuse/layered renders fill the missing full-light scopes.
- **Twelve workers: failed.** Twenty original-XPU renders established four frozen reference envelopes. Twelve of sixteen candidate images exceeded at least one bound. All four fixtures have a failed candidate. The numerical bounds were not refitted, widened or replaced after seeing results.
- The first diffuse disabled result exceeded only the differing-word fraction. Other runs also exceeded magnitude/RMS/mean bounds. For example, many-light disabled R max error was 0.081881 versus a reference-pair maximum of 0.077393. This is a failed measured gate, not proof of a new GPU arithmetic defect: GPU shading was off. A finite reference envelope also does not guarantee every future original-XPU render falls inside it; held-out reference validation remains useful.
- All 46 newly executed native renders completed successfully with requested worker count, native XPU selection and GPU intersection activity. A renderer-process guard ran before/during/after each render. Twelve-worker gate failures were retained as diagnostics and do not qualify the backend.
- Six image/accounting gate contracts, five previous CPU-cost contracts, and the native counter test passed. The native test now exercises twelve simultaneous counter owners across two generations, with exact call/lane totals. This tests the profiler registry, not enabled GPU queue safety.

## Disabled cost remains open

The profiling-off CPU-cost build retains experimental hooks and disabled profiler call sites. On one worker, its simple-fixture controls were 8.224/8.258 s MCRT against original 7.879 s (about 4.6% overhead); the reused many-light controls were 162.231/158.009 s against 148.272 s (about 8.0%). No native optimization was made here, so differences from earlier 7-9% measurements are not claimed as improvements.

Twelve-worker timings vary widely: many-light original MCRT spans 23.447-28.109 s and its off controls are 31.451/36.468 s. This diagnostic matrix is not the prospective five-repeat, warmed, rotated speed matrix for the new material job. It cannot establish a new backend speedup or precisely attribute that spread. New-job disabled/never-submit/always-late/normal measurements remain pending.

## Material choice and next integration boundary

The real kit serializer audit emits UsdPreviewSurface for ordinary materials and DwaBaseMaterial for glass, rough diffuse and MoonShine overrides. The first narrow target is the exported opaque, specular-black diffuse UsdPreviewSurface configuration. This is a code-path audit, not a user-scene frequency census. It does not qualify image maps or the eight-layer fixture.

[The pre-shading job contract](PRE_SHADE_MATERIAL_JOB.md) records the required owned queue, compact result boundary, immutable residency, exact OIIO software-filter requirements and spot-check recovery. The old rolling queue still calls shadev first; it cannot be relabeled as the requested material job. Its GPU lighting path remains off in these experiments.

## Reproducibility

- [Fixed acceptance protocol](MATERIAL_JOB_GATES.json), recorded before timing.
- [Compact results and raw-artifact hashes](material-ceiling-20261019.json).
- [Exporter audit and module hashes](material-export-20261019.json).
- `tools/xpu2_material_ceiling.py`: 1/12-worker runs, frozen reference envelope, retained failures and resume.
- `tools/xpu2_material_ceiling_summary.py`: revalidates earlier artifacts and one-worker float32 words before summarizing.
- Native profiling uses the reference toolchain arithmetic settings; no new fast-math or FMA contraction was enabled. The accounting contract was rebuilt with `-mno-fma -ffp-contract=off` and without fast-math.

Captured harnesses are preserved with hashes. After measurement, report writes were made atomic and imported helper hashing was extended. The tested comparison/accounting code is unchanged. No additional renders were run for those reporting-only changes.
