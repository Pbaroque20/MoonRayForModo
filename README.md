# MoonLightIPR

This is the development branch of [MoonRay for Modo](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo), where the next version's preview features are built and tried. For the plugin itself, its download and its installation, see the [main page](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo).

**MoonLightIPR** (echoing DreamWorks' earlier rasterizer MoonLight) is the plugin's fast GPU preview. It shows an approximation of what MoonRay will render and follows your edits as you make them. Final renders always come from MoonRay.

The current release is [0.3.51.3](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.3.51.3), which holds everything below. What is built here next will be listed as it comes.

## Built since 0.3.51.3

Not released yet. The full list, with pictures and what was checked, is in [What's next](docs/WHATS_NEXT.md).

- **A compositor**: Options > Compositor opens a node graph over the buffers of a finished render (merge, grade, blur, glow). Its result is the **Composite** buffer in the list, and Render EXR writes it beside the EXR. Nothing is rendered again.
- **Three engines, no Live box**: **MoonRay** for the full render; **MoonRay LS** (low sample) and **MoonLightIPR** follow the scene as you edit it. Those two start switched off; press **RT Off** and it reads **RT On**, lit.
- **Safe Denoising shows the render as it comes on**, and a stop says how far behind the picture it kept is.
- **A cleaner live picture**: no dark blocks while MoonRay renders, and none of their marks in a stopped render's denoised picture.
- **Stop keeps the picture, quickly**: a normal MoonRay render stopped part way is kept and denoised in about a second.
- **Tile outlines move evenly**, in pastel blue, and fade when a tile is done.
- **An idle MoonRay rests** instead of keeping a processor core busy, and ends itself if Modo goes away.
- **What Modo hides is hidden**: an item with its eye off does not render, and MoonLightIPR follows a surface's visibility to the camera, indirect light, reflections, refractions and shadows.
- **Two lines under the picture**, so the status is read whole.
- **Denoised Beauty denoises by itself**: choose it in the list and the picture is denoised, with no denoiser to set first. MoonLightIPR always has Beauty and Denoised Beauty.
- **MoonLightIPR is much nearer to MoonRay** on layered materials, glass, coats and the shadows of see-through things.
- **Rough Principled materials are no longer dark** seen at a low angle, and a Shader's Cast Shadows switch is followed.
- **Moving something is followed far faster**: a draft of a 266-mesh scene redraws in 0.3 seconds where it took 1.3.
- **Draft** follows the scene by itself, has black around the camera's frame and never shows a stale render when switched off; **Render** and **RT** switch it off; **Region** no longer zooms the view.
- **Safe Denoiser Mode is said on the picture**, at its foot, while Safe Denoising is on.
- **The preview window opens on MoonRay with the crest** and renders nothing until asked.

Some of these need the MoonRay of the next runtime, so the next release brings a new runtime ZIP.

![The preview window with MoonLightIPR chosen and realtime on](docs/images/preview-engines.png)
*MoonLightIPR chosen: RT On is lit, and the status has a line to itself.*

![The compositor: the nodes to add on the left, the graph, and the selected node's settings](docs/images/compositor-editor.png)
*The compositor: the beauty graded, given a glow, and sent to the Composite buffer.*

## Released in 0.3.51

**The preview window**

- **Draft**: the scene as clean outlines, with nothing rendered until you drag a **Region**. Then only that part is rendered, among the lines.
- **Region** is a button: press it and drag a rectangle in the picture.
- **R, G, B, A** channel buttons, a **colour probe** under the pointer, and **EV** and **Gamma** with one-click resets.
- **Export AOVs as Images** from the picture's right-click menu.
- **MoonRay's crest** in the window before the first render; click it to start one.

![Draft with a region rendered among the lines](docs/images/preview-draft-region.png)
*Draft, with a region rendered among the lines.*

**Rendering with MoonRay**

- **Safe Denoising**: stop a MoonRay render at any time and keep it, denoised. **Continue** then takes it up where it stood.

![A MoonRay preview stopped part way, kept and denoised](docs/images/safe-denoising.png)
*Stopped part way, kept and denoised, with Continue on offer.*

**In the MoonLightIPR preview**

- **Hair** shaded as hair, with MoonRay's hair material.
- **Skin** with MoonRay's skin material, including light glowing through thin parts.
- **Curves** drawn as real strands, as ribbons or round tubes.
- **Fog** inside a MoonRay box or sphere, and **VDB clouds and smoke** from a file, with their own glow. VDB volumes can overlap.
- **Rod, barn door, cookie and VDB light filters**, on MoonRay lights and on Modo lights.
- **Textures on every kind of light**, not only rect lights.
- **Render region**, and **mesh lights seen glowing**, clean in MoonRay too.

![Hair, MoonRay on the left and MoonLightIPR on the right](docs/images/moonlightipr-hair_dark.jpg)
*Hair in MoonRay (left) and in the MoonLightIPR preview (right).*

![A VDB cloud, MoonRay on the left and MoonLightIPR on the right](docs/images/moonlightipr-vdb_cloud.jpg)
*A cloud from a VDB file, MoonRay (left) and MoonLightIPR (right).*

**Closer to Modo**

- **Blinn and Ashikhmin materials** now match Modo's highlights, also where an image drives the roughness (in MoonRay).
- **The sun's disc** in a physical sky has Modo's colour and follows Disc In-Scatter.

**Working faster**

- **Assign a MoonRay material to selected polygons**, with a name, type, colour and smoothing angle.
- **MoonRay's materials in the Shader Tree's Add Layer list**, under Custom Materials.
- **A MoonRay page in Modo's Preferences**, including having the M key open MoonRay's Assign Material.
- **The asset library shows pictures** of saved materials, models, scenes and textures, each with one button for what it is for.
- **MoonRay Content**: MoonRay's example scenes as a third ZIP of the release, merged into the kit folder.
- **Graph editor**: big graphs open on the output node and zoom freely.
- **Ramps** open in the ramp editor straight from a material's properties.
- **Light Path Expressions** has its own entry in the MoonRay menu and under Advanced in the render settings.
- **Dragging the sun or an environment light** updates the preview when you let go.
- **Dense hair** grows and re-renders several times faster.
- **Smoothing** follows Modo's smoothing angle, and can be changed in a MoonRay material's properties.
- **Opening a large MoonRay scene** shows how far it has come.
- **A material that is on nothing says so** in Notices, with the polygon tag to set.

**More of MoonRay**

- **Bake Selected Mesh to Texture** in the MoonRay menu.
- **Deep EXR** output, saved beside the render.
- **More render settings**: volume, hair and presence bounces, a Volumes group, clamping, pixel filter and texture blur.
- **More one-click outputs**: indirect diffuse and glossy, reflections, subsurface, diffuse without shadows, albedo, motion vectors.
- **Light path presets**, and a plain message when an expression is mistyped.
- **Cast no shadow onto chosen objects**, per object, in Light Links, Emitters and Volumes.
- **Width and height of a MoonRay light scale together**, with Modo's own link button.
- **MoonRay light items can be linked**, and imported MoonRay scenes keep their light, shadow and shadow receiver sets.
- **Subsurface Neighbours** in a material's properties: the objects that share its subsurface light, so no seam shows where they meet.
- **OpenPBR and glTF materials** import from MaterialX files.
- **Modo's Fur material** grows fur in MoonRay and in the preview, with its curls, clumps, kink, frizz, strays and weight maps. Guides are not read yet.

![Modo's Fur material with curls, clumps and a weight map](docs/images/fur-extras.jpg)
*Modo's Fur material in MoonRay: curls, clumps with kink, and fur thinned by a weight map.*

## Known issues

The ones you are most likely to meet:

- Very smooth highlights are dimmer than Modo's, though closer than before under GTR.
- Hair in MoonLightIPR is close to MoonRay's but not exact.
- A glowing VDB volume, or a light with a cookie filter, renders in MoonRay's slower scalar mode. The faster modes do not draw them rightly in this build.
- Tested on one machine (RTX 3090) only.

Every known issue, and what is still to implement, is in the [issue tracker](https://github.com/Pbaroque20/MoonRayForModo/issues). Found something else? Please report it there.

## More

- [How MoonLightIPR works, what it draws and how closely it matches MoonRay](moonlightipr/README.md)
- [The plugin's main page](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo), with the full feature list, limitations and installation
- [Everything coming in 0.3.51](docs/WHATS_NEW_0351.md)
- [What was new in 0.3.50](docs/WHATS_NEW_0350.md)

Developed by Raphael Tobar with AI assistance. MoonLightIPR is under the [MIT License](moonlightipr/LICENSE) and is not affiliated with DreamWorks Animation; see [moonlightipr/NOTICE.md](moonlightipr/NOTICE.md). Plugin licensing is in [LICENSE](LICENSE).
