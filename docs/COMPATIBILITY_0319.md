# 0.3.19: graph file pickers

Click a filename value or its folder icon to open the native file picker.
Covers the portable image node, native FLAGS_FILENAME strings, and the catalog's
filename-described glitter texture parameter that lacks the filename flag.
OpenVdbMap uses VDB filters; texture fields offer image formats and All files.
Selection immediately updates the draft, Undo/Redo, and opt-in live preview.
Cancel preserves the existing value. Apply/Save persists to the scene.
F2 keeps manual path editing for relative paths, variables and UDIM patterns;
browsing does not guess UDIM sequences. UV map names and VDB grid names stay text.

Only Python syntax and XML parsing checked; no host/render tests run.
Deferred checks: image/normal/projection/glitter/VDB pickers, cancellation,
non-ASCII/spaced paths, F2 manual UDIM entry, Undo/Redo and live preview.
