# GitHub issue pass — 12 October 2026

Based on MoonLightIPR commit 60c0578 and the 58 open issues retrieved on 12 October. Work is isolated on `codex/github-issues`; another chat owns the changes to panel.py, evaluated.py and probe_cl_geometry.py.

## Implemented in this branch

- **#72 — Idle GPU memory.** Both preview sessions release their process after five idle minutes by default. Preferences offers Never, 1, 5, 15 or 30 minutes, plus Release Idle Renderer Memory Now. The timeout starts after completion (or MoonLightIPR pause), is canceled by a new submission, and does not interrupt pending work. Cached images remain; a subsequent render reloads the scene. This is an idle timeout, not an operating-system memory-pressure monitor. A buffer not previously cached may require rendering again after release.
- **#41 — Add Item light defaults.** Modo's newborn-item callback now applies the same starting values as MoonRay's own menu, including the current light-intensity preference. Existing scenes and duplicated items retain their values. The Modo 16.1v9 check exposed null-original handling and a premature evaluated-channel read in the initial callback. The follow-up uses the newborn item's setup channel writer directly; six direct-light types and environment defaults now pass in the isolated host check.
- **#51 — Content installation checks.** The release checker now merges kit, runtime and content ZIPs into a fresh folder and uses the installed asset-library code to discover the example scenes, paired RDLB files and licenses. Existing folders are never deleted, and archive members are validated before extraction. `--no-render` performs packaging/discovery checks only. This is headless library discovery; it does not establish that the library window renders correctly in Modo.

## Verification run

The user authorized tests on 12 October. Follow-up checks used a separate checkout and a disposable Modo 16.1v9 profile; the installed kit and other chat's files were not changed.

- `tools/check_idle_release.py`: **6 passed**, covering timeout, disabled timeout, manual release, pending work, new submissions, and completion-handler reentrancy. Uses a fake Qt timer; actual GPU memory recovery is not established by this check.
- `tools/probe_light_defaults.py`: **passed in Modo 16.1v9**. Mesh, Rect, Sphere, Spot, Disk and Cylinder lights created through the native scene API picked up intensity 37; duplicates retained authored intensity 8. Environment starting values also passed. This is a creation/duplication check, not a rendered-image or save/reload check. The probe writes to `MOONRAY_TEST_RESULTS/light-defaults`, or a temporary test folder if unset, and closes the isolated host.
- `tools/check_release_package.py`: **passed** on the three 0.3.51.3 release archives with `--no-render`: 10 scenes and 86 indexed assets discovered in the fresh installation. No renders were performed in that check.

- `tools/probe_content_library.py`: **passed in Modo 16.1v9**, loading a copy of the kit formed from all three 0.3.51.3 archives. The library displayed 76 usable assets and 16 RDL scenes (the content scenes plus kit examples), with paired RDLB files deduplicated. Category selection, search clearing, selected thumbnail and RDL action-button state passed. The saved library-window screenshot was inspected. No scene import or rendering was invoked.

Reproduce the host check with `MOONRAY_TEST_RESULTS` set to an output folder and `MOONRAY_TEST_KIT` set to the absolute `test-results/PROFILE/Configs/MoonRayForModo` path, then run `tools/launch_gui_probe.py probe_content_library.py --kit-source UNPACKED_KIT --profile PROFILE --wait --timeout 120`. Use a fresh profile. Read `content-library/report.json`: a normal Modo exit alone does not establish probe success.

- `tools/check_idle_sessions.py`: **passed with real MoonRay XPU and MoonLightIPR processes**, three 64x64 renders per engine. Each returned a 49,152-byte progressive RGB frame. Manual release and an accelerated idle timeout exited the child; subsequent submissions launched distinct processes and completed. Pending work refused release, no failure signal fired, and MoonRay logged successful GPU setup. Used `runtime/steady-0351-tiles` and `build/moonlightipr/stage` from the main project. The test ages the idle timestamp instead of waiting one minute; the separate timer unit checks cover elapsed-time behavior.

Run `tools/check_idle_sessions.py --moonray RUNTIME --moonlight MOONLIGHT_STAGE` with a PySide2-capable Python. Reports and native logs default to `test-results/idle-sessions`. This validates actual process teardown/restart, not a measurement of the driver's VRAM accounting, automatic memory-pressure detection, or the preview's cached-image UI. Those are not claimed. #51 has both headless installation/discovery and host library-window coverage. No claim of full production validation is made.

## Remaining priorities

