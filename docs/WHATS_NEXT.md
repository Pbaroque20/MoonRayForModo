# What's next

Built on the MoonLightIPR branch since 0.3.51.3 and not released yet. Checked two ways, as before: MoonLightIPR's picture set beside MoonRay's on small test scenes, and the plugin driven by scripts in a separate test copy of Modo 16.1v9. One machine (RTX 3090).

Several of these need the **MoonRay of the next runtime** (a rebuilt `moonray.exe` and `librendering_rndr.dll`), so the next release brings a new runtime ZIP as well as a new kit. They are marked *(next runtime)*. With an older runtime the plugin still works, without them.

## The preview window

- **Three engines, and no Live box.**
  - **MoonRay** renders the picture once, in full. Its button reads Render, Stop and, after a stop under Safe Denoising, Continue.
  - **MoonRay LS** (low sample) is MoonRay following the scene as you edit it, at fewer samples and a smaller size. It is what MoonRay with Live ticked was.
  - **MoonLightIPR** is the fast GPU preview, which also follows the scene.

  The last two are realtime. Each is on from the moment it is chosen. The window itself opens on MoonRay, showing the crest, and renders nothing until asked; Preferences > MoonRay can name another engine to open on. The button then reads **RT On** and is lit; press it and it reads **RT Off**, and the preview stops following the scene.
- **Draft comes up at once.** Nearly all of the wait for a draft's outlines was reading the scene out of Modo again (1.1 of 1.2 seconds on the origami cheetah); drawing them takes a twentieth of a second. With realtime on, where nothing in the scene has changed since it was last read for the picture on screen, it is not read again (0.17 seconds when first measured); with realtime off it is always read anew, so that a draft is never of an older scene. MoonLightIPR makes one render for a draft, and a second only for a region, by the engine you chose.
- **In Draft the paper is the camera's frame**, and the rest of the view is black.
- **Region leaves the view alone.** Setting or clearing a region no longer zooms the view, and a picture of another size and the same shape is looked at just as the last was. Zooming in is yours to do.
- **MoonLightIPR has Beauty and Denoised Beauty.** With the scene's denoiser on for previews, MoonLightIPR denoises and its buffer list offers both. It shows Beauty, the picture as it is rendered, until you choose Denoised Beauty. The change is at once: MoonLightIPR holds both and nothing is rendered again. With the denoiser off it renders the beauty alone. *Built and not yet tried in Modo.*
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
