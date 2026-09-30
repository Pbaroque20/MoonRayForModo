# MoonRayForModo — native Windows AVX preview

Target: **Modo 16.1v9, Windows x64, Python 3.9**.
Project: `C:\Users\Raphael Tobar\MoonRayForModo`.

The public MoonRay CPU renderer and its upstream shader modules now build as
native Windows executables and DLLs. Both scalar and vectorized rendering pass
on this computer's Intel Core i7-4930K (AVX1, without AVX2). The installed kit has
rendered a real Modo scene in a visible preview panel. Automatic scene-edit
refresh passed: a mesh move produced a different image without pressing Preview.

This is an experimental integration with a dockable Modo Custom View, not yet a
complete production replacement for Modo's renderer. It uses MoonRay itself,
with no WSL, remote service, emulation or substitute renderer.

## Using the installed kit

The kit is installed under `%APPDATA%\Luxology\Kits\MoonRayForModo` and connects
to `C:\Users\Raphael Tobar\MoonRayForModo\runtime\native-avx`.
Start **`C:\Program Files\Modo16.1v9\modo\modo.exe`**.

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
translated. The first alphabetically named UV and explicit vertex-normal maps
are exported per face corner; explicit normals apply to smooth polygon surfaces.
Appearance and light intensity are
approximate across the two renderers.

The panel does not register as Modo's F9 renderer or implement `ILxExternalRender`.
UV image layers support diffuse/specular/emission color, roughness, metalness,
clearcoat amount/roughness and glass transmission amount/color/roughness. Put an image layer directly in a
material-tag mask containing its material, select **UV projection** and a named
UV map, and use **Normal blending, 100% opacity**. One image per effect and one
UV set per material are supported. Set data maps to a linear/no-conversion color
space. Color maps in default sRGB are converted to linear before rendering.
Unusual color spaces, UV transforms, layer corrections and blending are reported
as unsupported. Missing UV values stop export rather than use arbitrary coordinates.

Textures are converted into tiled, mipmapped `.tx` files under
`%LOCALAPPDATA%\MoonRayForModo\Textures`. First conversion can pause the UI;
later renders reuse the cache. Source timestamp/size changes invalidate it and
trigger live updates. RDLA exports reference this local cache; copy referenced
textures when moving exports to another computer. Different UV sets can split
mesh topology and affect subdivision seams.

It does not yet translate procedural textures, UDIM image folders, normal/bump
image effects, image alpha compositing, layered shader graphs,
subsurface scattering, anisotropy,
instances/replicators, hair, volumes, motion blur, render regions,
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
