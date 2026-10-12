# What's next

Built on the MoonLightIPR branch since 0.3.51.3 and not released yet. Checked two ways, as before: MoonLightIPR's picture set beside MoonRay's on small test scenes, and the plugin driven by scripts in a separate test copy of Modo 16.1v9. One machine (RTX 3090).

Several of these need the **MoonRay of the next runtime** (a rebuilt `moonray.exe` and `librendering_rndr.dll`), so the next release brings a new runtime ZIP as well as a new kit. They are marked *(next runtime)*. With an older runtime the plugin still works, without them.

## The preview window

- **Three engines, and no Live box.**
  - **MoonRay** renders the picture once, in full. Its button reads Render, Stop and, after a stop under Safe Denoising, Continue.
  - **MoonRay LS** (low sample) is MoonRay following the scene as you edit it, at fewer samples and a smaller size. It is what MoonRay with Live ticked was.
  - **MoonLightIPR** is the fast GPU preview, which also follows the scene.

  The last two are realtime, and start switched off, so that nothing renders by accident: the button reads **RT Off**. Press it and it reads **RT On**, lit, and the preview follows the scene; press again to switch realtime off. The window itself opens on MoonRay, showing the crest, and renders nothing until asked; Preferences > MoonRay can name another engine to open on.
- **Draft comes up at once.** Nearly all of the wait for a draft's outlines was reading the scene out of Modo again (1.1 of 1.2 seconds on the origami cheetah); drawing them takes a twentieth of a second. With realtime on, where nothing in the scene has changed since it was last read for the picture on screen, it is not read again (0.17 seconds when first measured); with realtime off it is always read anew, so that a draft is never of an older scene. MoonLightIPR makes one render for a draft, and a second only for a region, by the engine you chose.
- **Draft follows the scene by itself, and refines.** With Draft on, its outlines are redrawn when the scene changes, whatever engine is chosen and whether or not realtime is on. A change is shown first in a quick, small picture (640 pixels wide; Preferences > MoonRay > Draft quick width) and then, once that is up, in a fine one as sharp as the view. On the 266-mesh cheetah a moved item is shown in about 0.2 seconds and refined 0.15 seconds later. A drag is waited out and the scene drawn as it is when the button comes up, so that what is shown is always the outcome of an edit. While it redraws by itself the window's status, progress bar and button are left alone. With a region set, the region is rendered again after the fine picture, by the engine chosen.

