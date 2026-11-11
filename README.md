# MoonLightIPR

This is the development branch of [MoonRay for Modo](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo), where the next version is built and tried. For the plugin itself, its download and its installation, see the [main page](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo).

**MoonLightIPR** (echoing DreamWorks' earlier rasterizer MoonLight) is the plugin's fast GPU preview. It shows an approximation of what MoonRay will render and updates quickly after each edit. Final renders always come from MoonRay. What of a Modo scene it draws is in [its audit table](#modos-features-in-moonlightipr).

The current release is [0.5.3.2](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.5.3.2). **Built on MoonRay [2026.29.1](https://github.com/dreamworksanimation/openmoonray/releases/tag/v2026.29.1)** (OpenMoonRay's latest release; MoonRay 18.4), with the plugin's own patches for Windows and the preview.

## New in 0.5.4 (coming)

- **Modo's Processing textures**: Gradient reads Incidence, Slope, Distance, Screen and Back Facing, as well as its other inputs; Occlusion, Variation by Item, Mesh Part and Particle, and Tension (Area and Angle) render in all three engines, matching Modo's own render to within about 0.03. A Gradient also reads Texture U and V (UV map, Solid and Planar along Z), Texture Value over a Constant, Surface ID, Bump and Displacement Height, and Clip Distance.
- **Render Settings tidied**: MoonLightIPR's Render Samples has its own MoonLightIPR group after XPU2 Sampling and is saved with the scene (it was a Preview Preference); MoonRay's Sampling group is now XPU Sampling; XPU2's Most Samples is gone (XPU2 keeps 16 times the average as its limit). Displacement Tessellation, Adaptive Error Override and Dicing Frame (Global Switches), missing from the form since they were added, are there.
- **Headless MoonRay renders**: the kit's `scripts/export_moonray.py` writes a scene for MoonRay from Modo's command-line version, with no window; [how to render headless](docs/INSTALLATION.md#rendering-headless-no-modo-window); and `runtime-xpu2\moonray_xpu2.exe render -in <scene> -out <beauty.exr>` renders it with XPU2, with no Modo.
- **Modo's Process texture** (Hue, Saturation, Value, Hue Shift) renders in all three engines as in Modo.
- **MoonLightIPR draws bokeh images, diffuse transmission maps and the motion of meshes that change shape**, and an environment flipped with Vertical Wrap -1 flips rightly.
- **16K textures stay on XPU2**, a VDB's fire renders when XPU2 hands a scene to MoonRay, and **Select Volume Here** in the preview's right-click menu.
- **Flipping an environment image (Horizontal Wrap -1) no longer changes its lighting**: the image is mirrored at its full size.
- **MoonRay graph images are found when a scene has moved**, as Modo's image clips are, and Relink Missing Images lists them.
- **Sharp textures in a MoonLightIPR Render**: full-size images, compressed on the graphics card so big scenes fit, and kept in the computer's memory where they still do not.
- **Render Animation with MoonLightIPR** (an Engine in its window), **motion vectors** in MoonLightIPR's AOVs, and Denoised Beauty after a MoonLightIPR Render without rendering again.
- **VDB sequences stay on XPU2**, a numbered VDB file plays as a sequence at once, and VDB shapes show their box and a point cloud in the viewport.
- **XPU2's sampling settings follow the engine in use**, and XPU2 realtime offers the denoised beauty, with the beauty, alone.
- **MoonLightIPR Render at the camera's resolution** (Preview Preferences), **Select Mesh Here** in the picture's menu, finer graph sliders.
- **AOVs in MoonLightIPR, for motion graphics**: Diffuse, Glossy, Emission and Environment background, which add up to the beauty, and Alpha, Camera depth, Shading normal, World position, Albedo, Motion vectors (wherever something moves) and a Shadow matte (how much of the direct light was blocked, 0 lit to 1 in full shadow), in the buffer list. All are gathered with the beauty from its first sample, so choosing one shows it at once, and **Export AOVs** (right-click the picture) saves the ones ticked as EXRs, a multilayer EXR or pictures, exactly as MoonLightIPR rendered them.

  ![MoonLightIPR's AOVs of a glass dragon: beauty, diffuse, glossy and albedo above; shading normal, world position, camera depth and the shadow matte below](docs/images/moonlightipr-aovs.jpg)
- **Fewer fireflies in MoonLightIPR**: it clamps from what the camera sees by default (its own Clamp From Bounce, 0), so Sample Clamp also takes the specks seen through clear glass; and it follows MoonRay's Roughness Clamp, on the materials MoonRay renders as DwaBase and on hair. The clamps are in Render Settings' MoonLightIPR group.

  ![A refractive dragon in MoonLightIPR: Clamp From Bounce 1 on the left, speckled with red, and 0 on the right, the new default](docs/images/moonlightipr-fireflies-dragon.jpg)

  ![Rough gold balls among near-mirror metal, Roughness Clamp off above and 1 below, MoonRay left and MoonLightIPR right: the clamp blurs and brightens their reflections alike](docs/images/roughness-clamp-engines.jpg)
- **Render missing frames continues a sequence**, taken further or finished after an edit, keeping the frames already there; **Convert to MoonRay Rect Light** on an area light's right-click menu; MoonLightIPR's Render Animation writes the denoised beauty beside the beauty; no more .postprocess folders beside frames.
- **Render with MoonLightIPR**: with RT off, Render is no longer greyed: MoonLightIPR gathers Render Samples a pixel (Render Settings > MoonLightIPR, 2000 unless changed, saved with the scene) as fast as the graphics card can, and stops. The label under the picture says how many samples a pixel the picture holds as it comes (137 / 500 ps), in realtime too.
- **Rhizome: render across the studio's machines** (MoonRay > Rhizome: Decentralized Rendering): this frame or a range rendered by XPU2 on every machine running a Rhizome node, the picture as one machine renders it. The same window starts a node on this machine, shows the machines at work, approves new ones and adds the Windows Firewall rule. Windows only.

## New in 0.5.3.2

- **Edits that change nothing leave realtime alone**: a value entered as it already is, in the graph editor or a MoonRay material's Properties (0 where it was 0, 0.3 where it was 0.30000000000000004), and Schematic work (workspaces, nodes added, moved or taken out) no longer start MoonLightIPR or XPU2's realtime again, nor read the scene whole.
- **One resolution for every realtime preview**: Preview Preferences' Realtime preview resolution now goes down to 1/8 and 1/16 of the render's, and MoonRay LS renders at it as MoonLightIPR and RT do. LS's own Width limit is gone, under which a tall picture stayed tall.
- **EV and gamma by dragging**: press anywhere on the preview window's EV or gamma field, its number or its arrows, and drag right or up for more, left or down for less; Ctrl for fine steps, Shift for coarse. A click on an arrow steps once; a click on the number lets you type. The picture follows exposure as it changes, where holding an arrow showed nothing until it stopped. The MoonShine graph's numbers drag the same way (a tester's report: their steps were 0.1 only, and the two arrows a few pixels apart): Ctrl drags in hundredths, and one drag is one undo.
- **MoonLightIPR clears its noise sooner**: the preview draws its samples from [OpenQMC](https://github.com/AcademySoftwareFoundation/openqmc), the Academy Software Foundation's sampling library, so each pixel's samples spread evenly instead of by chance. For the same noise it needs about half the samples where the light comes from lamps, an environment or fog, and fewer on VDB fog, hair, depth of field and glass. A sample takes up to about a tenth longer; the cleared picture is unchanged.
- **RT goes off after a MoonLightIPR Playblast**: once its frames are done, or it is stopped, RT says Off and one press follows the scene again. It stayed On with nothing updating until another engine was chosen.
- **Select a material from the picture**: right-click a surface in the preview window and choose Select Material Here: the material it wears is selected in Modo, found as Focus Here finds a surface's distance.
- **Toon lines in a colour, with their own alpha** (issue 134): a Toon filter's Ink Color draws its lines in any colour, the Compositor's Ink Lines node lays them over a picture, and lines saved or rendered alone keep their own alpha. A MoonRay Source Override, on by default.

  ![Toon lines in a colour over the shading](docs/images/toon-ink-color.png)

- **Toon lines smoothed**: outlines no longer step with the pixel grid. A MoonRay Source Override, on by default.

  ![Toon outlines smoothed along their direction](docs/images/toon-smooth-lines.png)

- **VDB fire from temperature or flames grids**: a VDB whose emission grid holds single values, as EmberGen, Houdini and Blender write fire, now glows in MoonRay, XPU2 and MoonLightIPR, coloured by the VDB volume's incandescence gain mult. MoonRay refused such a grid and left the whole VDB out. A MoonRay Source Override, on by default.

  ![JangaFX's free EmberGen explosion glowing from its flames grid: MoonRay left, XPU2's graphics card right](docs/images/vdb-fire-flames-grid.png)

- **Alembic fluids and other changing meshes**: set an object's Geometry file (production settings) to an .abc, and the kit reads its meshes itself each frame, even ones whose points and faces change, as a fluid mesher's do (Modo's own loader shows one frame of those), blurred along the file's velocities. A mesh that changes during the shutter no longer stops a render with "Motion blur requires stable topology".
- **VDB sequences**: untick a VDB shape's static (now beside its file) and the numbered files beside the one you chose (fire_1.vdb, fire_2.vdb...) play with the timeline, with a frame offset, and the volume hidden or held outside its frames.

  ![The EmberGen explosion as a VDB sequence, coloured by its temperature: frames 20, 45, 70 and 100, rendered on XPU2's graphics card](docs/images/vdb-fire-sequence.png)

- **Scene Proxies render with their own materials**: each proxy's geometry once, where it stands, shaded by the scene file it loads, as Modo renders it. Modo may crash as it quits with such a scene still open (Modo's own; your work and settings are kept).
- **Imported Alembic fluids blur**: a mesh brought in with File > Import of an .abc renders from the file itself, its own points and faces at each frame, blurred along the file's velocities. Modo's own import stretched one fixed mesh and had no velocities to blur a fluid mesher's mesh with.

  ![A fluid mesher's Alembic mesh at frames 90, 120, 150 and 180, its faces changing every frame, its drops blurred along the file's velocities, rendered on XPU2's graphics card](docs/images/alembic-fluid-frames.png)

- **VDB fire coloured by its temperature**: turn on a VDB shape's blackbody colour and choose its temperature grid as the emission grid: the fire glows deep red where it is cool, orange, then yellow-white where it is hottest, with kelvin at 1 to make it hotter or cooler. In MoonRay, XPU2 and MoonLightIPR. A MoonRay Source Override, on by default.

  ![The EmberGen explosion coloured by its temperature grid, rendered on XPU2's graphics card](docs/images/vdb-fire-blackbody.png)

- **MoonLightIPR keeps a VDB fire's colour**: an orange incandescence no longer glows white in the preview.
- **Glowing fog from maps on XPU2's graphics card**: a volume whose glow or colour comes from procedural maps (a gradient, a noise) renders on the card instead of the processor. Maps that read image files still glow on the processor.

  ![A fog box glowing orange to blue from a gradient map, rendered on XPU2's graphics card](docs/images/xpu2-mapped-glow.png)

- **Volumes render faster in XPU2**: VDB clouds and glowing fog render in about two thirds of the time on the graphics card, with the same picture.
- **A smaller XPU2 shader compile, with a memory meter**: Compile XPU2 Shaders takes 8 to 15 minutes and well under 12 GB, where it could climb past 40 GB. Preferences shows the free memory beside the button (enough, tight or not enough); the compile needs about 8 GB free to begin and stops itself before memory runs out.

## New in 0.5.3.1

- **Mesh lights render as in Modo in every engine**: a Prototype's n-gons, or quads beside triangles, shine in their own shape in MoonRay and XPU2; a mesh emitting by its Object controls lights again; the shown Prototype is the light, not also a grey surface over it; a hidden Prototype gives no light, as in Modo. MoonLightIPR shows a Mesh Light that is Visible to Camera, and shines from the polygons' front only, as Modo and MoonRay do.

  ![Two Mesh Lights, a square and an octagon beside a quad and a triangle, lighting a ball: Modo, MoonRay, XPU2 and MoonLightIPR](docs/images/mesh-lights-engines.jpg)

- **A mesh light hidden from the camera still shows in reflections**: with Object controls' camera appearance at Hidden, other surfaces reflect the light cleanly, not blotched with the mesh's grey; MoonLightIPR follows that setting too.
- **Glowing volumes render on XPU2's graphics card**: a fog that glows (a MoonRay volume's emission) or a VDB fire (its emission grid) renders on the card with the rest of the scene, lighting the surfaces and the fog around it; before, one glowing volume sent the whole scene to the processor. Compile XPU2 Shaders once more after installing.
- **Bump node in the MoonShine graph**: under Normals and bump, a Bump node turns a greyscale height image into the material's normal, as a Shader Tree Bump layer does; Amplitude is how high white stands, in scene units. In every engine; a MoonRay Source Override (Bump node in MoonShine graphs), on by default.
- **Realtime preview resolution as a share of the render's**: Full, 1/2, 1/3 or 1/4 in Preview Preferences, in place of a width in pixels, under which a tall picture could stay at full size. A width chosen before becomes the nearest share.
- **Exported Cryptomattes open as Cryptomattes**: Export AOVs saves each with its mattes' names (CryptoObject, CryptoMaterial) and the header readers need, so Photoshop (with ProEXR or Exr-IO), Nuke and Fusion pick its mattes; several in one multilayer EXR no longer clash. Object and material Cryptomattes render together again (since 0.5.2.1 the kit refused them).
- **Checkers placed as in Modo**: a Checker's squares, through its texture locator, are the size, angle and colour Modo gives them in every engine (they were twice as large and turned).
- **A missing UV map is a notice, not a failed render**: a material whose texture reads a UV map the mesh has not (one set up on another mesh) rendered nothing, with "missing UV values"; those polygons now render with the map at 0, and a notice names the mesh, the map and the material.
- **PBR validity in Preview Preferences** too, the same switch as in Modo's Preferences.
- **Realtime with standard XPU: Off, On the processor or On the graphics card**: RT with the standard MoonRay XPU can now render on the card too, in Modo's Preferences and Preview Preferences alike.

  ![Preview Preferences: Realtime with standard XPU, and PBR validity under Diagnostics](docs/images/preview-preferences-realtime-xpu.png)

- **Heavy scenes start much sooner**: a 1.5-million-polygon car's first realtime picture came after about 2 min 20 s of preparing; it now comes in about 16 s. Smoothing by each material's smoothing angle is done in the kit's native code on all processor threads, Cryptomatte by material no longer hashes every polygon, and the mesh reader no longer makes Python lists of every point. Meshes of any size now take their material's Modo smoothing angle.
- **A scene's first realtime run is much quicker**: environment images are shrunk straight from the file, side by side (the car's three HDRs: 85 s to 15 s), and meshes whose textures lay out their own UVs, or whose materials use different UV maps, are read whole. Grey environment images are no longer black. An environment's layers are laid over one another in the kit's native code (the car's: 10 s to nothing), every mesh is read by the native adapter, and a mesh missing a UV map its texture reads is read whole too, with its notice (the car's reading: 7.1 s to 3.2 s).
- **Fur guides**: a Fur material's guides are followed in every engine, from curves on the fur's own mesh wearing its material or from a guide item, in Modo's modes: Direction, Direction + Length, Shape, Range and Clump, with Guide Range and Guide Length.
- **Fur vector and width maps**: a Fur material's Vector VMap grows each fibre along its vector, as long as it is (none where it is nothing), and its width map thins the fibres by its weight, in every engine.
- **Weight and colour maps, and creases, read at once**: a mesh's weight, RGB and RGBA maps, and a subdivided mesh's Subdivision weights, are read in the kit's native code in one call, not a point or an edge at a time (a mesh of 21,600 polygons and six maps: 1 s to 0.08 s; its creases: 0.3 s to 0.05 s). Planar, cubic, cylindrical and spherical texture projections are worked out there too (a mesh of 359,400 faces: 6 s to 0.5 s). Hair grown from guides is shaped there too, its scalp read at once and its strands kept as the grower made them (30,000 strands on a 399,000-triangle scalp: the scene read 8.4 s to 3 s, MoonLightIPR's packing 1.2 s to 0.1 s).

## New in 0.5.3

A release for its lighter use of memory and XPU2 on several devices, with a new runtime: install it, and **Compile XPU2 Shaders once more**.

- **Look-dev is lighter on Modo**: graph editor changes no longer re-read the whole scene, hidden meshes' materials are left alone, and Low Value, High Value, gamma, brightness and contrast change without reloading the scene.
- **Wired inputs are locked in Properties**, and **a material node's inputs fold into groups** (Diffuse, Specular, Clearcoat ...), connected ones always shown.

  ![A DwaBaseMaterial node with Diffuse open and its other groups folded, beside the same groups in Properties](docs/images/graph-editor-groups.webp)

- **A material's lists come up quicker** in Properties and the graph editor, **switching networks keeps the graph editor open**, and **Remove Network** removes another material's network or a loose one, after asking.
- **A cookie light filter renders in XPU2**, at XPU2's speed, where it sent the whole render to MoonRay's slow scalar mode.
- **A bokeh image turns bokeh on**, and the dw camera fields Modo's camera drives are greyed while it does.

  ![Lights far out of focus through a hexagonal bokeh image, MoonRay left and XPU2 right](docs/images/xpu2-bokeh-image.jpg)

- **XPU2 needs a third of the texture memory**: a scene with a few 8K maps that went into texture overflow mode now holds 1.4 GB of textures on the graphics card, not 4 GB, with the same picture. **XPU2 also holds less of the card**: a scene with grass peaked at 9.7 GB rather than 10.9 GB (8.7 GB without subsurface).

  ![Grass, a crop at full size: XPU2 holding its textures in floats on the left, in a third of the memory on the right](docs/images/xpu2-texture-memory-grass.jpg)

- **Depth of field in XPU2 has even grain**: a light far out of focus showed a lattice inside its bokeh disc; the lens samples now have an order of their own and every sample sequence is Owen-scrambled, so the noise is MoonRay's kind.
- **A sliver triangle no longer sends an XPU2 frame to MoonRay**: a hit on a triangle too thin for its normal in single precision failed the sample, and with it the whole frame. The grass scene fell back to MoonRay every time on the processor alone and now and then with the graphics card.
- **XPU2 uses every graphics card and every processor**: a second or third NVIDIA card renders the same picture alongside the first, and a machine with more than 64 threads uses them all. A card that can't run OptiX's denoiser hands realtime denoising to one that can, or to Open Image Denoise on the processor. Tested in simulation only, as we have one card here.
- **Device Management**: under XPU2 in Preferences > MoonRay, lists the processor and every NVIDIA card XPU2 finds, each with its own switch, and compiles XPU2's shaders for each kind of card that is not up to date: a new kind of card shows as Out of date, naming it, and only it is compiled. It replaces the Devices choice on the XPU2 page.
- **XPU2 knows NUMA**: on two-socket workstations and many-die processors (Threadripper, EPYC, Xeons with Sub-NUMA Clustering), XPU2 puts its workers on every node, feeds each card from the node nearest it, and keeps texture tiles in the memory of the node that reads them. A node that runs short moves its tiles to another before letting any go. On a one-socket machine nothing changes. Tested in simulation only.
- **VDB volumes render on XPU2's graphics card**: a VDB cloud that did not glow was handed sample by sample to the processor; the card now samples its grids itself and marches it without a table of steps, about five times faster on a test cloud with the same picture. Glowing VDBs still render on the processor.
- **Mirrored meshes face outward**: a mesh with a negative scale and normals of its own rendered black in MoonRay and XPU2 (MoonRay's own behaviour), and one without them slightly wrong; a new MoonRay Source Override, on by default, turns them outward.
- **The graph editor does not restart the preview for nothing**: moving a node, or adding one wired to nothing, no longer renders the picture again.
- **A dw material's own roughness in MoonLightIPR**: a dw Metal or Base material's roughness was taken from Modo's Material Ref tab; it is now the material's own.
- **The MoonRay Widget renders with XPU2** (whatever the preview's choice), at the size it is shown, with 1024, 2048 or 4096 samples, and a **Scale** to size the ball in scene units for curvature and other procedurals.
- **A dwVdbVolume takes its VDB file**: adding one asks for the file, and its form has Load VDB File; the VDB shape that shows it is made for it.
- **PBR validity**, a diagnostic in Preferences > MoonRay > Renderer > Diagnostics: while it is on, MoonRay XPU's and XPU2's renders hold MoonRay's PBR validity output in place of the standard outputs, and the preview window shows it. Green is a plausible material, red one out of range, yellow in between: here the dragon's bright orange is just above the brightest plausible albedo. Off, the standard outputs come back.

  ![The dragon test scene, its beauty on the left and its PBR validity on the right: the floor green, the dragon yellow](docs/images/pbr-validity-dragon.jpg)

- **Realtime with MoonRay XPU, on the processor**: an opt-in in Preferences > MoonRay > XPU; with XPU2 off, RT then follows the scene with MoonRay and MoonRay LS.
- **After XPU2 hands a scene to MoonRay XPU**, MoonRay's sampling settings are no longer greyed: they are the ones used.
- **Modo no longer crashes as it quits**: with a graph editor open, or once the preview window or a material's properties had been used, Modo could end with an error on the way out. The kit no longer looks through all of Modo's windows to find its own, puts its open windows away first, and lets go of its scene listener properly.
- **Modo's Mesh Lights shine**: a Mesh Light gave no light in MoonRay, XPU2 or MoonLightIPR. It now shines from its Prototype mesh, shown or hidden, placed by the prototype or by the light as Use Prototype Transform says, with its radiance and colour, and seen by the camera when Visible to Camera is on.
- **Alembic streams in**: a file loaded as Alembic Streaming Meshes (Modo's Alembic Mesh items) now renders, moving over time and with motion blur, as files loaded as Modo meshes with streaming deformers already did. Alembic Curves and Point Clouds take the same path, though untested.
- **An environment no longer renders red**: a grey environment, saved as one channel since the texture memory work, lit the scene red in MoonRay and XPU2; images that light the scene keep three channels.

## New in 0.5.2.2

A hotfix to 0.5.2.1, to the kit alone.

- **Smart Render and Safe Denoising follow the renderer chosen**: switching Preferences > MoonRay > XPU2 to MoonRay XPU makes them editable at once, and they work in Vector and Scalar mode whichever renderer is chosen. Smart Render chosen from the picture's menu with the Denoiser off sets one: OptiX with an NVIDIA graphics card, Open Image Denoise without.
- **Render over a draft renders at the first press**: pressed while Draft is still drawing its lines, it had to be pressed again once they were done.

## New in 0.5.2.1

A hotfix to 0.5.2, with a new runtime ZIP: install both, and **Compile XPU2 Shaders once more**.

- **Playblasts render flat out**: each frame gathers all its samples as fast as the graphics card can, without the 8 seconds a preview spreads a render over, and previews keep that pacing for drags.
- **dw Perspective and Orthographic cameras use the Modo camera's lens**: focal length, film, offsets, depth of field, F-stop, focus distance, iris blades, stereo eye and shutter are edited in the camera's own Camera and Camera Effects tabs. The switch heads the dwPerspectiveCamera tab; turn it off to use the MoonRay values there, as scenes from before do.
- **Saved pictures keep their alpha**: with Alpha among the render's outputs, Save Image and Export AOVs save the Beauty and the Denoised Beauty with it, as PNG, TIFF, Targa or OpenEXR. Export AOVs can also save every output ticked as one multilayer OpenEXR, and a group's own checkbox (Pictures, Light and the rest) ticks and unticks what is under it.
- **MoonRay starts whatever is in the Windows PATH**: a file in it, such as `cmd.exe`, no longer stops every preview and scene load with "Not a directory".
- **XPU2 needs about half the graphics card's memory**: a simple scene went from about 11 GB to 4.5 GB, at the same speed and
  with the same picture, so XPU2 runs on smaller graphics cards. A leafy scene that filled 32 GB of graphics memory and
  crashed now renders in 20 GB.

  ![A tree's leaves against the sky, rendered in XPU2 in 20 GB of graphics memory (picture: Pixelwerk)](docs/images/Leaf.webp)
  _Image provided by Pixelwerk_

- **Moving subdivision surfaces render in XPU2**: a moving mesh with adaptive subdivision, and copies of a subdivision mesh
  that changes shape during the shutter, no longer send the scene to MoonRay XPU.
- **A still mesh is no longer taken for a moving one**: XPU2 sent some scenes with motion blur to MoonRay XPU for meshes that
  do not change shape.

## New in 0.5.2

A hotfix to 0.5.1, with a new runtime ZIP: install both, and **Compile XPU2 Shaders once more**.

- **XPU2 renders Modo's procedural textures worked out through the object**, Enhance: Modo's patterns among them, with the patterns MoonRay and MoonLightIPR share. Such a scene used to go to MoonRay XPU.
- **Scenes with Modo's fur render in XPU2**: they stopped with "No Attribute named 'vertex_list_1'" and went to MoonRay XPU.
- **Render Animation renders with XPU2** where XPU2 is chosen, and so does Render to a File, with each picture shown in the
  preview as it comes. Deep images and checkpoints stay with MoonRay. Under MoonRay XPU, each frame appears as it finishes.
- **Render with MoonRay has motion blur**: Motion Blur in Render Settings, or on the Modo camera, now applies to the Render button,
  so a still no longer needs Render Animation.
- **Motion blur in MoonRay XPU2 realtime** is a Preview Preference, off by default. Updates stay sharp while you drag, and the wait
  is longer once something moves during the shutter.
- **The Render Animation window opens with the scene's settings**: its frames, step, frame rate and Motion Blur, and it keeps
  what you last rendered with, in the scene.
- **Alpha reaches every file that can hold it**: a denoised EXR, and a PNG, TIFF or Targa saved from a render, now have the render's
  alpha while Alpha is on in Render Settings. Where the alpha is 0, as on a visible background, those pictures are transparent.
- **Realtime Sample % starts at 30%**, so realtime settles sooner. A value you set is saved with the scene, and a scene that already has one keeps it.
- **The graph editor's marquee starts at once**: it draws from the first pixel, and the property list fills when you let go, so clicking and marquee selecting no longer pause.
- **Playblasts show motion blur**: when Motion Blur is on in the scene or its camera, or in MoonLightIPR's Preview Preferences.
- **Hues and angles have a slider in the graph editor**: hue shift, rotation and the other values that go round a circle, beside their number.
- **The Toon filter's form** has Close Line Gaps, which it was missing, and its later controls change the right settings again.
- **Sliders in the compositor**: Blur, Glow, Sharpen and Median radius and Vignette have a slider beside their number.
- **Bokeh settings say what they do**: the two bokeh weight settings, which MoonRay does not use, are marked as having no effect, and Modo's Edge Weighting gets a notice.
- **A clearer notice for a texture with nowhere to go**: it names the material and the effect, and says where to move the texture.
- **A round light says when it stays round**: an uneven scale on a dwDiskLight, or another round MoonRay light, is averaged, and a notice now says so. dwRectLight has Width and Height.
- **Notices name more of what is left out**: Modo's other material kinds, Principled sheen, shadow distances and fog in MoonLightIPR, and weight maps in scenes with replicators or some masks. A group mask set to Normal Multiply no longer stops a scene reading; it is drawn as Normal.
- **Frames as JPEG, PNG, TIFF or Targa alone**: Render Animation can save just those, with no EXR left beside them. Those frames are denoised when the render is.
- **Denoised and composite frames keep their number last**: `frame.denoised.0001.exr` and `frame.composite.0001.exr`, so other programs read them as sequences.
- **Frame digits**: choose how many digits frame numbers have, so 4 gives `frame.0001.exr`.
- **Several sequences in one folder**, each under its own file prefix.
- **RT and Render come back after an output render**, with no need to switch engine and back.
- **XPU2 no longer stalls on a second motion-blurred picture**: from the second frame in a session, a scene with motion blur or a
  volume only the CPU renders waited for good.
- **XPU2 renders moving objects on the GPU**: moving meshes, subdivision surfaces, instances, curves, fog and any number of moving
  lights, and points whether moving or still, no longer send their samples, or the whole scene, to the CPU. Test scenes finished
  about 2.6 to 8.5 times sooner; a scene with nothing moving takes about 2 to 3% longer.
- **Fog no longer goes missing from XPU2's CPU samples**: a volume on a mesh with no material of its own was left out of what the
  CPU renders, which could thin it where the CPU and GPU render together.
- **MoonRay cameras no longer render black up close**: a dwPerspectiveCamera or another MoonRay camera kept MoonRay's near clip of 1 m,
  so within a metre of a surface it looked at the surface's dark inside. It now sees as near as a Modo camera, unless you set Near yourself.
  A new MoonRay camera also starts where the render camera stands, not at the origin, inside whatever stands there.
- **Soft edges no longer flare in PNG, TIFF and Targa**: with alpha and a visible environment, soft edges such as motion blur came
  out too bright, because the environment was divided by the alpha along with the surface. Measured on motion blur. It is now taken out first. Needs the new runtime.
- **The Environment background output has its picture**: MoonRay lost a light seen past every surface from light outputs, so this output was black.
  Lights seen by the camera in light outputs, in MoonRay Source Overrides, is on by default. EXRs with alpha now hold this channel too.
- **Round lights under an unevenly scaled parent stay on**: a disk, sphere, spot or cylinder light there now renders round, at the mean of
  its scales, in every engine. MoonRay would have switched it off, and XPU2 refused the scene.

## New in 0.5.1

A hotfix to 0.5, with a new runtime ZIP: install both, and **Compile XPU2 Shaders once more**.

- **Realtime Sample %** in the preview's preferences as well as Render Settings, its new name.
- **The About window gives a build number** after the version.
- **Automatic Presence Shadows** (Preferences > MoonRay > Renderer, off unless chosen): a label or other surface cut out
  by a Stencil layer or a map in its presence no longer shades what lies under its cut-out parts. Off where nothing is cut
  out, which is quicker. While it is on, Presence Shadows in Render Settings and on lights are greyed.
- **Samples for the material widget**: 32, 64, 128 or 256 in the graph editor, for a cleaner picture of the material.
- **Graph editor presets**: the Presets menu saves the selected nodes or a whole network, to load into any material.
- **A Car paint material in the library**: a dark metal with a sharp clearcoat and fine flakes, to start a metallic paint from.
- **Multi-part EXRs** (Render settings > Output Renders > Multi-Part EXR): each output in a part of its own, for a compositor to read one at a time.
- **EXR channels by standard names**: the beauty's alpha is `A`, so it comes in as the beauty's alpha, and depth is `depth.Z`.
- **A graph's new output reaches Modo's form**: changing a material's output shows the new material's form, selected and ready to edit, and the new output starts on its own colour.
- **Glitter no longer turns a material pink**, turned on or off again, in MoonRay, MoonRay XPU and XPU2.
- **MoonLightIPR follows a material's chosen subsurface model**: a Random Walk material rendered as Normalized Diffusion there, which could leave a dark brown patch where one part of a mesh passes close over another.
- **MoonLightIPR's subsurface colour is much closer to MoonRay's**: diffuse transmission now changes the colour light scatters by, as in MoonRay, rather than only dimming the result; a path scatters only as often as Subsurface per path allows; and a random walk also starts from the inside of a surface.
- **Glitter's flakes start at 3 centimetres**, not MoonRay's default of 1, which is a metre across in Modo's scenes and covered a surface in shards. A size you set is kept, and so is a scene imported from MoonRay.
- **The graph editor's colour numbers and swatches match Modo's form**: both show sRGB for the same stored colour.
- **The graph editor's Samples field shows its whole text.**
- **A MoonRay material's colour and Modo's diffuse follow each other**, under Traditional and Principled, so the viewport
  shows the material's colour. A new material starts on its diffuse.
- **Weight Map Texture layers render**, in MoonRay, XPU2 and MoonLightIPR, with their Low, High, Bias and Gain, matching Modo's own render:
  a weight map in the Shader Tree can drive a material's colour, reflections, roughness and more.
- **Toon lines come out whole**: no more broken gap showing the surface down the middle of a line. A MoonRay Source Override,
  on by default.
- **The Toon filter's Output Mode works under XPU2**, for its Lines and Shading passes: it always gave the shading with its
  lines.
- **A missing normal map texture leaves the surface flat**, where it darkened and streaked the surface's reflections in MoonRay.
- **Gradient and Curvature layers no longer stop halfway**: MoonRay kept only the first half of a gradient, holding its
  last colour from there on.
- **A scene XPU2 hands to MoonRay XPU keeps its geometry.** Its meshes could come out empty, leaving a white picture or
  none of the scene's objects.
- **Texture overflow mode:** where a scene runs out of memory as it loads, on the computer or the graphics card, XPU2
  compresses its textures, then makes them smaller if it still does not fit, and a notice in the preview says how far.
- **XPU2's Render gives the samples you set.** On a scene with heavy textures it could stop at about two thirds of them, its
  progress sitting at 100% for half the render. Progress now climbs steadily to the end. Such a scene takes longer than it
  did, with a cleaner picture: lower Generation Samples for the old speed.
- **A texture that cannot be read no longer ends XPU2 with no reason given.** The Terminal names the file, and MoonRay XPU
  renders the preview instead.
- **Compile XPU2 Shaders says whether the shaders are up to date**, or why they are out of date, where it only said they
  were compiled.
- **An environment image not yet cached no longer stops the render** with a "file not found" error.
- **The MoonRay Terminal reports XPU2's texture memory**: what the textures take in RAM and on the graphics card.
- **XPU2 takes Gaussian, Triangle and Blackman-Harris pixel filters**, and Material Samples of any count. Subsurface
  Samples above 4 render too, at 4 x 4 a hit: raise Pixel Samples for less noise.
- **Realtime on a heavy scene:** after a mesh's detail is cut anew the picture comes back in under a second, not several.
  A scene with much displacement or subdivision shows a first picture in seconds, and follows the camera while its full
  geometry is made.
- **Subdivided meshes no longer stretch textures in MoonLightIPR**: texture coordinates follow the smoothed surface.

## New in 0.5

0.5 is a **pre-production release**: the plugin is no longer experimental. In short: [What's new in 0.5](docs/WHATS_NEW_05.md).

### MoonRay XPU2

**XPU2** renders MoonRay previews with the processor and the graphics card on the same picture at once, neither
waiting for the other. Its pictures settle to MoonRay's own.

*XPU2: Asynchronous Monte Carlo Path Tracer designed by Raphael Tobar. Not affiliated with or endorsed by DreamWorks
Animation.*

- **The default GPU renderer**; MoonRay XPU is still a choice (Preferences > MoonRay > XPU2 > GPU renderer).
- **Compile XPU2 Shaders once** on the same page, in the background. Until then XPU2 does not render, and the preview says so.
- **Samples go where the picture is still noisy**, in generations; clean parts stop early. Settings in Render
  Settings > XPU2 Sampling; the line under the picture shows how it samples.
- **Realtime** takes up camera, object and light changes at once, with a quick picture while things move.
- **Devices**: processor and graphics card together, or either alone.
- **The Denoiser** works with XPU2 previews; Smart Render and Safe Denoising, which XPU2 is quick enough not to need, are greyed under it. Final renders come from MoonRay, as before.

### Everything else

- **Realtime that keeps up**: camera moves no longer reload the scene, editing one object updates only that object, and heavy scenes are cut by their size on screen.
- **A Scene cache** (Preferences): prepared scenes and meshes are kept in a cache folder of your choice, so a scene opens faster the next time. The status says Caching scene... while it keeps, and Loading scene from cache... while it reads back. **Clear Cache** empties it.
- **N-gons triangulated cleanly**: flat polygons of any size, CAD outlines and outlines with holes among them, are cut along their outline, the same in MoonRay and MoonLightIPR. A MoonRay Source Override, on by default.
- **Area lights seen by the camera**: Modo's Visible to Camera, and a MoonRay light's visible in camera set to Force on, show the light (with its texture) in MoonRay and MoonLightIPR.
- **HDRIs the right way round in MoonLightIPR**, and at full sharpness when the image is the whole environment.
- **Textures keep their shape in MoonLightIPR**: a non-square image is no longer squeezed into a square.
- **Water drops and other thin glass on a surface** come out clear in MoonLightIPR, as in MoonRay.
- **Motion blur in MoonLightIPR is off by default** (Preview Preferences); Motion Blur shows at the foot of the picture while it is on.
- **The preview window**: its buttons wrap onto a second line in a narrow window instead of being cut; R, G and B in their colours, γ and α for gamma and alpha; EV and γ toggle between the plain value and yours, and are lit while yours is shown; the picture's details are never cut off.
- **Memory in the picture**: the renderer's, the machine's and the graphics card's memory at the bottom right of the picture, in colour when it runs short (Preview Preferences).
- **MoonRay's preferences in pages**: General, Renderer, XPU and Source Overrides, each in Modo's Preferences list.
- **The Terminal names MoonRay by its mode**: MoonRay Vector, Scalar, XPU or Auto.
- **Fixes**: Modo crashing when the Render layout's view was changed (likely fixed); "Texture conversion needs maketx.exe" with maketx in place.
- **The memory meter no longer makes the preview hesitate**: it reads the machine and the graphics card on a thread of its own, once a second, where Modo's own thread waited for the card's driver while a render kept the card busy.
- **MoonLightIPR's textures at most 1024 pixels a side** (they were up to 4096): sharp enough at the preview's sizes, with far less for the graphics card to hold and read. Textures are converted again the first time a scene opens.
- **MoonLightIPR follows an edit at once**: moving an object, the camera or a light, or changing a material, no longer holds Modo while the scene is read three times for motion blur when nothing in it moves and nothing moved has keys (a fur scene: 0.6 s to 0.2 s from letting go to the new picture, Modo held 0.4 s to a hundredth). With keys, motion blur is read as before.
- **Heavy scenes start much sooner**: Modo's geometry is handed to MoonRay as it comes, without a step of Python for every point and face. A car scene's reading before a render went from about three minutes to a little over one, most of what is left being Modo's own work. MoonRay is handed the very same scene.
- **Displacement follows Modo's Displacement Rate**: Displacement Tessellation in the render settings cuts displaced meshes finely where they are large on screen and coarsely where small, as Modo does, with far less geometry and a quicker start. Fixed dicing camera holds the cut at the Dicing Frame so it stays put while the camera moves (no shimmer in an animation); Uniform cuts by each mesh's resolution, as before. Adaptive Error Override sets the pixels in place of Modo's rate. Scenes with displacement render with less geometry where it is small on screen.
- **A memory meter in the preview window**: the renderer's RAM, the machine's free RAM and the graphics card's memory, amber then red as they run short.
- **A Shader Tree displacement that is black everywhere is left out**, where MoonRay still tessellated every mesh of its material for nothing (a car scene's 24 materials all had one).
- **Cleaner denoising**: Keep Fine Detail lets the render through only over fur, hair and curves, where it used to bring the render's noise back over every textured or bumpy surface; and Open Image Denoise cleans its albedo and normal guides first and trusts them, leaving less noise on textured, bumpy and see-through surfaces (a MoonRay Source Override in Preferences, on by default).
- **Smart Render or Safe Denoising, plainly**: in the render settings, Safe Denoising is greyed while Smart Render is Draft, Medium or Fine, and Smart Render while Safe Denoising is on.
- **MoonLightIPR starts sooner**: about 15 seconds the first time on a machine, then a second or so, where it sat a minute and a half at Preparing scene. It begins with the plainest kernel and compiles the bigger ones only for scenes that use fog, hair or subsurface, and keeps them in a cache of its own.
- **Enhance: Modo's textures, 145 of them**: every family whose texture draws a pattern, worked out through the object in MoonRay and MoonLightIPR with a Solid projection: Noise (22: fBm, Bozo, Granite, Ridged, Marble, Stucco, Strata and the rest), Organic (22: Cellular, Crackle, Membrane, Fire, Wood, Veins, Scatter and the rest), Tiles (31: bricks, tiles of every shape, planks, parquet, paving, mosaic, Basket's 26 weaves, Tiler's 26 layouts), Geometric (14 shapes cell by cell), Waveforms (16), Skins (11: Camo, DinoSkin, FrogSkin, Leather, Scratches and the rest), Space (14: planets, rings, clouds, hurricanes, flares, star fields, windows), Panels (6, with rivets, rust, peeling paint and smears), Water (6: drips, rain, ripples, surf and waves, following Time) and Display (counters showing the frame or time code, LED boards), with their noise types, Lower, Upper, Bias, Gain and Fore and Back colours. Tiles, Geometric, Panels and Display lie on the texture locator's XY plane, Water on its XZ plane, Waveforms along X. Each is written after its name and settings, not yet compared with Modo's renders. Process's two work on the layers beneath them: EasyGrad maps their brightness through its eight-colour gradient, RegionalHSV gives each region (each colour beneath, as a pattern's Regions give each cell its own grey) a colour at random within its hue, saturation and value limits. After the patterns their names come from; not yet compared with Modo's renders. The other families follow.
- **Modo's Gabor and Poisson noise, Curvature and Wireframe**: Gabor and Poisson noise are drawn through the object like the patterns above (Solid projection); Curvature reads how the surface bends, through Modo's own gradient (MoonRay's CurvatureMap; in MoonLightIPR, triangle by triangle from the mesh's normals); Wireframe draws the polygons' edges as wide as Modo's, in MoonRay (its WireframeMap) and in MoonLightIPR. Modo's Surface Probe, which reads the shading of another surface beneath, is not among them.
- **Shadow rays in Light Links, Emitters and Volumes**: an object can be set to cast no shadow, and given its own shadow ray and secondary ray offsets against shadow acne; a light can have shadows begin only some way from it or end beyond a distance, and say whether its shadows respect dissolved and cut-out surfaces.
- **Modo's procedural textures through the object, at render time**: Noise (simple, fractal, turbulence), Cellular, Checker, Grid, Dots, Wood, Weave and Ripples with Modo's Solid projection are worked out at each point in MoonRay (a new MoonRay map, ModoProceduralMap) and in MoonLightIPR, from one shared piece of code: no baking, no UVs, no resolution. Grid's and Dots' Cube and every Noise and Checker type now draw. After Modo's patterns, not yet compared with Modo's renders.
- **MoonLightIPR draws a Combine light filter**: the filters it holds, joined as it says (multiplied, the least, the most, added or the first less the rest), Intensity filters among them. MoonLightIPR already drew the Intensity, Decay, Color Ramp, Rod, Barn Door, VDB and Cookie (v2) filters.
- **MoonRay lights take the Scale tool**: a RectLight's width and height, a disk, spot or sphere light's radius, follow the scale once it is let go of, the scale going back to 1, in one undoable step.
- **MoonLightIPR matches MoonRay's brightness for lights that are not normalized**: their colour and intensity are their radiance, as in MoonRay, where they came out about three times too bright.
- **Light filters on MoonRay lights list at once**: a filter attached or detached shows in "attached light filters" straight away, not once the light is selected again; choosing one there says it detaches it, "(choose to detach)".
- **Image nodes show their picture** in the graph editor: the image file itself, made small, at once and without rendering (View > Previews on Texture Nodes).
- **Toon lines apart from the shading**: a Toon display filter's Output Mode gives its ink lines alone, white on black, or its shading without them; add one of each to composite the lines yourself. A MoonRay Source Override in Preferences, on by default.
- **Clearcoat Bump Strength** is followed, in MoonRay and in MoonLightIPR: at 0 the coat stays smooth over a bumpy or normal-mapped surface.
- **The graph editor's Image node has Invert**, as a Shader Tree image layer does.
- **Images in the scene are a click away** when choosing a texture file in the graph editor: the images Modo's Clip Browser lists come first, then Browse Files.
- **Drag a wire off its input** to disconnect it, or onto another input to move it, in the graph editor and the compositor.
- **Tab and Shift+Tab move between fields** in the graph editor's and the compositor's settings.
- **A render working space for every new scene** in MoonRay's Preferences (Renderer), for scenes that have not chosen one in the Assets window.
- **Textures convert side by side**: MoonRay's .tx and MoonLightIPR's conversions run several at a time, the first render of a scene with many textures in a fraction of the time.
- **A colour correction on an image is sharp in MoonLightIPR**: it is baked over one repeat of the image at 2048 pixels and laid on as the image is, where it was 512 pixels over the whole of the UVs.
- **Turning an environment image is followed at once**: the scene's meshes are no longer read again for it.
- **A Modo package (.lpk)** can be made of a release, kit and runtime in one file to drop onto Modo (tools/package_lpk.py).
- **Display filters no longer come out pink for want of an input.** Each starts on every picture MoonRay needs it to have (a Toon filter on Albedo, Camera depth, Direct diffuse, Direct glossy and Shading normal; Depth of Field on Camera depth; Over on Alpha). One left empty in a scene takes that picture, with a notice, and one that cannot be given what it needs is left out, said, rather than drawn pink. A MoonRay Source Override in Preferences ("Display filters given the inputs they need"), on by default.
- **Modo's light volumetrics and environment fog render**, in MoonRay and in MoonLightIPR. A point light with Volumetrics on lights a sphere of fog, a spot light its cone and a directional light a cylinder, sized by the light's volumetric Radius, Height and Base, and thick as its light material's Density, Scattering, Scattering Color, Attenuation and Shift say; only that light lights it. The Environment Material's fog is fog around the camera, lit by the environment: Exponential at its density, Linear from Fog Start and thick by Fog End, Layered up to its height. Not yet compared with Modo's own renders.

## New in 0.4.3.1

A hotfix: the kit alone changed (with its geometry adapter); the 0.4.3 runtime is the same.

- **Adding geometry while MoonLightIPR follows the scene no longer stops or freezes it.** Turning realtime on could wait on Modo without end (while Modo's colour picker was open, for one); it no longer goes through a Modo command to read the scene.
- **Modo's fur renders with Modo evaluated geometry**, where it stopped the render with "Polygon indices failed". Under motion blur in the preview, fur that cannot be followed through the shutter is shown still, with a notice, rather than the render refused.
- **Assign MoonRay Material on a whole mesh tags its polygons**, as Modo's Polygon Set Material does. Its item mask had every reading of the scene go through Modo's render cache: one material on one sphere slowed a large scene's preview to seconds an edit. Polygons made in the mesh later keep the tag they are made with.
- **Large scenes read faster**: planar, cubic, cylindrical and spherical texture projections are worked out several times faster and kept between readings while a mesh is unchanged (a test scene with fur and a 324,706-face mesh, 45 s to 13 s, then under 2 s an edit), and moving an item with fur on it is followed without reading the scene again.

## New in 0.4.3

A critical performance update, with a new runtime ZIP: scenes load far faster before a render starts, and MoonLightIPR draws more of Modo's scenes for less power. Install the kit and the runtime together.

### Faster to start a render

- **Scenes load far faster before a render starts**, in MoonRay and in MoonLightIPR. A mesh's long lists (points, faces, normals, UVs, vertex maps) go to MoonRay in its own binary scene format beside the scene text, which MoonRay reads in a fraction of the time; the geometry adapter joins the many pieces Modo's render cache hands over into one per surface; and what was read of the scene is kept from one reading to the next. On a test interior, getting MoonRay ready went from about 107 seconds to 18, and MoonLightIPR's packing from 6.9 seconds to 2.3, with the same pictures. Preferences: **Load geometry as binary**, on.
- **Low-latency rendering**: MoonRay runs below Modo's priority and leaves one processor thread free, so Modo stays quick to use while it renders. Preferences, on.
- **MoonLightIPR is not sent the scene again for a change of frame alone**, in a scene where nothing moves.

### MoonLightIPR and the rest

- **Shader Tree Displacement and Stencil layers render in MoonRay**: displacement layers raise the surface by their value times the material's Displacement Distance, and a Stencil takes the surface away where it is white, as Modo's do.
- **Principled sheen**: a Principled material's Sheen and Sheen Tint show in MoonRay, as a soft glow at grazing angles fitted to Modo's renders. Specular Tint and Flatness, which MoonRay's material has nothing like, are named in a notice.
- **Principled highlights keep their edge**: a Principled material with a low specular amount, Modo's default among them, brightens toward the edge in MoonRay as it does in Modo.
- **Anisotropy follows Modo's UV map, and its strength Modo's**: a material with Anisotropy but no UV map named for it renders a round highlight, as Modo draws it; with one, MoonRay's highlight stretches and spreads nearer Modo's (fitted against Modo's renders). A very strong anisotropy still draws a shorter streak than Modo's.
- **Shader Tree masks checked against Modo**: material, Part and Selection Set masks colour the same surfaces in MoonRay as in Modo; a layer or group placed above the Base Shader, which Modo applies to nothing, is left out too, with a notice.
- **Exporting RDLB writes only the RDLB**: the scene text MoonRay's converter reads goes through a temporary folder, rather than appearing beside the scene while it is converted.
- **Displacement and stencils in MoonLightIPR**: Shader Tree displacement layers, and a node graph's displacement nodes (Normal, Vector, Combine and Switch), raise the surface in the preview as in MoonRay, the mesh split finer for them and blurred when it moves; Shader Tree stencils cut it away where they are white. A displaced mesh takes a moment longer to load.

![Displacement, MoonRay left and MoonLightIPR right](docs/images/moonlightipr-displacement.jpg)

*Shader Tree displacement: the balls raised by a striped image, the cube by another. MoonRay (left), MoonLightIPR (right). MoonRay tessellates a polygon cube coarsely, so its ridges barely show there.*

![Displacement nodes, MoonRay left and MoonLightIPR right](docs/images/moonlightipr-displacement-nodes.jpg)

*A node graph's displacement: on the balls, a Normal displacement combined with a Vector one in tangent space; on the cube, a Switch choosing the second of two. MoonRay (left), MoonLightIPR (right).*

![Stencils, MoonRay left and MoonLightIPR right](docs/images/moonlightipr-stencil.jpg)

*Shader Tree stencils cut the balls by sharp stripes and the cube by soft ones. MoonRay (left), MoonLightIPR (right).*

- **MoonLightIPR draws a material stack's rows with their own shine**: a dull print over shiny metal, as a can's label, shows the metal where the print lets it through, and a clear coat over it no longer brightens or mirrors it.
- **Light links in MoonLightIPR**: which lights reach each object, set in Object controls, a material's MoonRay links or Modo's own group light links, as MoonRay draws them (checked against MoonRay's renders). Shadows an object is set not to cast are still MoonRay's alone.

![Light links, MoonRay left and MoonLightIPR right](docs/images/moonlightipr-light-links.jpg)

*Light links: the balls lit by a warm sphere light alone, the cube by a cool panel and the environment, the floor by both. MoonRay (left), MoonLightIPR (right).*

- **Replicators render with motion blur**: a replicator whose copies Modo gives a moment from the frame in a different number no longer stops the render (MoonLightIPR, which renders with motion blur by default, showed nothing); a copy missing at an end of the shutter is held still, with a notice.
- **Glass nearer Modo's**: a tinted glass solid takes Modo's colour once, as Modo does, rather than at each surface, which made it much darker; and a rough glass blurs as much as Modo's (its refraction roughness fitted to Modo's renders at four values). Checked on a glass ball against Modo's own renders.

![Glass in Modo and MoonRay](docs/images/glass-modo-moonray.png)

*Glass in Modo (left) and MoonRay (right): a tinted ball (top) and a rough one (bottom), each in front of a gradient. The tint and the blur now come out as Modo's.*

- **MoonLightIPR rests once the picture is clean**: it judges the noise of each small square of the picture as it renders; a square that is clean takes no more samples, and the render stops once all are, so a simple scene stops after a few dozen samples a pixel, not the hundreds of Pixel samples, which is now the most it takes. A render is spread over about 8 seconds rather than run flat out, the first sample shown at once; the picture is shown less often once a render has settled; and the processor sleeps while it waits on the graphics card. The graphics card and the processor draw much less power, most on simple scenes.
- **A light's picture that cannot be found is left out**, with a notice, rather than drawn in MoonRay's pink for a missing file.
- **MoonRay's crest comes in once a Modo session**: a preview window opened after the first shows it at rest.

## New in 0.4.2.1

- **The graph editor's Live material preview renders again**: with Live on, the MoonRay Widget refused the scene ("Minimum adaptive samples must not exceed maximum samples").

## New in 0.4.2

More detail is in [What's new](docs/WHATS_NEW_04.md).

### MoonLightIPR

- **MoonLightIPR is faster on scenes without its heaviest materials**: a scene with no fog, hair, subsurface scattering, toon or velvet is drawn by a version of MoonLightIPR made without them, up to about 40% faster, and one with some of them by a version with only those. The picture is the same.
- **MoonLightIPR fits large texture sets on the graphics card**: pictures of high dynamic range are kept at half precision, half the memory, and where a scene's textures would still not fit, each is made smaller (halved, as light, until no side is longer than the largest size at which they all fit), which the status line says. A scene that runs out of graphics card memory all the same is said to have done so, with MoonRay offered, rather than rejected.
- **Velvet in MoonLightIPR**: MoonRay's velvet material and DwaBaseMaterial's fuzz show in MoonLightIPR with their grazing-angle sheen, dimming what is beneath them as MoonRay does, with their samples sent where the sheen is brightest so velvet clears up sooner; before, velvet showed as a plain stand-in.

![Velvet in MoonRay and MoonLightIPR](docs/images/moonlightipr-velvet.png)

*Velvet in MoonRay (left) and MoonLightIPR (right): two balls of MoonRay's velvet material and a cube of DwaBaseMaterial with its fuzz on. The sheen is brightest where the surface turns away from the view, and softens into the shadow.*

- **Motion blur in MoonLightIPR, on by default**: while the scene is followed too (an edit is shown blurred once it is let go; a drag is followed sharp), and moving lights blur, in MoonLightIPR and in MoonRay, which held them still before. MoonRay's own items (its lights and shapes) blur when they move, as Modo's do.
- **MoonLightIPR looks through MoonRay's own cameras** from their own place: perspective, orthographic and dome as well as fisheye and spherical. Modo's orthographic camera previews too.
- **MoonLightIPR draws MoonRay's hair toon material**: its hair colour under up to three toon highlights. A toon ramp that ends lit is now drawn right past its end.
- **MoonLightIPR draws a mesh filled with even fog**, and follows MoonRay's scene scale for lights and depth of field. A box of fog standing on the floor no longer shows stripes where it meets it.

### The preview window

- **The button greys while a render stops**: after Stop it says Stopping, greyed, while MoonRay finishes with what it has, and becomes Render (or Continue) again once it has.
- **MoonRay LS can sample uniformly**: Preview Preferences > MoonRay LS quality has a Sampling choice. Adaptive, as before, takes more samples where a pixel is still noisy, up to Most samples a pixel; Uniform gives every pixel the same samples (25, 64 or 121), for an even grain, with Adaptive error greyed.
- **Leaner notices**: they open only as tall as their text and two lines more, up to the height they had before, where a long list scrolls.
- **The size and samples beside the picture follow the engine chosen**: choosing MoonRay, MoonRay LS or MoonLightIPR says at once the size it renders at and its samples a pixel, before anything is rendered; a MoonLightIPR picture says its samples too.
- **Denoising... in the status line** while the denoised beauty is made from a finished render, until it is shown.
- **Closing a scene clears its render** from the preview window, and a render of it still going stops; closing another scene leaves the picture as it is. A render to files goes on to the end.
- **A MoonRay preview is always one render**, as MoonRay's own command makes it: it no longer starts over twice at 1 and 4 samples before the full render.
- **The preview shows MoonRay's wordmark** before anything is rendered.
- **The MoonRay mark moves**: it comes in as the preview opens, breathes while a render is on its way, and fades out over the first picture.

![The MoonRay mark coming in as the preview opens](docs/images/crest-entrance.gif)

*The MoonRay mark as the preview opens: after a second the letters rise in from the left, then the crescent fades in from the right.*

### Rendering with MoonRay

- **Gaussian, Triangle and Blackman-Harris pixel filters** in Render Settings. They are not in MoonRay's source: the plugin adds them to MoonRay, built the way its own are. They never go negative, as MoonRay's sampling needs. Box and the two B-splines are MoonRay's own.
- **Global Switches** in Render Settings: displacement, subsurface scattering and shadows on or off, lights seen by the camera, a limit to geometry resolution, and a dicing camera for adaptive tessellation.
- **Volume attenuation, contribution and phase attenuation factors** in Render Settings, Volumes: with Volume bounces above 1, how much less each further bounce of light in fog is stopped, adds and keeps its direction (MoonRay's defaults 0.65, 0.65 and 0.5). MoonLightIPR follows them.
- **Presence quality, Cryptomatte multi-presence and Sample hair lobes separately** in Render Settings: how finely partly see-through surfaces are sampled (MoonRay's 0.75), Cryptomatte mattes that count each layer seen through a partly see-through surface, and hair that samples its lobes one by one in place of MoonRay's faster way.
- **Subdivision creases render**: a subdivided mesh's edge and point weights (Modo's Subdivision weight map) are MoonRay's creases, in MoonRay and MoonLightIPR; before, MoonRay rendered every subdivided mesh soft whatever its weights.

### Cameras

- **MoonRay's cameras are Modo cameras**: a perspective, orthographic, fisheye, spherical or dome camera from the MoonRay menu is Modo's own camera with its MoonRay settings in a tab of its own. Modo's viewport lists it in its camera menu and looks through it framed by its MoonRay focal length and film width, with Modo's resolution gate. A fisheye, spherical or dome camera shows as a perspective view as wide across, up to 150 degrees, as Modo's viewport cannot bend the picture; the preview shows its true picture. Made Modo's render camera, a MoonRay camera is the one MoonRay renders through, and it brings its own Overscan to a render to a file. MoonRay cameras in scenes saved before become Modo cameras when the scene is opened, keeping their settings.
- **Camera Sequence** (MoonRay menu): key cameras to ranges of frames, each the one rendered through from its first frame to its last, in the preview at the current frame, Render to a File, Render Animation and playblasts. A camera's own resolution goes with it, MoonRay's camera items can be keyed too, and frames no key covers use the render camera. A strip shows which camera covers which frames, and where keys overlap or leave gaps.
- **Convert a Modo camera to a MoonRay camera**: in the MoonRay menu, and in the Item List's right-click menu on a camera. A popup asks which kind (perspective, orthographic, fisheye, spherical or dome); the Modo camera becomes that MoonRay camera in its place, taking its lens, film offset and depth of field where the kind has them, and keeping its name, place, parent, children, animation and role as render camera; Camera Sequence keys that named it name the MoonRay camera.
- **Change to Modo Camera**: right-click a MoonRay camera in the Item List to make it Modo's own camera again, the same item in the same place, framing as it did (its focal length, film and depth of field). Each camera's right-click menu shows only the entry that applies: Convert to MoonRay Camera, or Change to Modo Camera.
- **Stereo cameras and overscan from Modo's camera**: a stereo render camera renders its eye in MoonRay and in MoonLightIPR; set to both eyes, Render EXR writes `_left` and `_right` files beside the one chosen, and Modo's anaglyph composite in it when one is chosen. The camera's Overscan renders that much past the frame in a render to a file, the frame kept as the EXR's display window; the preview shows the frame. MoonLightIPR now also follows a perspective camera's film offset.

### Materials and the node editor

- **The graph editor opens a material with only its Diffuse and Specular groups unfolded**; the rest start folded, and a group folded or unfolded is still kept that way for that kind of material.
- **Glitter in reference space works, and is where glitter starts**, as in MoonRay: each mesh is sent with its rest positions (MoonRay's ref_P), its points before Modo's deformers move them, so that the flakes stay on a deforming surface. Without them MoonRay drew such glitter pink or black. A mesh whose deformer adds or takes away points, or one taken from Modo's render cache (as a material mask can need), gives its points as rendered: its flakes then move with the deformer, as in object space, and never fail.
- **Add Node by name**: Tab in the compositor or the material editor opens a field over the list of every node; what you type picks the node it names, whole or in part, and Enter adds it.
- **Switch displacement in the node editor.** The switch colour, float and normal maps, the switch and mix materials, and the toon materials' per-point ramp multipliers and offsets now reach MoonRay: they were never passed on before. Scenes saved with them are carried over.
- **Materials made of others**: Two Sided and Color Correct take the other DWA materials as their inputs. A layer, two-sided or hair layer material missing one of its pair, or an empty Adjust or Color Correct plugged into another material, no longer crashes MoonRay: the plugin fills in or leaves out what is missing and says so in the notices.
- **Modo's weight and colour vertex maps reach MoonRay** for its materials to read by name (AttributeMap): a value at each point, or set apart on a face's corners so that each face keeps its own. MoonRay scenes with such values import as vertex maps.
- **Assign MoonRay Material** in the Item List's right-click menu on a mesh.
- **A whole mesh's MoonRay material covers what is made in it later**: Assign MoonRay Material on one mesh binds its material to the mesh, as Modo's item masks do, so new polygons take it too. Picked polygons, or several meshes sharing one material, are still tagged.
- **The graph editor's properties fold by group**: a MoonShine material's settings sit under its own groups (Diffuse, Specular, Clearcoat and the rest), each folded or unfolded with a click and kept that way for that kind of material.
- **The graph editor's MoonRay Widget is quicker**: it renders under MoonRay LS with more samples to a pixel, starts as the editor opens, and shows a material it has already rendered at once. It has one Refresh/Stop button, no bucket outlines, and the object sits higher in the picture.

### Toon materials

- **A new toon material is brightest facing the light**: its diffuse ramp starts bright where the surface faces the light and darkens towards the shadow side, as Modo's toon does. MoonRay's own default runs the other way; a toon material whose ramp was never set takes the new start, and a MoonRay scene's own materials keep MoonRay's.
- **Toon materials have smooth edges on coarse meshes**: the lit band no longer comes out in steps along the faces of a low-poly or subdivided mesh, in MoonRay and in MoonLightIPR. "Smooth toon edges on coarse meshes" under MoonRay Source Overrides in Preferences, on by default; off renders as MoonRay itself does.
- **Toon materials denoise cleanly**: MoonRay's albedo output, the denoiser's guide, was full of bright specks on toon surfaces, and a denoised toon stayed as noisy as it was rendered. "Denoise toon materials cleanly" under MoonRay Source Overrides, on by default.

### Outputs

- **MoonRay's display filters**: all 18 from MoonRay's source (colour correct, toon, halftone, blur, depth of field and the rest) as MoonRay items. Each takes in the beauty, an AOV or another filter, and is a buffer of the preview and a channel of the final EXR.
- **Time per pixel** as an output: where the render spends its time, shown with the average pixel at a quarter of white. Its timings are now fine-grained on Windows.
- **Primitive attribute outputs** in the Outputs window: a vertex map or other value the shapes carry, by its name, as a picture of the render, a number or a colour. MoonRay scenes with such outputs import with them.
- **Visibility outputs** in the Outputs window: how much of the light reaches each point, from every light or from one light group, 0 in shadow to 1. MoonRay scenes with such outputs import with them.

### Cryptomatte

- **Cryptomatte names and IDs**: a Cryptomatte tab on objects and on materials. Things given the same name share one matte (all of a car's parts as "car"); a number is the matte's ID itself, for a compositing setup that expects one.
- **Pick from the Cryptomatte in the preview**: over a Cryptomatte buffer the pointer says the name under it. A click selects what it is in Modo, Shift-click picks more and Ctrl-click takes one away, and the mattes picked show in orange over the picture.
- **A Cryptomatte node in the compositor**: the matte of any name or ID given in a Cryptomatte tab, chosen from a list, for a Merge's mask or a Grade of its own. It is made for the render's composite file too.
- **Fog in Cryptomatte**: fog, smoke and clouds, from a VDB or in a MoonRay box or sphere, have mattes of their own, as strong as the fog is thick, and what lies behind fog is covered only as much as shows through. Fog also no longer stops a render with Object, Material and Asset Cryptomatte together. A MoonRay Source Override in Preferences, on by default.

### The compositor

- **Compositor: Build from passes or light groups.** Build > From Light Passes adds MoonRay's light passes to the scene (emission, lights and sky seen, direct and indirect diffuse and glossy, mirror reflection, refraction, glossy transmission, translucency) and lays out a graph that puts them back together, each through a Grade of its own; From Light Groups does the same for the environment's light and each light-group label, to relight after the render. Build asks which passes or light groups to work on, none ticked to start. A Remainder pass holds whatever the chosen ones leave out, so with every Grade left alone the Composite is the beauty. A new **Sum** node adds any number of pictures.
- **Preview Composite and Send Composite to Preview Window** in the compositor: the first shows the Composite in a viewer of its own under the settings, as the preview window shows it, following each new Composite; the second chooses the Composite buffer in the preview window. The Colour node shows its colour as a chip, clicked to choose another.
- **A mask on the compositor's colour nodes**: Grade, Levels, Contrast, Invert, Clamp, Tone Map and Math take a mask, so the change is made in full where it is white, not at all where it is black, and as much as it is grey: a Brightness Matte, a Channel or a Cryptomatte node wired in changes only part of the picture.
- **The compositor's probe at the pointer**: with Probe on, the pointer over the preview shows each node's value there. Right-click for a note that keeps that pixel's values and follows the graph and the render.
- **The compositor runs on the graphics card**, or on the processor where there is none, giving the same picture either way; wide blurs and glows are now true full-size blurs.

### Saving pictures

- **Standard picture types**: Render to a File, each frame of an animation, and Export AOVs save as PNG (8 or 16-bit), JPEG, TIFF (8, 16 or 32-bit float), Targa or OpenEXR (16 or 32-bit). The picture types go through the view transform as the preview shows them; OpenEXR and 32-bit TIFF keep the render's linear values. A render saved in another type keeps its OpenEXR beside it, with every output.
- **A new Export AOVs window**: the outputs grouped as pictures, light, surface data, mattes, render statistics and denoiser guides, each group ticked as a whole or one by one; the type and JPEG quality, the folder chosen in the window, the files it will write named as you choose, and the folder opened when it is done. A Cryptomatte is offered only in OpenEXR, where its IDs survive.
- **EXR compression** for Render EXR and animations: zip, as before, or any of MoonRay's others, lossy ones included.

### Importing and exporting MoonRay scenes

- **Export as MoonRay Scene**, in the MoonRay menu and the preview window's Options: the scene written as MoonRay reads it, to render with MoonRay on its own or on a farm, from a window that asks for the file and the format: RDLA (one text file), RDLB (one binary file, about a third of the size and quicker to load) or both, as MoonRay's split scene (its settings as text, its geometry binary). It can leave out the AOVs, Cryptomatte and deep output, collect every texture into a folder beside the scene, and write one scene for each frame of the frame range. Each way renders the same picture.
- **More of a MoonRay scene comes in on import**: what moves over the shutter is keyed as Modo animation at the shutter's two ends, the camera's shutter and Motion Blur set to match, copies an instancer makes included; a shape that changes over the shutter comes in as a morph keyed the same way; semi-sharp creases come in as subdivision weights; a mesh MoonRay fills with fog comes in with its volume, as a MoonRay volume item its material holds; maps wired into a MoonRay item's values (a noise in a fog's colour) come in wired; instanced curves come in, a curve set for each copy; a vector at each point comes in as a vertex map that goes back out to MoonRay as a vector; words by point or by face are kept on the mesh and go back out; a mesh given no normals comes in shaded as MoonRay shades it, smooth unless it says otherwise, where Modo would have faceted it; and an instancer of more than 20,000 copies comes in whole, the first 20,000 as Modo instances and the rest merged into meshes.

### Preferences and MoonRay Source Overrides

- **New MoonRay lights start at an intensity of 10**, not 50: the MoonRay page of Preferences, New light intensity. A value set there before is kept.
- **Draft quick width is a choice of 320, 640 or 1280**, in the MoonRay page of Preferences; a width typed before is taken to the nearest.
- **MoonRay preferences in sections**: the MoonRay page of Modo's Preferences is laid out in sections that fold, Preview Window, Lighting, Assign Material, Renderer and MoonRay Source Overrides, with the overrides in order of what they touch.
- **More pixel samples for the realtime engines**, in the preview's Preferences: MoonLightIPR 128, 256, 512 or 1024 (32 and 64 are gone), and MoonRay LS 32, 64 or 128 (1, 4 and 16 are gone). A preview set to one that is gone takes the fewest there are now.
- **MoonRay Source Overrides**: the MoonRay page of Modo's Preferences, now named with the MoonRay release it renders with (MoonRay (2026.29.1)), gathers in a section that folds where the plugin changes how MoonRay itself renders: smooth toon edges, toon materials that denoise cleanly, blurred moving lights, fog in Cryptomatte, fog in front of see-through surfaces in alpha, each Cryptomatte sample counted once, a stopped render finishing the tiles in hand, UsdPreviewSurface's specular colour, images without alpha read as opaque, rough glass under a smooth surface, and Auto rendering on the graphics card first. Each is a checkbox of its own, on by default; off renders as MoonRay's source does. What each changes in MoonRay's source, why, and how it was checked is in the [engineers' notes](patches/native-windows/README.md).
- **Two more MoonRay Source Overrides**, on by default: fog in front of a partly see-through surface counts in the picture's alpha (MoonRay leaves it out there, so the picture composites thinner than it renders), and Cryptomatte counts each sample once in vector and XPU modes (MoonRay now and then counts a pixel twice).

### Working in Modo

- **MoonRay lights, light filters, shapes, volumes and the bake camera have a Transform section** in their Properties, laid out as Modo's: Position, Rotation with its order, and Scale as X, Y and Z, with the Reset, Freeze, Zero and Add menus. MoonRay's perspective, orthographic, fisheye, spherical and dome cameras are Modo cameras, with Modo's own camera Transform.
- **Terminal** in the MoonRay menu: every program the plugin runs (MoonRay, MoonLightIPR, the denoiser, the scene reader and the rest), with its command line, what it prints and how it ended, as it happens. It shows "ready" while nothing runs.

![The MoonRay Terminal after a MoonRay render and a stereo composite](docs/images/terminal.png)

*The Terminal after a MoonRay render and a red/cyan stereo composite: each program's command, what it printed, and how it ended (green for success); "ready" while nothing runs.*

- **An image viewer in the asset library**: Open, or a double-click, shows a picture in a window of its own, zoomed with the wheel and moved by dragging, with Fit and Actual Size, and the arrow keys for the library's next picture. OpenEXR, HDR and .tx pictures are shown in sRGB from their linear values. Adding a picture to the scene stays on its Use button.
- **The About window** has MoonRay's current logo, and names the MoonRay version the plugin is compiled from.

### Fixes

- **A texture that cannot be found no longer stops the render**: a MoonRay material's image is rendered with an empty texture path in its place (the image node's own default, or a neutral grey), and a notice names each missing file. Shader Tree layers and environment images with a missing file were already left out with a notice.
- **HDRI environments reach MoonRay whole, and the right way round**: an HDRI layer as Modo makes one (its alpha set to Use, its corrections left alone) was taken for a layered environment and baked into a 512-pixel picture, every turn baked again; an image with no alpha of its own, with nothing to correct, is now sent itself, at full size, and an opaque one hides the environment's own material under it. Sent so, it showed half a turn from where Modo shows it: it now turns as in Modo (checked against Modo's renders at each eighth of a turn).
- **Turning a layered HDRI is quick**: an HDRI with anything more to it (a colour correction, less than full opacity, a layer under it) was baked into a new picture for every new rotation, five to seven seconds each. It is now baked once, unturned, and turned as the environment light, as a plain HDRI is: about a fifth of a second for each turn, in MoonRay and in MoonLightIPR. An HDRI turned by its texture's UV rotation, or under a gradient or a sky, is baked as before.
- **The Denoiser set to Off is off everywhere**: the denoised beauty chosen in the preview and Smart Render denoised all the same before. Denoise Preview, Save Denoised EXR, Keep Fine Detail and Smart Render are greyed while it is Off.
- **Pixel Samples is greyed under Adaptive sampling**, which does not use it.
- **The MoonRay Widget renders with the runtime the preview window uses** (the one chosen in Preferences): it took the kit's own first, and where that could not show a picture it said Rendered over the old one. It now says Rendered only when its new picture has come, and shows it; a render that ends without one says so.
- **The preview no longer stops when MoonRay's GPU mode fails**: now and then (about one preview render in ten here, whatever the scene) MoonRay's GPU tracing fails in the preview and the render ended with "Persistent MoonRay exited". The render is now begun again on the CPU, and the notices say so.
- **Modo's own light linking reaches MoonRay**: a light's Light Linking group, set to include or exclude, was passed over before, and every object took every light. Checked against Modo's own render in both modes. MoonLightIPR still lights every object alike.
- **Large MoonRay pictures the right way up**: a preview at 3840 x 2160 came out upside down in MoonRay, and now does not.
- **ACEScg scenes render and look right**: MoonRay no longer refuses them, and the preview no longer shows their colours washed out.
- **An ACES 2.0 view**: View Transform offers ACES 2.0 (sRGB display) beside ACES 1.3, ACES 2.0's own tone mapping from the ACES 2.0 configuration built into the plugin's OpenColorIO (2.5); ACES 1.3 stays as it was.
- **Less memory kept over a long session**: small leaks after each render and selection are gone.

## New in 0.4.1

- **MoonRay's toon material** starts as a toon material, and MoonLightIPR draws it.
- **Ramps are edited with the mouse**, and a material's ramp shows in the preview as you edit it.
- **The scene importer can import into a new scene**, and has a Close button.
- **Color management follows Modo's system preferences**, and what you choose in MoonRay is remembered.
- **MoonRay LS** shows and renders the beauty alone.

## New in 0.4

More detail and pictures are in [What's new in 0.4, 0.4.1 and 0.4.2](docs/WHATS_NEW_04.md).

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
- **MoonLightIPR is much closer to MoonRay** on layered materials, glass, coats, subsurface and see-through shadows.
- **Rough Principled materials** are no longer dark at low angles.
- **Hidden items stay hidden**: an item with its eye off does not render, and a Shader's Cast Shadows switch is followed.
- **Imported MoonRay lights** are no longer far too bright.
- **Bump and normal images show on subdivision surfaces** in MoonRay.
- **An image layer's Low Value and High Value** are followed.
- **The Notices button is coloured** when there is something to read: yellow for notices, red for errors.

0.4 comes with a new runtime ZIP: install it together with the kit.

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

## Modo's features in MoonLightIPR

Comparison audit between Modo 16.1v9 and MoonLightIPR, the realtime preview: what of a Modo scene MoonLightIPR draws. It draws what the plugin gives MoonRay, so a feature the plugin leaves out for MoonRay is left out here too. How closely it matches MoonRay is in [its own notes](moonlightipr/README.md).

| Modo feature | MoonLightIPR | Notes |
|---|:---:|---|
| **Lights** |  |  |
| Directional light, with the physical sun | ![yes](docs/images/feature-yes.svg) | The sun's disc in Modo's colour |
| Point, spot and area lights | ![yes](docs/images/feature-yes.svg) | Within about 1% of MoonRay's brightness; Visible to Camera shows the light |
| Mesh lights | ![yes](docs/images/feature-yes.svg) | From the shown Prototype mesh, placed as Use Prototype Transform says (a hidden Prototype gives no light, as in Modo); within 0.2% of XPU2's brightness. Shines from the polygons' front only, as Modo and MoonRay do; seen by the camera where Visible to Camera is on |
| Cylinder, dome and photometric (IES) lights | ![no](docs/images/feature-no.svg) | Left out by the plugin for MoonRay too; MoonRay's own cylinder and environment lights are drawn |
| Light linking (Modo's groups, include or exclude) | ![partly](docs/images/feature-partly.svg) | Which lights reach each object, from Object controls, a material's links or Modo's groups, compared with MoonRay at 0.96 to 1.01 of its brightness. Objects set not to cast some shadows, or not onto some objects, cast them all; said in Notices An object whose materials are linked to different lights is lit as its first |
| Light volumetrics, and fog | ![partly](docs/images/feature-partly.svg) | Point, spot and directional lights' volumetrics, and the Environment Material's fog (Linear and Layered approximated), as fog lit by all the scene's lights; not yet compared with Modo's renders. Area, cylinder and dome lights' volumetrics and the Shader's fog are named in Notices |
| **Environment** |  |  |
| Gradients, constant colours and HDRI image layers | ![yes](docs/images/feature-yes.svg) | An HDRI that is the whole environment at 1024 x 512 in realtime, at its full size in a Render; layered environments and physical skies at 256 x 128; a third environment image shows as grey |
| **Cameras** |  |  |
| Perspective and orthographic cameras | ![yes](docs/images/feature-yes.svg) | With depth of field (a bokeh image too), motion blur and stereo (a camera set to both eyes shows the left) |
| Other camera projections | ![no](docs/images/feature-no.svg) | MoonRay's fisheye, spherical and dome cameras are drawn in their place |
| **Materials** |  |  |
| Standard material: GTR, Blinn and Ashikhmin | ![partly](docs/images/feature-partly.svg) | Highlights fitted to Modo's as for MoonRay; very smooth ones come out dimmer |
| Principled model | ![partly](docs/images/feature-partly.svg) | Its diffuse does not brighten with roughness as Modo's does; sheen shows in MoonRay only |
| Transparency, refraction and dispersion | ![partly](docs/images/feature-partly.svg) | Tint and rough glass as Modo's, as for MoonRay; glass casts a solid shadow to direct light, as in MoonRay. Looser on glass than on plain materials |
| Subsurface scattering, clearcoat, metallic, luminosity, dissolve | ![yes](docs/images/feature-yes.svg) | Subsurface follows the material's model, colour and limit per path, with bounced light less tinted by the scattering colour than in MoonRay; Subsurface Neighbours show in MoonRay only |
| Anisotropy | ![partly](docs/images/feature-partly.svg) | Along the first UV map |
| Specular Tint, Flatness, and a reflection amount apart from specular | ![no](docs/images/feature-no.svg) | As for MoonRay; named in a notice |
| Unreal, Unity, glTF and AxF materials | ![no](docs/images/feature-no.svg) |  |
| **Shader Tree** |  |  |
| Image maps: UV and projections, UDIMs, Low and High values | ![yes](docs/images/feature-yes.svg) | Up to 8 UV sets a scene; images at most 1024 pixels a side in realtime, their shape kept, and at full size in a Render, compressed on the graphics card. A MoonRay graph's images are found when the scene has moved, as Modo's clips are. A texture reading a UV map its mesh has not is drawn with the map at 0, and a notice names it |
| Procedural textures | ![partly](docs/images/feature-partly.svg) | Modo's built-in patterns, Gabor and Poisson noise and Enhance textures run through the object with a Solid projection, as MoonRay draws them; other projections bake the built-in patterns flat, and Enhance needs Solid. Curvature, Wireframe, EasyGrad and RegionalHSV draw too |
| Processing textures: Process, Gradient, Occlusion, Variation, Tension | ![partly](docs/images/feature-partly.svg) | As in MoonRay; Occlusion and Tension worked out at the mesh's points; Variation by Item, Mesh Part and Particle; Gradient's Thickness not followed |
| Layer blend modes | ![partly](docs/images/feature-partly.svg) | All but Normal Multiply; Normal Map Blend on normal maps only |
| Bump and normal maps | ![yes](docs/images/feature-yes.svg) |  |
| Displacement and Stencil layers | ![yes](docs/images/feature-yes.svg) | Displacement layers, and a node graph's Normal, Vector, Combine and Switch displacement nodes, as MoonRay's, a displaced mesh split evenly up to 400,000 triangles; stencils cut the surface as MoonRay's do |
| Other texture effects (Modo has 218) | ![partly](docs/images/feature-partly.svg) | The ones a standard or Principled material uses; others named in Notices |
| Group masks by material, Part and Selection Set | ![yes](docs/images/feature-yes.svg) | As MoonRay draws them |
| Group masks by item | ![yes](docs/images/feature-yes.svg) | As MoonRay draws them |
| Layer masks | ![yes](docs/images/feature-yes.svg) | Masking the layer above, the same in MoonRay, XPU2 and MoonLightIPR |
| **Geometry** |  |  |
| Meshes, subdivision and creases | ![yes](docs/images/feature-yes.svg) | UVs follow the smoothed surface; up to 3,000,000 quads a mesh, cut by its size on screen; n-gons cut along their outline |
| Instances and replicators | ![yes](docs/images/feature-yes.svg) |  |
| Deformed and animated meshes | ![yes](docs/images/feature-yes.svg) | With motion blur where turned on in Preview Preferences; a subdivided mesh that changes shape does not blur |
| Alembic | ![yes](docs/images/feature-yes.svg) | Loaded as Modo meshes with streaming deformers or as Alembic Streaming Meshes, moving over time; either way read from the file itself, fluids with changing faces blurred along their velocities; Alembic Curves and Point Clouds untested |
| Curves, hair and Modo's Fur material | ![partly](docs/images/feature-partly.svg) | Hair close to MoonRay's but not exact; fur drawn with up to 150,000 fibres, following its guides (Direction, Direction + Length, Shape, Range and Clump), its vector map and its width map, as MoonRay draws them. The guides' Blend Amount and Blend Angle, and Modo's Hair Material, are not read |
| Weight and colour vertex maps | ![partly](docs/images/feature-partly.svg) | Weight maps through a Weight Map Texture layer, each taking one of the 8 UV sets; colour maps show in MoonRay only |
| Modo's volume items | ![partly](docs/images/feature-partly.svg) | Drawn from a VDB file attached in the MoonRay controls; no motion blur, whether the item moves or from a velocity grid |
| Blobs and particles | ![no](docs/images/feature-no.svg) |  |

## Known issues

The ones you are most likely to meet:

- Very smooth highlights are dimmer than Modo's, though closer than before under GTR.
- Under Principled, Modo's diffuse gets brighter with roughness and MoonRay's does not.
- A very strong anisotropy draws a shorter streak than Modo's.
- Glass under Blinn and Ashikhmin lets through about 8% less light than Modo's.
- Hair in MoonLightIPR is close to MoonRay's but not exact.
- Subsurface in MoonLightIPR is less tinted by its scattering colour in bounced light than MoonRay's.
- Modo's Principled sheen shows in MoonRay only, not in MoonLightIPR.
- Fog from a light's volumetrics in MoonLightIPR is lit by every light, not that light alone.
- A glowing VDB volume renders in MoonRay's slower scalar mode, and so does a light with a cookie filter outside XPU2. MoonRay's faster modes do not draw them rightly in this build.
- Now and then, a preview with glitter in the GPU (XPU) mode fails on the graphics card; it is rendered on the CPU instead, with a notice.
- Tested on one machine (RTX 3090) only.

Every known issue, and what is still to implement, is in the [issue tracker](https://github.com/Pbaroque20/MoonRayForModo/issues). Found something else? Please report it there.

## More

- [Rendering headless](docs/INSTALLATION.md#rendering-headless-no-modo-window): export the scene (from Modo, or from `modo_cl` with the kit's `scripts/export_moonray.py`), then render it with `runtime\moonray.exe`, or with XPU2: `runtime-xpu2\moonray_xpu2.exe render`.
- [How MoonLightIPR works, what it draws and how closely it matches MoonRay](moonlightipr/README.md)
- [The plugin's main page](https://github.com/Pbaroque20/MoonRayForModo/tree/codex/native-avx-modo), with the full feature list, limitations and installation
- [What's new in 0.4](docs/WHATS_NEW_04.md)
- [What was new in 0.3.51](docs/WHATS_NEW_0351.md)
- [What was new in 0.3.50](docs/WHATS_NEW_0350.md)

Developed by Raphael Tobar with AI assistance. MoonLightIPR is under the [MIT License](moonlightipr/LICENSE) and is not affiliated with DreamWorks Animation; see [moonlightipr/NOTICE.md](moonlightipr/NOTICE.md). Plugin licensing is in [LICENSE](LICENSE).
