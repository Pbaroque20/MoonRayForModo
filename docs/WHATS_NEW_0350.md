# What's new in 0.3.50.1

A summary of what changed since the packaged 0.3.49 kit. 0.3.50.1 was released on October 9,
2026. Most of it was checked in a separate test copy of Modo 16.1v9 driven by scripts, and
parts of it in everyday use; where something was only checked by script, or not at all, the
notes below say so. The notes were written as the work went, so a later entry sometimes
overtakes an earlier one; where it does, the earlier one says so.

## MoonLight, a GPU preview engine

MoonLight is a small OptiX path tracer that previews the scene on an NVIDIA GPU. It
approximates MoonRay: one fixed material model stands in for MoonRay's shaders, and output
renders always use MoonRay. Choose it in the preview window's engine popup.

It shows Modo and MoonRay lights (including cylinder, portal and mesh lights), textured
rectangle lights, decay, intensity and colour-ramp light filters, layered and physical-sky
environments, subsurface, anisotropy, dispersion, absorption in glass, gradient, checker and
noise layers, depth of field, Modo subdivision, and the Dwa surface materials' own attributes.
Motion blur applies to Render, not to IPR updates. Curves and hair are shown as tubes, and
imported MaterialX graphs as their nodes say (both added later in this version; see Curves and
MaterialX below). Volumes and the remaining light filters are not shown; the Notices list in
the preview window says what a render left out.

[moonlight/README.md](../moonlight/README.md) has the comparisons with MoonRay and the build steps.

## MoonRay's own items

**MoonRay > Add MoonRay Item** adds MoonRay's lights, light filters, cameras, shapes and
volumes as Modo items, 30 classes in all, named with a dw prefix (dwEnvLight). Their
attributes are Modo channels with native controls; popups choose a light's filters, a portal's
environment and a shape's volume; ramps have an editor; and each item draws a wireframe proxy
in the viewport. A dwEnvLight can replace Modo's environments, and a camera item can render in
place of the Modo camera.

## The preview window

The window is now a viewer, with everything else moved out of it.

- One toolbar: Render/Stop, IPR, engine, buffer, exposure, Region, Focus and an Options menu.
- **Render and Stop are one button.** IPR is a choice of how Render behaves: with it on,
  Render keeps following the scene until Stop, and Stop leaves the choice on.
- **Render settings are on the Render item.** Select Render in the Shader Tree, or use
  MoonRay > Render Settings: sampling, bounces, denoising, lighting, camera background,
  geometry, region, outputs, display, output renders and system. They save with the scene as
  they are edited.
- **Preferences** (MoonRay folder, preview size, IPR limits and similar) are in their own
  dialog, kept per machine.
- **Cryptomatte** for objects and for materials is always in the buffer list; choosing one the
  scene does not output adds it and renders. MoonRay only.
- **Focus** sets the render camera's focus distance to the surface under a click in the image.
- **Time remaining** now works for persistent previews: the renderer reports its progress with
  each update.
- Pixels a worker was writing while a preview picture was taken keep their last settled value.
  This reduced stray light and dark pixels in early passes; it has not been confirmed to remove
  every such mark.
- One-off tools (asset report, packaging, relinking, named outputs, colour spaces, light links)
  are in the MoonRay menu.

The window's viewport is called MoonRay Preview. The experimental adapter for Modo's native
PView was removed: Modo cannot host an external renderer there.

## Materials

- **Assign MoonShine Material to Mesh** makes a native MoonRay material, a DwaBaseMaterial
  unless another is chosen, placed above the Base Material so that it takes effect.
- **MoonRay's materials are in the Shader Tree's Add Layer list**, under MoonRay Materials.
  A material added this way was at first passed over at render time; that is fixed, and it
  now renders.
- A native material has **its own properties form**, with a control for each attribute, that
  opens in front when the material is selected. Edits show in the preview with either engine.
- **Open Graph Editor** on that form opens the same material as a node graph. The separate
  MoonShine Material Override layer is no longer offered in the menus; override layers in
  existing scenes keep working.

## The material graph editor

- A window of its own that does not block Modo, so it can stay open on another monitor. Save
  and Apply are undoable.
- A gridded canvas without scroll bars. Middle-drag or Alt-drag pans, the wheel zooms, F frames
  the selection and A everything.
- Compact nodes coloured by kind, showing a few inputs with the rest a click away; wires take
  the colour of what they carry.
- Tab or a double-click opens an add-node search. Dragging an input's wire to empty canvas adds
  the node that feeds it. Ctrl+D duplicates; Delete works on several nodes; nodes snap to the
  grid.
