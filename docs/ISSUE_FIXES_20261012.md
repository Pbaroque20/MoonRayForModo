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
