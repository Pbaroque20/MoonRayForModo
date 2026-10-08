# What's new in 0.3.50.1 (unreleased)

A summary of what changed since the packaged 0.3.49 kit. This build is in development and has
not been released. Most of it was checked in a separate test copy of Modo 16.1v9 driven by
scripts; where something was only checked that way, or not at all, the notes below say so.

## MoonLight, a GPU preview engine

MoonLight is a small OptiX path tracer that previews the scene on an NVIDIA GPU. It
approximates MoonRay: one fixed material model stands in for MoonRay's shaders, and output
renders always use MoonRay. Choose it in the preview window's engine popup.

It shows Modo and MoonRay lights (including cylinder, portal and mesh lights), textured
rectangle lights, decay, intensity and colour-ramp light filters, layered and physical-sky
environments, subsurface, anisotropy, dispersion, absorption in glass, gradient, checker and
noise layers, depth of field, Modo subdivision, and the Dwa surface materials' own attributes.
Motion blur applies to Render, not to IPR updates. Volumes, curves and the remaining light
filters are not shown; the Notices list in the preview window says what a render left out.

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
  The Add Layer popup itself has not been checked; a layer of this kind made directly behaved
  as described here.
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

## Daylight

- Modo's physically based daylight is followed from a table of Modo's own renders of it, over
  sun height and haze: the sky, its brightness clamp and gamma, the ground's colour and the
  blend to it below the horizon. Half the sky is within 1% of Modo's and nine tenths of it
  within 1 to 7%.
- A sun placed by date and time takes the colour and strength Modo gives it, following its
  clamp, gamma, thinning and haze.
- A sun turned by hand now lights its sky from where it stands.

## Outputs

- A new scene outputs the object Cryptomatte, so the first render already holds the mattes.

## Known gaps

- The solar disc is not drawn in the sky, and a ground colour other than mid-grey tints the
  sky only approximately.
- An ordinary Modo directional light is given to MoonRay at pi times Modo's strength; only the
  physical sun is corrected for this so far.
- Curves in MoonLight are tubes of four or eight sides, not true curves.

- Rendering a material added from Add Layer, and rendering a material with a wired graph, were
  not exercised in this round.
- IPR following with MoonLight, and the scene dialogs opened from the MoonRay menu, were not
  exercised in the new preview window.
- The sections of the Render item's form all start expanded.
- Unit tests show two failures that predate this work.
