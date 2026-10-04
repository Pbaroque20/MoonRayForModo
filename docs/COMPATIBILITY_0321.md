# 0.3.21: compatibility extensions, not full parity

## Implemented

- Native RdlInstancerGeometry xform_list_close holds a second affine transform
  array. One instancer shares the original prototype for rotating/scaling samples;
  per-instance identities and attributes remain separate. The extension uses the
  existing renderer transform-motion path. Two shutter samples only: it does not
  recover arbitrary intermediate animation or resolve topology changes. The build
  patch is repeatable and both geometry binaries are hash-gated at runtime.
  Older runtimes keep the previous one-instancer-per-transform fallback.
- Graph normalmap nodes offer connected-image, explicit UV, or primary basis.
  Each explicit basis has its own named UV, rotation (degrees), scale and offset.
  These feed existing scalar/vector named-UV derivatives. A direct texcoord node
  connected to an image can supply the automatic basis too. This does not provide
  analytic derivatives through arbitrary coordinate graphs or change every native
  ImageNormalMap/projection shader. Explicit basis transforms must match the image
  coordinates; they do not themselves transform image sampling.
- Every indexed asset extension has an action. OBJ/FBX/LXO/ABC/USD/USDA/USDC use
  Modo scene readers in import mode; missing readers are reported. Images become
  clips (codec support remains host-dependent); LUTs update the scene display LUT;
  VDBs create a locator with MoonRay density-grid controls; MaterialX chooses a
  named surface material and creates an override above the selected material or
  inside its mask. Presets/bundles and RDL keep their existing importers. This is
  dispatch coverage, not a promise that Modo reads every variant of every format.
- MaterialX graph-defined implementations select MoonRay-targeted graphs before
  generic graphs and ignore other-target implementations; ambiguous definitions
  are rejected. Graph / Inspect MaterialX support reports translation per named
  material. External source implementations are listed, never executed. No
  arbitrary BSDF/closure/code-generation support is claimed.
- MoonShine Material Override appears at the root of the native Shader Tree
  Add Layer list. Both dedicated creation commands use the source material's
  reversed child order to place it above that material. The visible name includes
  the complete layer name. Its dedicated pane has only Enable Override and Edit
  Material Graph. Existing standard-material controls remain compatible.

## Validation state

Native build and source/XML parsing completed. No unit, render, or host tests
were executed, per the user's explicit instruction. New runtime staged separately
as runtime/xpu-compatibility-0321. tests/test_compatibility_0321.py contains deferred
checks for routing, shared motion, independent normals, MaterialX target choice,
runtime capability tampering and portable override state.

tools/production_validation.py requires --runtime and --output. Without --run it
only writes a report plan. With explicit --run it performs the selected standalone
cases: unit checks, runtime hashes, large synthetic shared-instance renders in
Scalar/Vector/XPU, forced process cancellation and restart, and checkpoint/resume.
It requires actual XPU log confirmation rather than accepting CPU fallback. The
script preserves logs and EXR statistics; it does not certify visual equivalence.
The test process PATH is restricted to the runtime and Windows System32; this is
not equivalent to another machine. No second machine is available.

## Still incomplete

- Arbitrary MaterialX closures, external source implementations, all standard
  nodes/data types, units, target libraries and render equivalence.
- Exact native Modo procedural/effect semantics, all light-link rules, and
  arbitrary environment graphs.
- Complete analytic projection derivatives and tangent bases through every
  procedural coordinate graph/native normal-map shader.
- Simultaneous object/material/asset Cryptomatte buffers and volume coverage.
- Clean-machine validation, real large production scenes, host-side cancellation
  during capture, full recovery and independent OCIO/LUT reference comparisons.

These remain engineering and validation work, not completed by this release.
