# 0.3.12: widget material defaults and grouped node library

The widget failed before rendering with KeyError color because property drafts
were passed without captured Modo material channel values. Preview now captures
those values for the selected material and referenced materials before applying
the draft. Native texture bindings also accept a neutral fallback for standalone
native definitions that do not contain translated Modo color channels.

Native material choices are labeled as overrides. Saving the native editor
selects that override; Modo controls in the main dropdown restores translation.

The node library is a searchable left pane grouped by purpose. A single click
adds a node. Incompatible auto-connections leave the new node unconnected, rather
than discarding it. The canvas remains central and properties remain at right.

No render or Modo UI tests were run. Deferred checks: render a native DwaBase
widget with no authored color; render a mix referencing two native materials;
click library entries with/without a selected input, filter groups, use Undo/Redo,
and add a node through the canvas context menu. See 0.3.11 for inherited limits.
