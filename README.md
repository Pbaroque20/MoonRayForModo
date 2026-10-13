# MoonLightIPR

This is the development branch of [MoonRay for Modo](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo), where **0.4**, the next version, is built and tried. For the plugin itself, its download and its installation, see the [main page](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo).

**MoonLightIPR** (echoing DreamWorks' earlier rasterizer MoonLight) is the plugin's fast GPU preview. It shows an approximation of what MoonRay will render and updates quickly after each edit. Final renders always come from MoonRay.

The current release is [0.3.51.3](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.3.51.3).

## Coming in 0.4

Not released yet. More detail and pictures are in [What's coming in 0.4](docs/WHATS_NEXT.md).

**New**

- **Compositor**: a node graph over a finished render's buffers, in Options > Compositor: merge, colour correction, filters such as blur, glow, sharpen and vignette, and mattes. Nothing is rendered again.
- **MoonLightIPR Playblast**: renders an animation on the graphics card and plays it back. In the MoonRay menu and the preview's Options.
- **Three engines**: **MoonRay** for the full render; **MoonRay LS** for a quick low-sample render; **MoonLightIPR** updates after each edit once you press **RT Off** to switch realtime on.
- **Pixel samples for MoonRay LS and MoonLightIPR**, in the preview's Preferences.
- **Important Parts First**: MoonRay renders the buckets with the most detail before the plain ones, with or without Smart Render.
- **Smart Render**: MoonRay stops by itself once the picture is clean enough for the denoiser, and denoises it. Right-click the picture to choose Draft, Medium or Fine.
- **File > Open reads MoonRay scenes** (`.rdla`, `.rdlb`), as does File > Import.
- **Sampling shown beside the picture size**, such as "Uniform 16 ps", and new scenes start on uniform sampling.
- **The MoonRay menu is regrouped** by what each entry is for.
- **Modo fur without a limit**: every fibre Modo would grow, each as thick as the Fur material says. Remove Base Surface is followed.
- **Keep Fine Detail** when denoising: fur, hair and curves stay sharp over a denoised surface.
- **Cellular, Wood, Weave and Ripples** layers render.
- **The preview follows Modo's color management** by default, and names the view and LUT at the foot of the window.
- **Environment lighting preference**: always, or only with Modo's Global Illumination on.

**Faster**

- **Dragging with realtime on is much smoother**: MoonLightIPR updates quickly after drag.
- **Draft** redraws in about a third of a second after a move, where it took over a second, and follows the scene by itself.
- **Stop keeps a whole picture**: MoonRay finishes the tiles it is on, so nothing is left dark or blocky.
- **One pass, not three**: a MoonRay preview no longer starts over twice, and is about a third shorter.
- **A steadier time-left estimate**: one countdown for the whole render.
- **An idle MoonRay uses no processor.**

**Better pictures**

- **Denoised Beauty just works**: choose it in the list, with nothing to set up.
- **Safe Denoising** is on the picture's right-click menu and shows the render as it goes.
- **Reduced dark blocks** while MoonRay renders.
- **MoonLightIPR is much closer to MoonRay** on layered materials, glass, coats and see-through shadows.
- **Rough Principled materials** are no longer dark at low angles.
- **Hidden items stay hidden**: an item with its eye off does not render, and a Shader's Cast Shadows switch is followed.
- **Imported MoonRay lights** are no longer far too bright.
- **Bump and normal images show on subdivision surfaces** in MoonRay.
- **An image layer's Low Value and High Value** are followed.
- **The Notices button is coloured** when there is something to read: yellow for notices, red for errors.

Some of these need a newer MoonRay, so 0.4 brings a new runtime ZIP.

![The preview window with MoonLightIPR chosen and realtime on](docs/images/preview-engines.png)
*MoonLightIPR chosen, RT On.*

![The compositor](docs/images/compositor-editor.png)
*The compositor: the beauty graded, given a vignette and sharpened, with the nodes to add listed on the left.*

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

- **Safe Denoising**: stop a MoonRay render at any time after a first pass and keep it, denoised. **Continue** then takes it up where it stood.

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
- [What was new in 0.3.51](docs/WHATS_NEW_0351.md)
- [What was new in 0.3.50](docs/WHATS_NEW_0350.md)

Developed by Raphael Tobar with AI assistance. MoonLightIPR is under the [MIT License](moonlightipr/LICENSE) and is not affiliated with DreamWorks Animation; see [moonlightipr/NOTICE.md](moonlightipr/NOTICE.md). Plugin licensing is in [LICENSE](LICENSE).
