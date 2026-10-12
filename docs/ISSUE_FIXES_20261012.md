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
- `tools/check_release_package.py`: **passed** on the three 0.3.51.3 release archives with `--no-render`: 10 scenes and 86 indexed assets discovered in the fresh installation. No renders or library-window interaction were performed.

#72 still needs real renderer-process/GPU-memory verification; #51 has headless installation/discovery coverage, not a visual library-window check. No claim of full production validation is made.

## Remaining priorities

- **#62, #74 and #73:** restart/engine state, Shader Cast Shadows, and probes for the new engine controls overlap the other chat's work. Avoid duplicate changes; compare its final commits before closing the reports.
- **#63:** the source/patch mismatch is reported fixed in 8671e4f. Packaging and publishing the new runtime remains a separate step; these Python fixes do not require a native runtime rebuild.
- **#65, #66, #60:** remaining transient dark tiles and the cost/accuracy of stopping a render need runtime investigation and image comparisons. No verified fix is claimed here.
- **#19, #43, #49, #53, #57, #67, #69:** several reports require host interaction, reproduction, or another machine rather than a speculative code change.
- Material/lighting parity, motion blur, volumes, import, display filters and distributed rendering remain substantial independent issues; this pass does not claim to resolve the whole backlog.
