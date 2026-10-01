# Native Modo preview adapter (experimental)

This adapter targets **Modo 16.1v9 Windows**, using its `externalrender` interface.
It is not yet installed or enabled in the normal MoonRayForModo kit.
The existing custom docked preview remains the supported preview workflow.

The user supplied `lxsdk_661446.zip` (SHA-256
`bacdd6db4300766e8c76b714332d7fa0ae32e51eb8b825d2f460085577a687d2`).
Its version header identifies build 661446, dated 2022-04-25. It does not
establish an exact Modo 16.1v9 release match. Its external renderer, notifier,
and image queue interface IDs match the installed 16.1v9 Python SDK.
Registration and lifecycle checks passed, but later isolated tests consistently
showed a black PView despite valid rendered pixels reaching the display texture.
The earlier apparent success did not establish reliable PView display.
This route is suspended. The supported development direction is the Qt OpenGL
CustomView described in [CUSTOM_VIEW.md](../docs/CUSTOM_VIEW.md).

## Build

Extract the archive to `upstream/modo-sdk-661446/LXSDK_661446`, with `include`
and `common` immediately underneath. Run `tools/build_modo_bridge.py` with
Python. The script uses the project's GCC toolchain and creates
`build/modo-bridge/MoonRayPreview.lx`, plus source-version and binary hashes.
The SDK archive and extracted headers are not committed to this repository.
The linked SDK common code is covered by `SDK-NOTICE.txt`.

## Integration under test

`preview_bridge.cpp` registers `moonray.cpu` as **MoonRay CPU**. The Python
controller uses the existing scene translator and CPU renderer, sends linear
EXR images to the adapter, and tracks scene edits, pause, reset, and close.
Modo 16.1v9 PView uses the buffer queue; its notifier's image method returns
`LXe_NOTIMPL`. `WriteBegin` returns a buffer at the host's image resolution,
which can differ from the faster 640-pixel preview. The adapter copies or
bilinearly scales linear RGBA into that host-owned buffer. It never resizes or
frees it. Scaling tests run during the adapter build. The notifier fallback
for other clients uses an SDK-created image-processing object to initialize
the render output description; it must not receive a null description.

Run `tools/launch_gui_probe.py probe_native_preview_interactive.py` to open an
isolated Modo 16.1v9 test and leave it open. Click inside PView to activate it.
The launcher adds the built adapter to that test profile's startup scan.
It removes the precise saved layout overrides left by an early experiment
which had placed a PView inside Modo Intro. The probe then restores a fresh
PView viewport before selecting MoonRay. `repair_native_preview_windows.py`
performs the same window repair in an already-running test without altering
the scene.

`tools/probe_native_preview_gui.py` checks the host version is 1619. The GUI
probe must activate the preview pane before render results are meaningful.
Renderer selection is a numeric index in Modo; do not pass a server name as
the command argument. Headless server discovery alone does not verify image
display. Geometry display, color processing, shutdown, docking, and live
editing still require passing integration tests before enabling this adapter.

Native PView is an external-render viewport; this work does not establish
integration with Modo's separate legacy Preview or final Render View.
