# Rhea: a probe tracer on XPU2

*Research note, 2026-11-19. Local branch only. Named Rhea by the user on 2026-11-19 (it was Sol earlier that day, and the working name "Bregman" before).*

**Where it stands.** Sections 1 to 7 are the first two steps (the two phases, the frame cache, OpenQMC). Section 8 is
the third: Rhea's indexer, which handles geometry instead of shading, and reconstructs the visible surface in geometric
passes that converge within a tolerance. It replaces the fixed probe lattice of 2.1 and the rasterized region buffer of
section 5. The shading changes come next.

XPU2 renders every pixel by full Monte Carlo paths. This engine keeps XPU2's asynchronous architecture (CPU and GPU on
one picture, cells, broker, identity-derived samples) and its port of MoonRay's shaders, and changes the light
transport into two phases:

1. **Probes.** A particle leaves a pixel of a lattice bound to the render resolution, hits the scene, queries the
   lights there, scans the connected mesh around its hit ring by ring, and returns its position's radiance through a
   virtual reconstruction of that geometry.
2. **Refinement.** Monte Carlo paths leave the camera only into the regions phase 1 marked, take the secondary bounces
   that reach what is outside the camera's frame, and refine phase 1's radiance.

The reconstructions are Bregman Voronoi diagrams (Boissonnat, Nielsen, Nock, *Bregman Voronoi diagrams*, DCG 2010; "the
paper" below, sections cited as §) whose lifted space is built over the camera frame.

## 1. Where each phase runs in XPU2's pipeline

What XPU2 already gives, unchanged (`xpu2/manual/README.md`):

| XPU2 part | File | Used by |
|---|---|---|
| Scene to plan: meshes as positions + triangle indices, materials, lights, camera | `cpu_scene.h` (`cpu::Plan`, `cpu::MeshData`) | both phases; the scan reads `MeshData` |
| CPU lane: Embree scene and `CpuBackend::trace` (geom, prim, u, v, point, normal) | `async_cpu.h` | phase 1's probe hits |
| The shared integrator: MoonRay's estimator, lights, BSDFs, maps, DwaBase | `async_integrator.h`, `shade_*.h`, `light_*.h` | both phases' radiance |
| Async frame: grid, cells, broker, CPU and GPU lanes, merged film | `async_render.h`, `async_grid.h`, `async_gpu.h` | both phases' sampling |
| Per-pixel sample counts on both devices (a pixel with index >= its count is skipped) | `Plan::pixelSamples`, `integratePaths` | which pixels each phase samples |
| Depth limits per frame (`maxDepth` 0: light samples and BSDF samples to lights at the first hit only) | `Plan::maxDepth`, `mixed::Config` | phase 1's direct light |
| Light path expression AOVs (MoonRay's LPE state machines) | `aov_plan.h` | separating direct from indirect in phase 2 |

So both phases can be **XPU2 frames with different plans**, rendered by the unchanged CPU and GPU lanes at once; no
new GPU program is needed for the first prototype:

- **Phase 1, direct light at the probes:** an XPU2 frame whose plan has `maxDepth = 0` and `pixelSamples` = k at the
  probe pixels, 0 elsewhere. The CPU and GPU share it by cells as usual.
- **Phase 1, scan and reconstruction:** new host code (`rhea/`), run on the CPU lane's pool while the frame's GPU
  work drains; the reconstruction is per pixel arithmetic (section 3.3), cheap on either device.
- **Phase 2:** an XPU2 frame with the scene's own depth limits and `pixelSamples` = n inside phase 2's regions, 0
  outside, with an LPE AOV for the first hit's direct light so the indirect part is `beauty - direct` per sample.

Later, for speed: phase 1 as a mode of the GPU program (the probe trace, the scan over a CSR adjacency on the card and
the per-pixel diagram in one launch) and phase 2 skipping first-hit light samples where phase 1 is trusted. Both change
device code and need a shader compile (8 to 15 minutes, 4 to 11 GB on an RTX 3090).

## 2. Phase 1: probes

### 2.1 The lattice

One probe per s x s block of pixels (s = 1 is a probe a pixel), at a jittered position drawn from XPU2's sample
identity, so a probe is the same probe on either device. k samples a probe (camera jitter inside its pixel, light and
BSDF samples).

### 2.2 Direct light

At the hit, MoonRay's own direct estimator: light samples and BSDF samples combined by MIS, light sets, the light tree,
presence, the material's lobes, exactly as XPU2 computes it at a path's first vertex (`integratePaths` with
`maxDepth = 0`). Its result is the probe's radiance L_i; its first-hit AOVs (position, normal, depth, albedo) and the
host's own trace give the hit record (geom, prim, P_i, N_i).

### 2.3 The radial topological scan: what it reads

**On the host** a mesh is `cpu::MeshData`: `positions` (`std::vector<V3>`), `triangles` (`{a, b, c}` indices, after
MoonRay's tessellation and displacement), shading `normals` and `uvs` at a rate. Triangles share vertices by index, so
connectivity is there, but no adjacency is stored. The scan builds, once per mesh and kept while the mesh's signature
is unchanged (as XPU2 keeps tessellations):

- vertices **welded by position** (MoonRay's tessellation splits a vertex where its uv or normal differs, which would cut
  the rings at every seam), then a CSR vertex-to-triangle incidence and a triangle-to-triangle edge adjacency:
  about 3 x 4 bytes a triangle plus 4 bytes a vertex.

**On the card** the GPU lane already holds each mesh's positions and triangles (OptiX's build inputs and the arrays
`geometryHit` reconstructs hits from). The CSR arrays would be uploaded beside them, one more buffer a mesh.

**The scan** from probe i: a breadth-first walk from its hit triangle over edge-adjacent triangles, ring by ring,
keeping triangles that face the camera and project into the probe's window (its block and the eight around it), up to
R rings or K triangles. It yields the probe's **patch**: triangles of the same connected surface, exactly. Rings stop
at mesh borders and silhouettes, and never jump to another object however close it is.

### 2.4 What the probe returns

The patch is the virtual geometry; its use depends on the reading the user chooses (section 5, question B).

## 3. The reconstruction: Bregman Voronoi diagrams over the camera frame

### 3.1 The lifting map: the camera frame as the hyperplane

Let x = (x1, x2) be raster coordinates of the camera frame and d the depth along the view axis. Lift a camera-space
point P to

    L(P) = (x(P), w(P)),   w = 1 / d.

L is a projective map (in homogeneous coordinates (X, Y, Z, 1) -> (X, Y, 1, -Z)), so **planes go to planes**: the
plane n . P = c becomes the hyperplane w = <a, x> + b of R^3, with a and b from n, c and the camera's
`rasterToCamera` (for a perspective camera, P = d r(x) with r affine in x, so w = n . r(x) / c). The visible surface
becomes the graph of a function W over the frame, and the frame itself is the hyperplane w = 0 of the lifted space
(depth at infinity), onto which every diagram below projects (the paper's Proj_X, §3.2).

A probe at frame point p_i with lifted height w_i = W(p_i) and normal N_i has the tangent hyperplane

    H_i(x) = w_i + <x - p_i, a_i>,   a_i = grad W(p_i) from N_i,

which is the paper's H_q (eq. 5) for the generator F = W. The probe's own hit gives both w_i and a_i: nothing else
about W is needed to build the diagram.

### 3.2 Which generator

The paper needs F strictly convex. W is not convex everywhere: it is convex where the visible surface folds away from
the camera (a room's corner seen from inside: W = max of the two walls' hyperplanes) and concave where it bulges
toward it (a ball's visible cap). The generator is therefore **F = s W, with s = +1 or -1 by local convexity**, read
from the probes themselves: for two neighbouring probes, the divergence

    D(p_j || p_i) = s (w_j - H_i(p_j))

must be >= 0 both ways for the choice of s. Both signs non-negative with s = +1: convex; with s = -1: concave; mixed or
large: a saddle, a silhouette or two different surfaces. With F = s W:

    D_F(x || p_i) = s (W(x) - H_i(x)),

the gap in inverse depth, at pixel x, between the visible surface and probe i's tangent plane: how badly probe i's
plane predicts pixel x. On a plane it is exactly 0.

### 3.3 Diagram, triangulation, and a bound

- **First-type BVD = maximization diagram of the H_i** (§4.2): cell(i) = { x : s H_i(x) >= s H_j(x) for all j }. It is
  affine (§3.1, Lemma 3) and equals a power diagram (Theorem 4) of circles centred at a_i with radii
  r_i^2 = |a_i|^2 + 2 (s w_i - <p_i, a_i>) (as s scales F). On the GPU it is computed per pixel as an argmax over the
  probes of the 3 x 3 window, which is the maximization diagram rasterized; ties on a plane go to the nearest probe.
- **Bregman Delaunay triangulation** (§5.1, Theorem 11): the lower convex hull of the lifted probes (p_i, s w_i)
  projected onto the frame; its dual is the diagram above. It interpolates the probes' radiance.
- **The sandwich.** For convex F, every tangent lies below F (Lemma 1) and every chord above it, so over the probes'
  hull

      max_i H_i(x)  <=  F(x)  <=  BDT(x)          (in s-scaled inverse depth)

  and the gap g(x) = BDT(x) - max_i H_i(x) bounds the reconstruction's depth error at x (world units: about d^2 g).
  A probe pair whose divergences have the wrong sign, or a large g, marks where the reconstruction cannot be trusted.

The scan's patches add what the probes cannot: which probes lie on the same connected surface (a Delaunay edge is kept
for interpolation only when each end's patch reaches the other's triangle), and, inside a patch, the exact W
(the patch's triangles are exact pieces of W's graph, being planes).

## 4. Phase 2: regions and refinement

A pixel goes to phase 2's **refine** set when any of these holds:

1. no probe's patch covers it (its frame position is outside every patch footprint of its window);
2. its Delaunay triangle joins probes not on one connected patch (a silhouette, contact, two objects);
3. the sandwich gap g or the probe divergences exceed a tolerance (curvature too high for the lattice);
4. the probes of its triangle disagree in radiance by more than their own noise (a shadow edge, a highlight).

Every pixel phase 1 detected (a probe's cell holds geometry) also receives phase 2's **indirect** samples: full XPU2
paths, of which phase 2 keeps the part past the first hit's direct light (`beauty - direct LPE`, per sample). That part
carries the secondary bounces to everything, the objects outside the frame included. Pixels whose cell is empty
(the background) get no phase 2 samples beyond the probes'.

## 5. Combining the phases, and the questions for the user

**Bias.** Phase 2's paths are XPU2's, so its beauty is unbiased wherever it samples. Phase 1's interpolated direct light
is not: it is exact at the probes and biased between them by the reconstruction (texture detail and shadow edges between
probes). Options:

- (a) **Split by path space.** Final = phase 1 direct (trusted pixels) + phase 2 indirect (everywhere detected); phase 2's
  full beauty in the refine set. The only bias is phase 1's interpolation in trusted pixels, which the test measures.
- (b) **Progressive.** Phase 1's estimate counts as m virtual samples and phase 2's samples accumulate on it:
  consistent (bias -> 0 as samples grow), biased at a finite count.
- (c) **Control variate.** Phase 2 also evaluates phase 1's prediction for each of its own samples and adds the
  difference: unbiased everywhere it samples, at the price of a phase 2 sample in every pixel.

**Decided by the user, 2026-11-19:** A1 (the inverse-depth lift), B1 (shading reuse), and for the bias: "the indirect
light is where I want phase 1's bias to transform into an unbiased convergence". Also: "this subdivision into regions
can be stored/based on Z-depth information from the radial topological scan".

What the prototype does with them:

- **The region buffer is the scans' depths.** Each probe's patch is rasterized over its window as lifted depth (w is
  affine over a lifted triangle, so the blend is exact). Per pixel: the visible inverse depth W(x) (the nearest patch
  surface), the probes whose patch is that surface there (same depth), the cell's probe (smallest |W(x) - H_i(x)|, the
  divergence of 3.2 read exactly, not bounded) and the Bregman Delaunay triangle of those probes. Region borders are
  where the measured depths of the scanned surfaces part, never where probes merely look alike.
- **The combination** (a reading of the user's words, to confirm):

      final(x) = B(x) + m(x) / (m(x) + n(x)) * (R1(x) - D(x))

  B and D are phase 2's beauty and first-hit direct light at x (n(x) samples), R1 phase 1's reconstruction, m(x) the
  samples phase 1 counts as (0 where the region buffer does not trust it). The indirect light, B - D, is phase 2's
  alone and unbiased from its first sample; the direct light is phase 1's where trusted, its bias falling as
  m / (m + n) while phase 2's paths, which carry the indirect light, accumulate: biased at a finite count, consistent.
  Every pixel gets n(x) >= 1, so nothing phase 1 missed stays unsampled.

**Second step, asked for on 2026-11-19 after the first results:** phase 1 as a cache for phase 2's bounces, and OpenQMC in
phase 2. Both are in XPU2's shared integrator (`async_integrator.h`), so they run on the CPU and the GPU alike, and both
are off unless the engine's phase 2 sets them (`mixed::Config::frameCache`, `qmcDepth`):

- **The frame cache.** A bounce (depth 1 or more) whose hit P lifts onto a pixel phase 1 trusts, at that pixel's
  visible inverse depth (within 2%) and on the side the camera sees, takes phase 1's radiance C there and stops with
  probability 1 - p; with probability p it goes on as before, its throughput divided by p, and adds -C (1 - p) / p.
  The expectation is the continued path's for any C (a control variate chosen by Russian roulette), so the cache adds
  no bias: a poor C (a glossy surface seen from elsewhere, indirect light C lacks)
  costs variance only. This is the reading of "the indirect light is where phase 1's bias transforms into an unbiased
  convergence" that the first results pointed to: phase 1's biased radiance serves the indirect light, and the roulette
  makes its use unbiased. Bounces into what the frame does not see (the floor under the camera, the back of a ball) go
  on as plain paths: "secondary bounces to reach objects outside the camera's frame".
- **OpenQMC.** Past the first hit (where XPU2 already stratifies with its own Owen-scrambled Sobol), a vertex's light and
  BSDF samples' two directions come from OpenQMC's Owen-scrambled Sobol sampler (the headers MoonLightIPR vendors), one
  domain a branch and bounce, the branch being XPU2's deterministic tree address, so the same choice in every sample of
  a pixel is stratified across them. Built only with `XPU2_OPENQMC` (the engine's build); XPU2's own builds are unchanged.

**The readings that were offered** (kept for the record):

- **A. The hyperplane.** (A1, recommended) the camera frame is the domain, the lift is inverse depth (3.1), each probe's
  tangent plane is H_i and the generator is the visible surface itself, signed by local convexity (3.2): exact for planes,
  the cells mean "whose plane predicts this pixel best". (A2) a fixed analytic generator over the frame, for example
  squared Euclidean on (x, w) or Burg entropy (-log d, Itakura-Saito) on depth, so cells shrink with distance: simpler,
  no convexity test, but the cells no longer follow the surface's planes. (A3) the frame's plane in world space as the
  tangent hyperplane H_q at the camera of a generator over world space: D_F(P || camera) is then only a depth-like
  distance and gives no partition of the frame; noted, not recommended.
- **B. The virtual reconstruction.** (B1, recommended for the first prototype) **shading reuse**: sparse probes (s = 2 to
  4), the reconstruction spreads their direct light to the pixels of their cells and Delaunay triangles, phase 2 adds
  indirect light everywhere and full paths where the reconstruction is not trusted. Saves light samples and shadow rays;
  its cost is bias at texture and shadow detail. (B2) **frame-space transport**: a probe a pixel (s = 1); the
  reconstruction of the whole frame (probes' diagram plus the scans' hidden, connected parts) is the geometry that
  phase 1's near-field bounces are traced against without the scene's BVH, and phase 2's rays are only for what leaves it
  (objects outside the frame, hidden ones). Closer to screen-space global illumination done on a proper surface; more
  work, and its gain is fewer and shorter phase 2 paths rather than fewer light samples.
- **C. Bias policy:** (a), (b) or (c) above.

## 6. Is it sound? What holds, and what does not yet

Holds:

- The lift is exact: inverse depth over the frame sends every plane to a hyperplane, so a probe's tangent plane is the
  paper's H_q and the maximization diagram is a first-type BVD (§4.2) and a power diagram (Theorem 4).
- Both phases are XPU2 frames on both devices with per-pixel sample counts and depth limits XPU2 already reads; each
  probe is a sample defined by its identity, so it is the same on either device.

Does not hold yet, and what the design does about it:

1. **W is not convex everywhere.** The BVD's guarantees (every cell non-empty and holding its site, the Delaunay
   duality) need a strictly convex generator. Signed by local convexity, the diagram is a BVD inside convex or
   concave regions only; across a change of sign, a saddle or a silhouette it is a power diagram with no Bregman
   meaning, so those pixels go to phase 2. On a plane F is affine, all divergences are 0 and every tangent ties: the tie
   goes to the nearest probe.
2. **The reconstruction approximates radiance, not geometry.** The mesh is known exactly and a primary ray is cheap on
   an RTX card; what phase 1 truly approximates is the light between probes (texture, shadow edges, view-dependent
   highlights). The diagram makes that reuse follow surfaces and topology, which helps, but cannot make interpolated
   light right. The speed-up is irradiance caching's trade: fewer light samples and shadow rays against bias at detail.
3. **"Only the regions phase 1 detected" never repairs what phase 1 missed.** A thin object between probes would never
   be sampled: a bias that does not shrink with time. Either every pixel has some chance of a phase 2 sample, or the
   probes cover every pixel (s = 1).
4. **Phase 1 then phase 2 is a wait,** against XPU2's rule that no device waits. The sound form is per cell: a cell's
   phase 2 may start once the probes of its 3 x 3 window are in, which the cellular grid can express. The first
   prototype runs the phases in sequence and says so.
5. **Time savings need device code.** Phase 2 as an unchanged XPU2 frame still computes first-hit direct light it then
   discards; the gain appears only when the integrator skips first-hit light samples in trusted pixels (a GPU program
   change, one shader compile).

## 7. Prototype and measurements

Test scene: `MoonRayForModo-xpu2/test-results/overflow/scene.rdla` (320 x 240, `pixel_samples` 8, which is 64 samples a
pixel; floor, wall, three displaced UV spheres with DwaBase materials and a 2 MB `.tx`, an environment light and a rect
light, `max_depth` 5, `max_diffuse_depth` 0), and the same with `max_diffuse_depth` 2.

The prototype's first two steps (the fixed lattice, rasterized patches, a brute-force Bregman Delaunay triangulation
per window), built against XPU2's headers, ran both phases as XPU2 frames on the unchanged CPU and GPU lanes: no GPU
program change. Its one change to XPU2 is host-side: the sample audit lets a pixel planned no sample take none
(`async_render.h`), which no plan of XPU2's own makes.

Results, pictures and what they say: `RESULTS.md`. In short, the first step did not beat XPU2 at equal time (12%
slower without diffuse bounces, about 1.7 times with them); the trusted reconstruction was as good as XPU2 at 36 to 64
samples a pixel and the bias vanished on average; the losses were sparse-frame overhead on XPU2's grid and, with
indirect light, the noise phase 1 does not touch.

## 8. Rhea's indexer: geometry, not shading (third step, 2026-11-19)

The user's direction: "repurpose the indexer to handle not shading, but geometry". Two observations: the indexer is
"responsible to virtualize the geometry between the devices", and "the virtual geometry is reconstructed by the radial
topology in geometric passes ... it will start coarse, then it will refine itself within a variance ... convergence but
on the topological/geometric level". Then the shading changes.

**Decided by the user:** the virtual geometry is the **visible surface only** (the meshes stay in each device's ray
structures, so paths and their bounces stay exact), and the geometric variance is the **sandwich gap**, with the radial
scans deciding connectivity, silhouettes and saddles, where the bound does not hold.

### 8.1 What XPU2's indexer does, and what Rhea's does instead

XPU2's indexer (`xpu2/interactive/INDEXER.md`) classifies every scene object by the shading families it needs
(`entity_classes.h`), routes it to the devices that can render it (`routing_index.h`), and seeds each cell of the work
grid on the device that renders what it sees best, from a first-hit probe (`device_suit.h`). Its unit is the
material; its question is "which device shades this?".

Rhea's indexer (`virtual_surface.h`) asks "what surface does the camera see, and how well do the probes know it?":

| | XPU2's indexer | Rhea's indexer |
|---|---|---|
| Index | objects by shading family and device class | meshes as clusters of 128 triangles with their bounds, and their welded topology once a probe stands on them (`GeometryIndex`) |
| First-hit probe | four camera rays a tile, to weigh devices | the probes themselves: a quadtree of camera rays, each with its radial scan |
| Output | a device owner per cell | the virtual surface: sites (probes) and quads, one small piece |
| Shared between devices | decisions; every card holds every mesh | the piece, which any device evaluates per pixel without the meshes (`pack`, `SurfaceView`, `evaluate`) |

Both indexes are kept across frames by the plan's mesh objects, as XPU2 keeps tessellations: clusters are made once
(0.003 s for the test scene's 1,177 clusters), topologies the first time a probe stands on a mesh.

### 8.2 Geometric passes

1. **Pass 0, coarse.** Probes at the corners of a lattice of stride s0 (8, 16 or 32 pixels). Each probe's camera ray is
   traced on the CPU (Embree, `CpuBackend`), and its mesh scanned ring by ring (`scan.h`) over a window of its quads'
   size: the patch's triangles and the patch's **boundary**, the edges where the surface ends inside the window (a
   border of the mesh, or a silhouette where it turns away from the camera).
2. **Each quad is tested** (below). A quad that converged is a leaf. One that has not splits in four: new probes at its
   edges' middles and its centre, shared with its neighbours, traced and scanned in the next pass.
3. **Down to the finest stride** (min_stride, 2 pixels). What has not converged there stays untrusted: phase 2 renders
   it whole.

Like sampling, the passes converge: each pass resolves more of the frame (section 8.5's numbers), and a realtime preview
could show the surface after each pass.

### 8.3 When a quad has converged

Its reconstruction is the Bregman Delaunay interpolation of its four probes: one of the quad's two diagonals, the one
whose lifted edge is lower (`quadDiagonal`, the lower hull of section 3.3 on four sites), and the plane of each half.
It has converged within the tolerance when the reconstruction is the visible surface over the quad and a margin of
the pixel filter's reach:

1. **Connected.** Every probe's scan reached every other probe's triangle: one connected surface.
2. **No end inside.** No probe's patch boundary crosses the quad: no silhouette, border or hole.
3. **The sandwich gap** under the tolerance (relative inverse depth) at every pixel: for a convex piece the surface
   lies between the probes' tangent planes and the Delaunay interpolation (`sandwichGap`); a saddle, where the bound
   does not hold, counts the spread of all of them.
4. **No crease.** The scanned triangles over the quad, clipped to each half, lie within the tolerance of its plane on
   either side: a crease or a saddle's relief between the probes. A mesh is piecewise planar, so checking the clipped
   triangles' corners is exact.
5. **Nothing in front.** No other geometry lies in front of the reconstruction over the quad: the indexer's clusters
   whose bounds reach the quad nearer than its farthest point, then their triangles, clipped at the camera's near plane
   and to each half (`liftClipped`, `departs`). This is what catches an object smaller than the quad that no probe hit.

A quad whose four probes all missed has converged as background when no cluster's triangles reach it.

### 8.4 The piece

`pack` writes the virtual surface as one block: a header, the sites (pixel, hit, tangent plane, inverse depth, phase 1's
radiance; 36 bytes each) and the quads (corners, children, state, diagonal, the halves' planes; 56 bytes each).
`evaluate` reads only that block: it walks the quadtree from the root grid to the pixel's leaf and returns the leaf's
state, inverse depth, Bregman Voronoi cell (the corner whose plane predicts the pixel best) and phase 1's radiance
interpolated over the Delaunay half. It is plain code over arrays, as a GPU thread would run it. The engine's region
pass is exactly this, from the packed bytes, which makes the per-pixel buffers of the first steps unnecessary.

Today the piece is evaluated on the host and the frame cache handed to the GPU is still made per pixel from it; the GPU
evaluating the piece itself (and a Rhizome node receiving it as one more piece of the swarm's memory, named by its hash)
belongs to the shading step.

### 8.5 What it replaced, and what is open

Gone from the engine: the fixed lattice, the nine overlapping depth tiles per pixel, the brute-force triangulation per
window and mask behind locks, the per-pixel silhouette pass, and eight classes folded into the leaf states. The region
pass went from 37 ms to 2 ms, the probes from 19,200 to 1,754 (s0 16), and geometry is exact within the tolerance on
every converged pixel. Numbers and pictures: `RESULTS.md` section 6.

Open, for the shading step: the radiance between coarse probes (a converged wall quad of 16 pixels interpolates its
light over 16 pixels: the geometry is right, the shadow gradient is not quite); dense launches for both phases; the
probe frame's and phase 2's fixed costs; the piece on the GPU. Also open: T-junctions between leaves of different
levels (a coarse leaf's edge interpolates only its own corners, so its light can step against the finer neighbours'),
and the passes running on the GPU.

## 9. The shading step (2026-11-19)

The user's go: "start the shading step". After the geometry (section 8), the time was in the frames' shape on XPU2's
grid, and the error in the light between coarse probes.

### 9.1 Dense frames: per-tile depth and gather tiles (XPU2)

XPU2's grid published every 8 x 8 tile's chunks up to the frame's samples a pixel; a sample past a pixel's own count
was a claim the GPU skipped. Two changes, each used only where a plan asks for it:

- **Per-tile depth** (`async_grid.h` `GridOptions::tileSpp`, set by `async_render.h` whenever a plan has its own counts
  per pixel): a tile's chunks stop at the most any of its pixels takes, so a few 32-sample silhouette pixels no longer
  make every tile 32 deep. Cells no longer hold the same chunks in every range, so the progressive frontier reads each
  cell's ranges from where they start in its queue (`Cell::rangeStart`); for XPU2's own frames that is where it read
  them before. Host only. `async_grid_test.cc` checks it (every pixel gets exactly its tile's samples, tiles with none).
- **Gather tiles** (`Plan::gather`, `mixed::Config::gather`, `chunkPixel`): a plan may list each tile's 64 pixels. A
  probe frame packs its probes 64 to a tile, the tiles spread over the grid's cells. One line in the GPU's feed and one
  in the CPU lane read the list (a GPU program change); XPU2's own plans have none. The indexer's first-hit seeding is
  skipped for gathered frames, whose tiles are not the image's.

A sample is still defined by its pixel and index, so these frames render exactly the samples they did before.

### 9.2 Light passes, the light's curvature, and what paid

- **Light passes** (`VirtualSurface::refineLight`, option `light_passes`): after the probe frame, a quad whose geometry
  converged splits where its light bends more than `light_tol` between its probes, estimated from the light's second
  difference across each corner's neighbours at the quad's stride (an eighth of it, relative to the quad's light, is
  linear interpolation's error). Its children go through a geometric pass and the next probe frame lights their new
  probes alone, up to `light_passes` times. Built and measured: at a tolerance that catches the bias (0.2%) the test
  mostly chases the probes' own noise (a probe's second difference carries about a third of its noise), so it costs
  five times the probes and extra frames for what more samples a probe give cheaper. Off by default.
- **The curvature term** (`VirtualSurface::curvature`, options `curvature`, `curv_span`): measured against a converged
  direct-light reference, the probes are unbiased and the reconstruction is darker by 0.07% at s0 8 and 0.2% at s0 16:
  linear interpolation sits on the chords of a light that bends. The piece now carries each quad's curvature (d2L/dx2,
  d2L/dy2, from its corners' second differences) and `evaluate` adds the second-order term,
  -1/2 sum_k b_k (Lxx dx_k^2 + Lyy dy_k^2). Measured over neighbours one stride away it triples the reconstruction's
  noise; over four strides (32 pixels at s0 8) it halves the bias at the same noise. On by default, span 4.
- **More samples a probe.** Probes are few and a probe frame is dense now, so 64 samples a probe (and m0 128, phase 1
  counted as 128 samples) cost 12 ms and take a quarter off the error.
- **Phase 2 gathered by sample count** (option `gather2`): no gain over per-tile depth. Off.

### 9.3 What is left

- **One frame.** Geometry (15 ms, CPU) and two frames (41 ms probes, 94 ms phase 2). With the radiance-edge rule moved
  to the combination, phase 2's counts depend on geometry alone, so probes and phase 2 can be one frame: either a depth
  limit per pixel in the integrator (probe pixels direct only; a GPU program change) or probe pixels rendered as
  ordinary full paths whose direct-light outputs are the probes. Expected saving: a frame's fixed cost, about 15 to 20 ms.
- **Silhouettes** now hold the largest share of the error: phase 2's own noise in the 5% of pixels that never converge.
- **Indirect light** is still phase 2's alone, and with diffuse bounces Rhea still trails XPU2.
- T-junctions between leaves of different levels; the piece on the GPU; the passes on the GPU.

## 10. One frame: a depth limit per pixel (2026-11-19)

The user's choice: "go with the per-pixel depth limit". The engine was renamed Rhea the same day.

- **XPU2** (`Plan::fullSamples`, `mixed::Config::fullSamples`, `integratePaths`): each pixel's samples that are full
  paths; a sample past them stops at the first hit (max_depth 0 for that sample alone). The one place the integrator
  reads the depth limit now reads the sample's own. XPU2's plans have none.
- **The frame.** The geometric passes give every pixel its state, and so its n(x) full paths (the radiance-edge rule,
  the one rule that needs light, moved after the frame, where it only lowers phase 1's weight). A probe's pixel takes
  probe_spp more samples past its n(x), first hit only. The frame's pixels are gathered by their total samples
  (Plan::gather), so a tile's pixels take the same number.
- **What comes back.** The direct-light outputs (C[<L.>O] + C[DGS][<L.>O]) average all N(x) samples of a pixel: D, from
  the full paths' first hits and the probe samples alike. That is the probe's light at its pixel. The beauty's mean is
  (n (D + I) + (N - n) D) / N, so the indirect light I = N (beauty - D) / n comes from the full paths alone. Then the
  region pass runs with the probes' light, and
      final = I + (1 - k) D + k R1,   k = m / (m + N),
  which without probe samples (N = n) is the two-frame combination. It holds while a first-hit-only sample's beauty is
  its direct-light outputs (true on the test scene: probe/direct 1.0001); subsurface or volume light at the first hit
  would need its own expression in D.
- **Devices.** A gathered frame skips the indexer's suitability seeding (its tiles are not the image's), so cells start
  as a checkerboard and the CPU lane takes deep probe and silhouette tiles at about ten times the GPU's cost a sample:
  the frame waits for it. The default is the GPU alone for shading (`mode=1`); the CPU does the geometry. On this scene
  XPU2 itself is fastest on the GPU alone too.
- **Kept for what needs the probes' light first:** light passes and the frame cache still run phase 1 in frames of its
  own (`one_frame=0` forces it).

## 11. The CPU's part: pipelined frames (2026-11-19)

The user asked what the CPU can contribute, since Rhea is built on XPU2 (whose CPU lane shares the picture with the
GPU), and then: "build the pipelining". On the test scene the CPU lane renders a sample about ten times slower than
the RTX 3090 (section 10), so sharing pixels gains little and can hold a frame's end up. Its part is the work that suits
it: the geometry (the indexer, the probes' traces, the scans, the quads' tests: irregular, branching walks) and the
frame's bookkeeping (the region pass, the combination). XPU2's deferral path (samples the GPU cannot render) stays as it
is, for scenes that need it.

**The pipeline** (`rhea_engine.cc`, option `frames`; `orbit` swings the camera's yaw over the run, `seq_xpu2` times XPU2
on the same path): three frame slots turn round. While the GPU renders frame k, one CPU thread finishes frame k - 1
(the probes' light from its direct-light outputs, the region pass, the combination) and prepares frame k + 1 (its
geometric passes, states, samples and plan). The camera moves by its own transform each frame (render space stays,
as XPU2's camera-only updates keep it).

**Threads.** The pipelined CPU work runs on a pool of its own, 4 threads below normal priority (`seq_threads`,
`LowPriorityWork`, one pool for each thread count and priority). On all 12 threads at normal priority it slowed the
GPU's frames by 7 to 35 ms (the renderer's own host work shares the cores; its feeder already runs at the highest
priority), and the pipeline lost on the scene with diffuse bounces.

## 12. Diffuse bounces: probes that carry the whole light (2026-11-19)

The user: "find out and fix it" (why Rhea trailed XPU2 with diffuse bounces).

**What it was not.** Not the frame's shape: XPU2's launch trace (now in the report, `phase2_launch_trace`) shows Rhea's
frame in 5 large launches, as XPU2's 9 spp frame, with the GPU busy throughout; the progressive order off, larger
chunks, or no gathering all made it slower.

**What it was.** The samples' economics. Rhea's samples cost about what XPU2's do, but it did not save enough of them:
with diffuse bounces the error is the indirect light's noise, which only phase 2 reduced, so trusted pixels needed 8
full paths against XPU2's 9, and the probes (64 samples each) and silhouettes (32) cost more than the sample saved.

**The fix.** Diffuse indirect light is smooth, what interpolating probes handles best (irradiance caching's
observation). With `probe_full` the probes' extra samples are full paths: phase 1 reconstructs the beauty, and phase 2
corrects it,
    final = B + k (R1 - B),   k = m / (m + N),
B the pixel's beauty over its N samples. It stays consistent as before: k falls as phase 2's samples grow, and the
reconstruction's bias with it. Default: whole-light probes where the scene bounces diffusely (`max_diffuse_depth` > 0),
with phase 2 at 2 samples in converged pixels and 16 elsewhere; direct-light probes otherwise, at 4 and 32 (without
diffuse bounces whole-light probes cost about 10% more and gain nothing). This changes the split chosen at the start
(phase 2 alone carrying the indirect light) where diffuse bounces exist; `probe_full=0` restores it.

What it trades: per-pixel noise for low-frequency error. The reconstruction's error is smooth (faint blotches at the
probes' spacing, ten times magnified in the error image), so the relative MSE falls twelve-fold while the 8 x 8 block
error stays about XPU2's at 9 samples a pixel.

## 13. Frames that accumulate: jitter, and phase 1's weight over frames (2026-11-19)

The user: "jitter the probes across frames", so that the reconstruction's blotches become noise that frames average.

- **Jitter** (`jitter`, `SurfaceOptions::ox, oy`, the piece's header): each frame's root lattice offset within a stride
  by the R2 sequence, and its samples drawn afresh (`Plan::seed` + 7919 k); frame 0 keeps both, so it is the single
  frame's picture. `evaluate` finds the root quad from the offset.
- **What it showed.** Averaging finished frames, jittered or not, gave the same error at every count to 64 frames: the
  blotches were the probes' noise, which fresh seeds already average, and what stayed (a darkening of 0.02%) is
  one-signed: linear interpolation of light that bends sits on the same side of it wherever the probes are, so moving
  them cannot average it away.
- **What was wrong instead:** averaging finished frames keeps phase 1's weight m / (m + N) at every count, so its bias
  never fades, against the bias policy chosen at the start. **The convergent accumulation** (`accumulate`): each
  pixel's beauty and direct light (times their samples), its samples (all, and full paths), phase 1's reconstruction
  and weight summed over K frames and combined once, as one frame is, with phase 1 counting as mean(m) K^p samples
  against phase 2's sum. p = 1 is averaging; p < 1 lets phase 1's weight, and its bias, fall as phase 2's samples pile
  up (p = 0.5 by default: p = 0 removes the bias fastest but leaves phase 2's noise).
- Jitter and the convergent accumulation together take a little more of the darkening (0.99989 against 0.99981 at 64
  frames with diffuse bounces) for 5 to 8% of a frame and a third more per-pixel error: jitter stays an option, off.

## 14. Scenes of many meshes: convergence by coverage (2026-11-20)

The user: "start with fix 1" (after Sponza, RESULTS.md section 12).

- **Coverage** (`VirtualSurface::covered`, option `coverage`, on): a quad whose probes are not on one connected mesh, or
  whose patches stopped short or are crossed by a mesh's border, still converges where the four patches together cover
  every pixel centre of it and its margin, whatever their meshes. The tests after it hold the covering triangles to the
  reconstruction (each patch on its own mesh now) and allow nothing else in front, so the covering surface is the
  visible one: one connected mesh was sufficient, never necessary.
- **Probe samples where they are read** (`VirtualSurface::usedSites`): in one frame, only the corners of converged
  leaves take a probe's extra samples; a probe that stands where nothing converged gets its pixel's samples alone. On
  Sponza that halved the frame; on the test scene it saved a fifth (silhouette probes' pixels lose their extra direct
  samples, a little noise).

## 15. The floor (2026-11-20)

The user: "start with the floor": where little of the frame converges, Rhea renders as XPU2 does, so that it is never
worse than XPU2.

- **The test:** after the first geometric pass, the share of the frame its root quads converged
  (`VirtualSurface::firstPassArea`). Below `floor_area` (30%) the passes stop (`floored`), no probe takes samples, and
  the frame is XPU2's own: `floor_spp` samples every pixel (9 by default, the counts these tests compare XPU2 at), no
  sample map, no gather tiles, phase 1's weight 0. The first pass separates the scenes plainly: 92% on the test scene,
  8% on Sponza.
- **In a sequence** the test runs each frame, and pipelined the first pass is the CPU's work under the GPU's previous
  frame: the floor then costs nothing.
- What it does not do: give the floored frame what Rhea could have reconstructed in its 8%. A partial floor (probes
  only in the regions that converge) would; the first pass's quads say where.

## 16. Demodulated light: dividing out the surface's colour (2026-11-20)

The user: "divide out the surface colour" (irradiance caching's practice): probes interpolate light, not texture.

- **Colour:** the frame's albedo output (MoonRay's material AOV `albedo`, `RenderOutput("/rhea_albedo")`, added by
  `run_rhea.py`) at the first hit, averaged over each pixel's samples, probes' included. In one frame it is known for
  every pixel when the reconstruction runs.
- **The light interpolated** (`evaluate`): each corner's light divided by its colour (per channel, never by less than the
  floor 0.02), interpolated, and multiplied by the pixel's colour; plain radiance where a corner or the pixel is darker
  than the floor (metal, emitters, the sky). The curvature term and the radiance-edge rule read the same demodulated
  light (`VirtualSurface::lightOf`), so a texture's edge is not a light edge.
- **Option `demod`** (on): one frame and sequences. What it does not do: a surface whose light is not its colour times
  an irradiance (specular, emission) is scaled by the colour ratio between probes; the weight m / (m + N) is what
  corrects it.

## 17. Phase 2 capped: convergence at rest (2026-11-20)

The user: "the convergence should happen at rest, and phase 2 dominates, so then we should make phase two limited to
1-2 samples".

- **The cap** (`phase2_max`, 2): phase 2's samples a pixel in a frame, at most, whatever the probes say (`n_lo`, `n_hi`,
  `n_bg` and the floor's `floor_spp` all clipped to it). A frame then costs about what XPU2's 2 samples cost, while the
  camera moves.
- **At rest** the frames accumulate (section 13): phase 2's samples pile up and phase 1's weight fades as
  mean(m) K^p against them. With frames this cheap the weight phase 1 starts with (`m0`) and how it fades (`accum_power`)
  decide the picture: a weight that stays too long keeps the interpolation's bias after the noise has gone.

## 18. Persistent probes (2026-11-20)

The user: "it would also be faster if the probes are persistent instead of recomputing each frame", "since the probes
are persistent and reconstruct the geometry, there shouldnt be extra probes where geometry has already been discovered"
(frame by frame). The reconstruction triangulates the persistent probes; a probe's light fades older samples when the
camera moves; the GPU's own camera rays verify the reconstruction (`persist`, `rhea/persistent.h`).

- **A probe** is a point on a plan mesh's triangle (mesh, triangle, barycentrics, its point) with its light and colour
  summed over the frames it was sampled in, times their samples.
- **Each frame, before the GPU** (the CPU, pipelined under the last frame): the known probes are lifted onto the new
  camera's frame and kept where a camera ray at their raster point still meets their own triangle (a CPU ray each: what
  lies in front of a probe is what hides it). New probes go only where the last frame asked for them: an 8 x 8 cell
  (`cell`) whose verification failed, or one that holds no probe and did not meet sky. One a cell a frame, at a pixel
  jittered by the frame, never within 2 pixels (`spacing`) of another.
- **The triangulation:** the frame's probes by their raster points, Delaunay (`rhea/delaunay.h`: Delaunator's sweep-hull
  insertion with Lawson flips, ISC license), then flipped to the Bregman Delaunay triangulation of the
  inverse-depth lift: a convex quad takes the diagonal of the lower hull (`quadDiagonal`), a few passes. Where a
  triangle's sandwich gap over its pixels passes the tolerance, a probe goes at its centre and the triangulation is made
  again (`gap_passes`, 2). This is the quadtree's geometric convergence (section 2) on points that stay: a surface
  already resolved takes no new probe.
- **Samples:** a new probe's pixel takes `probe_spp` samples, a known one's `keep_spp` (4); phase 2 the cap's (section
  17): `n_lo` inside triangles whose gap passed, `n_hi` elsewhere, `n_bg` in sky cells.
- **After the frame:** each probe in it takes its pixel's light and colour, the sums first faded by `fade` (0.95) when
  the camera has moved, so light that depends on the view follows. 0.8 was tried first: a moving camera's probes then
  hold about 20 samples, and their noise showed as block error (RESULTS.md 16). A probe takes nothing where its pixel's
  depths say the samples met more than its own surface (`clean_absorb`: the probe's tangent plane holds the pixel's
  depth min and max, as in the verification below): a kept probe can come to lie in a pixel across an edge. The
  reconstruction interpolates each pixel's light over its triangle, demodulated as section 16, and its inverse depth is
  the triangle's plane.
- **Verification on the GPU:** phase 2's own camera rays carry it. Two depth outputs (`/rhea_depth_min`,
  `/rhea_depth_max`: the state variable depth with the min and max math filters) hold the nearest and farthest first hit
  among the pixel's samples. A pixel passes where both lie within the triangle's plane over the pixel's footprint,
  widened by the tolerance, or where no triangle is and no sample hit. A pixel that fails takes no phase 1 this frame
  (m 0) and asks for a probe in its cell for the next. The radial scans and the CPU's exactness tests (coverage,
  creases, occluders) have no part: what a pixel sees is what the GPU's samples meet.
- **The combination** is section 12's or 7's with the latest reconstruction as phase 1; accumulated frames take it as it
  stands now (its probes' sums already hold the frames before).
- **A moving camera** is a yaw in the camera's own space: XPU2's camera holds render space beside its node transform
  (`render2World`, `world2render` and its 3 x 4 form, which the depth outputs and the perspective rays' directions go
  through), and the sequence turns all of them, as XPU2's camera-only update does.
- **Defaults by mode:** with persistent probes phase 1 counts as `m0` 32 samples and its weight does not grow over
  accumulated frames (`accum_power` 0): a probe's sums already hold the frames before (RESULTS.md 16).
- What it does not do yet: a fade by how far a probe's light departs from its mean (not a fixed rate), pruning probes
  that have left the frame for good, a floor, moving geometry (a probe is a point on a triangle at rest).

## 19. Falling back to XPU2: gracefully (2026-11-20)

The user: "the fallback from Rhea to XPU2 RT should be graceful, not restarts", and Rhea may "serve biased-dominant at
first since that can be cheap on gpu".

- Biased-dominant first is what the combination does: in one frame phase 1 counts as `m0` samples against phase 2's 2,
  and as phase 2's samples pile up at rest its weight m / (m + N) falls, the picture converging to the unbiased one.
- Phase 2's samples are XPU2's own samples. A fallback, of a pixel, a region or the frame, is phase 1's weight going
  to 0, faded over frames, while phase 2's sample sums carry on: never a buffer reset or a frame-wide switch of engines.
  Coming back fades the weight in.
- Persistent probes already fall back so, pixel by pixel: a pixel the verification fails, or whose triangle is not
  trusted, takes m 0 that frame, and the accumulated weight is the mean over frames. The quadtree mode's whole-frame
  floor (section 15) is the abrupt kind: the floor that ships fades instead.
- **In the kit** (the user, for when it goes in): an opt-in in the preview preferences under XPU2 RT, "XPU2 RT
  (Rhea)", XPU2 RT staying the default; it follows drags; probes live in a session-only cache (never on disk) keyed by
  mesh: on a light or material edit their light fades and their places stay, on a mesh's geometry edit its probes go,
  a memory budget evicts the probes unseen longest, and a probe's point is made again each frame from its triangle and
  barycentrics, so moving and deforming meshes carry their probes.
- **Cameras** (the user: "rhea should practically support all camera features as in moonlightIPR"). Today the lift is
  a still pinhole perspective camera's. Depth of field and motion blur already fall back pixel by pixel (the
  verification fails where lens or shutter samples meet different surfaces) and gain nothing there until phase 1 is
  blurred by the circle of confusion or the motion; an orthographic camera needs its own lift (depth, not inverse
  depth, is linear across a plane); spherical and dome cameras keep the triangulation but rest on the verification
  alone, planes no longer staying planes in the picture.

## 20. The denoiser (2026-11-20)

The user: "the virtual surface should work as a denoiser's guide as well".

- **The denoiser** is the kit's realtime one: XPU2's `GpuLane::Denoiser`, OptiX's HDR model with albedo and normal
  guides, the albedo cleaned first (the kit's default), its inputs prepared as `xpu2_session.cc`'s realtime picture
  prepares them (colour clamped at 0, albedo to [0, 1]). Option `denoise` (with `seq_ref`): each scored frame, Rhea's
  and XPU2's, written as `dn-<variant>-<frame>`.
- **The guides:** the albedo output; the normal output (`/rhea_normal`, the state variable N, as the kit's
  `denoise_normal`) as it is, and projected onto the camera's axes as the kit's realtime does; and the virtual surface's
  normals: each probe's mesh triangle's normal in camera space, facing the camera, interpolated over the
  reconstruction's triangle where the frame's verification held, the normal output's elsewhere.
- **Variants:** XPU2's frame and Rhea's with each normal guide; Rhea's with the virtual surface's normals; Rhea's left as
  it is where phase 1 held (trusted and verified), denoised elsewhere.
- What the measurements say (RESULTS.md 17): a denoiser removes fine noise, and Rhea's interpolation turns noise into
  blotches the size of its triangles, which a denoiser keeps as picture. A guide that only marks edges cannot change
  that; where the virtual surface can serve a denoiser is in time: telling which of the last frames' samples still
  belong to a pixel (RESULTS.md 18, Open).

## 21. XPU2 RT (Rhea) in the kit (2026-11-20)

The user: "let's now bring Rhea into the kit for testing. We'll use it as the default XPU2 RT engine, as we noted it'll
gracefully switch to old XPU2 in areas that Rhea has issues with. It should have "follow drag" option like
MoonLightIPR, and like old XPU2 realtime it should only have beauty and denoised beauty"; "the status indicator should
say XPU2 Rhea active when realtime is on".

- **The engine** (`rhea/rhea_realtime.h`, `rhea::Realtime`): section 18's persistent probes as a class the XPU2 session
  runs. `prepare` makes a frame's plan from the session's (its camera current): the field's probes, the sample map (the
  cap's phase 2, probes' extra samples), gather tiles, the first hit alone past phase 2's samples, sampling generations
  off (a sample map is read only without them). `finish` makes the frame's picture and sums it with the frames since the
  camera last moved, as XPU2's result (rgba, counts, AOV values the sums'), so the session publishes, denoises and writes
  it as its own. At rest phase 2's samples a frame double each frame up to 32, so the sums gather at XPU2's pace.
  `rhea_engine.cc realtime=1` runs the class on the test paths: the same scores as the engine's own runs (RESULTS.md).
- **In the session** (`xpu2_session.cc`): with `XPU2_SESSION_RT_ENGINE=rhea` a realtime frame (the kit's RT) is Rhea's
  frames in place of XPU2's one render: short frames until a command comes (each drag step, each edit), a stop (Pause:
  the picture in hand), or phase 2's samples reach the frame's samples a pixel. The probes live across frames: a camera
  move keeps them, any other edit, or other geometry (a coarse first pass's full plan), forgets them. A scene Rhea does
  not take (`rhea::unsupported`: not a perspective camera, depth of field, motion blur, a sample map, the outputs
  missing) is XPU2's frame as before, and so is anything not realtime. The session says which renders each frame when
  it changes; the kit's status reads it: "XPU2 Rhea active" or "XPU2 active".
- **In the kit:** Preferences, under XPU2 RT Sample %: XPU2 RT engine (Rhea, the default, or XPU2) and XPU2 RT follows
  drags (off by default, as MoonLightIPR's Follow drags). `render.py` gives a realtime scene XPU2 renders with Rhea
  chosen Rhea's five outputs (`rdla.rhea_lines`, a file of their own). The views are XPU2 RT's: Beauty and Denoised
  Beauty (`panel._limit_buffers`, unchanged). Followed drags poll the viewport's camera as MoonLightIPR's do and send
  each step as a move of the camera alone (`incremental.move_only`), rendered as it comes; the drag's end is read the
  usual way at the release.
- **Its XPU2:** Rhea's frames need XPU2's per-tile depth, gather tiles and first-hit-only samples (section 9, 10), so
  the kit's XPU2 GPU programs are this branch's: Compile XPU2 Shaders once more after installing.
- Not yet: the CPU's part pipelined under the GPU's frame (section 11; here it runs in turn), the probes kept by mesh
  across edits (the session-only cache). The cameras: section 22.

## 22. Rhea's cameras (2026-11-20)

The user: "work on getting camera features compatible with rhea" (as MoonLightIPR draws them: perspective with depth of
field and bokeh, orthographic, spherical, fisheye and dome, and motion blur).

- **The view** (`rhea/view.h`, `rhea::View`, the persistent probes' camera; the quadtree keeps bvd.h's Frame): where a
  trace-space point lands in the picture and its lifted depth w, the chief ray through a pixel (XPU2's own
  `cameraSampleAt` at the lens' centre and the shutter's open), and a probe's tangent plane in the lifted space.
  - Perspective: Frame's lift, from the camera's focal point (a stereo eye's, where perspectiveRay starts), w = 1 / depth.
  - Orthographic: the picture is affine in camera space, so a plane stays a plane in (x, y, depth); w = 1 - depth / K,
    K twice the farthest depth the scene's bounds reach from the camera, so w falls as depth grows and stays in (0, 1].
  - Spherical, fisheye and dome (directional): a point's place is found from the camera's own rays by Gauss-Newton,
    from where the probe was last seen (or a coarse grid of the picture's rays); w = 1 / distance; tangent planes by
    the lifts of points a pixel apart on the probe's triangle. No plane stays a plane here: the GPU's verification is
    what holds the reconstruction to the picture.
  - Raster places are the picture's own: a render region's offset is taken out, as XPU2's rays put it in.
- **Depth of field and motion blur** keep the pinhole at the lens' centre and the shutter's open. Where a pixel's
  samples meet more than the triangle's plane holds (out of focus on a slanted surface, moving), its verification fails
  and it is XPU2's samples alone; in focus and still, it is Rhea's.
- **Verification** compares the depth outputs through the camera's own w (1 / depth, or 1 - depth / K).
- **Cells that keep failing** (out of focus, moving, an edge) take no new probe once they hold four (`maxPerCell`):
  more probes do not help there, and depth of field otherwise filled the frame with them.
- **Phase 1's light summed by its weight.** At rest each frame adds phase 1's weight and its light times that weight;
  the combination's light is their ratio. With the latest reconstruction and the weight of all frames, a pixel that
  verified in some frames and not the latest took the weight of those frames and the latest reconstruction's light, 0
  where it does not verify: out of focus, where verification comes and goes, the picture went 1.2% dark.
- **One sequence at rest** (`Plan::sampleBase`, XPU2): each pixel's samples in a frame at rest continue those it had
  (the frame's index plus its base, the seed held), so that the frames' samples stratify together as one frame's
  would. Drawn afresh each frame (a new seed, indices from 0), five frames of 2, 4, 8, 16 and 32 samples were noisier
  than XPU2's 32 in one go wherever phase 1 is not used. The sample map and the depth limit still read the frame's own
  index. Empty, XPU2's frames are as they were.
- **Directional cameras' phase 1 counts 8 samples** (`m0Directional`), not 32: their light interpolated over triangles
  the lens bends carries a one-signed bias that at 32 showed against XPU2's at the same samples (RESULTS.md 18).
- Refused (XPU2's frames as before): a bake camera, a dome's stereo eyes, an inside-out spherical camera.
- Tried and left off: a pixel verifies only where its alpha is whole (misses leave no depth). It held back probes that
  were right on the wide cameras, and the out-of-focus bias it was meant for was the summing above.

## 23. Slanted surfaces, and the frame's samples at rest (2026-11-20)

The user: "i think with the issue with Sponza is that Rhea needs another plane that can handle slanted planes. We can
create another virtualized plane to triangulate the angle".

- **Sponza in XPU2's session** (192 x 108, a realtime frame of 32): Rhea runs on it now (the quadtree's first pass had
  converged 8% and floored): 93% of the picture verified, phase 1 in 13%. Of the pixels verified, a triangle's
  sandwich gap held back 46 to 51% edge on (|N.z| under 0.1) and 22% face on; a light edge, 5 to 10% edge on and 37%
  face on (`rhea/tools/slant_study.py`).
- **The surface's own plane** (`FieldOptions::slant`, `planeLight`): a triangle's geometric fit judged along its
  surface's normal, the gap's tolerance in the lifted depth tol / cos (the surface's angle to the camera, at most 20
  times); and its light interpolated over the surface, each corner weighted by its w (perspective-correct). On Sponza
  the gap's share edge on fell from 51% to 46%, the rest as it was; on the cameras it is neutral but for the spherical
  camera's block error (1.69e-4 to 1.62e-4 with the light over the surface). Kept: they are right, and cost nothing.
  The gaps that remain on Sponza's slanted surfaces are geometry (bricks, tiles, arches meeting), not the lift's
  magnification.
- **The frame's samples at rest** (`RealtimeOptions::target`): at rest no pixel takes more phase 2 samples than it lacks
  of the frame's. The doubling frames had overshot to about 62 a pixel (the last of five doubling the cost for 2), so
  the cameras' table (RESULTS.md 18) compared Rhea at about 62 with XPU2 at 32; corrected there.
- **Each Rhea frame in the MoonRay Terminal**: its probes' time and count, the renderer's, the render's (launches, GPU
  samples, fine-detail tiles, provisional samples), the finish's. On Sponza the CPU's part is 0.02 s a frame; the first
  frame carries the new probes' 64 samples and the textures' first reads.

## 24. XPU2 renders the camera at rest (2026-11-21)

The user: "let XPU2 handle the camera at rest, and Rhea handle drags and camera moves".

- **A camera move** (a camera-only edit, probes in hand): one frame of Rhea's for where the camera now is, shown as soon
  as it lands (`rhea::Realtime::prepare`, `finish`).
- **Then, the camera at rest:** XPU2's own realtime frame (its sampling generations: its samples where the noise is),
  each of its pictures folded into Rhea's sums as it comes (`merge`): its samples full paths, its direct light its
  outputs'. Rhea's part (phase 1 and its own samples) fades as (1 - fraction)^2, so the frame begins as Rhea's picture
  and ends as XPU2's own, exactly (kept whole, Rhea's few even samples stood beside XPU2's in pixels its generations had
  left early, and the frame ended a little noisier). No restart either way: a move during XPU2's frame stops it and the
  next frame is Rhea's.
- **The probes learn from XPU2** (`absorbRest`): its frame's light as far as it came (a move may stop it; on a heavy
  scene the first may never end before a drag), each pixel's samples its weight, goes into the probes, so the next move
  begins with probes lit by many samples at no cost of the GPU's. A probe with no light yet takes a new probe's samples
  in Rhea's next frame.
- **A new scene, or an edit other than the camera** (the probes forgotten): the probes placed for the camera on the CPU
  (`place`, no frame of Rhea's), XPU2's frame, and the probes lit by it.

- **Probes, how many** (the user: "would it be performant if the probes were culled if at most one probe reached a mesh,
  so that there aren't redundant reconstructions from each probe hitting the same mesh?"). A probe is a sample of
  light as much as of geometry, and light varies over a mesh (shadows, falloff): one a mesh would light each mesh
  evenly. Their cost: about 0.02 s of the CPU's a frame and 5 to 10% of a moving frame's GPU samples on the test scene;
  on Sponza's first frame, before XPU2 lit them, 111k of the frame's 152k samples (1,734 new probes at 64). Planned:
  probes pruned where their neighbours already predict their light (flat, evenly lit regions keep few), and fewer
  samples for probes born in a move now that XPU2's frames at rest light the rest.
- **The probes' budget** (`RealtimeOptions::probeShare`, 0.5): a frame's probe samples at most half of phase 2's, the
  known probes' keepSpp first, the new or unlit ones sharing the rest (never fewer than keepSpp nor more than probeSpp).
  On Sponza a drag begun before XPU2's first frame at rest had lit the probes found 2,114 of them unlit, at 64 samples
  each: 135k of the frame's 176k samples, 8.5 s, longer than the drag's steps, so no frame of Rhea's was ever shown.
- **Textures as the card holds them** (`Plan::residentTextures`, XPU2): a camera move's frame asks for no fine-detail
  tile; a texel whose tile is not on the card is read from the nearest level up that is (the coarse levels always
  are: a texture's average colour, or a few dozen texels across), as the sample's own, nothing rendered again. Once
  XPU2's frames at rest have brought a texture's tiles, a move shows them. The user: "the textures on first phase is too
  heavy, it should just get the average color of the texture which would be of lower quality, then the textures can
  stream in once standard XPU2 realtime kicks in". On Sponza's first frame 147k tiles had streamed and 153k provisional
  samples were rendered again. The demodulated light keeps the probes right whichever detail lit them: a move's frame
  divides out the coarse colour, XPU2's the fine.

## 25. Rhea's virtual planes: three perpetual layers (2026-11-21)

The user: "there should be a virtual plane that is camera resolution size that is behind any geometry. This can be
calculated by the z-buffer"; "so Rhea concerning the virtualized planes, theres the back plane, and the slanted plane
(s) (to capture left-right grazing angles), and the front hyperplane. these need to be perpetual components to capture
any scene for its first pass".

Rhea's virtual geometry becomes three layers, each there from a scene's first pass, each pixel taken by the one that
holds for it (the GPU's verification decides):

- **The front hyperplane:** the lifted space (x, y, w) where the probes' tangent planes are hyperplanes and their
  Bregman Delaunay triangulation lives (sections 2, 18): surfaces facing the camera, near and middle.
- **The slanted planes:** surfaces at grazing angles, left and right (walls running away from the camera), each
  triangulated in its own plane's coordinates, where its probes are not foreshortened: a pixel's ray meets the plane,
  its light interpolated over the plane's triangles in world space. On Sponza the front hyperplane's gap holds back half
  of the edge-on pixels it verifies (section 23).
- **The back plane:** camera resolution, behind all geometry, made from the z-buffer (the depth outputs): each pixel's
  depth and light. On a camera move each pixel is reprojected by its depth into the new view and kept where the new
  frame's depths say it is still what the pixel sees: distant objects and the background, too small or too far for
  probes, have per-pixel light from the first frame on.

**As built** (`rhea/planes.h`, wired into `Realtime::finish` and `absorbRest`; RESULTS.md section 20). A pixel of a camera
move's frame takes phase 1 from the first layer that holds for it, front, then slanted, then back, each judged by the
frame's own depths:

- **The front hyperplane:** as before (trusted and verified).
- **The slanted planes** (`PlanarLayer`): the frame's probes joined along the front triangulation's edges where their
  normals agree within 3 degrees and each lies on the other's plane (within the tolerance times its depth); a region of
  three probes or more is triangulated in its own plane's coordinates (two axes in the plane), its triangles kept to
  sides of at most 4 cells (a region's triangulation spans its convex hull, whose long sides cross what the region does
  not hold), drawn into the picture nearest first. A pixel takes its plane where the front triangle failed for its
  geometry (a gap, the verification, none), never where it was refused for its light (a light edge: a plane's larger
  triangle has corners that agree across the shadow), and only where its depths lie on the plane (`planeHolds`). Its light
  is the corners', demodulated, perspective-correct over the plane. None for spherical, fisheye and dome cameras (a
  plane does not lift to a plane). Its light counts for a quarter of the probes' (`planarWeight`): against the
  reference it was 2 to 3 times better than the pixels' own samples, and on Sponza 4 to 22% bright in some frames.
- **The back plane** (`BackPlane`): camera resolution, a pixel each where the picture met one surface (its nearest and
  farthest depths within twice the tolerance): the light its surface reflects (the beauty less the emission output: a
  light seen in front of a wall has no depth of its own, and kept as the wall's it went with the wall on a move, a
  white blob where the light no longer was), not demodulated (glossy light divided by a dark colour and multiplied by
  another came back 2 to 3 times too bright, and the frame at rest's fine texture beats a move's coarse one), its weight
  the samples behind it. A camera move's frame looks it up from its own depths (`gather`): each pixel's point found
  where it lay in the stored view, its light blended bilinearly from the four stored pixels about it that saw that
  surface (lifted depths within reach), with the pixel's own emission added; the first version lifted each stored point
  to the pixel it landed in, its texture and edges up to half a pixel off, and its light was half as good. The frame's
  samples then fold into what it found (faded by 0.95 for the move), and XPU2's frame at rest folds its samples into the
  same camera's: the back plane gathers samples over the frames as the probes do. Weight: its samples, at most m0.
- **Fewer probes:** a cell any layer holds asks for no new probe (`quietNeed`), the start of the user's culling question
  (section 24): the planes take over where the front triangulation would have asked for more probes.

The CPU's part grows by the planes (about 20 ms a frame on the test scene at 320 x 240): on a scene whose moves come 0.3
s apart that is XPU2's samples given up; on Sponza (4 s) nothing. The perspective and orthographic cameras find a
pixel's point from its depth without a camera ray.

## 26. Drags (2026-11-21)

The user: "right now on camera drag, xpu2 realtime sometimes fails and falls back to XPU. Rhea just doesn't update fast
enough even on simple scenes".

**The fallback** was a crash of Rhea's: the back plane's store read its prior light through a null pointer where there
was none (XPU2's first frame of a scene, or the first after an edit, run to its end before any camera move), and the
session ended (0xC0000005 reading 0x30); the kit then renders the preview with MoonRay XPU. The harness had never let
such a frame end (each test's first move stopped it); a drag begun from a picture at rest does.

**Too slow.** A frame of Rhea's is shown only once it has landed: on the test scene 0.2 s at 640 x 360 and 1.15 s at
1280 x 720 (22,000 probes at 8-pixel cells), while the kit sends a drag's steps about 60 ms apart (panel.py's timer), so
during a drag no frame of Rhea's was ever shown; a step's first picture came 2.5 to 5 times later than XPU2's alone.
Three changes:

- **The warp** (`Realtime::warpTo`): each camera move first shows the last picture moved into the new view, each pixel
  lifted by its own depth output and the nearest kept, the holes a move opens filled from the farthest neighbour (what
  lay behind), its outputs moved with it and its depth outputs the new view's (so that it can be moved again). No GPU
  work: 17 to 23 ms at 640 x 360, 64 to 75 ms at 1280 x 720. Not for spherical, fisheye and dome cameras (their lift is a
  search a pixel). XPU2's pictures of the move fold into it (`mergeWarp`) where their depths hold its points, the warp
  counting as 8 samples (a filled hole as 2) and fading as XPU2's frame goes on. A frame a move stops gives no picture
  of its own: the session keeps the last one it published.
- **No frame of Rhea's while dragging:** a move that comes before Rhea's last frame would have landed (or whose frame
  the move stopped) goes to XPU2's frame at once, with the warp; the probes and the back plane still learn from XPU2's
  frames. Rhea's own frame stays for moves far enough apart that it lands (Sponza's).
- **The drag's next step looked for before the GPU** (`dragHold`, 80 ms): within a drag (Rhea's frame for the last move
  stopped by this one, until XPU2's frame ends or runs longer than Rhea's would; or a move begun within 0.15 s of the
  last) the warp is shown and the next step waited for a moment; when it comes, nothing of the GPU's has begun, where a
  frame begun took 0.2 s to stop at 720p. Steps then go through every 80 ms at 640 x 360 and at 1280 x 720 alike (the
  kit's 60 ms and the session's own), each with its picture 10 ms (640 x 360) or 37 ms (720p) after it. A move on its own
  goes to the GPU at once: held, the test scene's moves 0.33 s apart lost a quarter of XPU2's time and doubled their
  error. The time between moves alone does not tell a drag: once one step goes to the GPU its stop spaces the next
  past any threshold, and the drag stays slow (0.22 s a step at 720p).
- **Probe cells by the picture's size** (`cellsByPicture`): the cell grows with the square root of the pixels over 320 x
  240's, so 1,100 probes at 1280 x 720 where there had been 22,000 (placing them 0.06 s, not 0.12).
- **No copies of the picture:** the warp's picture and the last one published are Realtime's own vectors, swapped, not
  copied (70 MB a picture at 720p with its outputs).

**Pruning** (the user's culling question; `ProbeField::prune`): after a move's frame, a probe whose neighbours all lie on
its plane (its star closed) goes dormant where their light, fitted linearly over the picture, gives its own within its
noise (twice the standard error from the spread of the lights it took), never past 10% nor short of 3%; its neighbours
wait for the next frame. A dormant probe takes no samples and no place in the triangulation but holds its cell (no new
probe there), and wakes where its cell's verification fails or the reconstruction at its point departs from its light.
On the test scene it puts 130 to 250 probes to sleep a frame, on Sponza 0 to 12 (its probes' light too noisy to judge);
the pictures are the same with it and without (RESULTS.md section 21): at these sizes the probes' samples are a few
thousand of a frame's hundreds of thousands, so it saves little yet.

**Rhea's own frame, cheaper** (a separate move's: drags take none). At 1280 x 720 it had taken 0.73 to 0.82 s (0.1 s
placing probes, 0.35 s of the GPU's, 0.32 s of the CPU's after), now 0.53 s; on Sponza 3.1 s, now 2.0:

- the CPU's passes over the pixels a row at a time on the field's threads (the outputs read, the verification a cell
  row a task, the layers, the reflected light, the picture), where they had been one thread's;
- the sums since the camera moved kept from move to move (written by the first frame, not allocated and zeroed: 200 MB
  a move at 720p), the outputs kept as the frame's own floats, not summed in doubles and divided again;
- the gather tiles' order by a counting sort (samples a pixel are small numbers), not n log n over every pixel;
- one sample a pixel where the probes' triangle holds (`trustedSpp`, two before): 0.95 million samples, not 1.7, at
  720p; on Sponza 46,000, not 62,000, and the frame landing a second sooner gave XPU2's frame after it the time.

**The kit on Modo's thread** (XPU2 RT's drags in Modo, `tools/probe_rhea_drag.py`): each step's render asked for took
45 ms of Modo's thread, a third of it finding the kit's folder again and again (395 path resolutions in 44 ticks: the
kit's mark, `runtime.json`, looked for at every Preferences made where the kit has none, as the personal kit has none;
XPU2's runtime looked for at every tick). Both are now found once (`native.kit_root`, `installation_id`,
`xpu2_available`): a kit is installed with Modo closed.

## 27. The geometry cache for realtime (2026-11-21)

The user: "there should be a geometry cache so that realtime is improved". XPU2 had one (`cpu_scene.h`: a tessellated
mesh kept on disk in the Cache folder's `xpu2-geometry`, by a key of what shaped it), for displaced meshes and plain ones.
Modo's realtime preview kept almost none of a scene's subdivision surfaces: 9Spheres' nine meshes were tessellated again
at every start, one kept. Two rules had left them out:

- **Subdivision without displacement** was in neither rule (the first asked for displacement, the second refused
  subdivision): now in the first, keyed apart (`subdivision|` and its piece).
- **A dicing camera** refused every mesh: Modo's preview names one wherever the scene's displacement tessellation is
  fixed (`host.py`: the render camera, or the one chosen, held at the dicing frame), and the key held only the render
  camera's frustums. The dicing camera shapes only adaptive tessellation; an adaptive mesh's key now holds its frustums
  too, made by the same function the tessellation takes them from (`dicingFrustums`), so that the two cannot differ.

The pictures with the cache, without it, and from it (a dicing camera added to the exported 9Spheres, 16 samples,
640 x 480) are the same to the bit. In Modo the second start reuses 8 of 9 meshes (the first had saved 9), tessellation
1.6 -> 0.5 s; one displaced mesh is saved again at every start (something in its key changes between runs: not looked
into). `XPU2_SESSION_GEOMETRY_CACHE_SAY=1` says each mesh's way past the cache.

Not done: the GPU programs (3.5 to 4.4 s of a start in Modo, after the scene's preparation) cannot be made beside it on
another thread: their lane must be made by the thread that feeds it (made so, the session fell back: "GPU context
requires feeder owner"); the preparation would have to move instead, and MoonRay's tessellation takes few threads it did
not start.

## 28. Drag pictures as a mesh gradient (2026-11-21)

The user's video of a drag (a glass dragon over a sea, Denoised Beauty): the first phase "does look visually awful". The
pictures showed three faults of the warp (section 26), each its own:

- **The environment went black.** A pixel that met nothing has no depth, and the warp moved pixels by their depths.
- **Each warp was the next one's source.** A drag's steps come faster than XPU2's frame stops, so nearly every picture
  of a drag was a warp of a warp: what one step lost (the environment, what a move uncovered, a hole the three passes
  left) the next could not move again, and a long drag ended black with a few strips of XPU2's samples.
- **Blocks and facets.** Pixels moved one by one leave gaps where a surface grows; the farthest neighbour filled them, a
  warp of that again, into a mosaic. And the session's denoiser took the pixels XPU2 had not sampled yet as gaps and
  filled them from XPU2's few samples around (`realtimePicture`), throwing the warp away there.

The user's direction: the blotches "could be even more sparse, and look more like a mesh gradient, since we are now
accepting that textures should be represented as averaged colors on first phase"; "color interpolations between the
direct light information, and the thresholds between elevations determine how much a color should interpolate to its
next point" - "cleaner first phases, approximating vector mesh gradients".

So the warp now moves a mesh (`mesh_warp.h`), made once from the picture it moves:

- **Points, sparse where the picture is smooth.** Cells of 16 pixels at 1280 x 720 (scaled with the picture, a power of
  two), halved wherever the depth jumps inside, down to a pixel. A jump between neighbours: the lifted depth (inverse
  depth: affine across a plane, so a grazing floor is no jump) off the line through the two pixels before it by more
  than `warpJump` (3%) of itself, from both sides; the environment against a surface, always.
- **Each point the colour around it, over its own surface.** As far as its coarsest cell reaches (half a 16-pixel cell
  for a coarse corner, a pixel or two at an edge), tent-weighted; a neighbour counts fully while its depth is within
  `warpSoft` (1%) of the point's plane, less and less up to `warpJump`, not at all past it: the elevations' threshold
  deciding how far a colour reaches toward the next point. Textures come out averaged, as phase 1 has them.
- **Drawn as triangles into the new view**, the colours interpolated across them (Gouraud: a mesh gradient), the
  nearest surface winning. The environment's points move as directions (far past the scene), so a turn moves the sky.
- **What no triangle covers** (what lay behind a surface, past the picture's edges, a crack between cells of two sizes)
  is filled from the farthest around it, coarse to fine (push-pull: each coarser level keeps the farthest of its four and
  the mean colour of those as far; then a pixel still empty takes the coarser level's colour bilinearly).

The warp's source is the last picture rendered: Rhea's frame, or XPU2's picture once its samples reach 95% of the pixels
(`warpKeepCoverage`); a warp, or a picture mostly made of one, never is (`warpChain` off). A pixel the warp shows in a
picture of XPU2's is no gap to the denoiser. In the Beauty view Rhea's frame and XPU2's pictures folded into Rhea's or
into the warp, while its frame is short of half, are denoised as pictures with gaps are (`XPU2_SESSION_RHEA_DENOISE`);
the warp, already smooth, and XPU2's frame at rest are shown as they are.

Switches: `XPU2_SESSION_RHEA_WARP_MESH` (0: pixel by pixel), `_WARP_CELL`, `_WARP_JUMP`, `_WARP_SOFT`, `_WARP_CHAIN`
(1: as before), `_DENOISE`, `_DENOISE_BELOW`.

## 29. The completion fade (2026-11-22)

The user's design: "whatever is completed in XPU2 shading, that finished buffer should fade in, not show gpu/cpu
squares, but composite into the first phase", with five conditions - a completion signal (finished means a region has
its target samples, not some samples; pixels with few stay as the preview), a feathered fade of 100 to 200 ms, a move
invalidating what the old camera had in flight, the regions where the warp is worst finished first, and a decision on
denoising. And: if the warp with the completion fade looks good, most of sections 3, 8, 18 and 25 (the probes, their
indexer, their persistence, the planes) are off the critical path - the ablation's question.

What XPU2 gave: its realtime frame lays its samples over the whole picture in rounds (the seed, 16 to 19 samples a
pixel in four or five passes, then adaptive passes over the tiles still noisy), and with no noise target no tile drops
out early. "Finished" was the frame's end, everywhere at once; the squares were the devices' cells landing a pass at
different times.

- **Regions** (`Realtime::warpRegions`): the picture's 64-pixel cells (the work grid's) ranked by the warp's doubt over them
  - a pixel the fill made counts 1, an edge or a mixed pixel 0.5, the detail the mesh's average took away (the taps'
  luminance spread over their mean) up to 0.5 - and split into regions of as many cells each (a sixth of the cells, 4 to
  16 regions; `XPU2_SESSION_RHEA_REGIONS`).
- **XPU2's regional seed** (`RenderOptions::regionalBatch`, `async_render.h`): the seed's passes become one pass a region,
  each the whole seed over that region's tiles, in order, at most two out at once; the adaptive passes after them as
  ever. A region is finished when its pass retires - every sample of its seed in the film (`Renderer::retiredPasses`).
  Host code only: the GPU programs are unchanged.
- **The fade** (the session): a finished region's alpha rises over `fadeSeconds` (0.15 s, smoothstep;
  `XPU2_SESSION_RHEA_FADE_SECONDS`); the tiles' alphas blurred twice by [1 2 1] each way and spread bilinearly, an
  unfinished tile's pixels held at 0 (the feather goes inward: no unfinished sample shows). Pictures every 40 ms while
  the frame runs, every 30 ms after it until the last region has faded in. XPU2's picture over the warp by alpha
  (`Realtime::completeWarp`); the end is XPU2's own picture, exactly.
- **A move** stops the frame (its regions and samples in flight with it); the fade is the frame's own; a picture is the
  next warp's source only once 95% of it is wholly XPU2's.
- **Denoising**: in the Beauty view the finished regions fade in raw, as XPU2 RT shows them (denoised while fading and
  raw after, they would pop noisy); in Denoised Beauty the whole picture, warp and regions, goes through the denoiser.

`XPU2_SESSION_RHEA_COMPLETION=0`: XPU2's samples blended into the warp as they come (mergeWarp, section 28). The
completion fade applies where the warp is the picture's first phase (no frame of Rhea's: a drag, or no probes).

**In Modo (2026-11-22).** The user tried it: "probes off is better and the fade works, though the fade in should know
when XPU2's grid has been fully loaded so the fade is seamless" - then, with that, "there's no fade". Three things:

- **Once the grid is in** (`XPU2_SESSION_RHEA_FADE_WHOLE`, on): one fade over the whole picture once every region's
  seed is in, from the warp to XPU2's picture, 0.2 s. Probes are off by default (`XPU2_SESSION_RHEA_PROBES=1` brings
  them back).
- **A camera move that makes the plan again** (the user's dragon over a displaced sea: "not the camera alone: geometry
  tessellated for the camera") had reset Rhea as any edit does, the warp's last picture with it: no warp, so no first
  phase to fade from. The session now knows the edit was the camera's alone (`Scene::cameraEdit`) and forgets only the
  probes (`Realtime::resetProbes`); Rhea's own reset on other geometry keeps the picture too.
- **The fade's own clock.** XPU2 hands a picture over every 0.25 to 0.4 s on that scene, and a 0.2 s fade went from one
  to the next in a step. Once the grid is in, a thread shows the blend every 30 ms, XPU2's pictures only updating the
  latest it blends into. In Denoised Beauty the denoiser (one picture in about 0.25 s with XPU2's frame on the card) ran
  at each step: XPU2's picture is now denoised once, held (`Picture::hold`), and the denoised picture on screen
  cross-faded into it every 30 ms. On the dragon (640 x 360): Beauty 4 pictures across the fade, Denoised Beauty 6
  (relMSE to the frame's end 0.129, 0.112, 0.073, 0.035, 0.011, 0.002), where one picture had stood between before.

**Pictures of whole passes (2026-11-22).** "There shouldn't be black grid XPU2 iterations, that should be hidden until
they're done and there's another fade." XPU2 hands over a picture only once every pass sent out has completed
(`RenderOptions::passPictures`, `Renderer::picturedPasses`): the next adaptive pass waits until the picture of the ones
before it is taken, so none shows a pass part way. The first (the seed's regions all in) fades in over the warp, each
later one over the one before, on the fades' own thread; Denoised Beauty denoises each once and cross-fades. On the
dragon (640 x 360) a frame faded four times, nothing between. `XPU2_SESSION_RHEA_PASS_PICTURES=0`: XPU2's pictures as
they come.

**The release.** "The fade should also occur on mouse release as well when XPU2 realtime takes over." Modo tells of a
viewport's camera once the mouse is let go: the kit sends the camera where it already stands. That edit changed nothing,
but the session took it as a new scene and Rhea's picture went with it. An edit that changes no object now leaves the
scene as it was (`Scene::apply`); a frame with no move after one stopped short (`rheaUnfinished`) keeps the warp, its fade
starting from what is on screen (`Realtime::screenAsWarp`), and a phase one the release stopped part way is finished
first ("rhea should finish its phase one then have xpu2 gracefully follow").

## 30. Drag pictures from colours on the surfaces (2026-11-22)

The user: "currently the color interpolations are screen-space, but it would be better if the interpolations are
object-space, so that there aren't any gaps when the user tries to look behind the model. i'm thinking whichever
projection occurs is done is a radial vignette view, so that the computation is only where the user cares, and the
reprojection gracefully ends outside of this vignette"; and "during drag, the reconstructions should be streamed. the
user should be able to see the radial topology updating in realtime". `rhea/object_warp.h`:

- **The store** (`ObjectStore`): every picture kept as the warp's source adds its colours to cubes on the surfaces it
  shows (trace space, a sparse hash; a finest cube three of that picture's pixels wide, and three coarser sizes; kept by
  the side the surface faces), weighted by the pixel's samples. Positions from the picture's own depth output: no rays.
  Silhouette pixels (the environment, or two depths, in them) add nothing; the environment's pixels go to a map of
  directions. Pictures from other views add to it, so the far side of the model is there once a picture has shown it.
- **A move's picture** (`ObjectWarp`): the CPU lane's scene (Embree) gives each ray its first hit on the meshes as they
  are, coloured from the store (trilinear between cubes, coarser where the finer have none). A grid of rays, its stride
  from a budget inside the vignette (60,000), interpolated where its four corners are one smooth surface; a cell that is
  not takes a ray a pixel. Outside the vignette (75% of the half diagonal, its soft edge a quarter of that) a grid four
  times sparser, its light falling to 0.6 at the corners. What the store has nothing for is filled from the grid around
  it, its doubt 1 (the completion fade's regions take it first).
- **Streamed**: the coarse grid's picture first, then the fine grid in three rings of equal area from the centre out,
  each shown as it lands; the next move stops it.
- On the dragon (640 x 360): the picture in 0.061 s, the first in 0.009 s, 65,857 rays (15,368 at edges, every two pixels
  in the vignette), 12% of them unknown to the store. The coarse picture and the vignette's outside show the coarse grid's
  steps at silhouettes, and the sea seen at a grazing angle comes out in blocks (cubes sized by the old view's pixels).
- `XPU2_SESSION_RHEA_OBJECT_SPACE=0`: the mesh gradient. `XPU2_SESSION_RHEA_VIGNETTE` (0: the whole picture),
  `_VIGNETTE_SOFT`, `_VIGNETTE_DIM`, `_RAYS`, `_RINGS`, `_STORE_SCALE`.

**Grazing surfaces, finer cells, a soft coarse grid, the albedo composite (2026-11-22).** Build 45 showed the coarse
grid's steps along silhouettes, and the sea seen toward the horizon in blocks: a pixel there is far longer along the
surface than across it, and cubes sized by its width left gaps between them. A cube's size now follows a pixel's length
along its surface (one over the cosine between the normal and the ray, at most 8: `_GRAZING`), at the store and at the
lookup; the finest cube is two pixels wide, not three; the coarse grid's picture is blurred over about its step. On the
dragon (640 x 360) the store then knew every ray (12% unknown before), the picture took 0.077 s (first 0.020 s), and it
came close to XPU2's own: the sea's waves, the scales, clean silhouettes.
The user's composite ("re-use those buffers, like z-depth and albedo, with a composite to get cleaner first phases"):
`XPU2_SESSION_RHEA_STORE_ALBEDO=1` keeps each cube's colour, albedo and emission, and the albedo again in cubes half as
wide; a hit's colour is the fine albedo times the cube's light (colour less emission, over albedo), emission added back.
On the dragon it looked all but the same as the colours alone and took 0.196 s (first picture 0.075 s), the store three
times the cells: off by default, to try where textures carry the detail.
