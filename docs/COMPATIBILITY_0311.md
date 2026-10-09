# 0.3.11: interactive transfer and editable RDL import

This is an unverified development build. Native compilation and Python/XML syntax
are checked; no render or Modo tests have been run, as requested.

## Preview transfer and conversion

Progressive pixels use the existing shared-memory mailbox. A reusable isolated
`modo_display_stream.exe` now handles every display-kind path, including OCIO,
LUTs, depth, motion, position and sample-count views. RGB arrives by binary pipe;
RGBA returns by pipe. OIIO/OCIO libraries stay outside Modo's process. Config/LUT
file changes invalidate the processor. A 60-second watchdog terminates a stuck
conversion; failure is reported without restarting rendering. New runtimes no
longer encode temporary PFM/PNG files merely for color conversion. Older runtimes
retain their previous fallback converter.

Completed EXRs are still written, retained by the buffer cache, and decoded by
the helper directly into memory. These source outputs are intentional disk
artifacts. Denoising still uses its existing file-backed workflow. Progressive
image delivery can still fall back to PFM when shared-memory publication cannot
serve a frame. Shared frames are limited to 64 MiB RGB; file decoding to 512 MiB
RGB. This is not GPU zero-copy or a wholly file-free rendering pipeline. The small
AOV selector file remains; scene commands and scene payloads no longer need files
with the new runtime. Display changes may restart the lightweight display helper,
never MoonRay. Runtime latency/color correctness remain unverified.

## Scene updates

Named mappings transfer initial scenes, deltas and full reloads. Mappings stay
alive until the native APPLIED acknowledgment. An event-backed mapping carries
commands. Older runtimes retain their file protocol. The host still serializes
RDLA text in memory, with cached immutable geometry arrays. Scene text is bounded
to 256 MiB per mapping. Structural edits still reload the renderer context.

Changed ordinary meshes can be recaptured individually when there are no
instances, deformers, replicators, evaluated surfaces or extra geometry requiring
broader dependency handling. Unchanged mesh order and arrays are retained.
Material coordinate changes may still force a full capture. Camera/light/material
and supported transforms continue to reuse geometry. Additional channel schema
notifications invalidate stale caches.

The System option 'Periodically check for missed scene changes' controls the
15-second safety refresh. It defaults on because third-party providers may omit
notifications. Turning it off makes updates notification-driven, but does not
eliminate captures required by unsupported or structural changes. No universal
incremental dependency graph is claimed.

## Editable RDL scene import

> **Superseded by 0.3.50.1.** The importer was rewritten: it is at **MoonRay > Import MoonRay Scene (RDL)...**, keeps transforms and instances, brings in curves, MoonRay's own lights and other items, displacement, scene settings and outputs, and reads a scene kept as `scene.rdlb` and `scene.rdla` as one. See [What's new in 0.3.50.1](WHATS_NEW_0350.md). What follows describes the first importer.

Use MoonRay > Import RDL scene, choose .rdla or .rdlb, review the conversion report,
then Import editable objects. The asset library's Import action also accepts RDL.
MoonRay's own parser reads the source in a separate process. Generic .rdl is not
assumed to be RDLA. Missing DSOs/assets and parsing failures are reported.

Supported: embedded RdlMeshGeometry polygon/subdivision meshes, vertex or corner
UVs, material parts, native material/map graphs present in the plugin catalogs,
single-prototype matrix-list RdlInstancerGeometry expanded to editable meshes,
perspective/orthographic cameras and four direct light classes. Mesh transforms
are baked into editable points; material graphs are enabled in MoonShine.
Relative graph asset paths resolve from the RDL directory. Import is one undoable
command; host failures attempt cleanup of created items.

Not a lossless arbitrary RDL importer: external geometry procedurals, curves,
volumes, other lights/filters, animated samples, crease weights, authored normals,
per-instance attributes, displacement assignments, light linking, visibility sets,
render outputs and environment controls are not fully converted. Orthographic
framing and light shape/intensity need review. Unsupported features are reported.
Existing objects are preserved; selecting the imported render camera is intentional.

## Requested feature audit

- Direct progressive transfer/background display conversion: implemented for the
  paths above, with explicit failure handling; denoising and recovery fallbacks
  remain file based.
- Portable material graphs: referenced materials and graph textures are recursively
  bundled, checksummed and remapped. This update also handles filename arrays.
  External projector/camera references are rejected; native Modo Shader Tree
  texture layers outside graphs are explicitly excluded. Arbitrary Modo shaders
  are not portable through this format.
- Normal/bump UV transforms: Shader Tree named-UV derivatives and skew/mirror
  handling exist in scalar and vector code. This update corrects a directly
  connected image node's normal-map basis too. Arbitrary procedural coordinate
  graphs do not provide analytic derivatives; locator projections remain
  corner-interpolated. These broader cases are not claimed complete.
- MaterialX image addressing: periodic, clamp, mirror and constant modes exist.
  UDIM images currently require periodic addressing; non-linear filter types are
  rejected. Arbitrary MaterialX graphs remain unsupported.
- Stable point/strand IDs: explicit simulation IDs reorder shutter samples.
  Direct Modo points can now use an artist-selected ID weight map (unique exact
  integers within +/-16777216); curves can use a persistent four-character string
  tag supplied by their provider. Strict mode rejects missing IDs rather than
  trusting array positions. Providers without IDs require freeze/velocity or
  external geometry with IDs; native render-cache surfaces do not invent IDs.

Deferred checks: tests/test_compatibility_0311.py and the host/import checks in
that file. Existing remaining full-parity work is not completed by this release.


## MoonRay Widget material preview

The supplied six-part USD asset is bundled as mesh arrays, with subdivision and
face-varying UVs, converted to right-handed winding. Its ASWF Digital Assets
License v1.1 and source copyright are included with the asset; the plugin license
does not replace the asset license. Preview on MoonRay Widget in native material
properties, or Widget preview in the node editor, opens an isolated studio scene.
Render / Refresh reads the current unsaved draft and references without changing
the Modo scene. Base and stand can remain neutral or use the preview material.
This demonstrates native materials and graph inputs; external Shader Tree masks,
scene-dependent projections and hair strands are not recreated. The widget uses
its supplied UV layout (including coordinates outside 0–1). No render or UI test
was run, as requested. Deferred host check: open both editors, render a colored
material and image/normal graph, edit/refresh, then stop/close during rendering.
