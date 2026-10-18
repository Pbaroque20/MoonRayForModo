# Native first-bounce path restoration

This candidate restores **native post-shading child paths**, rather than replaying
captured arithmetic or deferring completed film values. It remains an experiment:
the BSDF/light calculation before this boundary is still synchronous, and the
owned GPU shading dispatcher is not yet connected to the restoration hook.

## Native boundary

The copied `CPP_addRayQueueEntries` adapter converts freshly generated native
SIMD child rays to scalar form as usual. For eligible batches it then:

1. Captures ray origin/direction, differentials, interval/time, visibility mask,
   flags, path-throughput/depth state, sequence ID, pixel/sample identity, texture
   footprint settings and tile/pass into an owned numerical record.
2. Frees the original native ray allocations. No intersection, BSDF, light,
   scene resource, arena allocation or native ray pointer is retained in a record.
3. Returns to the integrator. Its sample arrays and arena storage may be reused.
4. Reconstructs fresh ray allocations on the same owning CPU thread before the
   next native queue submission or flush, retaining original batch boundaries,
   then submits them to the existing XPU intersection queue.
   Subsequent shading, visibility and film accumulation use MoonRay's native code.

There are at most 64 registered owners and 4,096 queued paths per owner. A full
queue drains before accepting another batch; oversized/unsupported batches use
the original path. A recursion guard prevents native queue flushing during ray
allocation from reentering restoration. Queue emptiness includes owned paths.
Ray, occlusion, presence-shadow, radiance and AOV submissions drain older owned
paths first. This short deferred boundary preserves native ordering; it does not
permit arbitrary completion delays or out-of-order GPU results.
Frame teardown occurs only after the driver stops, discards any cancelled
numerical packets, verifies accounting, and clears all owners before another
frame can start. No worker is launched by this adapter.

The supported case is deliberately narrow: the first diffuse-reflection child
bounce in fixed-sample XPU beauty renders, no AOV schema, deep/Cryptomatte handles,
per-lobe light links, or pointer-bearing ray extensions. The previous first-bounce
BSDF and light samples have already been consumed; the sequence ID preserved here
is the address for subsequent native sampling, not a captured partially consumed
sampler window. Eligibility uses diffuse/reflection flags; it is not an arbitrary
material GPU capability classifier.

Legacy deferred-node and scalar Cryptomatte pointers in Subpixel are not consumed
or initialized by this bundled beauty path. They are neither inspected nor
serialized. On restore they are cleared. The native handle/AOV checks are separate.
Hit/intersection data and volume results are also not carried across: the next
native traversal/volume evaluation initializes those fields. This does not
establish volume, glass-medium, deep, Cryptomatte or custom-AOV compatibility.

## Validation and limits

The native runner compares an unchanged XPU runtime with the disabled candidate,
immediate reconstruction, deferred reconstruction, poisoned original ray
storage, and a throughput sentinel. The original-allocation poison happens only
after successful capture and before release, with the excluded handles set to null.
It tests that restoration does not depend on original pool contents.

The final fixture includes a sphere and ground receiving indirect illumination.
The sentinel must differ materially from the *unperturbed deferred* image, not
merely from the baseline: queue ordering can itself produce tiny float differences.
An early sphere-only check was insufficient to establish that sentinel proof and
is not used as evidence of image contribution. The initial explicit beauty/AOV
outputs also caused the strict schema gate to bypass restoration; that run is
retained locally as an unexercised diagnostic, not a successful restoration test.

Immediate one-worker reconstruction requires exact float RGBA agreement. Deferred
and multiworker comparison use the previously declared 1e-6 absolute/relative
bound because queue order can change accumulation order. The runner also checks
actual XPU execution, capture/restore/cancel counts, bounds, source/runtime hashes,
raw EXR data and scene identity. There is no claim of bitwise deterministic
multiworker accumulation or acceleration.

Reproduction uses new isolated output directories:

