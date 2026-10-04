# MoonRayForModo 0.3.8

Target: Modo 16.1v9, native Windows x64. The native scalar/vector map code compiles.
Python/XML syntax checks are not rendering tests. No automated, render or Modo UI
tests were run, following the user's instruction. This is a development release.

## Implemented

- MaterialX NodeDefs inherit input types, defaults and outputs with cycle/depth
  checks. Explicit versions and unambiguous default versions select the interface.
  Included documents retain inherited color-space annotations. Empty image paths
  keep their default-color behavior. Standard Surface remains a native lowering
  instead of expanding into unsupported closure nodes.
- Standard Surface specular rotation supports values or connected graphs;
  transmission extra roughness adds to specular roughness with a 0-1 clamp;
  grayscale opacity drives presence. Connected opacity uses luminance, since native
  presence is scalar. Authored colored opacity is rejected. Inactive default fields
  no longer prevent importing a stock definition. Non-neutral unsupported lobes
  still raise explicit errors, rather than claiming complete Standard Surface parity.
- Standard Surface subsurface weight builds a native DwaLayerMaterial with a
  scattering foreground, preserving connected radius, scale and color. RGB radii
  are normalized into scattering color and scalar radius. MoonRay uses its own
  BSSRDF; anisotropic scattering remains unsupported.
- Normal maps reverse their tangent direction on alternate mirrored tiles, including
  negative UV coordinates, before affine basis correction. Scalar and vector shader
  paths share the rule. Multiple tangent UV sets remain a separate limitation.
- Environment image layers use alpha as coverage exactly once. Filtering uses
  associated RGB and alpha together. Alpha-only images are supported as data, with
  layer corrections. Transparent top layers no longer discard underlying layers.
  Environment stack order follows the same sibling ordering as the Shader Tree.
- Lighting controls list individual environments as well as the all-environments
  shortcut. Explicit links deduplicate overlap. Native shader-group links can
  exclude individual environment identities without those lights being re-added.
  Native host group discovery still needs validation in Modo.
- Rotating/scaling affine instance motion emits one small RdlInstancerGeometry per
  transform with blurred node_xform, all referencing one shared mesh prototype.
  Translation-only motion retains the existing batched velocity path. Explicit
  no-sharing, per-object light restrictions and adaptive subdivision opt-outs can
  still expand meshes. This uses two shutter samples, not arbitrary rotation paths.

## Still not full parity

Remaining implementation includes arbitrary MaterialX closure/code implementations,
all Modo procedural and effect semantics, multiple normal/bump tangent UV sets,
complete projection derivatives, full native light-link and environment/fog behavior,
simultaneous Cryptomatte categories and volume coverage, and automatic conversion
of every asset format listed by the browser. Imported Standard Surface anisotropic subsurface,
colored specular, absorption depth and thin-film controls are not fully lowered.
Native MoonRay materials can expose capabilities unavailable in that importer.

Large-scene behavior, cancellation/recovery, color accuracy, SDK behavior and clean
installation still require runtime validation. They cannot be certified by compiling.

## Deferred scripts and host checks

`tests/test_compatibility_038.py` was written but not run. It covers inherited
NodeDefs, version errors and cycles, Standard Surface controls, shared motion scene
serialization, image alpha metadata and environment linking.

In Modo, compare transparent environment layers in both orders, RGBA versus RGB
images, alpha-only corrections, reflection/camera visibility and explicit light links.
Compare negative/positive mirrored normal UV tiles and animated instances across
scalar/vector/XPU. Confirm shared mesh motion preserves per-face material assignments,
Cryptomatte IDs and deformation. Check interruption while preprocessing environments.

References used during implementation:
- [MaterialX specification](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/documents/Specification/MaterialX.Specification.md)
- [Standard Surface definition](https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/libraries/bxdf/standard_surface.mtlx)
- [OpenImageIO image metadata serialization](https://github.com/AcademySoftwareFoundation/OpenImageIO/blob/main/src/libOpenImageIO/formatspec.cpp)
- Bundled MoonRay RdlInstancerGeometry and InstanceProceduralLeaf source.
