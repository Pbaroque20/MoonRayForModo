# 0.3.23 compatibility and input safety

Implemented in this update:

- No assigned light group is distinct from an assigned empty group. Base Shader
  no longer reports the expected-one-group warning when no group is selected.
  Multiple connected groups are combined; nested groups retain cycle detection.
  This does not complete item-shader precedence or all Modo graph semantics.
- Metallic color and metallic edge color have explicit 0-1 component limits in
  material schemas. Editor edits and saved graph validation reject invalid values.
  Existing min/max metadata now applies to vector/color components, not just
  scalar fields. Connected metallic colors are bounded after working-space
  conversion. Generic map values and emission remain HDR. This is input hardening,
  not a confirmed diagnosis of the reported crash; no crash reproduction was run.
- MaterialX named separate2/separate3 outputs, tan, asin and atan2 are translated.
  rotate2d, rotate3d, saturation and distance translate to native map
  operations. Literal angles tagged as radians convert to degrees. Neutral image
  layer/sequence defaults no longer prevent imported standard image definitions.
  Non-default image layer/sequence controls still raise an explicit limitation.
- Independent automatic normal-map tangent bases follow affine graph scale,
  translation, rotate2d, swizzle and combine operations. Nonlinear operations and
  expressions mixing different UV sets are not falsely treated as affine.
- Deferred regression script: tests/test_compatibility_0323.py. Reference-image
  comparison: tools/validate_reference_images.py, requiring reference/actual paths,
  runtime and an empty output directory; only --run executes it. Images must
  already share linear working space, exposure and framing. RGB comparison does
  not certify alpha, color transforms, or renderer equivalence.

Status of the broader request:

- Arbitrary MaterialX source shaders, closures, unsupported types and native
  code generation remain unimplemented. These additions extend the translator.
- Exact Modo procedural/effect behavior, item-level linking precedence and full
  environment graphs remain incomplete.
- Analytic derivatives through nonlinear coordinate/projection graphs remain
  incomplete; named UV and affine tangent bases are implemented.
- Paired shared rotating/scaling instance transforms were built in 0.3.21;
  more than two shutter samples and production verification remain outstanding.
- Simultaneous Cryptomatte categories and volume coverage need renderer film,
  integrator and output changes; they are not enabled by this update.
- All indexed asset types have import routes. Host reader/codec availability
  still controls scene/image formats; arbitrary variants are not guaranteed.
- Production checks are prepared only, per user instruction. No runtime tests,
  host tests, clean-machine tests or visual validation have been performed here.
  A second clean Windows computer remains unavailable.

Sources: MaterialX standard node definitions at
https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/libraries/stdlib/stdlib_defs.mtlx
and the installed Modo 16.1v9 shader UI/channel definitions.
