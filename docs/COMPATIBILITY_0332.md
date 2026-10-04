# 0.3.32 resolution-aware buckets

The default Bucket size (preview and final) is Auto (resolution), using the shorter full-image dimension: below 256px uses 32px buckets; 256–511px uses 64px; 512–1023px uses 128px; 1024px and larger uses 256px. Manual choices are 32, 64, 128 and 256px. The control is in MoonRay preview Settings, Render tab, and can be stored with the scene's other render settings.

The native scheduler and active-bucket telemetry share the same sizing function. Native 8px film/SIMD tiles and the selected traversal order are preserved. Auto recalculates on resolution changes. Changing a manual override restarts the persistent renderer; Auto resolution changes can reuse its process. Multiple workers and adaptive passes can still show overlapping or revisited buckets. No speedup is guaranteed.

The override is passed to plugin-launched renderer processes via MOONRAY_MODO_BUCKET_SIZE, not an unsupported SceneVariables attribute. Standalone RDLA exports use the runtime's Auto default unless that environment variable is supplied externally. This update installs runtime/xpu-adaptive-buckets-0332; older runtimes retain their old bucket policy.

Before the user's request to skip further tests, 360 native scheduler/region cases passed across all nine traversal modes and five size settings, checking exact pixel coverage and contiguous bucket groups. All 166 host tests passed in isolated Modo 16.1v9, with no skips/failures/errors. The subsequent real preview telemetry check was stopped at the user's request and is not claimed as passed. No further tests were run.