- **#62, #74 and #73:** restart/engine state, Shader Cast Shadows, and probes for the new engine controls overlap the other chat's work. Avoid duplicate changes; compare its final commits before closing the reports.
- **#63:** the source/patch mismatch is reported fixed in 8671e4f. Packaging and publishing the new runtime remains a separate step; these Python fixes do not require a native runtime rebuild.
- **#65, #66, #60:** remaining transient dark tiles and the cost/accuracy of stopping a render need runtime investigation and image comparisons. No verified fix is claimed here.
- **#19, #43, #49, #53, #57, #67, #69:** several reports require host interaction, reproduction, or another machine rather than a speculative code change.
- Material/lighting parity, motion blur, volumes, import, display filters and distributed rendering remain substantial independent issues; this pass does not claim to resolve the whole backlog.

## Subsurface Neighbours dialog (#26)

`tools/probe_neighbours_dialog.py` passed in an isolated Modo 16.1v9 profile. It exercises the real `moonray.material.neighbours` command: mouse press/release toggles, accepting mesh IDs, restoring checks on reopen, canceling without changes, applying to multiple selected materials, and clearing the stored trace set. Modo exited normally after the probe.

Screenshot inspection found that Modo's host style hid the check indicators. The dialog now gives its list explicit empty/filled indicators; checked and unchecked states were visually inspected after the fix. No global Qt style is changed. The probe writes JSON and screenshots under `MOONRAY_TEST_RESULTS/neighbours-dialog`, or a temporary test directory when unset. Run through `tools/launch_gui_probe.py probe_neighbours_dialog.py --profile NEW_PROFILE --wait --timeout 120`.

This completes #26's remaining dialog check. Renderer comparison and MoonLightIPR support remain tracked in #45; incomplete imported sets remain in #52. No rendering-parity claim is made by this UI test.

## Material thumbnail precedence (#50, partial)

Saved materials now use sidecar images before falling back to a drawing. For `paint.moonmat.json`, `paint.moonmat.png` (or JPG/JPEG) takes priority over the simpler `paint.png` name. Graph bundles without a supplied image show a labelled Graph tile rather than a misleading plain ball. The selection pane explains the fallback and the expected thumbnail filename.

`tools/check_asset_thumbnails.py`: **6 passed** using real Qt image loading offscreen: exact sidecar, simple filename and precedence, graph sidecar, graph placeholder, corrupt-image fallback, and texture-image precedence. Fixtures are PNG-encoded; JPEG codec coverage is not claimed. No host UI launch or renderer change was needed. Automatic generation of rendered material thumbnails remains open in #50.

## Authored RDL mesh normals (#23, partial)

RDL imports now create an editable `RDL Normals` map for authored point or polygon-corner normals. Invalid lengths, nonfinite components and zero vectors produce an explicit warning. Normals requiring a baked shear/mirror transform remain omitted with a warning rather than being stored in the wrong coordinate space.

Validation: 12 focused RDL unit tests passed. `tools/probe_rdl_normals.py` imported two meshes in an isolated Modo 16.1v9 profile and read back every point/corner normal, including different normals at shared vertices. The host exited normally. This checks stored geometry data, not rendered-image equivalence. Motion, subdivision creases and baked-transform normals remain open under #23.

### Baked shear follow-up

Authored normals now survive orientation-preserving shears baked into imported vertices. The normal matrix uses the inverse transpose of the linear transform and normalizes the result; translation does not affect it. Matrix magnitudes are scaled before inversion to retain very small uniform transforms. Mirrored, singular or near-singular transforms still omit normals with an explicit warning.

All 16 focused RDL tests passed, including transformed-tangent perpendicularity, nonuniform scale, translation independence, tiny scale and unsupported transforms. The Modo 16.1v9 read-back probe passed all four meshes: point/corner maps with and without shear. Rendered-image equivalence, mirrored winding, shutter motion and creases are not covered or claimed.

### Reflection follow-up

Mirrored transforms now preserve authored normals as well. When baking a reflection into mesh points, the importer reverses polygon winding while keeping UVs and corner normals associated with their original vertex. Singular/near-singular transforms still omit normals with an explicit warning.

All 17 focused RDL tests passed. The isolated Modo 16.1v9 probe imported six meshes (point/corner normals, ordinary/sheared/mirrored), checked polygon vertex order and every UV/normal value, and exited normally. Shutter motion and subdivision creases remain unresolved under #23. No rendered-image equivalence claim is made.

## Fully sharp RDL subdivision creases (#23, partial)

