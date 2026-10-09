# Native Modo adapters

`geometry_bridge.cpp` and `render_cache.cpp` build `MoonRayGeometry.lx`, the adapter the kit
ships for reading evaluated geometry. Build it with `tools/build_modo_bridge.py`; the script
uses the project's GCC toolchain and writes `build/modo-bridge/MoonRayGeometry.lx` with
source-version and binary hashes.

The user supplied `lxsdk_661446.zip` (SHA-256
`bacdd6db4300766e8c76b714332d7fa0ae32e51eb8b825d2f460085577a687d2`). Extract it to
`upstream/modo-sdk-661446/LXSDK_661446`, with `include` and `common` immediately underneath.
Its version header identifies build 661446, dated 2022-04-25. The SDK archive and extracted
headers are not committed to this repository. The linked SDK common code is covered by
`SDK-NOTICE.txt`.

## The PView adapter is gone

An earlier adapter, `MoonRayPreview.lx`, registered MoonRay as an external renderer for Modo's
native PView. Registration and lifecycle checks passed, but PView stayed black although valid
pixels reached its display texture. Modo cannot host an external renderer in its native PView,
so that adapter, its Python controller and its probes were removed in 0.3.50. The preview is the
Qt view described in [CUSTOM_VIEW.md](../docs/CUSTOM_VIEW.md).