- Properties are controls that stay in place: switches, named choices, numbers, colours with a
  swatch, vectors, and text that says what belongs in it. A line under the list describes the
  property under the pointer. A node's UV map is chosen from the maps of the meshes the
  material is on.
- A list of the scene's graph materials, each named with what it belongs to, switches the
  editor between them.

- A ramp is edited as a ramp: a RampMap's positions, colours and blends, and the same three
  lists on the materials that carry a ramp, are one row showing the ramp, which opens the ramp
  editor.

## Curves and hair

- A mesh's curves, splines and line polygons render as round tubes. All of a mesh's strands of
  one material are a single curve geometry, line polygons are read as they stand, and the long
  lists are written once and kept, so thousands of strands cost little more than one mesh.
- The controls are on the mesh's MoonRay tab, under its object overrides: whether curves
  render, the width at root and tip, the envelope between them, samples per bend for splines,
  and UVs that run along each strand by length.
- MoonLight draws the same curves, as tubes of polygons.
- Curves can be guides that hair is grown from. On the object overrides: the mesh the hair
  grows on, strands per guide, the width of a cluster and how far it closes toward its tip,
  variation in length, and a seed. Hair grows around each guide, as locks, or between guides,
  as fur. Every root is held to the surface of the scalp mesh; a strand that finds no surface
  within reach stays on its guide and is counted in a notice. The same seed grows the same
  hair on every frame.

## Daylight

- Modo's physically based daylight is followed from a table of Modo's own renders of it, over
  sun height and haze: the sky, its brightness clamp and gamma, the ground's colour and the
  blend to it below the horizon. Half the sky is within 1% of Modo's and nine tenths of it
  within 1 to 7%.
- A sun placed by date and time takes the colour and strength Modo gives it, following its
  clamp, gamma, thinning and haze.
- A sun turned by hand now lights its sky from where it stands.
- The sun of a physical sky shows as a disc of Modo's solar disc size, in both engines.

## Lights and materials against Modo

- Modo's directional, point, area and spot lights are given to MoonRay at the strength they
  have in Modo. Before, a directional light was 3 times too bright, a point light 13 times too
  dim, an area light wrong by its size, and a spot light faced away and gave no light.
- A Modo material's specular amount now reaches MoonRay: none means no highlight. Before, every
  standard material reflected 4% whatever it was set to.
- A Modo material is a metal only under its Principled shading model, as in Modo. Under that
  model its specular amount is a share of 8% and its diffuse colour shows in full, as Modo
  renders it.
- Modo's Fresnel setting is followed: at none, a material reflects the same at every angle, as
  it does in Modo; at full it rises toward the edge as Modo's does.
- MoonLight weights its specular layer as MoonRay does, so the two agree on Modo's materials
  and on a MoonRay material whose specular is below 1 (scene format MLSA).
- A standard material's highlight has the shape of Modo's own (GGX) unless it is stretched by
  anisotropy. Roughness then means the same in both: highlights agree to about 1% from
  roughness 0.15 up.

## MaterialX

- MoonRay > Import MaterialX Material... puts a MaterialX file's material on the selected meshes
  as a MoonRay material with the file's graph. Files written by material libraries now read:
  the nodes that only pass a value on, and the surface's own normal and tangent wired in to
  mean the default.
- An imported graph is set out in columns from its output back, and the graph editor's View
  menu can arrange any graph the same way.
- A material from a MaterialX file is a kind of its own in the Shader Tree, MaterialX Material,
  with its own tab: load its file, or open its controls and graph. It is also in Add Layer,
  under MoonRay Materials, to be given a file afterwards.
- A MoonRay material added from Add Layer now renders. It was passed over before.
- An imported material has controls of its own: the numbers and colours its file names (a
  paint colour, a UV scale, a roughness range) and its images, each chosen once however many
  nodes read it. They are the graph editor's properties while no node is selected.
- MoonLight shows such materials as their nodes say: UVs that nodes move, turn or scale, and
  arithmetic between images (one blended into another through a third, an image brought into
  a range, masks taken away) at the images' own sharpness. A wood, a marble, two wallpapers
  and a car paint from a library agree with MoonRay on 72 to 100% of the picture.
- MoonLight's denoiser keeps more of a texture. It is given the light without the surface
  colour, so a printed pattern is not its to smooth, and as samples gather a growing share of
  the picture's own detail is kept beside it. `tools/check_moonlight_denoise.py` measures it.
