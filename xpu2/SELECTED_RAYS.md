# Selected-ray CPU/OptiX comparison

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

## Result

The full-frame one-sample sphere fixture now has an isolated native diagnostic.
It records identical incoming rays through both Embree and OptiX at pixels
(96, 77) and (132, 96), with coordinates measured from the bottom left.
It does not narrow the render to a debug pixel, so GPU batches remain intact.

Across two identical traced runs, all 18 selected surface-ray records matched.
Two were camera hits; 16 were depth-one misses. There were no hit/miss or
primitive disagreements. Both camera hits had different distances/barycentrics:
maximum distance difference 4.76837158203125e-7 and maximum UV component
difference 1.7881393432617188e-7. Geometric normals matched exactly.

The copied control, instrumented-but-disabled, instrumented-enabled and repeated
instrumented renders matched numerically in every RGBA pixel, at zero tolerance.
The control also matched the earlier pinned XPU image. This validates the
instrumentation for this fixture, not the compatibility of the retained build
with every possible scene.

## Causal replay experiment

A separately enabled run replaced only the two selected primary-ray hit results
with their Embree results. It continued shading/rendering through XPU normally.
At (96, 77), the maximum RGBA discrepancy against the earlier vector reference
fell from 0.004094481468200684 to 1.4901161193847656e-8: one float32 step at that
value. At (132, 96), the colors already matched and continued to match. No other
image pixels changed.

This is evidence that primary-hit state explains almost all of the measured
color difference at the first selected pixel. It does not yet identify which
shading/sampling operation amplifies the perturbation. The remaining one-step
error is not attributed to accumulation without a contribution trace.

The replay is NOT a proposed production correction. XPU2 must follow the chosen
XPU reference contract, including its intersection behavior. Switching everything
to CPU intersections would neither establish XPU parity nor meet the speed goal.

## Scope and provenance

- Surface rays routed to GPU only; no shadow/occlusion trace, CPU-routed tail,
  BSDF trace, texture sampling trace or film-contribution multiset yet.
- Pixel, subpixel sample, sequence, depth, incoming ray and hit information are
  recorded. Sequence/depth are diagnostic labels, not a complete globally unique
  path-branch identity.
- Miss attributes are not compared. IDs are meaningful within this fixture;
  this is not a portable cross-scene primitive-ID mapping.
- Float32 values are logged with nine significant decimal digits and restored
  to float32 before comparison. This avoids counting decimal-formatting noise.
- One thread, fixed full-frame fixture, RTX 3090, driver 591.74. Logged GPU query
  percentage was 100%; that is not a measurement of GPU hardware occupancy.
- The source build's renderer DLL differs from the pinned runtime. The builder
  copies retained object/library files into an isolated folder, compiles only
  the handler, and produces control and trace DLLs. Every copied link input is
  hashed before/after, and all runtime binaries are checked before/after renders.
  This is a diagnostic link from existing objects, NOT a clean source build.
  Compiler headers/toolchain still come from the existing development install.
- No shared source, installed kit or installed runtime was modified. No Modo
  instance or user scene was used.

Nine native runs completed normally: four initial logging controls, followed by
four controls and one causal replay. The final code has 54 passing XPU2 unit
checks. Compact evidence including all 18 ordinary traced rays is in
`selected-rays-20261016.json`. Full logs, EXRs, frozen link inputs and runtime
inventories are under local `test-results/xpu2-ray-replay-build` and
`test-results/xpu2-selected-ray-replay`.

## Reproduce

From this isolated worktree, use fresh output directories:

```powershell
python tools/xpu2_build_ray_probe.py --source <existing-native-source-checkout> --runtime <reference-runtime> --output test-results/ray-build-new
python tools/xpu2_ray_probe.py --build test-results/ray-build-new --surface-reference test-results/xpu2-primary-state --output test-results/rays-new --replay-primary
python -m unittest discover -s tests -p "test_xpu2*.py" -q
```

Generate the primary-state reference with `tools/xpu2_surface_probe.py` first
if it is absent; that tool validates against the pinned reference inventory.
The ray-probe runner returns 0 for valid/non-invasive repeated diagnostics,
not for universal CPU/GPU parity. Each image comparison and the explicit replay
result are reported separately. A changed diagnostic or incomplete run returns 1.

Next: capture shadow decisions and shading contributions for these paths, then
establish a canonical contribution reduction and broaden the fixtures. Keep
zero tolerance while investigating; do not hide the discrepancy with an arbitrary
acceptance threshold.

The shadow/contribution follow-up now isolates the larger discrepancy to a
grazing visibility decision. See [CONTRIBUTIONS.md](CONTRIBUTIONS.md) for measured
evidence, diagnostic controls and implications for the XPU2 reference contract.
