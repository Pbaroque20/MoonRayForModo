# MoonRayForModo — native Windows AVX preview

Development version **0.3.21** adds paired shutter transforms to the shared native
instancer, independent normal-map UV basis controls, format-specific asset import,
and MaterialX implementation-target selection and compatibility reports. It also
puts MoonShine Material Override directly in Add Layer, fixes creation order above
the source material, and keeps the layer pane to Enable Override and Edit Material
Graph. Runtime: `runtime/xpu-compatibility-0321`. Compiled, not render-validated.
See [scope and remaining gaps](docs/COMPATIBILITY_0321.md).

Version **0.3.20** adds multi-file browsing for filename lists,
right-click property reset, and **Graph > Check asset files** with missing-path
details and UDIM checks. Portable bundles now preserve the override enable state
and include filename-described assets whose catalog flags are incomplete.

Version **0.3.19** adds file pickers to graph texture/path fields.
Click a file value or its folder icon to browse; selection commits immediately
to the graph draft. F2 retains manual path entry, including UDIM patterns.

Version **0.3.18** adds **MoonShine Material Override** to the
native Shader Tree's **Add Layer** list. Place it above the Modo material in the
same mask, enable its override, and choose **Edit Material Graph**. Disabling
or hiding the layer restores materials below it. The MoonRay menu also has an
**Add MoonShine Material Override** shortcut that creates an enabled layer.
The properties panel uses one graph-editor entry instead of the redundant
Material inputs / searchable editor button. Existing material overrides remain
compatible. Material property commands now subscribe to Modo's UI notifications.

Version **0.3.18** also adds **Set as Material Output** to a material
node's right-click menu, including its title and sockets. Apply or Save commits
the output to the scene; live preview follows the draft output.

Version **0.3.17** embeds the MoonRay Widget in the graph editor.
**Live material preview** is off by default; opt in for debounced updates while
editing, or use **Refresh** manually. Node-library tooltips explain node purposes.

Version **0.3.16** shows default values directly in the right-hand
Properties fields, with clickable RGB swatches. Node cards stay compact.

Version **0.3.15** adds an explicit **MoonShine Material Override**
checkbox. Enable it, choose **Edit Material Graph**, set the Output material, then
**Apply** or **Save**. The rendered override and material properties follow that
output. Disabling the override preserves the graph and returns to Modo controls.

Version **0.3.14** initializes new nodes with typed defaults and shows
inherited defaults for existing nodes. Connections and authored edits are preserved.
The graph editor now has a compact toolbar, grouped menus and a cleaner inspector.

Version **0.3.13** adds a node-search clear button, places new nodes
within the visible canvas, and explicitly commits color-picker edits before
preview/save. Render verification remains deferred.

Version **0.3.12** fixes the widget preview missing-color error, labels
native material overrides, and adds a grouped, searchable node library on the
left. Click a node to add it. See [update notes](docs/COMPATIBILITY_0312.md).

Version **0.3.11** added a reusable in-memory OCIO/LUT/AOV display
processor, shared-memory scene updates, targeted ordinary-mesh capture, and
**MoonRay > Import RDL scene...** for editable conversion of supported objects.
It also fixes direct image-to-normal UV bases and adds explicit persistent motion
ID sources. The supplied MoonRay Widget is bundled for material demonstrations:
use **Preview on MoonRay Widget** in native material properties or **Widget preview**
in the node editor, then **Render / Refresh**. Its separate asset license and
credits are included. CPU threads default to all available threads. Native compilation and
syntax checks passed; render and Modo tests remain deferred. Full Modo parity is
not complete. See [implemented paths and limits](docs/COMPATIBILITY_0311.md).

Target: **Modo 16.1v9, Windows x64, Python 3.9**.

The public MoonRay CPU renderer, its core shader modules and Moonshine DwaBaseMaterial build as
native Windows executables and DLLs. Both scalar and vectorized rendering pass tested 
on an Intel Core i7-4930K (AVX1, without AVX2). The installed kit has
rendered a real Modo scene in a visible preview panel. Automatic scene-edit
refresh passed: a mesh move produced a different image without pressing Preview.

This is an experimental integration with a dockable Modo Custom View, not yet a
complete production replacement for Modo's renderer. It uses MoonRay itself,
with no WSL, remote service, emulation or substitute renderer.

## Using the installed kit

The kit is installed under `%APPDATA%\Luxology\Kits\MoonRayForModo` and connects
to the runtime recorded in its `runtime.json`. Version 0.3.18 uses the existing
`runtime/xpu-compatibility-0311` build; previous runtimes are preserved.

Open **MoonRay > Render Setup**, or run `moonray.open` in Modo's command entry.
The menu also opens Live Preview, Object Properties, Shading and Lighting,
Render Passes (AOVs), and Runtime and CPU directly. The panel groups controls in
Render, Lighting, Objects, AOVs and System tabs beside the preview.
Click **Preview** to render the scene's perspective camera. Enable **Live updates**
to refresh after scene edits. **Environment** adds uniform lighting when the scene
has no lights; zero uses only translated scene lighting. **Stop** stops rendering
and live updates. **Save preview** saves PNG; **Render EXR** renders at the scene's
resolution. **Export scene** writes RDLA.

Render settings include sample grids, total/diffuse/glossy/mirror bounce limits
and shadow-boundary correction. Lighting includes an additional environment
and a multiplier for translated Modo lights. Use **Store render settings in scene**
on the Render tab, then save the LXO, to keep these settings and selected AOVs.

