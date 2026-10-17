# Live GPU contribution results in native rendered images

Status: **restricted image path validated; slower than native XPU**. The isolated
renderer now uses live GPU Lambert RGB plus GPU-computed BSDF-sampled direct and
indirect contributions in the native image. This is not an installable or fully
asynchronous XPU2 renderer.

The follow-up [contribution-window experiment](FILM_WINDOWS.md) reduces dispatch
overhead while preserving these image/fallback controls. Measurements below
describe the earlier per-packet milestone.

## What reaches the image

The new hook receives live light results, BSDF RGB/PDF, path throughput and sample
counts. It calculates the native nonmirror, valid-light MIS contribution on CUDA,
then writes distance, direct RGB and indirect RGB back to the native sample.
Native selective clamping, visibility, continuation, AOV processing and film
accumulation consume those values in their original order. No captured numeric
fixture supplies the GPU answers at render time.

Audit mode compares every supported result against the native CPU function and
keeps native output. CPU-skipping mode (the diagnostic `fast` flag) replaces that
function for accepted lanes; unsupported or failed lanes use the native function.
A sentinel mode halves returned contributions to prove they affect the image.
Missing-PTX failure is explicit in the profile and falls back completely.

The existing Lambert hook still retains native CPU sampling/reference work. The
new skipped work is specifically `integrateBsdfSample` arithmetic; this does not
remove all CPU shading. Light-sampled contributions and live light evaluation
remain native. Neither arbitrary materials nor a whole GPU path are certified.

The contribution bridge currently uses small synchronous packets and its own
CUDA context. The previously validated dedicated OptiX queue remains a separate
milestone; this bridge has not yet connected it to asynchronous path continuations.

## Image and lifecycle checks — 2026-10-17

Eleven final renders cover the original diffuse fixture and a framed sphere with
a ground plane, environment and distant key light. All use one native renderer
thread on the RTX 3090.

- Eight corresponding linear RGBA comparisons match exactly at zero tolerance:
  disabled hooks, GPU shading alone, audited contribution, CPU-skipping result,
  repeat, missing-kernel fallback, and the two larger-scene variants.
- On the smaller fixture, the GPU replaces 210,001 CPU contribution calculations
  in each normal CPU-skipping run. The deliberate sentinel changes 23,346 pixels.
- On the 384 by 216 sphere/ground scene, GPU results replace 1,997,771 CPU
  contribution calculations. Both audited and CPU-skipping images match native
  XPU exactly. This scene uses a 2 by 2 pixel sample grid.
- No accepted final run reports contribution mismatches or cleanup errors. The
  missing-kernel control reports expected errors, accepts no GPU contribution
  results, and produces the exact reference image through CPU fallback.
- All 315 XPU2 regression checks pass, including nine new evidence-gate checks.

The first image audit matched all contributions but failed its exit-time CUDA
cleanup gate. The final build closes contribution resources immediately after
the native render driver stops, before renderer/driver teardown. Exit cleanup is
idempotent. This fixes the observed failure; it is not a device-loss or long-run
memory certification.

The first presentation fixture omitted the ground from its GeometrySet and had
the key facing away. Those scene-construction errors were corrected before the
reported sphere/ground comparison. Earlier incomplete fixtures are retained
locally, not substituted for the final ground/shadow evidence.

## What the image reveals about overhead

The small fixture's native rendering time was 0.364 seconds. GPU Lambert alone
was 1.358 seconds; adding CPU-skipping GPU contributions took 4.145 and 4.352
seconds in two runs. Audited contributions took 4.171 seconds. Skipping the small
CPU arithmetic alone does not recover the transfer/dispatch overhead.

The ground/shadow fixture took 3.784 seconds in native XPU, 67.014 seconds with
audited GPU contributions, and 57.664 seconds with CPU-skipping contributions.
The CPU-skipping contribution stage made 250,981 calls for 1,997,771 samples:
approximately eight samples per call. Its measured 28.675 seconds included
15.950 seconds waiting for GPU completion and 9.186 seconds reading results back,
about 88 percent combined. These are host-side intervals; wait time is not a
measurement of arithmetic alone. GPU scheduling/context switching and transfer
costs can be included.

These are instrumented process runs with warmed/uncontrolled caches, one native
reference per fixture and a small repeat only on the first fixture. They identify
an overhead problem, not a production throughput estimate or acceleration result.

The next optimization should batch complete contribution windows, reuse the
resident GPU context/buffers, and keep intermediate results on the GPU. Then fuse
supported shading/light/contribution stages where their dependencies allow it.
Use these same exact-image and negative/fallback controls after each change.
A native asynchronous continuation is still needed to avoid blocking the caller.

## Reproduce and inspect

Build with `tools/xpu2_film_build.py --source <read-only-native-checkout> --base
test-results/xpu2-owned-contribution-build-v2 --output <new-build-folder>`.
Run `tools/xpu2_film_probe.py --build <new-build-folder> --base
test-results/xpu2-owned-contribution-build-v2 --output <new-results-folder>`.
Add `--showcase` for the framed sphere/ground reference, audit and CPU-skipping
comparison. The runtime and PTX remain outside the installed kit.

Final local results are `test-results/xpu2-film-validation-v2` and
`test-results/xpu2-film-showcase-final`; the latter includes `gpu-image.png` and
`fast/beauty.exr`. The PNG uses a simple gamma-2.2 display conversion; comparison
uses the original linear RGBA values. The candidate is under
`test-results/xpu2-film-build-v2`. It links retained native objects and is not a
clean-source distributable build. Source and [aggregate evidence](film-image-20261017.json)
are published; binaries, rendered files and captures stay local.
