# 0.3.29 typed graph values and preview start

Metallic 0.5 is valid. Numeric graph properties now use persistent fields: users can type values directly, Enter commits without closing the graph, and starting preview commits pending input without requiring Tab. The selected parameter remains available for reset and property actions. Parameter limits and shading are unchanged.

Preview-button and empty-view clicks queue capture until the mouse event returns. Diagnostics start when the graph editor opens, including failures before a render starts. The native runtime remains `runtime/xpu-compatibility-0327`.

## Validation

The exact sequence was exercised in isolated Modo 16.1v9: create a sphere, assign a material using the material-assignment command, select the material, add MoonShine Override, open the graph editor, type 0.5 into Metallic, and click the empty preview without pressing Tab or Enter. The candidate completed with 13 image updates. A separate run with copied user UI settings and other installed root kit definitions completed with 12 image updates. Original user settings and scenes were not modified.

All 161 host checks passed with no skips, failures or errors. Five numeric-field regressions cover typed entry, pending-value capture, the first graph override, focus commit and deferred preview capture.

The old implementation also passed the exact isolated click sequence. Three baseline edit scenarios each completed 60 edits. These results do not reproduce or prove resolution of the intermittent user crash. Recent dumps report an access violation in Shiboken wrapper traversal; the damaged wrapper and root cause remain unidentified.

See [validation-0329.json](validation-0329.json). Reproduction scripts are local developer tools launched through `tools/launch_gui_probe.py`, not clean-machine certification. `probe_graph_numeric.py` and `probe_graph_sphere_fixed.py` are prepared scripts, not additional executed validations.
