# MoonRayForModo — native Windows AVX preview

Development status: CPU compatibility work is ongoing. The current source adds an
experimental Modo Render Cache path for evaluated subdivision/displacement,
named UVs, shared instances and item-scoped material overrides. Native PView
startup, image-buffer handling and shutdown are still under validation; the
installer blocks unvalidated native adapters. See [the CPU checklist](docs/CPU_READINESS.md)
for verified features and remaining work. This is not yet production-ready.

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
to `\MoonRayForModo\runtime\native-avx`.

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

The preview refines through separate 1, 4 and target sample-grid renders.
Live updates check supported scene data every 1.2 seconds and replace obsolete
render requests. This is image-pass refinement, not persistent bucket streaming.
The default execution mode is AVX vectorized CPU rendering.

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
maps are not translated for this shader. The full Moonshine shader catalog and
every DwaBase attribute are not exposed. Other Modo materials retain their existing
translation until explicitly switched.

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
