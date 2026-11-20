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
  across edits (the session-only cache), the cameras of section 19.
