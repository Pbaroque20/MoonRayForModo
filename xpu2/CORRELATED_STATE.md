# Correlated native sampler and Lambert state

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

The diagnostic now captures the native ISPC BSDF sample and its nested Lambert
call together. This closes the earlier gap where the surface payload and shader
packet came from unrelated captures. It is still not a native path continuation.

## Capture contract

A shared diagnostic DLL holds a thread-local, eight-lane context. The integrator
sets it immediately before BsdfSampler_sample and clears it after the call.
The nested Lambert hook records its original SIMD lane and rejects random values
that differ from the integrator's draw. No native shading result is changed.

Each XCL1 record contains 28 metadata words, 24 shader-input words and eight native
output words. Metadata includes pixel/subpixel, sequence identity/hash, lobe seed,
sample count before/after the draw, total samples, lobe/sample indices, original
lane, light-filter sampling flag, position, throughput, time and footprint.
There are no retained pointers. The capture is restricted to two fixture pixels
and 1,024 records, with checked writes. It is a process-lifetime diagnostic,
not an unload-safe production service.

The ISPC sampler is distinct from the C++ cached AVX sampler tested earlier.
These counters and random words do not constitute a complete restorable native
sampler, BSDF, light set or integrator state.

## Validation

[Evidence](correlated-state-20261017.json) records frozen build inputs, hashes,
render results, captures, GPU observations and queue accounting.

- Four single-worker native XPU renders passed: control, disabled instrumentation,
  enabled capture and repeat. All instrumented RGBA images match the control bit
  for bit. The capture repeats bit for bit.
- Eight native events were recorded: four BSDF samples at each selected pixel.
  They match the prior surface fixture uniquely by identity, position and
  throughput. Their geometric normal and outgoing direction also agree exactly.
- The pre-shading normal and Lambert normal differ by small float changes.
  UsdPreviewSurface constructs a tangent frame and normalizes the transformed
  input normal before creating the lobe. An initial diagnostic incorrectly
  required these two stages to match. It now retains both separately, and the
  GPU receives the actual Lambert normal. This changes no image/GPU tolerance.
- Six real-GPU queue cases passed using these correlated events: pressure,
  missing-PTX fallback, restart, leased restart, ready restart and admission
  fallback. GPU direction, RGB, PDF and validity agree bit for bit with native
  outputs. A deliberately halved-RGB sentinel verifies delivered GPU results are
  consumed; this transport harness does not produce a final image.
- Owned sampler metadata survives caller-buffer reuse, reverse collection, four
  CPU readers and cancellation. Repeating the eight events fills stress packets;
  those repetitions are not extra image samples.

All 219 XPU2 unit tests passed, including five new capture-parser checks.
The earlier 15-render shading matrix was not rerun for this capture milestone.

The initial build also exposed retained library flags; the builder now preserves
their original ordering. Neither preliminary failure is presented as a pass.

## Remaining handoff

The mailbox still resumes immutable test payloads, not MoonRay paths. Native
light sampling, ownership of BSDF/attributes and other dependencies, CPU work-queue
resumption with valid TLS/arena state, child-ray construction and film/AOV
accounting still need an adapter. General materials and indirect/volume paths
are outside this fixture. Multithread bitwise image parity remains unresolved.

No production selector or installed runtime changed. This milestone makes no
render-speed or scene-loading claim.

## Reproduce

Use new output directories and the retained fixture/build inputs:

    python tools/xpu2_build_correlated_capture.py --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --pbr-build test-results/xpu2-surface-capture-build --shading-build test-results/xpu2-native-async-build --output test-results/correlated-build-new
    python tools/xpu2_correlated_capture_probe.py --build test-results/correlated-build-new --scene-reference test-results/xpu2-primary-state --surface-reference test-results/xpu2-surface-capture --output test-results/correlated-new
    python tools/xpu2_continuation_probe.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --correlated-capture test-results/correlated-new/capture/correlated.bin --output test-results/correlated-queue-new
    python -m unittest discover -s tests -p test_xpu2_correlated_state.py -v

## Native handoff follow-up

[DEFERRED_SHADING.md](DEFERRED_SHADING.md) moves GPU result collection out of
the Lambert call and past native CPU light evaluation. That adapter retains the
native stack until collection; whole-path suspension remains a separate step.
