# Dreamworks' MoonRay for Modo

<img width="1292" height="939" alt="cheetah_capture1" src="https://github.com/user-attachments/assets/9d630bb7-9103-42b4-8e8c-f249c7d47490" />
<p align="right">Paper Cheetah 3D Model (created by Raphael Tobar/Genoma)</p><br>

MoonRay for Modo integrates DreamWorks’ open-source MoonRay renderer with **Modo 16.1v9 on Windows**, running natively without WSL. Developed by Raphael Tobar w/ AI-Assistance.

The plugin includes CPU and XPU rendering, a dockable live preview with a second GPU preview engine, native MoonRay materials with a graph editor, Shader Tree translation, MoonRay's own lights and other items, MaterialX and RDL scene import, AOVs, and denoising.

**Current version: 0.3.51.1 — experimental development build.** It is 0.3.51 with fixes to Draft and Stop in the preview window.

[Download 0.3.51.1: the kit, the Windows runtime and the MoonRay content](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.3.51.1) · [Installation instructions](docs/INSTALLATION.md) · [What's new in 0.3.51](docs/WHATS_NEW_0351.md)

Work on the next version goes on in the [MoonLightIPR branch](https://github.com/Pbaroque20/MoonRayForModo/tree/MoonLightIPR).

![The MoonRay Preview window in Modo, rendering an imported MoonRay scene](docs/images/preview-window.png)
*The preview window in Modo 16.1v9, rendering The Wooden Staircase (by Wig42, CC BY) after it was imported from MoonRay's own scene files.*

## New in 0.3.51

The full list is in [What's new in 0.3.51](docs/WHATS_NEW_0351.md).

**The preview window**

- **Draft**: the scene as clean outlines, with nothing rendered until you press **Region** and drag. Then only that part is rendered, among the lines.
- **Region** is a button you drag with; **R, G, B, A** show one channel; a **colour probe** follows the pointer; **EV** and **Gamma** reset with a click.
- **Export AOVs as Images** from the picture's right-click menu.

![Draft with a region rendered among the lines](docs/images/preview-draft-region.png)
*Draft, with a region rendered among the lines.*

**Rendering with MoonRay**

- **Safe Denoising**: stop a MoonRay render at any time and keep it, denoised. **Continue** then takes it up where it stood.
- **Bake Selected Mesh to Texture**, **deep EXR** output, more render settings and one-click outputs, and **light path presets**.
- **Mesh lights** are seen glowing; MoonRay light items can be **linked**; an object can cast **no shadow onto chosen objects**.

![A MoonRay preview stopped part way, kept and denoised](docs/images/safe-denoising.png)
*Stopped part way, kept and denoised, with Continue on offer.*

**The MoonLightIPR preview** (echoing DreamWorks' earlier rasterizer MoonLight; it was shown as "MoonLight" in 0.3.50)

- **Hair, skin and curves** shaded with MoonRay's own materials; **fog and VDB clouds**, with their glow.
- **Rod, barn door, cookie and VDB light filters**, textures on every kind of light, and **render regions**.

![Hair, MoonRay on the left and MoonLightIPR on the right](docs/images/moonlightipr-hair_dark.jpg)
*Hair in MoonRay (left) and in the MoonLightIPR preview (right).*

**Materials and scenes**

- **Modo's Fur material** grows fur, with its curls, clumps, kink, frizz and weight maps.
- **Blinn and Ashikhmin** highlights match Modo's, and a material's **smoothing angle** is followed.
- **MoonRay's materials in the Shader Tree's Add Layer list**; assign one to **selected polygons**; **OpenPBR and glTF** surfaces from MaterialX.
- **Imported MoonRay scenes** keep their light, shadow and shadow receiver sets.

![Modo's Fur material with curls, clumps and a weight map](docs/images/fur-extras.jpg)
*Modo's Fur material in MoonRay: curls, clumps with kink, and fur thinned by a weight map.*

**Working with the plugin**

- **The asset library shows pictures** of things to use, each with one button for what it is for.
- **MoonRay Content**: MoonRay's ten example scenes, as a third ZIP of the release that merges into the kit.
- **A MoonRay page in Modo's Preferences**, including having the M key open MoonRay's Assign Material.
- **Dense hair** grows and re-renders several times faster.

![The asset library with MoonRay's example scenes](docs/images/asset-library.png)
*The asset library, showing MoonRay's example scenes.*

## From 0.3.50

- **MoonLightIPR** (echoing DreamWorks' earlier rasterizer MoonLight), an approximate NVIDIA GPU preview engine, chosen in the preview window. It follows edits as they are made; output renders still use MoonRay. See [moonlightipr/README.md](moonlightipr/README.md).
- **MoonRay-specific items, added from the MoonRay menu**: 30 of MoonRay's own lights, light filters, cameras, shapes and volumes as Modo items (dwEnvLight, dwRectLight, dwSpotLight and the rest), each with its own properties form and a viewport proxy, for what Modo has no item for. VDB volumes load from a file.
- **Import MoonRay Scene (RDL)**: a MoonRay scene comes in whole. Meshes keep their transforms and are instanced, curves come in as curves, lights and other MoonRay objects become MoonRay items, materials keep their graphs, and the scene's settings and outputs go to the render settings. A scene in two files (`scene.rdlb` and `scene.rdla`) is read as one. All ten of MoonRay's published example scenes re-render as the same picture after a trip through Modo.
- **MaterialX import**: a `.mtlx` material becomes a material of its own kind in the Shader Tree, with controls for the values and images its file names.
- **Curves and hair**: a mesh's curves render as tubes or ribbons, with width, taper and UVs along the length; hair can be grown from guide curves, held to a scalp mesh. (In the releases MoonLightIPR draws them as tubes of polygons; on the branch they are true curves.)
- **Modo parity for lights, daylight and standard materials**: Modo's lights, physically based daylight (with its sun disc) and the standard material's specular, roughness and Fresnel are translated by measurement against Modo's own renderer.
- **A leaner preview window**: one toolbar with a single Render/Stop button, IPR, engine, buffer, exposure, region and a focus picker; render settings on the Render item; one-click Cryptomatte; a working time estimate.
- **MoonRay materials on objects, in place of material overrides**: select a mesh and assign a MoonRay material to it. Each is a material of its own kind with its own properties form. The separate MoonShine and MaterialX override layers of earlier versions are no longer offered; scenes that hold them still load and render.
- **A redesigned graph editor**: its own window that does not block Modo, a gridded canvas, compact nodes, an add-node search, and a proper control for every property, including ramps and a UV map chooser.
- **Editing that goes both ways, live**: a material can be edited in the graph editor, in its properties form or in the Shader Tree; a change in one shows in the others, and with IPR on the preview follows each change as it is made, without a re-read of the scene. MoonLightIPR follows lights, transforms and materials even while they are being dragged.
- **ACES by default**: the preview's view transform starts as ACES for an sRGB monitor, with no configuration file to find. Plain sRGB and others remain as choices.
- **Heavy scenes**: meshes of 5,000 polygons or more are read from Modo in one call by the native adapter, and written out for MoonRay several times faster. GPU renders with many outputs have four times the room they had, and fall back to the CPU rather than stop if that still runs out.

### The graph editor

![The material graph editor with a MoonRay material](docs/images/graph-editor.png)
*A MoonRay material in the graph editor: nodes to add on the left, the graph in the middle, and a control for every property of the selected node on the right. Edits here, in the material's form and in the Shader Tree show in each other, and IPR follows them.*

![The graph editor with an imported MaterialX material](docs/images/graph-editor-materialx.png)
*An imported MaterialX car paint. With no node selected the panel shows the material's own controls: the colours, numbers and images its file names.*

### Curves as tubes

![Curves rendered as tubes, in MoonRay and in MoonLightIPR](docs/images/curves-tubes.jpg)
*A mesh's curves, splines and line polygons rendered with a width at the root and at the tip: MoonRay on the left, MoonLightIPR on the right. The gold strands taper to a point; the red ones keep their width.*

### Imported MoonRay scenes, before and after

In each pair, MoonRay's render of the scene from its own files is on the left; on the right is the same scene after it was imported into Modo and rendered through the plugin. Small, low-sample test renders; [docs/images](docs/images/README.md) has the scenes' authors and licenses.

| | |
|---|---|
| ![Bedroom](docs/images/rdl-bedroom.jpg) | ![Country Kitchen](docs/images/rdl-country_kitchen.jpg) |
| Bedroom (SlykDrako, CC0) | Country Kitchen (Jay-Artist, CC BY) |
| ![Modern Hall](docs/images/rdl-modern_hall.jpg) | ![Contemporary Bathroom](docs/images/rdl-contemporary_bathroom.jpg) |
| Modern Hall (NewSee2l035, CC BY) | Contemporary Bathroom (Mareck, CC0) |

### Imported MaterialX materials

![A wood from a MaterialX library, in MoonRay and in MoonLightIPR](docs/images/moonlightipr-materialx-TH_Wood_Table.jpg)
*TH Wood Table from [AMD's GPUOpen MaterialX Library](https://matlib.gpuopen.com/main/materials/all), imported from its `.mtlx` file: MoonRay on the left, MoonLightIPR on the right.*

![Car paint flakes close up, in MoonRay and in MoonLightIPR](docs/images/materialx-flakes.jpg)
*The flakes of the library's Car Paint, close up: MoonRay on the left, MoonLightIPR on the right. The flakes are in the reflection, driven by the file's own flake textures.*

![The car paint in the preview window with each engine](docs/images/materialx-flakes-preview.png)
*The same material at a normal viewing distance in the preview window, with MoonRay and then MoonLightIPR chosen. MoonLightIPR's denoiser softens the flakes at this distance until the picture has gathered more samples.*

### View transforms

![One render shown as sRGB, ACES and highlight compression](docs/images/view-transforms.jpg)
*One linear render shown three ways: plain sRGB, ACES (the default), and highlight compression + sRGB. Modern Hall by NewSee2l035, CC BY.*

### MoonLightIPR beside MoonRay

![Lights that are not normalized, in MoonRay and in MoonLightIPR](docs/images/moonlightipr-entity_unnormalized.jpg)
*MoonRay on the left, MoonLightIPR on the right: a rect, a disk and a sphere light. [moonlightipr/README.md](moonlightipr/README.md) has more pairs and the measured differences.*

## Currently implemented

- Native Windows rendering: CPU/AVX and NVIDIA XPU, with XPU → Vector → Scalar fallback.
- Interactive preview: dockable window, live updates, draft and region rendering, a colour probe, worker-tile/bucket overlays, and the MoonLightIPR GPU engine.
- Materials: native MoonRay materials with their own forms, a visual node editor, material preview, and MaterialX import.
- Modo scene translation: standard and Principled materials, image textures, normal/bump maps, procedurals, lights, daylight, environments, subdivisions, instances, replicators, curves and hair—with the limits below.
- MoonRay items: lights, light filters, cameras, analytic shapes and volumes with their own properties.
- Render outputs: configurable AOVs, Cryptomatte surface categories, buffer switching, deep EXR, texture baking, and denoising (OptiX or Open Image Denoise) that survives a stopped render.
- Workflow tools: ACES/sRGB/OCIO view transforms and LUTs, animation output and recovery controls, an asset library with MoonRay's example scenes, and RDL scene import.

## Known issues in 0.3.51.1

The ones you are most likely to meet:

- Very smooth highlights (roughness under about 0.2) are dimmer than Modo's: about three quarters as bright under GTR, less under Blinn and Ashikhmin.
- Under Principled, Modo's diffuse gets brighter with roughness and MoonRay's does not.
- Hair in MoonLightIPR is close to MoonRay's but not exact.
- A glowing VDB volume, or a light with a cookie filter, renders in MoonRay's slower scalar mode; the plugin switches for you and says so.
- Draft assumes an ordinary lens: a fisheye or spherical camera's draft does not line up with its render.

Every open issue is in the [issue tracker](https://github.com/Pbaroque20/MoonRayForModo/issues). Found something else? Please report it there.

## Limitations

- **Windows and Modo 16.1v9 only.** XPU and MoonLightIPR need an NVIDIA GPU; they have been exercised on an RTX 3090 only.
- **MoonLightIPR is an approximation.** It matches MoonRay closely on many scenes but not all; [moonlightipr/README.md](moonlightipr/README.md) says how closely, scene by scene, and what it leaves out.
- **Modo parity is partial.** Only Modo's own lights and standard/Principled materials are matched. Blinn and Ashikhmin highlights are matched to Modo's by measurement (the lobe, roughness and strength that came closest to Modo's own renders), closely once the roughness is 0.2 or more and loosely below that; a roughness driven by an image is not remapped. A Modo material's smoothing angle is not read, so a box Modo draws with flat faces is smoothed unless the MoonRay material settings say otherwise. Under Principled, Modo's diffuse brightens with roughness and MoonRay's does not. Anisotropy is untested, rough environment reflections come out dimmer in MoonRay, and remaining Shader Tree effects, some masks and light linking are not translated.
- **MaterialX is a supported subset**: Standard Surface, OpenPBR and glTF surfaces made of images, arithmetic and UV transforms. Nodes outside that subset are not read.
- **RDL import leaves some things out**, and names each in its report: motion (the scene comes in as it stands at shutter open), values that differ face by face or point by point, subdivision creases, authored normals and light filter sets.
- **Geometry**: some instancing, motion, subdivision, UV-projection and normal-map cases differ from Modo. A mesh that mixes polygon kinds or needs per-polygon projection is read the slower way.
- **Cryptomatte**: volume coverage is unfinished; ID previews are not an interactive matte-selection tool.
- **Preview**: some edits still need the whole scene read again; with a denoiser on, the denoised view is off while Live follows the scene. Safe Denoising and Continue are for MoonRay with Live off.

## Still to implement

- Fur guides, and the fur vector and width maps.
- More of Modo's material: the Principled model's diffuse (which brightens with roughness in Modo) and smooth highlights under every model.
- Per-face and per-point values (primitive attributes) with a form for editing them.
- Motion from imported RDL scenes as Modo animation; subdivision creases and authored normals on import.
- Motion blur while the preview follows edits; the remaining Shader Tree effects and masks.
- Modo 17.1 on Windows, then macOS.
- Broader validation: other GPUs and drivers, clean-machine installs, very large scenes, recovery under load, and colour matching.

Each of these, and what MoonRay documents that the plugin has no control for yet (display filters, Alembic and USD procedurals, Arras and more), is in the [issue tracker](https://github.com/Pbaroque20/MoonRayForModo/issues).

**Production readiness:** this is an experimental development build, not a production-certified release. It has been exercised on one machine. Each release note says what was and was not checked.

Detailed implementation notes and recorded checks are in [docs](docs/). Plugin licensing is in [LICENSE](LICENSE); MoonRay and bundled assets retain their respective licenses. MoonLightIPR, the GPU preview engine, was created by Raphael Tobar and is under the same MIT License; it is not a DreamWorks Animation product and is not affiliated with or endorsed by DreamWorks Animation (see [moonlightipr/NOTICE.md](moonlightipr/NOTICE.md)).
