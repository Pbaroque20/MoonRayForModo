# MoonRayForModo — native Windows AVX preview

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
unsupported. Focused caustics are not validated. Opaque materials retain the
previous shader path; its upstream specular-color workflow is incomplete.

### Other scene translation

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
