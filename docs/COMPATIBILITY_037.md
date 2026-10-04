# MoonRayForModo 0.3.7

Target: Modo 16.1v9, native Windows x64. Native compilation completed; automated,
rendering and Modo UI tests were intentionally not run. The installed development
build preserves the preceding kit and runtime for rollback.

## Implemented in this release

- Persistent previews publish immutable float RGB through a Windows shared-memory
  mailbox, with process/generation checks, acknowledgment and a five-second stale
  publication timeout. Publications are limited to 64 MiB each. Larger images use
  the existing file path. Snapshot cadence is 250 ms, subject to renderer readiness.
- Standard raw, sRGB and Reinhard display conversion runs in a native worker off
  the UI thread. Exposure and supported cached AOV changes do not restart rendering.
  OCIO, LUTs and diagnostic views not handled by the helper retain file conversion.
  Cached progressive AOV payloads are capped at 128 MiB, plus the displayed/in-flight
  frame and conversion storage. Completed EXR output remains unchanged.
- Progressive snapshots supply weight, heat and odd buffers when required by a
  selected render output. Deep and Cryptomatte images still require completed output.
- Asset Library > Save graph bundle collects native material parameters, supported
  node graphs/MaterialX overrides, referenced materials and original texture/UDIM
  files. Assignment validates checksums and paths before creating materials and is
  an undoable command. Scene camera/projector references are rejected. External
  Modo Shader Tree layers and animated channels are not captured in these bundles.
- Normal/bump UV locators support affine rotation, offset, scale and negative scale;
  normal directions are corrected for the transformed tangent frame. Layers on a
  material must share a normal/bump UV set; incompatible layers report a warning.
- Supported MaterialX image nodes add periodic, clamp, mirror and constant addressing,
  default color, and an empty-filename default. Nonperiodic UDIM and non-linear filter
  requests are rejected rather than silently approximated. This does not enable
  arbitrary MaterialX implementations or four-component graphs.
- File-backed points/strands are captured at shutter endpoints. Optional JSON `ids`
  identify each point or strand and reorder samples consistently. Missing, duplicate
  or changing IDs fail with an explicit message. Birth/death topology still needs
  the existing freeze or velocity policy. VDB sequences retain frame-time density
  and use velocity grids for density motion, with sampled owner transforms.

## Work still required for full compatibility

Full arbitrary MaterialX graphs; remaining Modo procedural/effect semantics;
multiple simultaneous normal-map tangent bases and complete projection derivatives;
all native Modo light-link and environment graph behavior; shared rotating/scaling
instance motion without expansion; simultaneous Cryptomatte categories and volume
coverage; automatic import of every indexed asset format; and production validation
of large scenes, cancellation, recovery, color and clean-machine installation.

These are remaining implementation or validation tasks, not completed features.
See earlier compatibility notes for the limitations of existing features.

## Deferred verification

`tests/test_compatibility_037.py` covers affine coordinates, point/strand identity
reordering, malformed shared-image packets, portable graph asset relocation and
checksum rejection. It was written but not run. Before production use, verify:

1. Compare scalar/vector/XPU image orientation and colors with completed EXR output.
2. Change exposure/AOVs rapidly during rendering; cancel and restart; close the panel
   during conversion; confirm old generations never replace the new scene.
3. Compare rotated/negative-scale normal maps and bump maps against Modo, including
   seams and mirrored image tiling. Image tiling mirroring is not yet a separately
   corrected tangent basis.
4. Save/reload a bundle on another asset path and undo its assignment in Modo.
5. Render shuffled-ID strand/point sequences with shutter blur and VDB velocity.
6. Verify OCIO/LUT file fallback and views larger than the shared-image size cap.
