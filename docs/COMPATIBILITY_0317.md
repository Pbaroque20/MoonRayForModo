# 0.3.17: embedded opt-in material preview and descriptive tooltips

The graph editor embeds the MoonRay Widget below Properties in a vertically
resizable split. It no longer opens a separate widget dialog. Live material
preview starts off on every editor opening. Enable it to render committed graph
edits after a 650 ms pause; Refresh also works manually. Graph changes include
connections, output selection, values and undo/redo. Panning, node positions and
selection do not trigger renders. Live uses 256 pixels / 4–16 adaptive SPP;
manual Refresh uses 384 pixels / 4–64 SPP. Stop disables live updates. Closing the
editor cancels its timer and renderer. The separate native-parameter editor keeps
its existing manual preview dialog.

Library tooltips provide a purpose description and examples of relevant controls
from bundled shader metadata. The widget retains its source credit and license.
External referenced-material edits outside this graph still need manual Refresh.
Syntax checked; no tests run. Deferred host checks: editor opens without rendering,
live on/off, rapid edits, output switching, undo/redo, Stop, close during rendering,
manual refresh, pane resizing, and hover descriptions across library categories.