Persistent preview keeps the renderer session alive and publishes intermediate
images while a pass runs. The selected beauty/AOV view is cached independently of
display settings. Supported camera, light, material and direct-transform edits
reuse captured geometry; unknown dependencies and periodic reconciliation trigger
a full capture. IPR uses reduced resolution and sampling. Automatic execution
fallback follows **XPU → Vector → Scalar**, subject to the runtime and scene.
Image delivery still uses intermediate files and a display converter.

### Docking the preview

Select the pane you want to use in Modo's Render layout, then choose
**MoonRay > Use MoonRay in Current Viewport** (`moonray.dock`). This replaces that
pane with a native Modo Custom View, using Modo's own viewport borders and layout
persistence. The viewport menu can switch it back. **Settings** hides the controls
to give the image more space. This is a MoonRay viewport within the layout;
it does not feed Modo's built-in F9 Render View or its render slots.

### MoonShine Material

Select one or more mesh items and choose **MoonRay > Assign MoonShine Material to
Mesh**. This assigns all their polygons to a new material-tag group in the Shader
Tree and selects **MoonShine Material**. The assignment supports Undo. Its
**MoonShine Material** property sheet exposes base color, diffuse amount, metalness,
reflection/refraction roughness, IOR, transmission color/amount, clearcoat, emission,
bump distance, dissolve and thin geometry. Values and the shader choice save in
the LXO. **Use MoonShine (DwaBaseMaterial)** can also switch an existing selected
Modo material to this backend without replacing its polygon assignments.

Moonshine is the upstream shader collection. This entry renders with the real
`DwaBaseMaterial`, compiled for native Windows AVX1; it is not just a renamed Modo
material. Modo's standard material channels store the exposed values, so supported
image layers above it work too. Dielectric reflection uses IOR; specular-color
maps are not translated for this shader. The material dropdown exposes the compiled Moonshine catalog and updates its
properties. Native graph sockets and the supported MaterialX translator provide
additional authoring options; unsupported graph operations report limitations.

Place an image **above** its material inside the same Shader Tree group and use
the mesh's named UV map. Layers below their material now produce a placement
warning. Modo's native effect names (`diffColor`, `specColor`, `lumiColor`,
`tranColor`, `tranAmount`, `coatAmount`) are translated to the renderer bindings.

### Jagged shadows on smooth polygon objects

Coarse polygons can cast stepped shadows even when their shading looks smooth.
**Surface > Smooth subdivision** rounds the exported mesh and gives MoonRay a
denser surface. Level 3 removed the stepped boundary in the reported sphere.
This preview/export option does not edit the Modo model and can round sharp edges.
For mixed scenes, select a mesh and use **Properties > MoonRay**: enable
**Use object overrides**, then choose subdivision, level and smooth shading.
The Objects tab offers the same controls with **Apply to selected meshes**.
Object overrides take priority over the scene default, support Undo, and persist
in the saved LXO. Without overrides, **As modeled** respects Modo polygon types.
Modo SUBD and Pixar subdivision polygons are now recognized. Their default
MoonRay subdivision level is 3; the panel can adjust it. Creases and matching
Modo's exact subdivision rules are unfinished. Material groups now share one
mesh topology, avoiding the previous subdivision seams at material boundaries.

### Explicit render passes

Choose passes on **MoonRay > Render Passes (AOVs)**, then **Render EXR**.
Beauty RGB is always included. Optional named channels are alpha, camera depth,
shading normal, geometric normal, world position, UV coordinates, wireframe,
direct diffuse, direct glossy, emission and refraction/transmission. All are stored in one 32-bit linear
multichannel EXR. The preview displays beauty only. Exported RDLA includes the
same pass definitions with an EXR filename beside the exported scene.

## Supported scene data and limits

### Modo environments

The Lighting tab now enables **Use Modo environments** by default and offers a
separate **Modo environment multiplier**. Modo's Environment **Intensity**,
**Visible to Camera**, **Visible to Indirect Rays**, **Visible to Reflection Rays**,
and **Visible to Refraction Rays** drive native MoonRay EnvLights. The existing
Uniform environment value remains an additional fill light; leave it at zero to
use only the scene's environments. Store the panel settings in the scene to keep
the enable switch and multiplier with the LXO.

Supported Environment Material types are Constant, 2 Color Gradient, 4 Color
Gradient and CIE Overcast Sky. Zenith, Sky, Ground, Nadir and exponent changes
update the preview. Gradient interpolation is a Y-up approximation, not measured
pixel parity with Modo. For HDR lighting, put a still **Environment Color** image
above the environment material and choose **Spherical** projection on its Texture
Locator. Latitude/longitude EXR/HDR images retain linear high-dynamic-range values;
the locator's rotation controls orientation. Absolute azimuth alignment with Modo
has not been calibrated. Environment images use full-resolution tiled float
textures and bilinear filtering, avoiding the native importance sampler's
unsupported 1x1 mip level.

