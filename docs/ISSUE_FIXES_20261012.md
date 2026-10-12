# GitHub issue pass — 12 October 2026

Based on MoonLightIPR commit 60c0578 and the 58 open issues retrieved on 12 October. Work is isolated on `codex/github-issues`; another chat owns the changes to panel.py, evaluated.py and probe_cl_geometry.py.

## Implemented in this branch

- **#72 — Idle GPU memory.** Both preview sessions release their process after five idle minutes by default. Preferences offers Never, 1, 5, 15 or 30 minutes, plus Release Idle Renderer Memory Now. The timeout starts after completion (or MoonLightIPR pause), is canceled by a new submission, and does not interrupt pending work. Cached images remain; a subsequent render reloads the scene. This is an idle timeout, not an operating-system memory-pressure monitor. A buffer not previously cached may require rendering again after release.
- **#41 — Add Item light defaults.** Modo's newborn-item callback now applies the same starting values as MoonRay's own menu, including the current light-intensity preference. Existing scenes and duplicated items retain their values. The callback must be checked in Modo before calling the issue verified.
- **#51 — Content installation checks.** The release checker now merges kit, runtime and content ZIPs into a fresh folder and uses the installed asset-library code to discover the example scenes, paired RDLB files and licenses. Existing folders are never deleted, and archive members are validated before extraction. `--no-render` performs packaging/discovery checks only. This is headless library discovery; it does not establish that the library window renders correctly in Modo.

## Verification prepared, not run

- `tools/check_idle_release.py`: timeout, disabled timeout, manual release, pending work, new submissions, and completion-handler reentrancy without renderer processes.
- `tools/probe_light_defaults.py`: run in a separate Modo 16.1v9 profile; checks Add Item defaults and duplicate preservation without rendering.
- `tools/check_release_package.py VERSION NEW_FOLDER --no-render`: checks all three release archives and installed asset discovery. Omit the flag only when render checks are authorized.

No automated tests, render tests or Modo launches were performed for this change. Source syntax and configuration structure are checked separately. These issues should not be marked verified until their checks run.

## Remaining priorities

- **#62, #74 and #73:** restart/engine state, Shader Cast Shadows, and probes for the new engine controls overlap the other chat's work. Avoid duplicate changes; compare its final commits before closing the reports.
- **#63:** the source/patch mismatch is reported fixed in 8671e4f. Packaging and publishing the new runtime remains a separate step; these Python fixes do not require a native runtime rebuild.
- **#65, #66, #60:** remaining transient dark tiles and the cost/accuracy of stopping a render need runtime investigation and image comparisons. No verified fix is claimed here.
- **#19, #43, #49, #53, #57, #67, #69:** several reports require host interaction, reproduction, or another machine rather than a speculative code change.
- Material/lighting parity, motion blur, volumes, import, display filters and distributed rendering remain substantial independent issues; this pass does not claim to resolve the whole backlog.