Import plans validate crease/corner indices, topology and finite nonnegative weights. Fully sharp values (10 or higher) become editable Subdivision edge/corner weights of 1 on Catmull-Clark polygons. Semi-sharp values remain omitted with an explicit notice; their scale conversion is not established.

Twenty focused RDL tests passed. The isolated Modo 16.1v9 probe read back edge/corner weights and Catmull-Clark polygon type and exited normally. An initial candidate crashed when writing edges in the topology-creation edit; the final implementation commits polygons before opening a second edit for edge weights. This failure is resolved in the passing candidate, not hidden. No rendered surface comparison is claimed.

## MeshLight RDL bindings and sets (#52, partial)

MeshLight membership in light and shadow sets now resolves to its emitting mesh rather than being dropped. The importer retains emitter geometry even without a surface material and converts the MeshLight geometry reference to the imported mesh ID. Previously the generic MoonRay-item reference filter discarded that reference too.

All 21 focused RDL tests passed. An isolated Modo 16.1v9 import verified the emitter exists without a material assignment, the MeshLight geometry channel points to it, and receiver light/shadow exclusions contain its ID. Host shutdown was normal. No rendered-lighting comparison was performed. Per-part sets, light-filter sets and assignments on native MoonRay shapes remain open under #52.

## Native MoonRay shape assignments (#52, partial)

Imported native shapes now retain light and shadow-exclusion sets. Exported shapes, volume-only shapes and their primitive-attribute holders use their per-object light/shadow assignments instead of always using the shared light set.

All 22 focused RDL tests passed. An isolated Modo 16.1v9 probe verified a BoxGeometry receiver retains its MeshLight links and exclusions and exited normally. Export assertions cover assignment construction; rendered-lighting equivalence is not claimed. Per-part sets, light-filter sets and native shapes as shadow-receiver targets remain open.

### Native shadow-receiver targets

Native MoonRay shapes can now be retained as excluded shadow-receiver targets during RDL import and scene export. Export uses the actual geometry type, including mesh-converted volume shapes and attribute holder instancers.

Validation: 25 RDL tests and 19 core exporter tests passed; isolated Modo 16.1v9 import/read-back retained a SphereGeometry target. The first host probe omitted the target material assignment and correctly skipped that shape; after correcting the fixture, the check passed. No rendered-shadow comparison is claimed. Per-part and light-filter sets remain open in #52.

### Imported light-filter sets (#52, partial)

RDL LightFilterSet assignments now retain supported filter items and store their IDs on the imported geometry. Meshes and native shapes export the set in their layer assignment. Missing/unsupported imported filters are named in warnings; deleted filter targets cause an explicit export error.

Validation: 27 RDL tests, 19 core exporter tests, 32 CPU-feature tests, 8 production tests, and isolated Modo 16.1v9 import/read-back passed. `tools/check_rdl_link_roundtrip.py RUNTIME` also passed: MoonRay's native reader accepted the exported file and read back all four light/shadow/receiver/filter sets. This is scene-reader validation, not a rendered-lighting comparison. Different sets on individual parts remain open.

### Per-part mesh assignments (#52)

Differently lit/filtered/shadowed RdlMeshGeometry parts now receive distinct imported material layers, even when they share one source shader. Mesh vertices and faces stay intact. Assignment metadata survives direct and evaluated Modo capture; explicit object links retain precedence on export. Non-mesh per-part assignments still report the unsupported case.

Validation: 28 RDL, 19 core, 32 CPU-feature and 8 production unit checks passed. The isolated Modo probe imported two faces sharing a shader with distinct lights and retained their filter/shadow differences. Both direct and evaluated exports passed native MoonRay-reader assignment checks. The first evaluated run lacked the adapter in the isolated kit; copying the installed adapter into the test kit enabled the successful rerun. No installed kit changes or rendered-image equivalence are claimed.

## Mesh emitter camera appearance (#42, native MoonRay)

Objects/geometry now offers a native MoonRay camera-appearance choice: existing emitter settings, emitter, surface only, or hidden while retaining illumination. This works for object emitters and MeshLight items. Hidden surfaces still retain their other visibility and shadow settings. MoonLightIPR support remains open because its exporter/kernel are owned by the concurrent work.

Validation: 20 core, 32 CPU-feature and 8 production tests passed. Native MoonRay reader checks passed all four modes, including unchanged enabled light/intensity and camera visibility. The isolated Modo control saved and restored the hidden choice. Rendered-image comparison is not claimed.