```powershell
python tools/xpu2_native_path_build.py --source <shared-source-read-only> --base test-results/xpu2-origin-build --output test-results/native-path-build-new
python tools/xpu2_native_path_probe.py --build test-results/native-path-build-new --reference test-results/xpu2-origin-build/control --output test-results/native-path-one-new
python tools/xpu2_native_path_probe.py --build test-results/native-path-build-new --reference test-results/xpu2-origin-build/control --output test-results/native-path-four-new --threads 4 --diagnostic
python tools/xpu2_native_path_probe.py --build test-results/native-path-build-new --reference test-results/xpu2-origin-build/control --output test-results/native-path-adaptive-new --adaptive
python tools/xpu2_native_path_cancel.py --build test-results/native-path-build-new --reference test-results/xpu2-origin-build/control --baseline test-results/native-path-one-new --output test-results/native-path-cancel-new
```

## Ordering regression found during implementation

Deferring only until ordinary ray submission or XPU queue flush failed on the
indirect-light fixture: immediate reconstruction was exact, but deferred RGB
errors reached 0.06244. Preserving child batch sizes alone was insufficient.
Draining before the other native queue submissions restored exact one-worker
agreement, including the poisoned-allocation run. Thus changing queue order is
not assumed to be a harmless accumulation-rounding change. No tolerance was
increased to accept the failed candidates.

The successful boundary is deliberately short: its measured one-worker peak was
72 retained paths. Longer GPU waits need an explicit ordering/dependency contract
before they can use this adapter. Current capture occurs after native shading
has already constructed child rays, not before Lambert evaluation.

## Measured results (2026-10-18)

Evidence: [native-path-restoration-20261018.json](native-path-restoration-20261018.json).
The final candidate is an isolated relink with five copied native sources
recompiled against retained build inputs, not a clean rebuild of all dependencies.

- **One worker, fixed samples:** disabled, immediate, deferred and poisoned-original
  images match unchanged XPU exactly in float RGBA. Each restoration case resumed
  1,632,493 child paths, with zero outstanding at frame end. The throughput
  sentinel changed 31,080 pixels, maximum RGB difference 0.31827.
- **Adaptive bypass:** all six cases completed; every candidate image matches
  unchanged XPU exactly. All restoration attempts used the native fallback.
- **Persistent cancellation/reload:** unchanged persistent XPU, a fresh candidate,
  and a cancelled/reloaded candidate match exactly. Each completed candidate
  restored 6,470 child paths. The old frame was cancelled before completion;
  both frame epochs closed with zero outstanding paths. This run drained its
  captured paths before teardown, so it does not prove disposal of a deliberately
  held pending packet.
- **Four workers:** every render completed and all admitted paths were accounted
  for, but the image acceptance gate remains **failed**. Repeating unchanged XPU
  itself changed RGB by up to 0.05635; disabled and enabled candidate comparisons
  also exceeded 1e-6. These are recorded differences, not certification. The
  diagnostic option completes the matrix without converting failures to passes.

Cancellation initially exposed controlling-thread cleanup calls using worker TLS.
The adapter now permits atomic pending queries from that thread but never touches
another worker's vectors or native pools. Progressive phases can also use a new
physical worker; such submissions retain the original path rather than migrating
owned state. This explains the smaller restored count in persistent sessions.
Multiple simultaneous RenderContexts are unsupported by this single-frame adapter.

The cancellation runner compares like-for-like persistent progressive scheduling.
A previous comparison against a batch-rendered reference was invalid: scheduling
changed image samples even with the same scene. That failed local diagnostic is
not used to claim old-frame contamination or successful restart parity.

## Next integration

Establish ordered completion barriers for native queues, then move the supported
Lambert preparation boundary earlier and connect its GPU results to native
child-path construction. Preserve matching shadow/direct-light work and sampler
state; do not substitute arbitrary asynchronous results at this tested boundary. The existing owned dispatcher and this native restoration
adapter are separate components until that connection is implemented and tested.
Arbitrary shading paths, CPU migration, adaptive completion barriers and other
native resource ownership remain unfinished. XPU and the installed kit are unchanged.
