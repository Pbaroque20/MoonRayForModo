# 0.3.15: explicit MoonShine material override

The material panel has a MoonShine Material Override checkbox and an Edit
Material Graph button enabled when the override is active. Enabling initializes
from the existing material or restores its stored graph. Disabling preserves the
graph and native parameters while host export returns to Modo controls. Existing
native materials/graphs default to enabled for backward compatibility.

The graph's material Output drives preview and export. Apply synchronizes the
native material type and parameters without closing; Save applies and closes.
Cancel discards changes since the last Apply (an applied change remains applied).
The output type is visible in the toolbar. Invalid non-material outputs fail
validation. MaterialX Override keeps its separate workflow.

Includes 0.3.14 defaults and UI changes. No render or host tests run. Deferred host
checks: enable on a translated material; switch output between two materials;
Apply and observe properties/render; disable/re-enable; Undo; Save/reopen; verify
legacy graphs and MaterialX layers independently.
