# 0.3.14: explicit node defaults

New nodes initialize editable fields from bundled MoonRay definitions or the
plugin node schema. Existing nodes show inherited defaults in italics without
rewriting authored parameters or connections. Reset Input clears the override
and displays the default again. Scene-object sockets stay unconnected.

The parser supports numeric, boolean, string, color, vector, matrix and array
initializers without executing source expressions. Missing primitive defaults
follow SceneRdl2's type defaults (zero, empty string/vector, null reference).
Native projection maps retain the plugin's existing identity-TRS mode 2 default
when no projector is supplied. Lowercase float schema entries are normalized.
Texture paths still require an asset; layer/mix/hair nodes still need appropriate
inputs/geometry. Default values do not make all nodes meaningful in isolation.

No tests run. Deferred checks: add ConstantColorMap (white), color/math nodes,
DwaBaseMaterial, ramps with array defaults, and projection maps; inspect an older
graph, edit/reset fields, connect maps, save and reopen without losing edits.


## Leaner graph UI

One compact toolbar contains Graph / Node / View menus, Undo / Redo, Frame all
and Widget preview. Less frequent connection, file, override and reset commands
are in the menus. The left library starts with Materials expanded; search expands
matching groups. The right inspector shows the selected node name, a clearable
property filter, the override selector and a borderless alternating-row table.
Short interaction help sits below the canvas; fuller instructions are in its
tooltip. Save and Cancel remain explicit. Deferred checks include all menu actions,
small-window resizing, filtering, layer selection and input socket expansion.
