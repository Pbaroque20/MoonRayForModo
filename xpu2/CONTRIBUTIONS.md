# Where the selected-pixel difference is amplified

## Measured result

The larger difference at (96, 77) is a visibility discontinuity on a grazing
shadow ray. A tiny change in primary-hit state changes that ray's origin and
minimum distance. It changes from unblocked to blocked and loses an entire
lighting contribution, rather than merely rounding its color differently.

The lost RGB contribution is approximately
(0.0040945108, 0.0002691871, 0.0002120927). Its red component accounts for almost
all of the previously measured 0.00409448 pixel discrepancy. The fixture has
one sphere and an environment light, so the blocker is self-shadowing geometry.

For the uniquely matched changed shadow ray:

- Direction is exactly identical before and after primary-hit replay:
  (-0.9091821313, -0.3662445545, -0.1981229782).
- Replayed origin minus original origin is
  (2.9802322388e-8, -7.4505805969e-9, 4.7683715820e-7).
- Minimum-distance change is -5.4569682106e-12.
- Embree and OptiX both report blocked for the original ray and unblocked for
  the replayed ray. There are no same-input shadow disagreements among the
  21 selected checks in either XPU run.

Thus the observed amplification is not evidence of disagreement between the
shadow-query backends for identical inputs. The differing primary intersection
feeds a precision-sensitive visibility decision downstream. The trace does not
identify the exact blocking primitive or prove which component of the origin
perturbation alone is decisive.

## Contribution and accumulation evidence

Both selected pixels together produce 38 queued RGBA contributions in ordinary
XPU and 39 in the primary-hit replay and vector reference. Zero contributions
and duplicates are preserved. The replay and vector reference have identical
contribution multisets at BOTH selected pixels, including their weights. The
ordinary XPU trace, including its contributions, repeats exactly.

The last one-float-step image difference at (96, 77) therefore occurs downstream
of the observed contributions. Canonically sorted float32 reduction and a
higher-precision math.fsum reduction agree between the replay and vector data.
The native film groups contributions in batches; the recorded queue order is
not necessarily its addition order. These results isolate the remaining error
to downstream processing; they do not constitute a complete film-operation trace.

## Controls and diagnostic repairs

The final seven-render experiment includes unmodified control XPU, instrumented
XPU with tracing off, two traced XPU renders, the primary-hit replay, and vector
renders with tracing off/on. The control images remain exactly equal to their
pinned single-thread references. Tracing itself changes no image pixels.

Two earlier diagnostic attempts were correctly rejected: one completed seven
renders but failed report assembly; another completed four renders before normal
progress output interrupted a JSON record. Both are preserved locally as
incomplete experiments. Report assembly is fixed, and native observations now
use a dedicated XPU2_TRACE_FILE rather than sharing stdout/stderr with renderer
progress. An invalid record remains an error, never a missing/zero contribution.

There were 18 native renders in this investigation, with seven in the final
complete experiment. There are 65 passing focused XPU2 unit checks. No installed
runtime, kit, shared checkout or user scene was changed.

## Reproduce and limits

Build and run into fresh directories:

```powershell
python tools/xpu2_build_ray_probe.py --source <native-source-checkout> --runtime <pinned-runtime> --output test-results/contribution-build-new --contributions
python tools/xpu2_ray_probe.py --build test-results/contribution-build-new --surface-reference test-results/xpu2-primary-state --output test-results/contributions-new --contributions --replay-primary
python -m unittest discover -s tests -p "test_xpu2*.py" -q
```

See SELECTED_RAYS.md for the pinned fixture and retained-object build limitations.
The GPU shadow comparison mirrors the existing CPU surface-shadow query setup;
unsupported/nonstandard cases are recorded with cpu=-1, not guessed to be clear.
Matching between runs uses only unique identical directions plus pixel/sample/
sequence/depth/type. Ten directions match exactly here, with one visibility
change. Unmatched directions and ambiguous identities are not silently paired.

These are selected pixels in a fixed one-sample, single-thread scene. There is
no general scene, volume, motion or MaterialX parity claim. The trace does not
provide stable branch IDs, texture/BSDF internals, or a production deterministic
accumulator. The replay remains diagnostic only.

## Consequences for XPU2

Preserve sample identity AND a specified intersection/secondary-ray spawning
contract. Image parity cannot be guaranteed merely by sharing material formulas
or allowing a small tolerance on the first intersection. Tiny errors can change
visibility and remove a whole contribution.

A robust ray-origin policy should be investigated consistently on both sides,
using near-contact, thin geometry, large coordinates and grazing-ray fixtures.
Do not hide this result by increasing a global shadow bias: that can cause light
leaks and intentionally changes the reference image. Any accepted change to the
reference's spawning/intersection policy must create a new reference version.
Contribution-level comparisons and canonical reduction now provide the next
step toward separating those changes from scheduling and accumulation noise.

The copied-ray scale/contact experiment is now measured. See
[ORIGINS.md](ORIGINS.md): larger offsets demonstrably skip the closest blocker;
smaller candidates remain experimental.
