# Ocean at sunset

An 800 m sea under a low sun, made with the MoonShine graph's **Ocean** and **Ocean Foam** nodes. It renders the same in MoonRay, XPU2 and MoonLightIPR, and the waves move when you play the timeline (frames 1 to 120).

The ocean is based on Jerry Tessendorf's research paper **"Simulating Ocean Water"** (SIGGRAPH course notes, 2001, revised 2004): wind-driven waves from a Phillips spectrum summed by FFT, choppy crests, and foam where the surface folds over. The kit's own implementation of it is credited in the kit's third-party notices.

## What is in the scene

- **Sea**: a flat plane, 800 m across, 200 x 200 quads, with a UV map running 0 to 1 across it.
- **Sea Water**: a DWA Base material. Its MoonShine graph holds:
  - an **Ocean** node: a vector texture of the waves (red the push along U, green the height, blue the push along V).
  - a **Vector Displacement** node, the graph's displacement output, with the Ocean node wired into its **Vector**. It moves the plane into waves.
  - an **Ocean Foam** node, with no settings of its own. It follows the Ocean node.
  - two **Mix** nodes driven by the foam. One blends the dark water colour to white foam on Albedo. The other blends a smooth surface (0.03) to a rough one (0.5) on Roughness.
- A physical sky, a sun low ahead of the camera, and a camera 14 m above the water.

## Using the Ocean node in your own scene

1. **Make a plane with a UV map.** The ocean is laid over the surface's first UV map. It covers the 0 to 1 square, **Repeat** times across. A plane made in Modo with UVs from 0 to 1 is all it needs.
2. **Give it a MoonShine material** and open its graph in the MoonShine Graph Editor.
3. **Add an Ocean node** (Tab, or Node > Add Node; it is under Procedural textures) and wire it into a **Vector Displacement** node's **Vector**. Set the Vector Displacement as the displacement output (select it, **Node > Set / Clear Displacement Output**).
   - Shortcut: select the Ocean node itself and choose **Set / Clear Displacement Output**. The editor adds the Vector Displacement, wires it and sets it as the output in one step; the same entry takes it off again.
   - Keep the Vector Displacement's **Source Space** on tangent and its **Tangent Space Style** on TNB, as it starts: that is the order the ocean's colours are in.
   - **Factor** scales the whole sea. **Bound Padding** is raised for you to what the waves need.
   - A **Combine Displacement** node can add the ocean's Vector Displacement to another displacement.
4. **Add an Ocean Foam node** (also under Procedural textures) where you want foam. Wire it into the **Mix** input of a Mix node, with the water's colour in **BG** and the foam's in **FG**. Wire that Mix node into Albedo. A second Mix node, foam into Mix, makes the foam rough.
5. **Size the waves to your plane.** A tile of **Size** metres repeats **Repeat** times across the UVs. For the waves to come out at their real size, make Size times Repeat equal to the plane's width: 80 m times 10 makes this scene's 800 m sea.

## The Ocean node's settings

| Setting | What it does | In this scene |
|---|---|---|
| Size | The tile's width in metres. Waves longer than this can't appear. | 80 |
| Repeat | How many tiles across the UV square (U, V). | 10, 10 |
| Resolution | Points across the tile: 64 to 1024. Higher gives finer ripples and takes longer. | 512 |
| Wind Speed | Metres a second. It sets how big the waves are: about 0.5 m high at 5 m/s, 2 m at 10, 8.5 m at 20. | 12 |
| Wind Direction | Degrees, from U towards V. Keep it off 0 and 90, so no wave runs along a tile's edge. | 30 |
| Wave Height | Times the height a sea reaches in that wind. Below 1 is calmer. | 1 |
| Choppiness | How far the crests are pushed together sideways. 0 gives smooth rollers; 1 to 2 gives sharp crests. Too high folds them over. | 1.2 |
| Small Waves | Waves shorter than this many metres fade out. | 0.05 |
| Wind Alignment | How strongly the waves follow the wind. | 2 |
| Against Wind | What is left of waves running against the wind, 0 to 1. | 0.3 |
| Depth | Water depth in metres. 0 is deep water; shallow water slows the waves. | 0 |
| Seed | Another seed gives another sea with the same settings. | 1 |
| Time Scale, Time Offset | The ocean's time is the scene's time times Time Scale, plus Time Offset, in seconds. | 1, 0 |
| Loop | Seconds after which the waves repeat exactly, for looping animations. 0 never repeats. | 0 |
| Foam Threshold | Foam shows where the surface is squeezed below this. Higher gives more foam. | 0.8 |

## Getting more foam

The foam sits on the sharpest crests, so this 12 m/s sea has only a little. For whitecaps:

- raise **Wind Speed** to about 18, or
- raise **Choppiness** to about 1.8, or
- raise **Foam Threshold** towards 1.

## Good to know

- **The plane can be coarse.** MoonRay and XPU2 split the surface as finely as the pixels need. MoonLightIPR moves the plane's own vertices, and its shading adds the ripples that fall between them.
- **The tiles are made for each frame** while a frame renders, and kept in the Cache folder (the Ocean folder in it). A frame you have rendered before comes back at once.
- **MoonRay has no ocean of its own.** The kit computes Tessendorf's FFT ocean, from the SIGGRAPH course notes "Simulating Ocean Water", and gives MoonRay two textures, the waves and the foam. It is a MoonRay Source Override: **Ocean nodes in MoonShine graphs** in MoonRay Source Overrides turns it off, which leaves the sea flat.
