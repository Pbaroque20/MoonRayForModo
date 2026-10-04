# 0.3.16: explicit inspector values and color swatches

The right-hand Properties fields show typed default values before editing, using
the 0.3.14 default resolver, instead of empty cells with tooltip-only defaults.
Inherited values are italic; authored values are normal. Node cards stay compact.
RGB property rows show a clickable swatch alongside their values. The RGB editor
uses a live swatch instead of a Color button. Picker OK commits immediately;
Cancel preserves the value. Numeric component editing remains available.

Swatches clamp their display to 0–1; numeric HDR values remain stored unchanged
unless replaced in the standard color picker. This is an editor color preview,
not an OCIO-managed render. Includes pending 0.3.14/15 changes. Syntax checked;
no UI/render tests run. Deferred checks: select a new/legacy node, inspect defaults
without entering fields, reset values, swatch OK/Cancel, HDR values and Undo.
