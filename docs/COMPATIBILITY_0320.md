# 0.3.20: material workflow follow-through

Filename-list inputs support multi-file browsing. The property context menu
provides Browse and Reset input to inherited value. Reset removes the current
layer's parameter and connection; override layers inherit the base node value.
The graph asset check reports assigned missing files, including active overrides
and UDIM patterns; optional empty inputs and external referenced materials are
excluded. Shared filename metadata also fixes bundle collection of unflagged
filename-described glitter inputs. Bundles preserve explicit override enable state.

Syntax/XML checked only; no host/render tests run. Deferred checks: multi-file
normal texture list, cancellation, reset connected/base/override inputs,
Undo/Redo, missing/existing UDIM paths, disabled material bundle roundtrip.

Added explicit itemtype:textureLayer category entries and CommandHelp names for
both override types, matching Modo 16.1 and the installed Octane configuration.
Shader Tree path: Add Layer / Custom Materials / MoonShine Material Override.
The prior package registration alone did not provide the menu category.

The standard material right-click menu adds Add MoonShine Material Override.
It creates an enabled override immediately above the selected material in the
same parent/mask, seeds its graph from supported source values or existing graph,
and selects the new layer. The original material remains untouched. Multi-select
is disabled. Menu insertion uses Modo 16.1 native shader popup category.
Deferred host checks include both Add Layer and right-click insertion/undo.
