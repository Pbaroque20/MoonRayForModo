# 0.3.26 implementation status

## Installed Python/UI changes

The graph material thumbnail now uses software Qt painting; the main dockable viewer remains OpenGL. Preview shutdown detaches UI callbacks before stopping native processes. Long-running conversion workers retain their inputs and Qt ownership until the thread has fully exited. Refresh cannot recursively start another capture. Runtime crash resolution is not confirmed: no host tests were run.

MaterialX adds position and normal inputs, explicit object/world point/vector/normal transforms, geometric-property reads with defaults, RGB/HSV conversion, vector2 images, and supported defaultgeomprop connections. NodeDef expansion preserves unit/color-space metadata. Arbitrary external shader implementations, closure graphs, four-component data and all geometric spaces are still not supported. These additions follow the official MaterialX stdlib definitions: https://raw.githubusercontent.com/AcademySoftwareFoundation/MaterialX/main/libraries/stdlib/stdlib_defs.mtlx

## Native candidate (not activated by this installation)

`runtime/xpu-compatibility-0326-candidate` contains the compiled simultaneous surface Cryptomatte implementation. Object, material and asset IDs accumulate and rank independently; the vector ray record retains its 64-byte allocation bound. Each output uses a separate EXR part and corresponding manifest. Scalar, vector/XPU and presence accumulation forward all category IDs. Checkpoint loading resets the selected category without clearing previously restored categories. Shared instances override object/asset identities and inherit material identity from prototype faces. Each configured category is available as a cached preview buffer.

The exporter checks hashes of the matching scene-schema, integration and output libraries before enabling multiple categories. The installed 0.3.24 native runtime remains selected until candidate validation. The candidate has compiled; it has NOT been render-tested, visually verified, or certified for production. Fixed Cryptomatte channel names remain scoped to their EXR parts; downstream multipart-reader compatibility needs verification.

Volume Cryptomatte coverage is NOT implemented. Multi-category scenes containing VDB volumes fail explicitly. This update does not claim full Modo parity or arbitrary MaterialX support.

## Deferred checks

- `tests/test_compatibility_0326.py`: export parts, metadata, instances, runtime/volume guards and MaterialX graph translation.
- `tests/test_preview_lifetime_0326.py`: Qt thread/input lifetime and software graph thumbnail. Requires compatible PySide2; not a host-crash certification.
- `tools/validate_crypto_categories.py --runtime runtime/xpu-compatibility-0326-candidate --output test-results/crypto-0326`: prepares fixtures and a report, without rendering. Add `--run` explicitly to execute scalar/vector/XPU checks. Process/EXR structure checks do not establish pixel-coverage equivalence; review the generated multi- and single-category images. Presence, motion and checkpoint equivalence need additional review.

Still required: volume transmittance-weighted matte integration, complete MaterialX execution, remaining Modo procedural/mask/light/environment semantics, multi-tangent derivatives, production-scale host/renderer/cancellation/recovery/color validation and clean-machine installation validation.
