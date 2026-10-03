# MoonRayForModo 0.3.6

Development build targeting Modo 16.1v9 on native Windows. No automated, render,
or Modo UI tests were run for this release at the user's request. Native compilation
and Python/XML syntax checks are distinct from runtime validation.

## Rendering tiles

Render Setup exposes **Tile order (preview and final)**: Morton (upstream default),
top, bottom, left, right, random, square/rectangular spiral and shifted Morton.
The choice also drives checkpoint and progressive ordering. It prioritizes native
8x8 tiles; worker scheduling makes completion order nondeterministic. It does not
change tile size, promise faster total renders, or render only a moved object.

**Active tiles**, beside the buffer dropdown, displays sampled native worker
rectangles. Tracking uses padded atomic slots, RAII cleanup, and bounded 10 Hz
telemetry, with no per-tile file I/O. Up to 512 active workers are displayed.
The overlay expires on missing telemetry and clears on completion, failure or
cancellation. Changing this display checkbox does not resubmit the scene.
XPU outlines represent CPU tile dispatch, not the lifetime of queued GPU rays.
Quick tiles can start and finish between snapshots and therefore never appear.
Older runtimes remain usable but cannot provide these outlines.

## Asset library

Open **MoonRay > Asset Library** (also in the preview System tab).
Search and category filtering cover the installed material types, eight original
starter looks, two OBJ test models, seven unmodified upstream test scenes, and
user-added asset directories. Assign material types/presets to selected meshes;
import OBJ/FBX models; save self-contained native material parameter presets.
Graph presets and cross-item material dependencies are not flattened into these
parameter presets. Texture layers above the material are not saved with them.

The local index includes MaterialX, USD, Alembic, VDB, images, TX, LUT and Modo
files. Unsupported native formats are listed for browsing; listing them does not
imply import or render support. RDLA is never executed just by browsing. Large
collections remain optional downloads via the official source page; this is not
a claim that every MoonRay asset has been downloaded. Extract downloaded packs
and add their folder to index them, preserving dependencies and licenses.

[Official test scenes and licenses](https://docs.openmoonray.org/getting-started/test-scenes/)
include the Widget shader ball, curated example scenes, and Netflix ALab.
The Widget and ALab use the ASWF Digital Assets License 1.1; they are not covered
by the plugin's MIT license. Bundled repository examples retain Apache-2.0 and
source credits. Starter materials are illustrative linear-color presets, not
measured materials or official DreamWorks looks. Visual validation is pending.

## Compatibility and packaging

- Translation-only instance motion keeps shared prototypes using native instance
  velocities. Rotating/scaling instances still expand for two-sample transforms.
  Object overrides that require expansion retain shutter-close transforms.
- MaterialX adds unclamped componentwise mix, range (signed gamma), smoothstep,
  contrast, luminance, conditionals, sign, sqrt, exp, round and acos. Color/vector
  lowering remains three-component; this is not arbitrary MaterialX support.
- Experimental native light/shader groups use unambiguous shadeLoc connections.
  Evaluated shader membership is preferred. Unsupported connections warn;
  explicit MoonRay object links take precedence. Environment illumination remains
  outside this native group filter. Host graph behavior needs Modo validation.
- Animation packages deduplicate texture/VDB bytes in a content-addressed store,
  hardlinking when supported and copying otherwise. Treat collected assets as
  immutable; editing a hardlinked file changes every linked frame.
- Packages include a standalone render_sequence.py runner with asset/scene hashes,
  launch logs, interruption records and --missing recovery for verified completed
  frames. Existing unverified output is never overwritten. Recovery verifies all
  recorded EXR outputs, but does not inspect their pixel contents or implement
  partial-frame recovery itself. Individual checkpoint controls remain separate.

## Deferred checks

`tests/test_compatibility_036.py` is provided but was not executed. In Modo, check
all tile orders on scalar/vector/XPU, region rendering and odd image dimensions,
fast cancellation, resolution changes, stale generation rejection, completed-image
buffer switching, library assignment/Undo, OBJ import, and preset save/reload.
Compare native group links to explicit object links before relying on them.

Still incomplete: arbitrary MaterialX implementations, all Modo shader/procedural
semantics, full native light-link graph coverage, per-instance rotation blur
without expansion, direct shared-memory progressive images, and production
validation. Asset import/conversion for every indexed file format is not present.
