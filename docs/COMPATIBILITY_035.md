# 0.3.5 compatibility development update

Target: Modo 16.1v9 on native Windows. Native C++/ISPC compilation and Python
syntax inspection completed. Automated tests, render checks and Modo UI checks
were deliberately not run. The kit uses the existing geometry adapter and a
separate runtime, with installer rollback backups.

## Implemented in this update

- Translated Modo/MoonShine materials composite their parameter channels through
  nested group opacity, masks, inversion and blend modes before shading. Scalar
  channels participate alongside colors. Contradictory nested material tags select
  nothing. Native shader graphs continue to use BSDF layering.
- Surface/environment image gamma, brightness and contrast; procedural bias/gain
  before color interpolation; soft light, color dodge and color burn blending.
  Existing UV transforms, projections and node catalog remain available. Projector
  camera/locator sockets can reference Modo items from the node property editor.
- Local MaterialX include libraries, file prefixes, named multi-output graph
  implementations, interface expansion, component extraction/swizzling, combining,
  clamps, constant graph outputs and indexed UV sets. Standard-surface sheen and
  coat-color/normal inputs have Dwa approximations. Includes reject cycles,
  conflicting definitions, document entities and oversized libraries.
- Standard-material F0 maps drive reflection IOR; transmission IOR remains
  independent. Glass dispersion uses an Abbe approximation of Modo's violet/red
  index span. Translated layered interiors composite transmission color and inverse
  attenuation distance with their masks, then derive extinction. This is a single
  homogeneous interior, not overlapping nested media.
- Conservative incremental material and direct-transform captures, retaining
  geometry when safe. Structural and uncertain changes fall back to full capture.
  The selected supported AOV receives intermediate images without a scene restart;
  previously received progressive AOV images remain cached until scene replacement.
  Exposure, LUT and display transforms operate on cached linear images.
- Rod, barn-door, cookie, distance-color-ramp and VDB light filters with optional
  locator transforms. Portals can select one lighting environment in scenes with
  multiple environments. Existing explicit object light and shadow sets remain.
- Object, material or artist-assigned asset Cryptomatte categories; one category
  per render in this runtime. Shared instances carry instance IDs instead of
  expanding every prototype for Cryptomatte. Material IDs can vary per face.
  Object light-link/emitter overrides still expand affected instances as needed.
- Per-object changing-topology policy: strict error, frame-time geometry, or
  velocity blur for supplied point/strand velocities. These choices preserve
  frame-time membership; they do not integrate births/deaths within the shutter.
- Rec.709 or ACEScg/AP1 render primaries. Authored Modo texture/channel math remains
  Rec.709; color outputs, lights and environment maps convert at shading boundaries.
  Normals, positions, masks and IDs remain data. Saved EXRs retain working primaries;
  display conversion uses the working space of the actual cached image.
- Missing-clip relinking, old derived-texture cache maintenance, and frame-by-frame
  portable animation packaging. Each frame has asset hashes; a sequence manifest
  records completion, cancellation/failure and scene hashes. Assets are currently
  copied per frame. Live preview is locked during collection.

## Where to find the controls

Use Render Setup's scene controls for light filters, portal environment, object
Cryptomatte asset labels and changing-topology policy. Custom Outputs exposes the
Cryptomatte category. Input Color and Assets exposes working primaries and cache
maintenance. The System page provides missing-image relinking and animation
packaging. Projector references appear on compatible nodes in the node editor.

## Remaining compatibility limits

This release does not finish all previously requested parity work:

- Arbitrary MaterialX code/shader implementations and all standard-library nodes
  are not supported. Only graphs expandable to supported nodes can render.
- Native BSDF graphs require explicit mix nodes for nontrivial group processing.
  Modo's independent Fresnel edge multipliers and every procedural algorithm are
  not exact MoonRay equivalents. Subsurface model/radius differences remain.
- Random locator offsets and transformed/multiple-basis normal or bump maps still
  need tangent/derivative work. Corner-baked projections require sufficient detail.
- Automatic translation of Modo's native shader/light item-group links is pending;
  enabled native links produce a warning to use explicit MoonRay Object controls.
- Intermediate images still travel through PFM files and the display converter.
  This is not direct shared-memory or GPU texture delivery. Heat/weight/odd/deep/
  Cryptomatte outputs are excluded from this progressive snapshot path.
- Cryptomatte volume coverage, multiple simultaneous categories, instance motion
  sharing and stable simulation-ID/lifetime integration remain incomplete.
- Color parity needs image comparison. Shader-internal spectral colors and VDB
  color grids must be considered separately; arbitrary working primaries are not
  offered. ACEScg support here is not an ACES certification claim.
- Sequence packages are render exports, not relinked editable LXO archives. OCIO
  dependencies must be resolvable locally. Runtime dependencies are not bundled
  into every frame package.

## Deferred checks

`tests/test_compatibility_035.py` adds focused offline checks for color matrix
round trips, blend behavior, MaterialX includes/outputs, group scopes, absorption,
Cryptomatte instance identities and changing-topology policies. These checks are
written but not run. Run them explicitly with:

    python -m unittest discover -s tests -p test_compatibility_035.py

Then use an isolated Modo 16.1v9 profile to compare nested groups against Modo,
edit camera/material/mesh transforms during IPR, switch AOVs during a long pass,
inspect matching object/material/asset mattes, and package two animated frames.
Check scalar/vector/XPU images separately; compilation cannot establish visual
or host-API correctness. No automated test opens or changes the user's Modo scene.

References: [DwaBaseMaterial](https://docs.openmoonray.org/user-reference/scene-objects/materials/dwa/DwaBaseMaterial/),
[MoonRay light filters](https://docs.openmoonray.org/user-reference/scene-objects/light-filters/),
[ACEScg primaries](https://docs.acescentral.com/encodings/acescg/).
