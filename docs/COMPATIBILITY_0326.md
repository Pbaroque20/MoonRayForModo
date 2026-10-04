# 0.3.26 implementation status

## Installed Python/UI changes

The graph material thumbnail now uses software Qt painting; the main dockable viewer remains OpenGL. Preview shutdown detaches UI callbacks before stopping native processes. Long-running conversion workers retain their inputs and Qt ownership until the thread has fully exited. Refresh cannot recursively start another capture. Two standalone Qt lifetime checks passed using Modo 16.1v9's bundled Python/Qt libraries on 2026-10-04. Runtime crash resolution inside Modo is not confirmed: no host sessions were launched.

MaterialX adds position and normal inputs, explicit object/world point/vector/normal transforms, geometric-property reads with defaults, RGB/HSV conversion, vector2 images, and supported defaultgeomprop connections. NodeDef expansion preserves unit/color-space metadata. Arbitrary external shader implementations, closure graphs, four-component data and all geometric spaces are still not supported. These additions follow the official MaterialX stdlib definitions: https://raw.githubusercontent.com/AcademySoftwareFoundation/MaterialX/main/libraries/stdlib/stdlib_defs.mtlx

## Native candidate (not activated by this installation)

`runtime/xpu-compatibility-0326-candidate` contains the compiled simultaneous surface Cryptomatte implementation. Object, material and asset IDs accumulate and rank independently; the vector ray record retains its 64-byte allocation bound. Each output uses a separate EXR part and corresponding manifest. Scalar, vector/XPU and presence accumulation forward all category IDs. Checkpoint loading resets the selected category without clearing previously restored categories. Shared instances override object/asset identities and inherit material identity from prototype faces. Each configured category is available as a cached preview buffer.

The exporter checks hashes of the matching scene-schema, integration and output libraries before enabling multiple categories. The installed 0.3.24 native runtime remains selected until candidate validation. The candidate has compiled and passed the bounded scalar/vector/XPU surface-category checks described below. It is not certified for production, and remains separate from the installed runtime. Fixed Cryptomatte channel names remain scoped to their EXR parts; downstream multipart-reader compatibility needs verification.

Volume Cryptomatte coverage is NOT implemented. Multi-category scenes containing VDB volumes fail explicitly. This update does not claim full Modo parity or arbitrary MaterialX support.

## Candidate checks — 2026-10-04

The checks found and fixed four defects: missing material/asset IDs at shading intersections; missing checkpoint support buffers; a null-cache access in synchronous checkpoint writing; and unnamed multipart EXR parts that made checkpoint reading fail and silently restart rendering. Resume validation now rejects logged errors and requires confirmation that saved samples were restored.

- Six exporter/MaterialX tests passed in `tests/test_compatibility_0326.py`.
- Two Qt checks passed in `tests/test_preview_lifetime_0326.py`, using Modo 16.1v9's bundled Qt 5.15.2 offscreen. Closing during conversion preserves worker inputs until exit; graph thumbnails use a software widget. This is not a host-crash certification.
- `tools/validate_crypto_categories.py` and `tools/check_crypto_coverage.py` passed opaque, partial-opacity, shared-instance and rotating/scaling-instance scenarios in scalar, vector and XPU. Each scenario renders all categories together and separately. Pixel IDs, manifests, category aggregation and coverage were checked at a 1e-6 tolerance; GPU activation was required for XPU cases. The final rebuilt candidate also passed the opaque matrix again.
- `tools/validate_crypto_resume.py` passed nine category comparisons across scalar/vector/XPU: stop at four samples, restore the checkpoint, complete sixteen samples, and compare against uninterrupted rendering. Logs confirm restoration of nonzero saved samples. Maximum coverage difference was 1.20e-7. This controlled stop does not test power loss or interruption during file writing.
- The wider Python suite remains **not clean: 150 tests, 123 passed, 10 failed, 17 skipped**. Failures concern Windows path aliases, tile-order expectations, older material/assignment expectations, layered absorption/opacity and instance-motion expectations. They require triage; none have been removed or weakened to obtain a passing result. The separately executed Qt checks are reported above.

[Machine-readable results and remaining failures](validation-0326.json) include the final runtime hashes. Detailed images/logs remain under `test-results/crypto-0326-*`. The candidate has not been installed or marked generally render-validated.

To repeat category checks, run `tools/validate_crypto_categories.py --runtime runtime/xpu-compatibility-0326-candidate --output <empty-directory> --scenario <opaque|presence|instances|motion> --run`, then run `tools/check_crypto_coverage.py <directory>` with the toolchain Python (OpenImageIO required). Resume checks use that Python with `tools/validate_crypto_resume.py --runtime runtime/xpu-compatibility-0326-candidate --output <new-directory> --run`.

Still required: volume transmittance-weighted matte integration, complete MaterialX execution, remaining Modo procedural/mask/light/environment semantics, multi-tangent derivatives, production-scale host/renderer/cancellation/recovery/color validation and clean-machine installation validation.
