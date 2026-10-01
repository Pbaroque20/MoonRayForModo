# MoonRay CustomView

The MoonRay viewport uses Modo's `CustomView` interface through its Python
binding (`lxifc.CustomView`), with a QWidget panel and QOpenGLWidget viewer.
The supplied SDK explicitly supports populating CustomView through Python.
It uses Modo's bundled PySide2 and requires no separately linked Qt library.

`moonray.open` opens the panel. `moonray.dock` replaces the current viewport
with it, so use that command in the pane intended for MoonRay. The legacy
`moonray.native.open` and `moonray.native.dock` commands now alias these routes.
No external-render controller starts automatically.

The viewer displays the existing renderer's progressive beauty images.
Wheel zooms around the pointer, dragging pans, and double-click or **Fit image**
restores the full image. Live updates, Stop, render settings, EXR output and
Save preview continue to use the existing panel. Save preview saves the image,
not the zoomed viewport. AOVs can be written to EXR; selecting them for display
and calibrated display color management remain future work.

This is a dedicated MoonRay viewport, not Modo PView or the final Render View.
A developer reported that the external-render interface broke in Modo 14/15;
our tests independently observed valid image data with a black PView display.
That report is not an independently obtained Foundry bug confirmation.

Run `tools/launch_gui_probe.py probe_custom_view.py --profile gui-custom-opengl
--without-native --wait` in Modo's Python environment. The bounded probe renders
a scene, checks the OpenGL framebuffer for bright pixels, and disposes the
panel. It does not load the experimental native adapter. Installation with
`tools/install_kit.py --custom-view-only` requires matching tested kit sources
and a clean exit, and backs up the previous kit before excluding the adapter.
Modo-evaluated geometry requires that separate experimental adapter and is
unavailable in this adapter-free installation; ordinary geometry still works.

Validation on October 1, 2026: Modo 16.1v9 produced two progressive frames,
with 200,740 bright framebuffer pixels, a valid OpenGL context, successful panel
disposal and clean process exit. Existing host regression checks also passed.
Dock layout persistence, extended live-edit stress testing and display color
calibration are not established by this bounded test.
