# 0.3.13: node editing and visible placement

The library search has a clear button. New nodes are placed in the current visible
canvas, choosing the least occupied candidate there. Adding a node no longer pans
the view. If the viewport is smaller than the node, the node is centered and may
be clipped; crowded views can overlap rather than force an offscreen placement.

Accepting a color picker explicitly commits its RGB values into the graph. Pending
property edits also commit before widget refresh, Save, or adding another node.
Previously the composite color editor relied on Qt focus-out behavior. This fixes
that edit-delivery gap; the user's exact purple-render outcome is not yet verified.
The latest inspected preview scene had a checker map bound to albedo, not a purple
constant, so it does not establish a native ConstantColorMap rendering fault.

No render or UI tests run. Deferred host checks: choose purple in ConstantColorMap,
connect color output to DwaBaseMaterial albedo, Refresh, then Save/reopen; clear a
library search; add nodes at different pan/zoom levels, including crowded views.


Confirmed interaction requirement: Enter commits the current value without
accepting the graph dialog. The graph's buttons no longer act as default Enter
actions. Composite RGB editors retain values while the color picker is open;
accepting its color commits, clicking away commits, and Escape cancels the field.
Spin-box text is interpreted before the value is read. Save remains explicit.
Deferred checks also include Enter, numeric RGB typing, picker Cancel, Tab between
components, click-away, and Escape in an active field.