The uppermost supported opaque layer supplies each environment. A lone layer's
opacity scales its contribution; multi-layer blending, masked groups, image alpha,
light-probe projection, image corrections, UV transforms, physical daylight and
fog are not translated. Unsupported layer/projection settings produce warnings.
Indirect-ray visibility maps to MoonRay's diffuse visibility; exact Modo ray-depth
semantics and overall brightness parity are unverified. See Foundry's
[environment material controls](https://learn.foundry.com/modo/14.2/content/help/pages/shading_lighting/environment_material.html).

### Glass and refraction

Use Modo's standard material **Transparency Amount**, **Transparency Color**,
**Refraction Index**, **Roughness**, and **Transparency Roughness**. For clear
glass, start with transparency 100%, white transparency color, IOR 1.5, and both
roughness values at zero. Raise Transparency Roughness for frosted glass.
Use closed meshes with outward-facing normals; give window glass actual thickness.
The exporter automatically selects the native AVX `ModoGlassMaterial` shader.
Reflection uses dielectric Fresnel from IOR, independently of Modo's specular color.
Dissolve controls geometric presence separately from refractive transmission.

Total and mirror/refraction bounce defaults are now 8. Older scene-stored settings
are preserved: increase those limits, and Glossy bounces for rough glass, when
rendering through several surfaces. Select **Refraction / transmission** in the
AOV tab to export light paths whose first surface interaction is transmission.
UV maps can drive transmission amount, color and transparency roughness using the
same image-layer restrictions described below.

Tint is applied at surfaces, not as distance-based volumetric absorption.
Absorption distance, dispersion, thin-sheet mode, nested dielectric priorities,
glass clearcoat/metalness, and exact Modo reflection-strength parity remain
unsupported. Focused caustics are not validated. Opaque standard materials use
the native USD shader with an implemented Schlick reflection lobe: specular color
sets normal-incidence reflectance, roughness spreads reflections, and reflection
attenuates the underlying diffuse lobe. This is not full Modo Fresnel parity.

### CPU amount and dissolve maps

Image, constant and supported procedural layers can drive **Diffuse Amount**,
**Luminous Amount**, and **Dissolve**. Amount layers replace the corresponding
constant amount and combine with the color stack once; layer opacity and blending
still apply. Dissolve uses black for solid and white for absent geometry, including
alpha output. Use linear grayscale images for these scalar controls.

**Specular Amount** maps work with standard and **MoonShine Material** shaders.
Standard materials multiply specular color by the mapped amount. MoonShine maps
control reflection weight; IOR still determines its dielectric Fresnel.
Standard materials with dissolve
maps use the existing glass/presence backend; use MoonShine when also mapping
clearcoat or metalness.

### Other scene translation

Perspective cameras translate Modo's depth-of-field switch, focus distance,
f-stop, iris blade count and iris rotation. Scene units are explicitly meters.
Focus-plane preservation, defocus, aperture changes and scalar/AVX agreement are
render-tested; matching Modo's iris bias and exact bokeh appearance remains open.

MoonShine's **Anisotropy** property stretches the reflection highlight along the
surface tangent; changing its sign exchanges the stretch axes. Standard materials
still report an explicit warning for this setting. Exact Modo tangent parity and
anisotropy texture controls remain unverified.

The Render tab provides **Render region** and Left/Top/Right/Bottom percentage
bounds. Regions apply to preview and final EXR output, preserving full-frame
dimensions with black pixels outside the region. Store render settings in the
scene to retain the bounds. Modo's own region selection is not yet imported.

Translation covers evaluated polygon meshes, world transforms, perspective
cameras, material polygon tags, constant diffuse/specular amounts and colors,
roughness, metalness, emission, clearcoat, IOR and dissolve opacity, plus
directional, point, rectangular and spot lights. Spot cone and soft edge are
translated. A material's selected UV map and the first alphabetically named explicit
vertex-normal map are exported per face corner; explicit normals apply to smooth
polygon surfaces.
Appearance and light intensity are
approximate across the two renderers.

The panel does not register as Modo's F9 renderer or implement `ILxExternalRender`.
UV image layers support diffuse/specular/emission color, roughness, metalness,
clearcoat amount/roughness, glass transmission amount/color/roughness, tangent-space
normal maps (`normal`) and bump maps (`bump`). Put layers above the material in its
material-tag mask and choose **UV projection** and a named UV map. One UV set per
material is supported. Normal/bump images are sampled as raw data; color maps in
default sRGB are converted to linear. Bump uses the material's **Bump Distance** in
scene units. Normal-map red/green inversion and layer opacity are supported.

Multiple texture layers for an effect evaluate bottom to top. Normal, Multiply,
Add, Subtract and Screen blending, opacity, inversion and color-image alpha are
translated. Constant layers, square UV checkers and static UV fractal noise are
supported; procedural filtering and noise patterns are approximations, not exact
Modo matches. Organizational groups work inside a material-tag mask. Group opacity,
selection masks and compositing multiple material BSDFs are not supported; an upper
material replaces lower material layers and produces a warning. Unsupported modes
are reported. UV repeat counts work; arbitrary UV rotations/transforms and image
color corrections remain unsupported. Missing named UV values stop export.

Visible mesh instances share a MoonRay geometry prototype, including its materials,
UVs, normals and subdivision settings. Instance world transforms and render
visibility are sampled live. A hidden source can supply a visible instance with an
explicit render-visibility override. Instances inherit source materials and MoonRay
object settings; per-instance material overrides and replicators are not translated.

Textures are converted into tiled, mipmapped `.tx` files under
`%LOCALAPPDATA%\MoonRayForModo\Textures`. First conversion can pause the UI;
later renders reuse the cache. Source timestamp/size changes invalidate it and
trigger live updates. RDLA exports reference this local cache; copy referenced
textures when moving exports to another computer. Different UV sets can split
mesh topology and affect subdivision seams.

It does not yet translate other procedural textures/projections, UDIM image folders,
object-space/engine-specific normal-map effects, arbitrary layered BSDF graphs,
subsurface scattering, anisotropy, replicators, hair, volumes, motion blur, render regions,
orthographic cameras, lens effects or animation output. Mesh sampling is not
Modo's Render Cache tessellation; subdivision creases, procedurals and displacement
do not have final-render parity. Full scene sampling can pause the UI on large scenes.
Color-management parity and production scene compatibility are unverified.
GPU rendering is disabled. The native port supports one Windows processor group
(up to 64 logical processors).

## Verification

- `runtime/native-avx/validated-render.json`: successful scalar and vectorized
  image renders, and prompt failure for an invalid output path; executable and
  image checksums included.
- `test-results/live-process/report.json`: actual Qt process cancellation,
  replacement rendering, image delivery and temporary-file cleanup; passed.
- `test-results/live-preview/report.json`: graphical Modo 16.1v9, installed kit,
  visible preview, and two different rendered images after a real mesh move;
  passed. The move uses a native Modo command; live polling requests the render.
- `build/native-renderer-avx/test.log`: seven passing native component tests,
  including AVX arithmetic, the Windows ISPC mask ABI, codecs, platform services
  and Embree.
- `test-results/glass/report.json`: actual clear, tinted, frosted, partial and
  dissolved glass renders; scalar/AVX parity, IOR-dependent ray bending and a
  non-black transmission EXR pass. Shader checksums gate installation.
- `test-results/surface-updates/report.json`, `test-results/moonshine/report.json`:
  normal/bump maps, layer math, procedural patterns, shared-instance parity and
  the real DwaBase material. Validated shader hashes also gate installation.
- `test-results/material-host.json`, `test-results/dock.json`: material assignment,
  properties, Undo, LXO persistence and native viewport embedding in Modo 16.1v9.

These are focused checks, not the complete upstream regression suite or a claim
of scene parity. The older downloaded community Windows runtime crashed at an
AVX2 instruction on this CPU and is not used by the installed kit.

Build instructions and source-port details: [docs/AVX_BUILD.md](docs/AVX_BUILD.md).
Pinned upstream revisions, patches and package versions are retained under
`patches/native-windows`. The toolchain is project-local.

Run plugin unit tests with:

```powershell
& 'C:\Program Files\Modo16.1v9\modo\resrc\python3kit\extra64\modopython.bat' -m unittest discover -s tests -v
```

Sources: [MoonRay](https://github.com/OpenMoonRay/openmoonray),
[Modo SDK](https://learn.foundry.com/modo/developers/latest/sdk/index.html).

## Expanded native material library (development update)

The current AVX build includes all 20 vendored MoonShine materials and four core MoonRay material types, with Shader Tree assignment and a searchable native parameter editor. See [material library usage and limitations](docs/MATERIAL_LIBRARY.md). The installed development runtime is `runtime/material-library-20261001`; its build succeeded, but rendering and Modo interaction tests are deferred. This does not extend the older validated-render claims to the newly added shaders.

### Material nodes and About (0.2.0 development)

The material selector now sits above its properties. A separate MaterialX Override
Shader Tree layer and visual node editor provide a supported MaterialX subset
and native material graphs. See [workflow and limitations](docs/MATERIAL_NODES.md).
MoonRay > About includes the supplied artwork, Raphael Tobar credit, plugin
version, MIT plugin license and separate Apache 2.0 MoonRay attribution.
These additions have deferred UI/render validation.

### XPU (0.2.1 development)

Native NVIDIA XPU builds are now available through the Windows port. Choose XPU,
CPU AVX or CPU scalar in Runtime and CPU. XPU uses GPU ray intersections alongside
CPU shading. See [build instructions and limitations](docs/XPU_WINDOWS.md).


### Sampling, denoising and geometry controls (0.2.2 development)

Render Setup now exposes **Uniform / Adaptive**, minimum and maximum linear
samples per pixel, and MoonRay's native **Target adaptive error**. New scenes
start at 16–256 SPP and error 1.5; this is a starting point, not a production
quality guarantee. Existing saved uniform settings stay uniform when loaded in
Render Setup. Pixel sample grid is ignored in adaptive mode. Adaptive lighting
has its own mode and quality; light, BSDF and BSSRDF grid settings are separate.
MoonRay's error scale is not a normalized variance threshold: do not copy 0.005
from another renderer without measuring convergence. Select **Sample count** in
the preview buffer menu or EXR AOVs to inspect where samples were spent.

**Denoising** offers Off (default), OptiX GPU, and OIDN CPU, independently for
beauty preview and final output. It operates on linear HDR beauty with albedo
and normal guides before display transforms. Data AOVs are never denoised.
Final rendering preserves the original EXR/AOVs and writes a separate
`name.denoised.exr` RGB beauty; original alpha remains in the raw EXR. Existing
denoised sidecars are refused rather than silently overwritten. Animation uses
per-frame denoising with no temporal stabilization; inspect for flicker. The
legacy experimental native PView adapter does not use this denoising path.

Object Properties > MoonRay and Render Setup > geometry now offer:
- **Override normals by smoothing angle**, in degrees, for polygon and evaluated
  meshes. Enable object overrides and smooth shading. It creates area-weighted
  corner normals across connected manifold edges inside the chosen angle;
  boundaries remain separate. Off preserves exported Modo normals. Material/UV
  export partitions may remain separate. Subdivision sharpness still uses creases.
- **Estimate subdivision density from angle**, with the subdivision level as a
  maximum. This estimates segments from control-cage face bending divided by
  the desired angle. It is not a guaranteed limit-surface angular tolerance.
- **Subdivision screen error**, MoonRay's camera-space tessellation edge-size
  control in pixels, capped by mesh resolution. Zero uses uniform tessellation;
  nonzero adaptive tessellation is unsupported by MoonRay for instances.

Evaluated geometry keeps Modo's tessellation/displacement and warns when these
MoonRay density controls are bypassed. Angle-driven retessellation of evaluated
surfaces and guaranteed angular convergence remain unimplemented.

The small standalone check is `tools/check_adaptive_denoise.py <runtime>`.
It verifies actual XPU setup without CPU fallback, adaptive completion, both
denoisers, finite nonconstant RGB output and an unchanged original EXR.
`tools/check_geometry_controls.py` is a deferred pure-data regression script;
Modo visual/large-scene geometry checks have not been run for this update.

References: [MoonRay adaptive sampling](https://docs.openmoonray.org/user-reference/how-to-guides/adaptive-sampling/),
[SceneVariables](https://docs.openmoonray.org/user-reference/scene-objects/scene-variables/SceneVariables/),
[denoise](https://docs.openmoonray.org/user-reference/tools/denoise/).


### Replica sharing and camera-adaptive subdivision (0.2.3 development)

Modo replicators automatically select the evaluated-geometry path. Compatible
surfaces share one MoonRay prototype and a list of replica transforms, including
single-replica groups. Material, visibility, Shader Tree and active object-setting
differences partition groups. Inactive object settings no longer split otherwise
identical prototypes. World/locator-projected textures still require separate
geometry to preserve their mapping.

Object controls now accept meshes, mesh instances and replicators. Enable object
overrides to use **Share replica / instance geometry** (default on). These
settings apply to the source item reported by Modo's render cache; for caches
reporting the prototype mesh, set controls on that mesh. Mesh-instance overrides
request evaluated export to retain per-instance material and visibility behavior.

**Camera-adaptive subdivision (expands instances)** enables MoonRay screen-space
tessellation for exported subdivision cages. It uses the configured pixel error,
or 2 pixels when that value is zero, with the existing resolution cap. Subdivision
instances are expanded into separate geometry because MoonRay cannot adapt a
shared prototype to each instance camera distance. This costs memory; leave this
option off to retain shared instances. Camera changes and animation frames are
retessellated when a new render starts; this is not in-place tessellation during
a running render.

Evaluated replicators contain already-tessellated polygons, so their subdivision
and displacement continue to come from Modo. This update does not reconstruct
subdivision cages from evaluated surfaces or implement dynamic replica LOD.
`tools/check_instances_tessellation.py` provides deferred regression checks.
No Modo or render tests were run for this update.


### Auto execution and render meter (0.2.4 development)

Rendering mode now offers **Auto (XPU → Vector → Scalar)** followed by the three
manual modes in that order. Auto is the default for new settings; saved choices
are preserved. The Windows runtime enables upstream's XPU-first Auto branch:
vector-incompatible features select Scalar; otherwise XPU is attempted with
unsupported GPU features disallowed, falling back to Vector when necessary.
GPU initialization/memory fallback remains inside MoonRay. Explicit modes retain
upstream behavior and may warn about unsupported features. The status reflects
logged mode selection and distinguishes GPU initialization from confirmed setup.

The render panel includes a progress meter, elapsed time and estimated time
remaining for the current pass. It parses only MoonRay's `Rendering [N%]` records,
not utilization statistics. Preparation, denoising and display conversion use an
indeterminate meter. Adaptive progress estimates can change or finish early;
remaining time excludes later passes, denoising and output work. Animation timing
is per frame, not a whole-sequence prediction. Completion freezes the elapsed time.

Build preparation now also runs `tools/port_execution_mode.py`. Tests were
requested as deferred scripts: `tools/check_execution_modes.py <runtime>` renders
small Auto, Vector and Scalar cases; `tools/check_render_progress.py` covers log
chunking, utilization rejection, timing estimates and logged fallback ordering.
These checks and Modo UI checks have not been run for this update.


### Shader mask routing correction (0.2.5 development)

Empty material-tag masks now behave as unfiltered groups instead of rejecting
all child materials/images. Material/Part tag types are normalized across case,
byte strings and four-character integer codes. Item masks and other tag/selection
mask types automatically request Modo Render Cache evaluation. For the latter,
material/image membership comes only from the host-provided per-surface Shader
Tree stack; they are not widened into global assignments. Additional Material,
Part and item restrictions remain checked per surface. Group opacity/blending
restrictions are unchanged. `tools/check_mask_routing.py` is a deferred regression
script; the affected user scene has not been rendered to verify appearance.


Missing image paths can now recover a unique matching directory suffix beside a
saved scene, e.g. an old Linux `/project/textures/body.png` resolves to
`textures/body.png` beside the relocated FBX/LXO. Valid paths are preserved and
recovery is reported. Multiple matches require explicit relinking in Modo;
unsaved scenes without a source filename still require valid image paths. The
plugin does not edit the original scene/image references or search entire drives.


### Shader Tree order correction (0.2.6 development)

Shader child enumeration is normalized to visible top-to-bottom order at each
parent before material assignment and texture compositing. This corrects the
reported inversion where images below a material rendered while those above it
were discarded. Put image layers **above** the material in the Shader Tree;
upper textures composite last. Material boundaries, nested groups and evaluated
material assignment use the same traversal. The deferred regression script is
`tools/check_shader_order.py`; confirmation against Modo's displayed tree and a
render of the affected scene remains pending.


### Material editor usability (0.2.7 development)

Reviewed the supplied Octane for Modo manual's setup/viewport controls (pp. 25–37),
node creation/properties (pp. 33–34), NodeGraph workflow (pp. 62–63), material
workflow and image controls. The design lessons applied here are adjacent graph
and property editing, compatible connection feedback, auto-connect, and consistent
viewport navigation. This does not import Octane implementation code or expand
MoonRay's supported shader/MaterialX definition set.

MoonShine and MaterialX Override editors now support drag-and-drop wires in either
direction, green/red compatibility feedback, cancellation without removing the
old connection, right-click disconnection, wheel zoom, middle-button pan, Frame
All (F), and dialog-local undo/redo. Search node types from the editable creation
menu. Select an input socket and enable Auto-connect to connect a newly created
node; incompatible additions are rejected without modifying the graph. Connected
ports stay visible; Show all inputs exposes the remaining sockets. Node positions
remain part of the saved graph. Save commits the draft; Cancel leaves it unchanged.

Properties use numeric controls, boolean/enum menus, vector/color editors and
plain string editing on double-click. Browse Image sets an image node's file.
Reset Input restores a base default or removes the selected layer's override.
The property filter and connected-value highlighting make large shader schemas
more navigable. Complex unsupported value types retain the existing text editor.

Render settings tabs now scroll at smaller window sizes. Clicking an empty
preview starts a render; Fit and 100% give explicit image scale controls.

Deferred check: run `tools/check_node_editor_interaction.py` within Modo 16.1v9.
It creates a temporary graph dialog, exercises dragging/undo/disconnect, and
closes without saving an item. Syntax was checked, but Qt interaction and visual
checks were not run for this update. Full Modo schematic integration, editable
shared node groups, previews inside each node and incremental material updates
remain future work; this is still the plugin's Qt graph editor.


### Render workflow polish (0.2.8 development)

Refresh preview keeps the last image visible until the replacement arrives.
Lock preview holds automatic scene, AOV and display updates while allowing the
current render to finish. Manual Refresh remains available; unlock with Live
updates enabled to apply held changes automatically. Final EXR and animation
renders reject preview restarts or competing output requests until stopped.

The displayed image has an AOV, dimensions and execution-mode caption. Scene
translation notices are de-duplicated in a collapsible, selectable text panel.
Copy Image copies the displayed image (including its display transform); use
Render EXR for linear output. Saving PNG uses an explicit default extension.

The render log supports search, copy, save and following live output. Searching
pauses following so new output does not reset the selection. Panel tab, splitter
position and settings visibility persist between sessions. Preview lock is
session-only.

No automated or interactive tests were run for this update, at user request.
These are workflow improvements, not additional scene translation coverage.


### Animation and output workflow (0.2.9 development)

Animation uses one setup window with output folder, filename prefix, first/last
frame, frame step, FPS and motion blur controls. Its summary shows the requested
frame count and first filename. The exporter checks every requested frame for
existing beauty or denoised outputs before starting, and rejects an existing
sequence manifest. Frame stepping samples the original timeline at frame/FPS;
it does not retime the animation. Sequence manifests record the full requested
range, step, prefix, motion-blur choice and completed frames.

PNG, EXR, RDLA and log save dialogs remember separate output folders and supply
default extensions before the dialog's overwrite confirmation. Pending output
requests are also protected from competing preview requests. The renderer retains
its existing no-overwrite restrictions. No tests were run for this update.


### Persistent preview sessions (0.3.0 development)

The bundled `runtime/xpu-persistent-20261001` adds a persistent native preview
protocol. Enable **System > Keep MoonRay loaded between preview updates**
(enabled by default), then enable **Live updates**. MoonRay remains running
after a preview completes. Compatible transform, camera, light, material-value
and sampling edits are sent as changed RDLA attributes to the loaded scene.
Native acceleration/geometry updates still run when those attributes require it.

Structural changes (including object additions/removals, shader connections or
types, changed attribute layouts, topology and resolution) load a fresh scene
context within the same process. Execution-mode, runtime or thread-count changes
restart the process. Stop releases it; a subsequent preview starts a new session.
Older runtimes without the executable-matched protocol marker retain the previous
separate-process behavior. Final EXR/animation output remains on the batch path.

Commands are atomically published in a private temporary folder. Each applied
update is acknowledged before constructing the next delta, so rapid edits can
coalesce without losing intermediate state. Stale completions are discarded.
Denoising, AOV conversion and color transforms still run after a completed pass.
Interrupted render preparation reloads the full snapshot before continuing.

This preserves the native process and compatible loaded scene data; it does not
reuse old pixel samples or restrict lighting updates to the moved object's pixels.
Modo still captures a complete scene snapshot and serializes it locally to detect
changes. Eliminating that capture/serialization cost is future work.

Native compilation succeeded; no renderer or Modo interaction tests were run at
the user's request. `tools/check_persistent_preview.py <runtime-folder>` is an
optional standalone check for same-process rendering, a transform delta, changed
image pixels, a structural reload and orderly shutdown. It has not been run.
The normal native build applies `tools/port_persistent.py`; the implementation
is tracked in `native-port/persistent_session.inc`.


### Low-cost IPR mode (0.3.1 development)

Toggle **IPR** next to the render-buffer selector to start live previews at reduced
quality. Defaults are a 160-pixel width cap, minimum and maximum both 1 SPP,
and target adaptive error **100** (the error threshold has no stopping effect at the default one-sample cap). The Render tab offers 80/160/240-pixel caps,
1/4/16-SPP caps and an adjustable error. Normal preview/scene width and sampling
caps remain upper limits. A looser existing adaptive error stays looser. Light,
BSDF and subsurface sample grids use a side of one during IPR. MoonRay internally
clamps adaptive sampling to at least two samples, so the one-sample preset uses
uniform sampling with pixel grid 1; higher caps use adaptive sampling from 2 SPP.

IPR limits are applied only to a preview request copy. Final EXR, animation, RDLA
export and stored scene settings retain their regular quality. Denoising follows
the existing preview preference. Disable IPR to refresh at regular preview quality;
there is no automatic idle refinement. Lock preview holds automatic changes, and
active output renders cannot be interrupted by toggling IPR. Stop stops live
updates; Refresh can still render an IPR image. Quality preferences persist locally,
but IPR starts off when opening a panel so it does not trigger renders at startup.

This reduces rendering work; it still displays completed passes, not streaming
buckets, and still captures the scene for live updates. Instant feedback is not
guaranteed. No tests were run for this update. Deferred checks are in
`tests/test_ipr.py`.


### Buffer switching without rerendering (0.3.2 development)

Each preview pass writes beauty and all built-in dropdown AOVs together. The last
completed pass is retained in a separate temporary cache. Switching the Render
buffer dropdown converts that cached buffer without restarting MoonRay, changing
its generation, or canceling denoising. Cached views are also available during
the next render, while locked, after Stop, and during final-output rendering.
Before the first pass finishes, selection is remembered until buffers arrive.

Exposure, LUT and other Color / LUT controls now also convert the cached linear
image. Background, execution and IPR changes still request a render. Display and
buffer selection are excluded from live-update scene comparisons. Image captions
identify the actual cached buffer and completed preview, rather than the currently
requested render. Beauty denoising follows the preview preference regardless of
the selected buffer; other AOVs retain their original linear values.

All preview AOVs add rendering, file-writing and cache-copy costs; final EXR AOV
selection is unchanged. Only completed passes are viewable, not unfinished native
framebuffers. The cache retains the latest linear pass and up to 24 converted views
(with an in-flight conversion temporarily retained) and is removed when the panel
closes. No tests were run; deferred coverage is in `tests/test_preview_buffers.py`.


### Native texture and normal node library (0.3.3 development)

The node editor exposes 81 native Map/NormalMap schemas from the vendored
MoonRay/MoonShine declarations. The Windows AVX/XPU runtime now builds the
MoonShine map and normal-map libraries: noise/Worley, ramps, projections, UV
transforms, color corrections, math, normal images, normal combinations and
normal conversions. Native map inputs use their actual interface types; normals
cannot connect directly to color sockets. Image nodes now accept coordinate
connections. Native projector nodes default to identity TRS; host projector/camera
object references are not yet wired. Filename inputs have texture browsing and
mipmap preparation. Native gamma controls remain responsible for color decoding.

Texture-only Shader Tree groups support the existing twelve blend modes, scoped
opacity/masks, and RGB inversion. Groups containing base materials still report
unsupported whole-material group operations; arbitrary layer-mask hierarchies
are not silently claimed as translated.

MaterialX import additionally translates common arithmetic/vector operations,
remap, default texture-coordinate connections, graph interface inputs, and local
single-output NodeDef implementations made from supported nodes. Native map and
normal nodes can be exported using MoonRay-specific NodeDefs. This remains a
translator, not an arbitrary MaterialX shader compiler: external implementation
libraries, multi-output custom definitions, channel swizzles, unsupported node
categories, and nonzero indexed UV sets are explicitly rejected. Procedural
appearance follows MoonRay, not an assertion of identical Modo/MaterialX noise.

No renderer, Modo, or automated tests were run. Deferred checks are in
`tests/test_map_library.py`. Reference semantics:
[MoonRay maps](https://docs.openmoonray.org/user-reference/scene-objects/maps/),
[MaterialX specification](https://materialx.org/Specification.html), and
[Modo material groups](https://learn.foundry.com/modo/16.1v8/content/help/pages/shading_lighting/shader_items/material_group.html).


### Production feature expansion (0.3.4 development)

This update implements the feature paths below. The native renderer and geometry
adapter were compiled, and Python source syntax was checked. **No automated,
standalone-render, or Modo UI tests were run**, as requested. The deferred checks
below must pass before this update can be described as production validated.

- **Displacement:** add `NormalDisplacement` (scalar height), `VectorDisplacement`,
  or `CombineDisplacement` in the material node editor and select **Displacement
  output**. The surface output remains separate. The exporter assigns displacement
  through each MoonRay Layer material/part assignment. Edit `bound_padding` on the
  displacement node and subdivision level/adaptive error in Object controls.
  Polygon displacement also receives a tessellation budget. Use raw/linear images
  for displacement data. Modo evaluated displacement remains baked into evaluated
  geometry; a native displacement graph adds to that surface, so do not author
  the same displacement twice.
- **Lighting:** Lighting → **Object light links, emitters and volumes** provides
  per-item LightSets and ShadowSets, mesh emitters, Disk/Cylinder/Portal overrides,
  light group labels, IntensityLightFilter color/exposure, and DecayLightFilter
  distances. Shadow exclusions control which lights an object casts shadows for.
  A portal targets the single lighting environment; independent camera backgrounds
  do not count as portal targets. Mesh-light illumination is separate from its
  visible surface material; use an emissive material for a glowing visible surface.
  These are MoonRay scene overrides, not an assertion that all Modo light-link
  graphs or every upstream light-filter type are automatically translated.
- **Outputs:** AOVs → **Configure named outputs** adds custom LPE, light-group,
  material, motion-vector, depth/normal/position/alpha and object Cryptomatte
  outputs. Set channel names, EXR parts, half/float precision and math filtering.
  Cryptomatte uses native fixed `Cryptomatte00…` names, float channels, stable
  item-derived MurmurHash3 IDs, an embedded manifest and resume support. One
  Cryptomatte set is supported per render. Shared mesh instances are expanded
  when per-instance assignments or unique IDs require them. VDB volume IDs are
  not included in the object manifest. Enable **Include motion blur / motion
  vectors in final outputs** to sample the shutter for stills, exports and
  packaged scenes; animation has its own motion-blur checkbox.
- **Preview:** native persistent sessions publish in-progress linear beauty images
  once per second with one-image backpressure. Modo keeps completed AOVs available
  while a new beauty converges. Switching cached AOVs or display/LUT settings does
  not restart rendering. Scene listeners suppress idle recaptures; camera/light
  channel edits can reuse geometry, with a bounded 64-MB serialized-array cache.
  Other edits conservatively recapture; a 15-second reconciliation catches host
  providers that omit notifications. Texture-file timestamps also trigger updates.
  Progressive beauty still uses temporary PFM and the display converter; it is not
  a zero-copy GPU viewer. AOVs become available at completed-pass boundaries.
- **Recovery:** enable final-render checkpoints and resume matching checkpoints.
  Persistent `.exr.recovery` folders keep native checkpoint and guide files, with
  scene/settings/runtime/asset signatures. Animation **Render missing frames**
  resumes matching completion manifests, verifies recorded output hashes and
  fills gaps without replacing completed files. Save the scene before starting a
  resumable sequence and keep the same saved scene/settings. Legacy manifests
  without a signature cannot be automatically certified as matching. Completed
  raw frames whose denoising was interrupted retain `.exr.postprocess` guide files
  and can finish denoising without rerendering. Invalid/mismatched recovery data is
  preserved and reported. Stopping cannot recover samples since the last written
  checkpoint; checkpoint EXRs are ultimately decoded/validated by MoonRay.
- **Geometry:** the rebuilt read-only adapter exports evaluated hair/fur segments
  and particle points, with radii, velocities, visibility and Shader Tree surface
  assignments. Choose evaluated geometry for procedural hair/particles. Native
  hair materials can shade the exported strands. Ordinary curve items are sampled
  through Modo's CurveGroup API in control-cage mode. Objects → **Strands, points
  and VDB assets** supplies radius, curve sampling, material tags and file geometry
  attached to a locator. VDB controls include density/emission/velocity grids,
  scattering color/anisotropy and multipliers. `####` filenames select animation
  frames. A VDB simulation must already exist; Modo procedural fog is not a VDB
  simulator. Native point/strand motion and VDB velocities use scene FPS.
- **Color/assets:** Color / LUT → **Input color spaces and texture cache** sets
  an input OCIO config, its linear Rec.709 target-space name, per-file/UDIM input
  overrides and the native texture-cache budget. Modo/MaterialX named input spaces
  are converted explicitly; normal/bump and scalar Shader Tree maps remain data.
  Native map color rules disable the map's extra gamma conversion. Rendering and
  authored RGB values have a declared **linear Rec.709** contract; changing the
  OCIO target name does not turn the renderer into an arbitrary-primary working
  space. System → **Report scene assets** lists files/UDIMs, missing paths and
  compatibility notices. **Package portable render scene** writes a fresh folder
  containing RDLA, prepared textures, VDBs, display LUT/config dependencies and
  hashes. It packages the current frame, not an editable Modo project or a whole
  animation; run it per frame for animated assets. Missing OCIO file dependencies
  fail packaging rather than producing a knowingly broken package.

File-backed strand/point JSON uses `kind: "curves"` or `"points"`, `vertices`,
`radius` or `radii`, optional `velocities` / `vertices_close`, and a `material` tag.
Curves also require `counts` summing to the vertex count and `curve_type` (`0`
linear, `1` Bezier with 3n+1 controls, `2` B-spline). Curve UVs are per strand.
Coordinates are local to the selected owner. Radius values are meters; zero tips
are allowed, but the geometry must contain at least one positive radius.

Deferred checks (run explicitly when testing is authorized):

```powershell
python -m unittest discover -s tests -p test_production.py
python tools/check_production.py --runtime runtime/xpu-production-20261003
# The previous command only writes a fixture. This one executes the renderer:
python tools/check_production.py --runtime runtime/xpu-production-20261003 --run --mode scalar
# Repeat in vector / xpu mode, optionally adding --vdb path/to/smoke.vdb.
```

Manual acceptance still includes shutter topology changes, light-link inheritance,
filter distances, displacement bounds at grazing angles, EXR compositor import,
stop/reopen/resume under load, procedural hair/particle variation, OCIO reference
swatches, relocating a package, and visual evaluation in Modo 16.1v9. Full Modo
scene parity and arbitrary MaterialX implementation graphs remain outside the
validated compatibility claim.

References: [displacement](https://docs.openmoonray.org/user-reference/how-to-guides/displacement/),
[light sets](https://docs.openmoonray.org/user-reference/scene-objects/light-set/LightSet/),
[Cryptomatte setup](https://docs.openmoonray.org/user-reference/how-to-guides/render-outputs/cryptomatte/),
[checkpoint rendering](https://docs.openmoonray.org/user-reference/how-to-guides/checkpoint-resume/checkpoint/).
