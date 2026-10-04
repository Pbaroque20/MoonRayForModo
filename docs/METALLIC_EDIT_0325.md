# Metallicity editing fix, 0.3.25

Three recent Modo dumps (13592, 22500, 26880) record access violations in shiboken2.cp39-win_amd64.dll at module offset 0x145f. This points to the host Qt/Python interface, but is not a complete symbolic diagnosis.

Scalar parameter commits no longer rebuild the graph and destroy the property table. Failed validation no longer opens a modal dialog or immediately destroys the table during setModelData. Deferred editor callbacks check that their Qt objects still exist. Numeric editors apply schema limits. Dwa metallic is restricted to 0–1, including connected export values; 1 remains valid.

## Deferred manual validation

Use Modo 16.1v9 and a disposable scene. Keep live preview off initially. Add a DwaBaseMaterial graph. Set metallic to 0, 0.5 and 1 via Enter, Tab and clicking another field. Repeat after changing node selection and reopening the graph. Try typing 8: the editor must constrain it to 1. Confirm saved graph values survive reopening. Repeat with live preview enabled, then render using scalar, vector and XPU separately. Check cancellation and closing the editor with an active cell. Record host/runtime versions and any crash dumps. These checks were prepared, not run.

No native shader crash has been reproduced or ruled out. This is a targeted editor-lifetime fix, not a claim of confirmed crash resolution.
