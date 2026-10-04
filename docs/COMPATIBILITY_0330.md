# 0.3.30 native property decorations

The user reproduced the Metallic 0.5 preview-start crash in installed 0.3.29. Numeric entry completed and the graph remained responsive until preview capture. Process 26804 failed while decoding widget geometry; the native access violation was in Shiboken at offset 0x145f, before the renderer received work.

An instrumented manual reproduction (16424) traversed all tracked Qt wrappers successfully, then failed when releasing the diagnostic object list. The faulting object address matched a recorded QApplication wrapper; the native failure was in Shiboken at offset 0x6dfb. This diagnostic changed object lifetimes, so it does not alone establish the original root cause. The manual run retained QPainter, QModelIndex and QStyleOptionViewItem wrappers absent from the successful automated run.

## Concrete callback failure

The first native-decoration candidate exposed an exception while populating the property pane (isolated process 8888): `RuntimeError: Internal C++ object (PySide2.QtWidgets.QCommonStyle) already deleted.` The failing expression was `self.editor.style().standardIcon(...)`. The old custom painter used this same lookup for file fields. The incomplete property table then caused the reproduction script to fail; shutdown also produced an access violation. This failed candidate was not installed.

The corrected candidate removes all host-style lookups from graph property decoration and uses a bundled folder SVG. This establishes a real failed API call, although its relationship to every earlier crash remains to be confirmed by the user's original workflow.

## Change

Remove the Python property delegate paint override. Color swatches and file icons now use Qt DecorationRole, with Qt's native delegate drawing them. Swatches update on typed RGB changes and retain the existing color-picker action; numeric entry and material shading are unchanged. No garbage collection is disabled in the plugin.

This is a candidate correction for the painting/lifetime path, not proof that all crashes are resolved. The prior isolated, normal-profile and painted baseline reproductions also passed. The original user's manual workflow remains the acceptance check.

## Checks

The final candidate passed 163 host tests with zero skips, failures and errors in Modo 16.1v9. The new regression checks native swatch data, updates on edits, and repeated repaint/collection. The complete Metallic 0.5 preview passed with 10 image updates and a clean host exit. A regression verifies file decoration works even when accessing the host style would raise. The runtime remains xpu-compatibility-0327. See validation-0330.json for recorded results.

Development-only diagnostics: probe_graph_gc.py and probe_graph_observed.py inspect tracked wrappers; they may themselves crash the disposable host. probe_graph_observed.py creates a test sphere and waits for manual input. probe_graph_painted.py performs the bounded automated render. Do not run diagnostics in a process with valuable unsaved work.