- Import RDL Scene brings a MoonRay scene in whole. Meshes keep their transforms and are
  instanced, not copied, however deeply the scene's instancers nest; curves come in as curves;
  lights, light filters, volumes, MoonRay's own shapes and its other cameras become MoonRay
  items holding every attribute the scene set; materials come in with their graphs and
  displacement, as their own kind in the Shader Tree; image size, sampling, depths and render
  outputs go to the render settings. A scene in two files, scene.rdlb and scene.rdla, is read
  as one. What has no home in Modo is listed before anything is made. By default the result is
  lit only as the RDL scene is lit. `tools/check_rdl_import.py` renders a scene before and
  after its trip through Modo: five of MoonRay's six test scenes and all ten of its published
  example scenes come back the same picture. A large import shows how far it has come and can
  be stopped, which takes back what it had made.
- Heavy scenes are read far sooner. The plugin's native adapter hands over a mesh of 5,000
  polygons or more in one call, such a mesh is put together whole where it is of the usual
  kind, and its long lists are written out for MoonRay without a step for each number. A
  bedroom of 121 MB as MoonRay's own file is read in 14 seconds and written out in 16.
- The scene's settings keep MoonRay scene variables the plugin has no control for; an imported
  scene's arrive there and are written back out, so that it renders with what it was made with.
- A texture already in MoonRay's .tx form, with nothing to change in its colours, is used as
  it is and no longer converted again.
- An item can carry values for its material to read (MoonRay's primitive attributes), each
  instance its own; an imported scene's per-shape and per-instance colours arrive this way.
  There is no form for them yet. A value that differs from face to face is not held.
- A mesh's curves can be round tubes (Round Curves), and a line's points can be the control
  points of a Bezier or B-spline curve that MoonRay draws (Line Points Are).
- A material that cannot be blended with others, such as a hair material, now renders when it
  is over the base material. It was refused before.
- A scene's view transform starts as ACES (sRGB display): the ACES 1.0 SDR view for an sRGB
  monitor, from the configuration OpenColorIO carries, with no file to find. Plain sRGB, linear
  light shown as an sRGB monitor expects it, is the next choice, and highlight compression is
  still there. A scene that has its view stored keeps it.
- With a preview denoiser on, a finished MoonRay preview shows the denoised picture even where
  the preview was opened, or the render begun, before the buffer list had been set to it.
- A GPU (XPU) render of a scene with many outputs and adaptive sampling no longer stops with
  "timed out whilst trying to allocate a CacheLine1". MoonRay's store for what rays in flight
  owe each output is four times its former size in the rebuilt renderer library (about 4 GB
  of address space, used only as needed); MOONRAY_MODO_CL1_POOL_SCALE sets another size, from
  1 to 8 times the original. Should the store still fill, the render begins again on the CPU
  and says so, and stays there until an execution mode is chosen again.
- A scene with an imported MaterialX material is read in a fraction of the time. Its texture
  coordinates were worked out again for every polygon, which stopped Modo for seconds on a small
  mesh and for minutes on a dense one, each time the preview read the scene.
- IPR no longer reads the whole scene again every 15 seconds unless asked to, in the preview's
  preferences. It is for procedural items that do not announce their changes.
- A MoonRay material set to metal now renders as one. Its metallic setting never reached
  MoonRay before.

## Outputs

- A new scene outputs the object Cryptomatte, so the first render already holds the mattes.

## Known gaps

- A ground colour other than mid-grey tints the physical sky only approximately.
- MoonRay takes what a surface reflects out of its diffuse light; Modo adds the two. A surface
  seen edge on, such as far ground, is therefore up to a fifth darker in MoonRay.
- A rough surface reflects less of its surroundings in MoonRay than in Modo, down to a third at
  full roughness, though its highlights from lights agree.
- A reflective material (30% and up) with Fresnel at full rises less toward the edge in MoonRay.
- Modo's separate reflection amount, with Match Specular off, is not followed.
- A spot light matches Modo on its axis and dims off it by the cosine of the angle.
- Curves in MoonLight are tubes of four or eight sides, not true curves.

- Curves and hair wear the ordinary surface shader in MoonLight; there is no hair shading model
  or skin there yet, and no volumes.
- An RDL import leaves out motion, values that differ face by face, subdivision creases,
  authored normals and light linking, and names each in its report. Opening a large scene's
  files takes minutes, with no progress shown, before the import proper begins.
- The values an item carries for its material (primitive attributes) have no form.
- With a preview denoiser on, one order of working left the preview on Beauty when the render
  finished; that is fixed, but the case first reported was not reproduced, so it may not be
  the only one.
- The import's progress bar and Stop button were not watched in the dialog.
- The sections of the Render item's form all start expanded.
- The package was run from an empty folder with a bare environment, on the machine that built
  it. It was not installed on a clean machine, and XPU and MoonLight were run on one GPU.
