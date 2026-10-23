# Copied-ray origin candidates

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

## Result

The small-offset candidates cleared the observed self-shadowing decision in the
unit and translated sphere fixtures. The small and large sphere fixtures had
no blocked-to-clear changes at these selected rays.

Normal-sign offsets of 1, 2 and 4 float32 representable steps preserved all tested
blockers. An 8-step offset and a coordinate-scaled offset skipped the closest
blocker, producing an unblocked query where the original ray intersects the
blocker ahead of its near limit. Both Embree and OptiX agree on those results.

This rejects the larger candidates for this contact case. It does not establish
a universally safe smaller offset or authorize a production shadow-bias change.

## Experiment

The diagnostic copies shadow rays, changes only their origins, and queries both
native backends. It preserves the renderer's original GPU occlusion buffer before
issuing extra GPU queries, then restores that buffer for actual image processing.

Six policies were tested:
- unchanged;
- 1, 2, 4 or 8 nextafter steps per coordinate, toward the outgoing side indicated
  by the geometric normal;
- geometric-normal offset of 4 * float32 epsilon * maximum absolute coordinate,
  followed by one outward nextafter step.

The step policies are coordinate-wise normal-sign moves, not an exact vector
offset along the normal. Near/far limits, ray direction, time, shadow receiver
and light identity are preserved. Normals come from the selected primary GPU
hits. The helper is diagnostic-only, one render thread, one camera sample and
two fixed pixels; it is not a general path-state cache.

Retained cases:
- unit sphere;
- scale 0.01;
- scale 1000;
- unit sphere and camera translated by (1e6, 1e6, 1e6);
- finite two-triangle blockers at nominal normal gaps 1e-6, 1e-5 and 1e-4.

The blockers are hidden from the camera, but shadow-visible. Their vertices are
rounded to float32 before serialization. Their object transform matches the
camera transform, making their stored coordinates camera-relative for the
triangle checks. Nominal gaps are not promises of exact representable distances.

The test checks actual two-face/four-vertex native geometry statistics and
rejects unknown attributes. It also requires newly blocked identical inputs on
both backends compared with the unit fixture, proving the blocker participates
in visibility. For the three gaps, 3, 5 and 65 candidate inputs respectively
become blocked on both backends.

## Validation and rejected evidence

All seven retained cases have exactly equal RGBA pixel values with probing
disabled/enabled. Each contains 21 selected source rays and six policies:
882 paired CPU/GPU queries in total. There are zero same-input visibility
disagreements. Unchanged candidate queries must also match the original GPU
result; otherwise the experiment fails.

Two candidate queries skip the nearest blocker: the 8-step and coordinate-scaled
policies. The finite-triangle analysis verifies that the original intersection
is ahead of the original near limit, while the candidate no longer reaches it
after its near limit. This is independent geometric corroboration, not a new
intersection implementation for the renderer.

The first three blocker fixtures were invalid: incorrect RdlMeshGeometry
attribute names produced empty meshes. A successful process exit had not caught
the warning. Those six renders are rejected; a correction record is retained.
Only the three affected fixtures were rerun after fixing the names and adding
topology/occlusion validation. The four scale/translation cases were retained
and re-audited from their original logs. There were 20 native renders overall,
14 retained and six rejected. The focused XPU2 suite has 82 passing unit checks.

Compact audited evidence is in origins-20261016.json. Local native outputs are
under test-results/xpu2-origins and test-results/xpu2-origins-blockers. The first
folder's validation-correction.json supersedes its original blocker results.
The diagnostic's extra queries are not included in renderer ray-count statistics;
its timings must not be used as a rendering performance benchmark.

## Reproduce

Build and run into fresh folders:

~~~powershell
python tools/xpu2_build_ray_probe.py --source <native-source-checkout> --runtime <pinned-runtime> --output test-results/origin-build-new --contributions --origins
python tools/xpu2_origin_probe.py --build test-results/origin-build-new --surface-reference test-results/xpu2-primary-state --output test-results/origin-new
python -m unittest discover -s tests -p "test_xpu2*.py" -q
~~~

The --cases and --baseline-origins options allow a blocker-only rerun using
previous unit queries. The source runtime, scene and retained-object build
limitations from SELECTED_RAYS.md still apply. No installed files are modified.

## What remains

Before selecting a production policy, derive the reconstruction/transform error
bound from the actual hit representation and test reflected, transmitted,
instanced, deforming, thin and edge-contact geometry. Camera-relative coordinates
help the translated case here; they do not prove all large-coordinate scenes are
safe. A direction-dependent offset can cross nearby geometry even if it fixes a
grazing self-hit.

Keep original XPU as the reference/fallback. Changing its ray-spawn policy would
require a new reference version. These measurements approve no XPU2 backend,
global bias, general parity threshold or production offset.
