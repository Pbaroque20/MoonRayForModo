# 0.3.27 runtime and host validation

New runtime: `runtime/xpu-compatibility-0327`, targeting Modo 16.1v9 on Windows. Includes the previous candidate's simultaneous surface Cryptomatte and checkpoint fixes plus the bucket scheduling update. It remains a development build, not a production certification.

## Changes

- Default scheduling buckets are 256 by 256 pixels. The selected traversal orders the larger buckets; each retains MoonRay's 8 by 8 film/SIMD tiles. Telemetry reports a bucket only while at least one worker is inside it and clips boxes to image dimensions. Multiple workers and adaptive passes mean boxes can overlap in time and revisit a bucket in later passes. There is no guarantee of a speed improvement or a single box completing before another starts.
- Fixed UDIM patterns rejected by Windows Python 3.9 path resolution. Both texture enumeration and input color-space rules resolve the parent directory while preserving the `<UDIM>` filename token.
- Material preview separates host capture from render submission for reproducible integration checks. Per-process diagnostics in `%LOCALAPPDATA%/MoonRayForModo/Diagnostics` record live-preview startup stages and enable Python fatal-stack logging if another handler has not already been installed.

## Completed checks

- **153 tests passed, zero failures/errors/skips** in isolated Modo 16.1v9 using the new runtime. The previous ten failures were stale export expectations or Windows short/long-path comparison differences. Assertions now check current native materials, assignment helpers, ordered parameter blending, numerical absorption and stable instance identities. None were dropped. Running host tests also exposed the real Python 3.9 UDIM bug fixed here.
- The previous 17 skips represented 15 host-dependent tests, a skipped Qt lifetime module, and an unset native-display runtime. Providing the real host and runtime removed all skips. The Qt module expands to two tests; two additional parameter-editor checks make the final count 153.
- Five full right-pane Metallic 0.5 edits followed by enabling Live Preview completed in the actual graph editor with XPU active: 38 progressive images and clean host shutdown. Earlier three-cycle comparisons passed with both the installed 0.3.24 runtime and the 0.3.26 candidate. **The user's intermittent crash was not reproduced; its root cause and resolution are not confirmed.** Do not treat this as a metallicity-limit fix.
- Native scheduler probe: 36 cases across all nine traversal modes and full/cropped/unaligned regions. No missing, duplicate or outside-region pixels; 256px bucket groups contiguous; 8px native tiles preserved.
- Checkpoint/resume repeated on the new runtime for scalar, vector and XPU. All nine category coverage comparisons passed, with actual saved-sample restoration required and maximum coverage difference 1.20e-7. This is controlled checkpoint stopping, not power-loss recovery.

Machine-readable results and runtime hashes: [validation-0327.json](validation-0327.json). Local detailed logs are under `test-results/regression-0327-host`, `metallic-0327-final`, and `crypto-0327-resume`.

## Repeating checks

`tools/probe_candidate_suite.py` and `tools/probe_metallic_live.py` are local Modo scripts for the isolated launcher (`tools/launch_gui_probe.py`). They start no work until explicitly run. The latter uses a fresh material and closes only the isolated test instance. `moonray_bucket_probe` is built with the native renderer and registered as `moonray_bucket_schedule` in CTest; use the staged runtime DLL environment. The existing checkpoint script requires `--run`.

Volume Cryptomatte coverage, arbitrary MaterialX execution, exact Modo scene parity, production-scale validation and clean-machine installation remain incomplete. Old 0.3.26 reports are historical and intentionally retained.
