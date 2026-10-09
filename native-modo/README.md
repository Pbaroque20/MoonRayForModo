# Native Modo adapters

`geometry_bridge.cpp`, `render_cache.cpp` and `mesh_reader.cpp` build `MoonRayGeometry.lx`, the
adapter the kit ships. `render_cache.cpp` reads evaluated geometry from Modo's render cache.
`mesh_reader.cpp`, added in 0.3.50.1, hands a whole mesh to the plugin in one call
(`MR_mesh_file`), which is how meshes of 5,000 polygons or more are read; the plugin falls back
to reading a polygon at a time where the adapter is missing or older. Build it with
`tools/build_modo_bridge.py`; the script uses the project's GCC toolchain and writes
`MoonRayGeometry.lx` with source-version and binary hashes into `build/modo-bridge`, or the
folder given with `--output-dir` (the 0.3.50.1 release used `build/modo-geometry-fast`).
`tools/probe_mesh_reader.py` checks in Modo that the two ways of reading give the same mesh.

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
