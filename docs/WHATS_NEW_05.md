# What's new in 0.5

0.5 is a **pre-production release**: the plugin is no longer experimental, and it brings a new GPU renderer, MoonRay XPU2.

## Coming in 0.5.1

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
- **Compile XPU2 Shaders once more** after installing: XPU2's programs have changed.

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
  **Realtime Samples** sets how much of the render realtime makes (100% by default).
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