![The cheetah's draft after it has refined](images/draft-refined.png)
*The cheetah in Draft, refined: black outside the camera's frame.*

- **Moving something is followed without reading the scene again.** Of the 1.3 seconds a draft took to redraw on the origami cheetah (266 meshes), 1.0 was reading every mesh out of Modo again. When only an item's place changes, only its place is now asked for: 0.29 seconds. This holds for the realtime engines as well as Draft, and for scenes whose meshes are read as Modo evaluates them, as the cheetah's are for its nested material masks. Editing a mesh, a mask or the scene's structure still reads everything.
- **Reading a scene whose meshes Modo evaluates is more than twice as fast** *(new geometry adapter, in the kit ZIP)*. The adapter wrote every number of every mesh out as text, which the plugin then read back: for the cheetah's 392,000 numbers that was 0.55 seconds of writing and 0.19 of reading, against 0.04 seconds for Modo's own work. The numbers are now handed over as they are. The adapter's part went from 0.58 to 0.05 seconds, and a whole reading of the cheetah from about 1.0 to 0.4 seconds. What comes back was compared with the old way and is the same. This is every reading that is not just a move: switching Draft on, a change to a mesh's shape, a first render.
- **In Draft the paper is the camera's frame**, and the rest of the view is black.
- **Draft switched off shows nothing stale.** The render made before the draft is put back only where the scene is still the one it was made from. Where the scene has changed, the view is cleared: a realtime engine that is on renders it, and MoonRay waits for Render.
- **Region leaves the view alone.** Setting or clearing a region no longer zooms the view, and a picture of another size and the same shape is looked at just as the last was. Zooming in is yours to do.
- **MoonLightIPR has Beauty and Denoised Beauty.** With the scene's denoiser on for previews, MoonLightIPR denoises and its buffer list offers both. It shows Beauty, the picture as it is rendered, until you choose Denoised Beauty. The change is at once: MoonLightIPR holds both and nothing is rendered again. With the denoiser off it renders the beauty alone, and the list holds only Beauty. In a test, the denoised picture's grain measured 0.42 against the beauty's 0.61, and going back to Beauty gave the picture as it was.
- **Each engine renders at its own size.** MoonRay, chosen as the engine, renders at the camera's resolution, or the scene's where the camera does not override it; it used to render at the preview size. MoonRay LS and MoonLightIPR are previews, at the realtime preview size (640 pixels wide unless changed in the window's Options) and never wider. The option to preview at scene resolution is gone. Tried on a 1280 x 720 scene and with a camera override of 800 x 400: MoonRay rendered each at that size, and MoonLightIPR at 640 wide both times.
- **Two lines under the picture.** The status has a line to itself, so a long message is read whole. Below it are the values under the pointer, how the render is getting on, and the picture's size.
- **Tile outlines move evenly.** They are pastel blue. An outline eases in, stands for as long as MoonRay keeps coming back to its tile, and fades when the tile is done with. MoonRay now tells of its tiles on a clock of their own: about eighteen times a second reach the window where four did, and no gap is longer than 150 ms where there were gaps of half a second *(next runtime)*.

![The preview window with MoonLightIPR chosen and realtime on](images/preview-engines.png)
*MoonLightIPR chosen: RT On is lit, and the status has a line to itself.*

## Rendering with MoonRay

- **Safe Denoising shows the render as it comes on**, like any other render, instead of only at each save *(next runtime)*. In a test of 70 seconds the view was brought up to date 35 times, with the saves going on beneath.
- **A stop says what it kept.** Under Safe Denoising a stop keeps the last save, which may be some seconds behind what was on screen. The status says how far behind, the picture's own line is marked for as long as that picture is shown, and while the render runs its timing ends with how long ago MoonRay last saved. Stopped before the first save, the picture as it stands is kept in place of nothing.
- **No dark blocks in the live picture**, in a normal render or under Safe Denoising *(next runtime)*. With the graphics card sharing the work, MoonRay counts a pixel's sample before all of that sample's light has come back, and for that moment the pixel reads too dark. The live picture caught such pixels in blocks, and under Safe Denoising in a dither. A pixel is now held at what it last showed for as long as the samples still coming in are a large share of what it has. Counted as pixels that dip markedly darker in one picture than in those before and after it: on two balls the worst picture of a safe render had 2% of its pixels dipped, now 0.03%; on the origami cheetah (1920 x 900) over three minutes, the worst picture of 94 had 0.08% under Safe Denoising, a single small tile, and 0.04% in a normal render.
- **A render stopped part way denoises cleanly.** The same pixels left faint marks in the denoised picture of a stopped render. The picture and the denoiser's guides are now taken five times over at a stop and the middle of the last three used. A stop of a normal render takes about four seconds for that.
- **An idle MoonRay costs nothing** *(next runtime)*. The MoonRay kept loaded between renders kept one processor core busy while it waited for its next frame. It now rests, and starts again without delay. Measured with nothing changing in the scene: MoonRay LS went from 100% of a core to 0%. MoonLightIPR was at 0% already. Both keep the graphics card memory they hold (2.3 to 2.6 GB in the test), which is what lets them start again at once.
- **A MoonRay left behind ends itself** *(next runtime)*. If Modo ends without closing the preview, the loaded MoonRay no longer stays running.

![The cheetah part way through a safe render, with no dark blocks](images/live-picture-safe.jpg)
*The worst of 94 pictures taken of the cheetah during a safe render: one small dark tile, on the pale flank at the upper right.*

![A safe render stopped part way: the status and the picture's line say it is the last save](images/safe-stop-last-save.png)
*Stopped under Safe Denoising: the picture is the last save, seven seconds before the stop, and both lines say so.*

![A normal render stopped part way, kept and denoised](images/stop-keeps-picture.png)
*A normal render stopped after 25 seconds: kept and denoised, with no marks.*

## What Modo hides is hidden

- **An item with its eye off no longer renders**, in MoonRay or MoonLightIPR. Left at Render: Default, an item renders as it is shown; Render: Yes or No still settles it either way. A parent hides its children only when it is set to hide them with it.
- **MoonLightIPR follows a surface's visibility to each kind of ray**: seen by the camera, by indirect light, in reflections, in refractions, and whether it casts shadows. Light that a scattered ray comes upon is stopped by what casts shadows, as in MoonRay. On four test scenes (hidden from the camera; casting no shadow; seen by the camera only; casting its shadow only), 96 to 100% of the picture is within 10% of MoonRay's. These settings reach the renderer with Surfaces set to Evaluated.

![Four cubes, of which the two with their eye off or Render: No are not rendered](images/visibility-eye.png)
*Four cubes in a row. The second has its eye off and the third is set to Render: No: neither is rendered. The fourth has its eye off but Render: Yes.*

![An object that only casts its shadow, MoonRay on the left and MoonLightIPR on the right](images/moonlightipr-seen_shadow_only.jpg)
*Two balls hidden from everything but shadows: MoonRay (left) and MoonLightIPR (right).*

## Not checked

- The heavy scene used for 0.3.51.3 (1920 x 900, 26 buffers) was rendered for three minutes in each mode to look for dark blocks; a stop of it, and its speed under Safe Denoising against a normal render, were not measured again.
- Continue after a stop was offered in every test and was not itself run on the newest MoonRay.
- A Shader's visibility switches were tested as scene descriptions, not through a Shader item in Modo. Lights and environments with their eye off are now left out too, by the same rule, and that was not rendered.
- The tile outlines were measured (how often they are told of, and that they ease and fade) and not watched during a real render.
- MoonLightIPR's two buffers and Draft's handling of a changed scene were tried on a single ball, not on a heavy scene.
- The faster following of a moved item was timed in Draft only. MoonRay LS and MoonLightIPR with realtime on take the same path and were not timed; and a scene with instances, replicators or deformers still reads everything for a move.
- Draft following the scene with a region set, which renders the region again at each change, was not tried.
- With the scene's denoiser on, MoonLightIPR denoises every picture whichever buffer is shown; what that costs while Beauty is shown was not measured.
