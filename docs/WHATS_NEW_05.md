# What's new in 0.5

0.5 is a **pre-production release**: the plugin is no longer experimental, and it brings a new GPU renderer, MoonRay XPU2.

## New in 0.5.4 (coming)

- **Modo's Processing textures** render in MoonRay, XPU2 and MoonLightIPR. A Gradient's input can be Incidence Angle, Locator Incidence, Slope, Camera Distance, Distance (and X, Y, Z, to the object), Screen X, Y and R, and Back Facing, within 0.01 of Modo's render (the distances within 1 to 2%). Occlusion works out how open each point is from rays over the scene, within 0.03 of Modo where the mesh is fine enough (it is measured at the points, not at each pixel). Variation by Item gives each mesh item its own random number, the same each render, by Mesh Part each Part of it its own, and by Particle each replica of a Replicator its own; Texture Particle is named in a notice and left out. Tension compares a deformed mesh with its base mesh, by Area (stretched or squashed) or Angle (folded), within 0.02 of Modo. A Gradient also reads Texture U and V: the UV map's coordinate under a UV map projection, the point in the texture locator's space under the default (Solid) projection, and wrapped under Planar along Z (along X and Y are named in a notice); Texture Value, the Value of a Constant layer directly beneath it; and Surface ID, a number for each item as Variation by Item gives (not Modo's own numbers). Bump Height and Displacement Height read the Bump and Displacement the layers beneath give, exactly as in Modo; Clip Distance is held at 0, as Modo's render shows it on visible surfaces. Thickness is not followed, since it needs a ray traced through the object; nor are Process's Bias and Gain.
- **Render Settings tidied**: MoonLightIPR's Render Samples has its own MoonLightIPR group after XPU2 Sampling and is saved with the scene (it was a Preview Preference); MoonRay's Sampling group is now XPU Sampling; XPU2's Most Samples is gone (XPU2 keeps 16 times the average as its limit). Displacement Tessellation, Adaptive Error Override and Dicing Frame (Global Switches), missing from the form since they were added, are there.
- **Headless MoonRay renders**: `scripts/export_moonray.py` in the kit writes a Modo scene as a MoonRay scene (RDLA or RDLB, one frame or each frame of the range) from `modo_cl.exe`, with no window, to render with `moonray.exe` on a farm. The steps are in [Rendering headless](INSTALLATION.md#rendering-headless-no-modo-window). `moonray_xpu2.exe render -in <scene> -out <beauty.exr>` renders such a scene with XPU2, with no Modo: one frame at the scene's full XPU2 samples, its render outputs written as the scene names them, MoonRay taking over a scene XPU2 cannot render.
- **Modo's Process texture** renders in MoonRay, XPU2 and MoonLightIPR: its Hue, Saturation, Value and Hue Shift on the layers beneath it, matching Modo's own render to within 0.0004. Its Bias and Gain are not followed yet, and say so.
- **MoonLightIPR draws a camera's bokeh image**: out-of-focus highlights take the image's shape, turned as the blades are, where they were round.
- **MoonLightIPR takes a map wired to diffuse transmission colour** (a leaf's or a blade of grass's translucency), at the material's diffuse transmission amount, where the map was left out.
- **MoonLightIPR's motion vectors follow a mesh that changes shape** during the shutter, not only its item's move.
- **Vertical Wrap -1 flips an environment image top to bottom**, and both wraps at -1 flip it both ways, at its full size; a vertical flip smeared the image's top row over the sky.
- **16K textures stay on XPU2**: a texture whose file was larger than 1 GB sent the whole scene to MoonRay XPU (a tester's volcano with a 16K EXR diffuse map), and textures past 2 GB each or 4 GB together, as decoded, went into Texture Overflow on any machine (the same volcano at 8K). XPU2 reads a texture a tile at a time, so a file's size no longer matters, and textures may now take half of XPU2's memory ceiling, 4 GB at least. Grass with a 16K float EXR renders on XPU2 with no overflow.
- **A VDB's fire renders when XPU2 hands a scene to MoonRay**: a VDB made with Load VDB File whose emission grid is set (flames, temperature) failed in MoonRay XPU, which this build cannot draw it in; MoonRay now starts in scalar for it, as for a cookie filter, while XPU2 keeps rendering it where it can.
- **Select Volume Here**: right-click in the preview to select the VDB volume under the pointer, found where it is thick rather than anywhere in its box.
- **An environment image flipped with Horizontal Wrap -1 lights the scene as it should**: a flip made the image a layered environment, baked at 512 x 256 for MoonRay and 256 x 128 for MoonLightIPR, which smeared an HDRI's sun and lit the scene oddly. A flip alone (Vertical Wrap 1, no rotation or other change) now sends the image whole, mirrored once at its full size and kept in the texture cache. Other wraps are baked as before.
- **A MoonRay graph's images are found when a scene has moved**: an image a node graph names that is not where it says is looked for as Modo's own image clips are, beside the scene, and then by its name in a folder the scene's other images are in (only where exactly one such file is there). Grass, made on another machine, rendered its grass grey; it renders green now. Relink Missing Images lists a graph's missing images too, with the file found already filled in, and writes it into the graph when applied (undoable). The Terminal says each image found this way.
- **Sharp textures in a MoonLightIPR Render**: a Render, and Render Animation with MoonLightIPR, have every image at its full size, where realtime keeps them to 1024 pixels across for speed. Textures are compressed on the graphics card, a quarter of the memory or less, so large scenes fit: Grass's 8K maps take 89 MB each rather than 256 MB, with no visible change and no loss of speed. A texture far away reads faster and no longer sparkles. The first Render of a scene prepares its images once (Grass: 109 s); after that its first picture came in 16 s. Where a scene's textures still do not all fit on the card, the largest are kept in the computer's memory and read from there, rather than every texture being made smaller.
- **Render Animation with MoonLightIPR**: the Render Animation window has an Engine: MoonRay as before, or MoonLightIPR, which renders each frame on the graphics card at the render's resolution to Render samples a pixel, denoised where the Denoiser is on, and writes it as an EXR (the beauty), with the picture type chosen beside it or in its place. Frames already in the folder are kept, as MoonRay's are.
- **Render missing frames continues a sequence as it is**: with it on, Render Animation keeps every frame already in the folder and renders only the others, so a sequence can be taken further (frames 1 to 100, then to 200) or finished after the scene or its settings changed, which the status line says. Before, it refused unless the range, the step and a fingerprint of the saved scene file were all as before: saving the scene was enough to stop it. Frames already there are still never overwritten, a sequence with another file prefix shares the folder, and the scene no longer has to be saved first.
- **Convert to MoonRay Rect Light**: right-clicking an area light in the Item List (or MoonRay > Convert Area Light to MoonRay Rect Light) makes it a MoonRay RectLight in its place, keeping its name, place, parent, children and Lighting controls, with its size, colour, strength and Visible to Camera as MoonRay renders the area light: in a test the scene MoonRay was given held the same light before and after. An ellipse-shaped area light is left as it is.
- **No more .postprocess folders beside rendered frames**: the denoiser's albedo and normal kept beside a frame (so that a render stopped before its denoised copy is made can make it without rendering again) are removed once that copy is made.
- **MoonLightIPR clamps from what the camera sees**: MoonLightIPR has its own Clamp From Bounce in Render Settings' MoonLightIPR group, 0 unless changed, so that Sample Clamp also takes the fireflies seen through clear glass (refraction through smooth glass is not a bounce). MoonRay's own stays under Noise and Filtering. A tester's refractive dragon went from about 1,200 specks to none, 0.6% darker.

  ![A refractive dragon in MoonLightIPR: Clamp From Bounce 1 on the left, speckled with red, and 0 on the right, the new default](images/moonlightipr-fireflies-dragon.jpg)

- **A shadow pass in MoonLightIPR**: Shadow joins MoonLightIPR's AOVs, a matte of how much of the direct light at what the camera sees its lights' samples found blocked, from 0 where it is lit to 1 in full shadow, the sky's light included. It is gathered with the beauty as the others are, so it shows at once and is in Export AOVs. MoonRay's own Visibility output is the same the other way round (1 lit).
- **Export AOVs with MoonLightIPR**: the preview's right-click Export AOVs is no longer greyed out with MoonLightIPR as the engine. It lists MoonLightIPR's own outputs (the beauty and denoised beauty; Diffuse, Glossy, Emission and Environment background; Albedo, Depth, Normal, Position, Alpha, Motion vectors where something moves, and Shadow) and saves the ones ticked as MoonRay's are: each picture type, one multilayer EXR, and the beauty with its alpha. Only the outputs ticked are asked of MoonLightIPR, once the window is closed, and the buffer list is left as it is; nothing is rendered again. In a test every EXR held MoonLightIPR's own numbers exactly, the beauty's alpha was the Alpha AOV, and the multilayer EXR's layers were the single EXRs.

  ![MoonLightIPR's AOVs of a glass dragon: beauty, diffuse, glossy and albedo above; shading normal, world position, camera depth and the shadow matte below](images/moonlightipr-aovs.jpg)

- **Motion vectors in MoonLightIPR wherever something moves**: a MoonLightIPR render reads the scene once and asks whether anything moves during the shutter; where it does, the scene is read with the shutter's two ends (held at the frame's moment where motion blur is off), so the motion vectors are gathered with every other AOV from the first sample and choosing them renders nothing again. A still scene is read once, as before. In a test, a sliding cube's vectors came 0.11 s after being chosen, 11.8 pixels across against about 12 expected.
- **Roughness Clamp in MoonLightIPR**: Render Settings > Noise and Filtering > Roughness Clamp, MoonRay's cure for fireflies from indirect caustics, now works in MoonLightIPR as in MoonRay: after each bounce, what the path meets further on is made at least as rough as the surface it left (a diffuse bounce counting as fully rough) times the clamp. As in MoonRay it roughens hair and the materials MoonRay renders as DwaBase (glass, subsurface, anisotropy, coat bump and MoonRay's own Dwa materials), not plain materials. In a test of rough gold balls among near-mirror metal, the clamp brightened the blurred reflections by 0.084 on average in MoonLightIPR and 0.073 in MoonRay. Sample Clamp, Clamp From Bounce and Roughness Clamp are shown in Render Settings' MoonLightIPR group as well: the same settings as under Noise and Filtering.

  ![Rough gold balls among near-mirror metal, Roughness Clamp off above and 1 below, MoonRay left and MoonLightIPR right: the clamp blurs and brightens their reflections alike](images/roughness-clamp-engines.jpg)

- **MoonLightIPR's Render Animation writes the denoised beauty beside the beauty**: with the Denoiser on, each frame is saved as its beauty EXR and its denoised copy beside it (frame.denoised.0001.exr), as MoonRay's frames are, both from the same samples; a JPEG, PNG or other picture type is made from the denoised one. Before, the denoised picture was written in the beauty's place.
- **Motion vectors in MoonLightIPR**: Motion vectors joins MoonLightIPR's AOVs: how far what the camera sees moves, in pixels across and up, from the shutter's opening to its closing, as MoonRay's say it; moving objects and the camera (a mesh changing shape not yet). With motion blur off the picture stays sharp, the scene read with the shutter's ends and held at the frame's moment. In a test, a cube's front face moved 128.84 pixels against the 128.8 its keys and the lens give.
- **Denoised Beauty after a MoonLightIPR Render**: chosen once the Render is done, the picture is denoised as it stands, not rendered again.
- **VDB sequences stay on XPU2**: a VDB shape playing a sequence (static unticked) fell back to MoonRay XPU, which XPU2 refused static unticked for; the kit hands MoonRay each frame's own file, so it is now passed on as static, and XPU2 renders it. Standard XPU, which crashed on such a scene with a mesh beside it, is no longer reached.
- **A numbered VDB file plays as a sequence**: Load VDB File unticks static by itself where the file chosen is one of a numbered run (EmberGen, Houdini), so that scrubbing the timeline steps through it at once, and says so in the Event Log. Tick static again for the one file.
- **VDB shapes show their size in the viewport**: the box the grid fills and a cloud of points where it is thick, read once in the background and drawn natively, of the frame's own file as the timeline moves.
- **XPU2's sampling settings follow the engine in use**: where XPU2 falls back to MoonRay XPU for a scene, its Sampling settings are greyed and MoonRay's own come back; they return as XPU2 takes the scene again.
- **XPU2 realtime with denoising**: the buffer list under XPU2's realtime is the beauty and the denoised beauty alone, and the denoised beauty is offered again.
- **MoonLightIPR renders at the camera's resolution**: Preview Preferences > MoonLightIPR quality has an opt-in for a MoonLightIPR Render (RT off) to be made at the active camera's resolution, as MoonRay's is; realtime keeps Realtime preview resolution, as XPU2's realtime does. Pixel samples there is now RT pixel samples, realtime's; Render samples is the Render's.
- **Select Mesh Here**: right-click the picture to select in Modo the mesh under the pointer, or the instance of it there.
- **Finer graph sliders**: the MoonShine graph's numbers drag in steps of 0.01, 0.001 with Ctrl and 0.1 with Shift, and a colour's parts stay between 0 and 1.
- **The engine's status stays put**: the persistent session no longer says "Reloading scene structure" over what the status bar says of the engine rendering.
- **Render with MoonLightIPR**: with RT off, the Render button is no longer greyed for MoonLightIPR. A Render gathers the samples a pixel set in Render Settings > MoonLightIPR > Render Samples (2000 unless changed, saved with the scene), flat out, neither paced nor stopped early once the picture looks clean, and stops; Stop keeps what it has. The label under the picture says how many samples a pixel the picture holds, against the target, as each frame comes (137 / 500 ps), in realtime as well.
- **AOVs in MoonLightIPR, for motion graphics**: with MoonLightIPR as the engine, the buffer list offers the passes a motion graphics composite is made with, at once, with nothing to compile and no cost to the beauty. The light in four passes that add up to the beauty (fog's light before the first surface apart): Diffuse (with subsurface), Glossy (with hair, mirror reflections and refraction), Emission and Environment background, gathered beside the beauty from its own paths. And from what the camera sees first: Albedo, Camera depth, Shading normal, World position and Alpha. All of them are gathered together with the beauty from its first sample, so choosing one, or going back to the beauty, shows it at once, with nothing rendered again; gathering them costs the beauty no measurable time. In a test, switching took 0.05 s and the four light passes added up to the beauty within 0.0006. Cryptomatte and MoonRay's other buffers stay MoonRay's. Motion vectors are to follow.
- **A diagnostic for MoonLightIPR crashes**: with the environment variable MOONLIGHTIPR_VALIDATE=1 set before Modo starts, OptiX checks every launch and writes what went wrong to the Render Log. Slower; for reports from graphics cards not tested here.

## New in 0.5.3.2

- **MoonLightIPR clears its noise sooner**: the preview now draws its samples from OpenQMC, the Academy Software Foundation's sampling library, so each pixel's samples spread evenly over the lights, the lens and the ways light bounces, where before they fell by chance. For the same noise it needs about half the samples where the light comes from lamps, an environment or fog, and fewer on VDB fog, hair, depth of field and glass; subsurface random walks gain little. A sample takes up to about a tenth longer. Nothing changes in how the preview looks once it has cleared.
- **Edits that change nothing leave realtime alone**: an edit that changes nothing no longer starts MoonLightIPR or XPU2's realtime over, nor has the scene read whole. Checked in Modo with both engines, each against a real change of the same kind, which still renders:
  - A value entered as it already is, in the graph editor or in a MoonRay material's Properties: Enter pressed on 0 where it was 0, a start value entered as shown (the graph editor used to store it, which counted as a change), or 0.3 entered where the field showed a stored 0.30000000000000004. The graph editor's own preview is left alone too.
  - Schematic work: a workspace made, an item added to it or taken out, a node moved. Modo told of these as links and groups, which were taken for changes to the scene. Every link Modo tells of was so taken, as its graph is told by name; a transform made for an item's first move is now the move it is, not a reading of the whole scene.
  - A Modo material channel set to its own value is still read (Modo tells of it as an edit), but renders nothing anew.
- **One resolution for every realtime preview**: MoonRay LS quality's Width limit (80 to 1280 pixels wide) is gone: it held a tall picture, narrower than it, at the realtime preview's size, and set LS apart from the other previews. Preview Preferences' Realtime preview resolution now offers 1/8 and 1/16 of the render's resolution as well as Full, 1/2, 1/3 and 1/4, and MoonRay LS renders at it, as MoonLightIPR and RT with MoonRay XPU2 or XPU do, so a portrait shrinks as a landscape does.
- **EV and gamma by dragging** (a tester's report): the preview window's EV and gamma changed only from their small arrows, held to repeat slowly, or by typing, and exposure was shown only once they stopped changing. Each field now changes as the pointer is dragged from anywhere on it, its number or its arrows: one step (0.25 EV, 0.05 gamma) every 4 pixels right or up, back left or down, a tenth of that with Ctrl held and five times it with Shift. A click on an arrow steps once, and a click on the number puts the cursor in it to type; an arrow held still no longer repeats. Exposure is shown every fifth of a second while it changes.
- **The MoonShine graph's numbers by dragging** (a tester's report): a graph number showed six decimals but stepped only by 0.1, each arrow went one way only, and the two arrows were about three pixels apart, so where the pointer landed decided up or down. Its numbers, whole numbers and colour and vector parts now drag as EV does: 0.1 every 4 pixels right or up (whole numbers by 1), back left or down, Ctrl for 0.01, Shift for 0.5; a click on an arrow still steps once. A whole drag is one undo, back to where it began. The material, and Modo's form for it, take the value once, when the drag is let go; the graph's own swatch follows as it goes.
- **RT goes off after a MoonLightIPR Playblast**: a playblast stopped the preview's following of the scene but left realtime switched on, so RT said On after it with nothing updating, until another engine was chosen and MoonLightIPR chosen again. Realtime is now switched off as the playblast starts, as for Render Animation, and RT says Off when its frames are done, it is stopped or a frame fails: one press follows the scene again.
- **Select a material from the picture**: the preview window's right-click menu has Select Material Here beside Focus Here. The same ray Focus Here sends through the scene the picture was rendered from finds the polygon under the pointer; the material its tag names (a Shader Tree material, or a MoonRay material) is selected in Modo, ready in Properties or the graph editor. Before, a material could be picked from the picture only with a material Cryptomatte rendered and shown.
- **Toon lines in a colour, with their own alpha** (issue 134): a Toon display filter's lines alone came out white on black, so laying them over the beauty took an invert and a multiply, and fading them showed white. Now:
  - The Toon filter's Ink Color draws its lines in any colour over its shading (a MoonRay Source Override, "Toon lines in a colour", on by default).
  - The Compositor's Ink Lines node (in Merge) lays a colour over a picture through a Toon filter set to Lines only; Mix fades the lines towards the picture beneath, never towards white.
  - Saving a Toon filter's lines alone from the preview gives the lines in their Ink Color with what they cover as alpha: premultiplied in OpenEXR, straight in PNG, TIFF and Targa.
  - A render to a file gives them the same way in its EXR: the lines' channels become the lines in their Ink Color with an alpha channel of what they cover.
  - Outlines no longer step with the pixel grid: the lines are smoothed along their direction (a MoonRay Source Override, "Toon lines smoothed", on by default).
- **Memory meter for the shader compile**: Preferences' Shaders section (under Graphics cards) shows the machine's free RAM beside Compile XPU2 Shaders, read every few seconds while Preferences is open: enough, tight (the compile begins but may stop if other programs take the memory it needs) or not enough (it needs about 8 GB free to begin). Once a compile has finished, the meter goes by what that compile took on this machine.
- **VDB fire from temperature or flames grids**: a VDB's emission grid of single values (temperature, flames or heat, as EmberGen, Houdini and Blender write them) glows grey, coloured and scaled by the VDB volume's incandescence gain mult. MoonRay takes only an RGB emission grid; it refused one of single values ("is not an RGB grid") and left the whole VDB out of the render, smoke included. MoonRay, XPU2 and the MoonLightIPR preview all follow it. A MoonRay Source Override in Preferences ("VDB fire from temperature or flames grids"), on by default.

  ![JangaFX's free EmberGen explosion glowing from its flames grid: MoonRay left, XPU2's graphics card right](images/vdb-fire-flames-grid.png)

- **Alembic fluids and other changing meshes**: an object's Geometry file (in its production settings) can now be an Alembic file. The kit reads its meshes at each frame's time itself, with a native reader of its own, and renders them with the object's material tag, where the object stands: in MoonRay, XPU2 and MoonLightIPR. That includes meshes whose points and faces change from frame to frame, as a fluid mesher writes them; Modo's own Alembic loader shows one frame of such a mesh. Before its first sample and after its last, it is not there. With motion blur on, it blurs along the file's velocities.
- **A mesh that changes during the shutter no longer stops the render** (a tester's report: "Motion blur requires stable topology"): an object's Changing topology during shutter now starts at Blur by velocities where it has them, else frame-time. Such a mesh blurs along its velocities where it has them and otherwise renders as it is at the frame, without motion blur, with a notice. Require stable topology can still be chosen.
- **VDB sequences**: untick a VDB shape's static (MoonRay's own setting, now just after its file) and the numbered files beside the one chosen (fire_1.vdb, fire_2.vdb... or smoke.0001.vdb, smoke.0002.vdb...) are its frames: each frame renders its own file, in MoonRay, XPU2 and MoonLightIPR, live as the timeline moves. A frame offset shifts it; outside its frames the volume is not there, or, with hold first and last frames, shows its first or last file. A frame missing in the middle shows the one before.

  ![The EmberGen explosion as a VDB sequence, coloured by its temperature: frames 20, 45, 70 and 100, rendered on XPU2's graphics card](images/vdb-fire-sequence.png)

- **Scene Proxies render with their own materials**: an object brought in as a Scene Proxy (Add Item > Scene Proxy) now renders in MoonRay as Modo renders it: its geometry once for each proxy, where each proxy stands, shaded by the Shader Tree of the scene file it loads, where before it took the main scene's or came twice. A proxy with a Render Item renders that item alone. Imported references (File > Import Reference) already rendered with theirs. Modo itself may crash as it quits while a scene with a Scene Proxy is still open, once it has been rendered or previewed (with or without the plugin's code); saved scenes and Modo's settings are kept. Closing the scene first avoids it.
- **Imported Alembic fluids blur**: a mesh brought in with File > Import of an Alembic file renders from the file itself, its own points and faces at each frame, blurred along the file's velocities, in MoonRay, XPU2 and MoonLightIPR. Modo's own import hands a render one mesh of fixed size stretched to follow the file, with no velocities, so a fluid mesher's mesh could not be blurred. Its switch is on the MoonRay Source Overrides page.

  ![A fluid mesher's Alembic mesh at frames 90, 120, 150 and 180, its faces changing every frame, its drops blurred along the file's velocities, rendered on XPU2's graphics card](images/alembic-fluid-frames.png)

- **VDB fire coloured by its temperature** (blackbody): with a VDB shape's blackbody colour on and its temperature grid chosen as the emission grid, the fire glows in the colours a hot body glows at each voxel's temperature: deep red, orange, then yellow-white where it is hottest; hotter is also brighter. Kelvin at 1 sets the temperature a grid value of 1 stands for (3,000 K at first). The kit makes a copy of each frame's file with the colours added (about a second a frame, then kept). The incandescence gain mult still scales the glow. A MoonRay Source Override in Preferences ("VDB fire coloured by its temperature"), on by default.

  ![The EmberGen explosion coloured by its temperature grid, rendered on XPU2's graphics card](images/vdb-fire-blackbody.png)

- **MoonLightIPR keeps a VDB fire's colour**: the preview averaged a VDB volume's incandescence gain mult, so an orange fire glowed white; it now glows in its colour.
- **Glowing fog from maps on XPU2's graphics card**: a volume whose emission, colour or density comes from procedural maps renders on the card, where before it sent the whole scene to the processor. Maps that read image textures still run on the processor.
- **Volumes render faster in XPU2**: on the graphics card a VDB cloud renders in about two thirds of the time (88 s to 57 s on a test cloud) and glowing fog in about three quarters, with every pixel the same as before.
- **A smaller XPU2 shader compile**: the compile could climb past 40 GB of memory and never finish; it now takes 8 to 15 minutes and at most about 11 GB. It will not begin without about 8 GB free, and stops itself, saying so, if memory runs low while it works.

## New in 0.5.3.1

- **Mesh lights render as in Modo in every engine**, checked against Modo's own renders:
  - **Any polygons**: MoonRay reads a mesh light's corners in steps of three or four, never cutting its faces, so a Prototype with n-gons, or quads beside triangles, shone from triangles that were not its own (an octagon beside a quad and a triangle lit only from the triangle). The kit now hands MoonRay the faces as triangles, for MoonRay's Scalar, Vector and XPU modes and XPU2.
  - **Meshes emitting by their Object controls** (Use mesh as emitter, or a MoonRay MeshLight item naming them) light again, in the preview window and in renders: the light's copy of the mesh held no points, as the scene's meshes go in a binary file beside its text.
  - **The Prototype is the light**: Modo never renders a Mesh Light's Prototype as a surface. The kit drew it as a grey mesh too, lying on the light, which hid the light and blocked its own light.
  - **A hidden Prototype gives no light**, as in Modo's own renderer, with a notice saying so. Show the Prototype mesh to light with it.
  - **MoonLightIPR** shows a Mesh Light that is Visible to Camera (before, it lit the scene but stayed invisible), and shines and is seen from the polygons' front only, as Modo and MoonRay do; it shone from both faces.

  ![Two Mesh Lights, a square and an octagon beside a quad and a triangle, lighting a ball: Modo, MoonRay, XPU2 and MoonLightIPR](images/mesh-lights-engines.jpg)

- **A mesh light hidden from the camera still shows in reflections**: a mesh emitting by its Object controls, with MoonRay camera appearance at Hidden; keep illumination, is now left out of reflections as a surface too, so a mirror or glossy floor shows the light itself; before, the mesh's grey surface lay on the light in reflections and blotched it. MoonLightIPR follows the camera appearance setting as well (Show emitter, Show surface only, Hidden), where it went by the emitter's own settings alone and drew a hidden one as a dark surface.
- **Glowing volumes render on XPU2's graphics card**: a MoonRay volume's emission, or a VDB's emission grid (a fire), renders on the card with the rest of the scene and lights the surfaces and the fog around it, where one glowing volume sent the whole scene to the processor. Checked against MoonRay: a thin and a thick glow, two glows overlapping, a glow lighting a fog, and a VDB fire, each as close as two renders of one scene. A volume whose maps give its emission still renders on the processor. Compile XPU2 Shaders once more after installing.
- **Bump node in the MoonShine graph**: the graph's Normals and bump section had only normal maps. A new Bump node turns a height (a greyscale image, or any texture) into a shading normal, as a Shader Tree Bump layer does: wire the image into Height, set Amplitude (how high white stands above black, in scene units, 5 mm to start, as Modo's Bump Amplitude) and connect the node to the material's normal input. MoonRay has no node of its own for this; the kit's, as for the Shader Tree, works in every engine, MoonLightIPR included. It is a MoonRay Source Override, Bump node in MoonShine graphs, on by default: off, the node leaves the normal flat, as MoonRay itself would.
- **Realtime preview resolution as a share of the render's** (a tester's suggestion): Preview Preferences' Realtime preview size limited the realtime previews' width in pixels (320 to 1280), so a tall picture, narrower than that, stayed at its full size (a 1180 x 2000 portrait was rendered whole at every update). It is now Realtime preview resolution, Full, 1/2, 1/3 or 1/4 of the render's resolution, which shrinks a tall picture as it does a wide one: MoonLightIPR, MoonRay LS and RT with MoonRay XPU2 or XPU. A width chosen before is taken to the nearest share of a 1920-wide render (640 px, the old default, a third); a third where none was chosen. Playblast starts from the same share of the camera's width.
- **Exported Cryptomattes open as Cryptomattes**: a Cryptomatte saved with Export AOVs, on its own or in the multilayer EXR, had its channels but not the header (its name, hash and manifest of matte names) that every Cryptomatte reader looks for, so Photoshop's readers (ProEXR, Exr-IO), Nuke and Fusion did not take it for one. It is now saved with that header, the manifest from the scene it was rendered from, and its channels named for its category (CryptoObject00, CryptoMaterial00...), so that object and material Cryptomattes can share one file; the channels MoonRay keeps only for resuming a render are left out. A Cryptomatte from Render was already whole.
- **Object, material and asset Cryptomattes together again**: since 0.5.2.1 a scene with more than one Cryptomatte category would not render ("Multiple Cryptomatte categories require a matching category-enabled runtime"): a rebuilt MoonRay library no longer matched the record that says the runtime writes several. The record is brought up to date, checked by rendering all three categories in scalar, vector and XPU mode.
- **Checkers placed as in Modo**: a Checker laid through the object (Solid projection) came out with squares twice as large as Modo's and at another angle. Measured against Modo's renders of each locator turn, projection axis and position: a square is half the locator's size, lies across the locator's two axes other than its projection axis, and the locator's turns apply as Modo applies them. In every engine.
- **A missing UV map is a notice, not a failed render**: a material whose texture reads a UV map that the mesh wearing it has not (a texture set up on another mesh's map) stopped the render with "Mesh ... is missing UV values in map ...". Those polygons now render with the map's values at 0, and a notice names the mesh, the map and the material, so the texture can be pointed at a map the mesh has.
- **PBR validity in Preview Preferences**: the Diagnostics switch is in the preview window's Preview Preferences as well as in Modo's Preferences > MoonRay > Renderer, one setting, each following the other.
- **Realtime with standard XPU** is a choice of three, where it was a switch: Off, On the processor (vector, as before: quick to restart, the card left to Modo's viewport) or On the graphics card (XPU: somewhat quicker to render, slower to restart as each change of geometry is built on the card again). In Preferences > MoonRay > XPU (graphics card) and in Preview Preferences, one setting. Where the switch was on, the choice starts at On the processor.

  ![Preview Preferences: Realtime with standard XPU, and PBR validity under Diagnostics](images/preview-preferences-realtime-xpu.png)

- **Heavy scenes start much sooner**: on a tester's 1.5-million-polygon car, realtime's first picture came after about 2 min 20 s of preparing the scene, and now comes in about 16 s (XPU2, cached textures).
  - **Smoothing in native code**: normals smoothed by each material's smoothing angle are worked out by the kit's geometry adapter on all of the processor's threads, about a second for 1.5 million polygons where Python took a minute on one. Meshes of any size now take their material's Modo smoothing angle, where those over 300,000 polygons were smoothed all over.
  - **Cryptomatte by material** hashes each material once, where it hashed every polygon (40 s of every scene written on the car).
  - **Smoothed normals are kept for every mesh**: kept for 64 meshes, a scene of more had all of them worked out again at every write.
  - **The mesh reader keeps the numbers as they come**, where it made Python lists of every point, UV and normal (5 s of every reading of the car).
- **A scene's first realtime run is much quicker**: on the car, the first picture of a run with nothing cached yet came after more than 4 minutes, and now after about 47 s.
  - **Environment images shrunk straight from the file**, their colours converted as before, several side by side: each was first made into a full-size float texture only to be shrunk to 512 by 256 (the car's three 16,000-pixel-wide HDRs: 85 s to 15 s).
  - **Grey environment images are grey**, where they came out black: an image of one channel was asked for its red, green and blue.
  - **Textures that lay out their own UVs** (moved, rotated, scaled or projected) are worked out for whole meshes at once, and **meshes whose materials use different UV maps** (a tyre's tread and sidewall) are split by map in the kit's native code and read whole: both were read a polygon at a time (the car's reading: 7.7 s to 4.6 s, the same numbers).
  - **Environment layers laid in native code**: an environment of image, colour and sky-gradient layers is laid together by the kit's geometry adapter over all the processor's threads, where Python did it a direction at a time (the car's four layers: 10 s to a fraction of a second, the same map to the bit). Layers in groups or with masks, procedurals and physical skies are laid in Python as before.
  - **Every mesh is read by the native adapter**, small ones too, and **a mesh missing a UV map its texture reads is read whole**, its polygons without the map at 0, with the same notice (the car's reading: 7.1 s to 3.2 s, the same lists and notices).
- **Fur guides are followed**, as Modo's own renderer draws them: guides are the curves on the fur's mesh that wear its material (Use Guides from Base Surface), or the curves of the guide Item, optionally of one polygon tag. **Direction** turns each fibre to its nearest guide's way out of the surface; **Direction + Length** also takes Guide Length to its length; **Shape** gives each fibre its nearest guide's form at the fibre's length times Guide Length; **Range** grows fur only within Guide Range of a guide, at the guides' own length; **Clump** gathers the fibres within Guide Range to the guides, as the Clumps setting does with its tufts. Grown by the kit's native fur grower, as before, which has the guides too. Blend Amount and Blend Angle are not read yet.
- **The Fur material's vector map and width map are followed**, as Modo's own renderer draws them: each fibre grows along the vector map's vector at its root and as long as the vector, whatever the material's Length, and none grows where the vector is nothing; the width map's weight at a fibre's root is its share of the material's width. Grown by the native fur grower, which writes each fibre's own radii, so the preview engines and MoonRay draw them the same.
- **A mesh's weight and colour maps are read at once**: its weight, RGB and RGBA maps, with values set apart on some polygons, are read by the kit's native geometry adapter in one call instead of a point and a corner at a time from Python, the same values (a mesh of 21,600 polygons and six maps: 1.04 s to 0.08 s, Modo's thread free sooner).
- **A subdivided mesh's creases are read at once**: its Subdivision weights on edges and points, which go to MoonRay as crease sharpness, are read by the native geometry adapter in one call instead of an edge and a point at a time from Python, the same creases (a subdivided mesh of 21,600 polygons with 8,000 weighted edges: 0.3 s to 0.05 s).
- **Texture projections are worked out at once**: a texture locator's planar, cubic, cylindrical or spherical projection, with the layer's UV matrix, rotation and scale, is worked out at every corner of a mesh by the native geometry adapter in one call instead of a corner at a time in Python, the same numbers as 32-bit floats (a mesh of 359,400 faces: 6 s to 0.5 s).
- **Hair is lighter to read and pack**: hair grown from guides keeps its strands as the hair grower hands them over, its scalp is read and laid out in the world in one call, and each strand's taper and UVs, and MoonLightIPR's segments, are worked out by the native geometry adapter, not a point at a time in Python, the same numbers (30,000 strands of 7 points on a scalp of 399,000 triangles: reading the scene 8.4 s to 3 s, MoonLightIPR's packing 1.2 s to 0.1 s).

## New in 0.5.3

A release for its lighter use of memory and XPU2 on several devices, with a new XPU2 runtime (runtime-xpu2): install it, and **Compile XPU2 Shaders once more**.

- **Look-dev is lighter on Modo**: a change in the graph editor is a material's edit, not a reading of the whole scene with its meshes; values stepping in the graph editor are written at most every 150 ms; the Shader Tree is walked once for a reading, not once for each material; and the check of the scene's texture files runs beside Modo, not on its thread once a second.
- **Hidden meshes' materials are left alone**: a material worn only by hidden meshes is not read at each edit of another, and its images are not made ready for rendering.
- **Low Value, High Value and the texture corrections change without a reload**: gamma, brightness, contrast and Low and High Value are the same nodes whatever their values, so a change is a value MoonRay's session takes as it is, where moving one to or from its default loaded the whole scene again (twenty seconds on a heavy one).
- **An input wired in the graph editor is locked in Properties**: it is greyed there, and setting it can no longer cut the wire.
- **A material node's inputs in folding groups**: Diffuse, Specular, Clearcoat, Fuzz, Glitter and the rest, as Properties has them; click a group to open or fold it; connected inputs always show.

  ![A DwaBaseMaterial node with Diffuse open and its other groups folded, beside the same groups in Properties](images/graph-editor-groups.webp)

- **A material's lists come up quicker**: the Properties panel reads each material once for all of its controls (a DwaBaseMaterial's refresh 60 ms to 15 ms), and the graph editor's property table makes the fields of a folded group only when it is opened or searched into (0.9 s to 0.3 s).
- **Switching networks in the graph editor keeps the window**: choosing another material in its list closed the editor altogether when it had been opened from another one.
- **Remove Network**: Graph > Remove Network removes another material's whole node network, offered only while the scene has more than one and never the one open; right-click a node > Remove Network removes the loose network it belongs to, beside the material's own. Each asks first, and undoes.
- **A cookie light filter renders in XPU2**: XPU2 draws it as MoonRay's scalar mode does, so a light with a cookie no longer sends the whole render to scalar mode. Should XPU2 hand the scene back, MoonRay renders it in scalar, as MoonRay's vector and XPU modes leave the picture blank.
- **XPU2 needs a third of the texture memory**: float textures are held in half floats (each value within 1/2048 of itself; a tile with a value past their range, such as a sun, stays in floats), grey images in one channel (the kit makes them so, and converts textures again once), a tile of one colour as that colour alone, and the graphics card's texture cache gives each texture slots of its own size. A grass scene with 8K ground maps went from 4 GB of textures on the card to 1.4 GB, out of texture overflow mode, with the same picture. Set `XPU2_SESSION_FLOAT_TEXTURES=1` to keep floats.
- **XPU2 holds less of the graphics card**: the queue for samples waiting on texture tiles is made only where a frame can use it, the subsurface stack only where a material scatters under its surface (any DwaBase material kept it, some 3.5 GB of a 24 GB card), and the texture cache grows as tiles are read. A scene with grass peaked at 9.7 GB rather than 10.9 GB, 8.7 GB without subsurface, with the same picture.

  ![Grass, a crop at full size: XPU2 holding its textures in floats on the left, in a third of the memory on the right](images/xpu2-texture-memory-grass.jpg)

- **Depth of field in XPU2 has even grain**: a light far out of focus showed a lattice inside its bokeh disc; the lens samples now have an order of their own and every sample sequence is Owen-scrambled, so the noise is MoonRay's kind. The lens and shutter times draw Sobol's first dimensions in a per-pixel scrambled order (Burley's padding) instead of sharing the pixel position's; at 256 samples a pixel the difference from MoonRay halves. Pictures change in their noise only.
- **A sliver triangle no longer sends an XPU2 frame to MoonRay**: a hit on a triangle too thin for its normal in single precision failed the sample, and with it the whole frame. The grass scene fell back to MoonRay every time on the processor alone and now and then with the graphics card. The normal is worked out again in double precision, else facing the ray. A fallback now names the sample that failed (its status and pixel); `XPU2_SESSION_DEBUG_FAILURES=1` says why.
- **XPU2 uses every graphics card and every processor**: a second or third NVIDIA card renders the same picture alongside the first, taking samples from the same grid at its own pace, and a machine with more than 64 threads (several processor groups in Windows) puts XPU2's workers on all of them. A card that can't run OptiX's denoiser hands realtime denoising to the next card that can, and with none, to Open Image Denoise on the processor. A card that fails to take the scene is left out and the others carry on. Tested in simulation only, with one card here.
- **Device Management**: in Preferences > MoonRay > **XPU2**, lists the processors and NVIDIA cards XPU2 finds, each with its own switch (a card keeps its switch by its own ID if the cards are renumbered), and Compile XPU2 Shaders there compiles for each kind of card not up to date, switched on or not, so one switched on later renders at once; a new kind of card shows as Out of date, naming it, and only it is compiled. It replaces the Devices choice on the XPU2 page, and what was chosen there is kept until a switch is changed. The last device on cannot be switched off.
- **XPU2 knows NUMA**: a two-socket workstation, or a processor of several dies (first- and second-generation Threadripper, EPYC, Xeons with Sub-NUMA Clustering), reaches its own node's memory quicker than another's. XPU2 now puts a share of its workers on each node, feeds each graphics card from the node nearest it, and keeps the texture tiles it decodes in the memory of the node that decoded them. A node that runs short moves its oldest tiles to the node with the most room, a hop across the sockets instead of a fresh read from disk, and only then lets tiles go. On a one-socket machine nothing changes. Tested in simulation only.
- **A bokeh image turns bokeh on**: with the switch to use the Modo camera's lens on, choosing a bokeh image on a dw camera uses it whatever Modo's iris blades say. The dw camera's fields that Modo's camera drives (focal length, film, offsets, depth of field, blades, stereo, shutter) are greyed while the switch is on.

  ![Lights far out of focus through a hexagonal bokeh image, MoonRay left and XPU2 right](images/xpu2-bokeh-image.jpg)
- **VDB volumes render on XPU2's graphics card**: a VDB cloud that did not glow was handed sample by sample to the processor; the card now samples its grids itself and marches it without a table of steps, about five times faster on a test cloud with the same picture. Glowing VDBs still render on the processor.
- **Mirrored meshes face outward**: a mesh with a negative scale and normals of its own rendered black in MoonRay and XPU2 (MoonRay's own behaviour), and one without them slightly wrong; a new MoonRay Source Override, on by default, turns them outward.
- **The graph editor does not restart the preview for nothing**: moving a node, or adding one wired to nothing, no longer renders the picture again.
- **A dw material's own roughness in MoonLightIPR**: a dw Metal or Base material's roughness was taken from Modo's Material Ref tab; it is now the material's own.
- **The MoonRay Widget renders with XPU2** (whatever the preview's choice), at the size it is shown, with 1024, 2048 or 4096 samples, and a **Scale** to size the ball in scene units for curvature and other procedurals.
- **A dwVdbVolume takes its VDB file**: adding one asks for the file, and its form has Load VDB File; the VDB shape that shows it is made for it.
- **PBR validity**, a diagnostic in Preferences > MoonRay > Renderer > Diagnostics: while it is on, MoonRay XPU's and XPU2's renders hold MoonRay's PBR validity output in place of the standard outputs, and the preview window shows it. Green is a plausible material, red one out of range, yellow in between: here the dragon's bright orange is just above the brightest plausible albedo. Off, the standard outputs come back.

  ![The dragon test scene, its beauty on the left and its PBR validity on the right: the floor green, the dragon yellow](images/pbr-validity-dragon.jpg)

- **Realtime with MoonRay XPU, on the processor**: an opt-in in Preferences > MoonRay > XPU; with XPU2 off, RT then follows the scene with MoonRay and MoonRay LS.
- **After XPU2 hands a scene to MoonRay XPU**, MoonRay's sampling settings are no longer greyed: they are the ones used.
- **Modo no longer crashes as it quits**: with a graph editor open, or once the preview window or a material's properties had been used, Modo could end with an error on the way out. The kit no longer looks through all of Modo's windows to find its own, puts its open windows away first, and lets go of its scene listener properly.
- **Modo's Mesh Lights shine**: a Mesh Light gave no light in MoonRay, XPU2 or MoonLightIPR. It now shines from its Prototype mesh, shown or hidden, placed by the prototype or by the light as Use Prototype Transform says, with its radiance and colour, and seen by the camera when Visible to Camera is on.
- **Alembic streams in**: a file loaded as Alembic Streaming Meshes (Modo's Alembic Mesh items) now renders, moving over time and with motion blur, as files loaded as Modo meshes with streaming deformers already did. Alembic Curves and Point Clouds take the same path, though untested.
- **An environment no longer renders red**: a grey environment, saved as one channel since the texture memory work, lit the scene red in MoonRay and XPU2; images that light the scene keep three channels.

## New in 0.5.2.2

A hotfix to 0.5.2.1, to the kit alone: the runtime of 0.5.2.1 stays.

- **Smart Render and Safe Denoising follow the renderer chosen**: switching Preferences > MoonRay > XPU2 to MoonRay XPU makes them editable in the Render item at once, and they work in Vector and Scalar mode whichever renderer is chosen. Smart Render chosen from the picture's menu with the Denoiser off sets one, OptiX with an NVIDIA graphics card and Open Image Denoise without, and the foot of the picture says when Smart Render is not applied.
- **Render over a draft renders at the first press**: pressed while Draft is still drawing its lines, it stopped the draft and had to be pressed again; now the draft stops and the region renders, with MoonRay XPU and XPU2.

## New in 0.5.2.1

A hotfix to 0.5.2, with a new runtime ZIP: install both, and **Compile XPU2 Shaders once more**.

- **XPU2 needs about half the graphics card's memory**: a simple scene went from about 11 GB to 4.5 GB, at the same speed and
  with the same picture, so XPU2 runs on smaller graphics cards. A leafy scene that filled 32 GB of graphics memory and
  crashed now renders in 20 GB.

  ![A tree's leaves against the sky, rendered in XPU2 in 20 GB of graphics memory (picture: Pixelwerk)](images/Leaf.webp)

- **Moving subdivision surfaces render in XPU2**: a moving mesh with adaptive subdivision, and copies of a subdivision mesh
  that changes shape during the shutter, no longer send the scene to MoonRay XPU, nor does a still mesh taken for a moving one.
- **Playblasts render flat out**: each frame gathers all its samples as fast as the graphics card can, without the 8 seconds a preview spreads a render over, and previews keep that pacing for drags.
- **dw Perspective and Orthographic cameras use the Modo camera's lens**: focal length, film, offsets, depth of field, F-stop, focus distance, iris blades, stereo eye and shutter are edited in the camera's own Camera and Camera Effects tabs. The switch heads the dwPerspectiveCamera tab; turn it off to use the MoonRay values there, as scenes from before do.
- **Saved pictures keep their alpha**: with Alpha among the render's outputs, Save Image and Export AOVs save the Beauty and the Denoised Beauty with it, as PNG, TIFF, Targa or OpenEXR. Export AOVs can also save every output ticked as one multilayer OpenEXR, and a group's own checkbox (Pictures, Light and the rest) ticks and unticks what is under it.
- **MoonRay starts whatever is in the Windows PATH**: with a file in it, such as `cmd.exe`, every preview and scene load stopped with "directory iterator cannot open directory: Not a directory". The kit now hands MoonRay only PATH's folders, and MoonRay's own look passes over such entries (Start with any PATH, among the Source Overrides).

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

## MoonRay XPU2

**XPU2** is a new way of rendering MoonRay previews: the processor and the graphics card work on the same picture at
once, each taking its own share, neither waiting for the other. Its pictures settle to MoonRay's own.

*XPU2: Asynchronous Monte Carlo Path Tracer designed by Raphael Tobar. Not affiliated with or endorsed by DreamWorks
Animation.*

- **The default GPU renderer.** Where MoonRay would render the preview on the graphics card, XPU2 does. To go back to
  MoonRay XPU: System > Preferences > MoonRay > XPU2 > GPU renderer.
- **Compile XPU2 Shaders once**, on the same page. It runs in the background while Modo stays usable, and the page
  shows how far it has come. Until it is done, XPU2 does not render, and the preview says so.
- **Samples go where the picture needs them.** XPU2 renders in generations: every pixel gets a first look, then each
  generation sends more samples to the parts still noisy, and clean parts stop. Plain walls and skies finish quickly;
  glossy reflections, soft shadows and glass get more.
- **XPU2 Sampling** in Render Settings: Generation Samples (16), Halting Rule (Time or Exact), Halt at Noise (10),
  First Look (4), Most Samples (16 times the average) and CPU Workers (on). While XPU2 renders the preview, MoonRay's
  own sampling fields are greyed and show what XPU2 takes; final renders use them as always.
- **The line under the picture** says how XPU2 samples: *XPU2 Gen. 16 ps avg (4-256), noise 10* is 16 samples a pixel
  on average, 4 to 256 in any one pixel, each part stopping at noise 10.
- **Devices** (Preferences > MoonRay > XPU2): the processor and the graphics card together, or either one alone.
- **Realtime**: camera moves, object moves and light changes are taken up at once, without preparing the scene again.
  While things move, the picture comes at the Realtime preview size, every pixel from the start, and is not denoised.
  **Realtime Sample %** sets how much of the render realtime makes (100% by default), in Render Settings and the preview's
  preferences.
- **Denoising**: the Denoiser works with XPU2 previews. Smart Render and Safe Denoising are MoonRay's own, and are
  greyed while XPU2 renders the preview: it is quick enough to need neither.
- **Final renders come from MoonRay**, as before. A scene XPU2 cannot render yet goes to MoonRay XPU.
- **The MoonRay Terminal** names the renderer (MoonRay XPU2, Vector, Scalar, XPU) and shows XPU2's generations as they go.

## Realtime and large scenes

- **Realtime keeps up**: after the first reading the scene is never read whole again. Moving an item reads only where
  it stands, editing a mesh reads only that mesh, and camera moves no longer reload the scene.
- **Heavy scenes start much sooner**: Modo's geometry goes to MoonRay as it comes, and realtime previews cut heavy
  scenes by their size on screen.
- **A Scene cache** (Preferences): a prepared scene is kept in a cache folder of your choice and opens faster the next
  time. **Clear Cache** empties it.
- **Displacement follows Modo's Displacement Rate**: Displacement Tessellation in the render settings dices finely
  where a mesh is large on screen and coarsely where it is small. A displacement that is black everywhere is left out.
- **MoonLightIPR starts in seconds**: about 15 seconds the first time on a machine, then a second or so.
- **MoonLightIPR follows an edit at once**, and its motion blur is off by default (Preview Preferences).
- **N-gons triangulated cleanly**, the same in MoonRay and MoonLightIPR, CAD outlines and outlines with holes among
  them. A MoonRay Source Override, on by default.

## Textures

- **Modo's procedural textures through the object**: Noise, Cellular, Checker, Grid, Dots, Wood, Weave, Ripples, Gabor
  and Poisson noise with a Solid projection are worked out at render time, with no baking and no UVs, in MoonRay and
  MoonLightIPR.
- **Enhance: Modo's textures, 145 of them**: Noise, Organic, Tiles, Geometric, Waveforms, Skins, Space, Panels, Water
  and Display, plus EasyGrad and RegionalHSV, which work on the layers beneath them.
- **Curvature and Wireframe** render in MoonRay and MoonLightIPR.
- **Textures convert side by side**: a scene with many textures starts in a fraction of the time.
- **In MoonLightIPR**: HDRIs the right way round and at full sharpness, textures that keep their shape, sharp colour
  corrections on images, and water drops and thin glass that come out clear.

## Lights and shadows

- **Light volumetrics and environment fog**: Modo's point, spot and directional light volumetrics, and its
  environment fog, render in MoonRay and MoonLightIPR.
- **Shadow rays** in Light Links, Emitters and Volumes: an object can cast no shadow; a light's shadows can start or
  end at a distance.
- **Area lights seen by the camera**, with their texture, as Modo's Visible to Camera has them.
- **Light filters**: attaching or detaching shows at once, and MoonLightIPR draws a Combine filter.
- **MoonRay lights take the Scale tool**: a RectLight's width and height, a disk or sphere light's radius, follow the
  scale and keep it, in one undoable step.
- **MoonLightIPR matches MoonRay's brightness** for lights that are not normalized.

## Materials, graph editor and compositor

- **Clearcoat Bump Strength** is followed: at 0 the coat stays smooth over a bumpy surface.
- **Image nodes show their picture** in the graph editor, at once and without rendering.
- **Images in the scene are a click away** when choosing a texture file; the Image node has **Invert**.
- **Drag a wire off its input** to disconnect it, or onto another input to move it; **Tab** moves between fields.
- **A render working space for every new scene** in MoonRay's Preferences.

## Denoising and outputs

- **Cleaner denoising**: Keep Fine Detail now works only over fur, hair and curves, so textured and bumpy surfaces stay
  clean.
- **Smart Render or Safe Denoising**: each is greyed in the render settings while the other is on.
- **Toon lines apart from the shading**: a Toon display filter can give its ink lines alone, or its shading without
  them. A MoonRay Source Override, on by default.
- **Display filters no longer come out pink** for want of an input.

## The preview window and preferences

- **Memory in the picture**: the renderer's, the machine's and the graphics card's memory, in colour when it runs short.
- **The top row wraps** onto a second line in a narrow window; R, G and B in their colours.
- **MoonRay's preferences in pages**: General, Renderer, XPU, XPU2 and Source Overrides.
- **Fixes**: Modo crashing when the Render layout's view was changed (likely fixed); "Texture conversion needs
  maketx.exe" with maketx in place.
