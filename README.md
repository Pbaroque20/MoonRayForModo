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

Open **MoonRay > MoonRay Preview**, or run `moonray.open` in Modo's command entry.
Click **Preview** to render the scene's perspective camera. Enable **Live updates**
to refresh after scene edits. **Environment** adds uniform lighting when the scene
has no lights; zero uses only translated scene lighting. **Stop** stops rendering
and live updates. **Save preview** saves PNG; **Render EXR** renders at the scene's
resolution. **Export scene** writes RDLA.

The preview refines through separate 1, 4 and target sample-grid renders.
Live updates check supported scene data every 1.2 seconds and replace obsolete
render requests. This is image-pass refinement, not persistent bucket streaming.
The default execution mode is AVX vectorized CPU rendering.

### Jagged shadows on smooth polygon objects

Coarse polygons can cast stepped shadows even when their shading looks smooth.
**Surface > Smooth subdivision** rounds the exported mesh and gives MoonRay a
denser surface. Level 3 removed the stepped boundary in the reported sphere.
This preview/export option does not edit the Modo model, but it affects every
exported mesh and can round sharp edges. For mixed scenes, keep **As modeled**
and mark only the intended objects as subdivision surfaces in Modo.
Modo SUBD and Pixar subdivision polygons are now recognized. Their default
MoonRay subdivision level is 3; the panel can adjust it. Creases and matching
Modo's exact subdivision rules are unfinished, and material boundaries can form
seams because material groups are exported separately.

## Supported scene data and limits

Translation covers evaluated polygon meshes, world transforms, perspective
cameras, material polygon tags, constant diffuse color/roughness/metalness, and
directional, point and rectangular lights. Appearance and light intensity are
approximate across the two renderers.

The panel does not register as Modo's F9 renderer or implement `ILxExternalRender`.
It does not yet translate textures/UV shading, layered shader graphs,
instances/replicators, hair, volumes, motion blur, AOVs, render regions,
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
