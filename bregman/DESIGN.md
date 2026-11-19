# Bregman (working name): a two-phase realtime engine on XPU2

*Research note, 2026-11-19. Local branch only. "Bregman" is a placeholder name: rename the folder and this title freely.*

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
- **Phase 1, scan and reconstruction:** new host code (`bregman/`), run on the CPU lane's pool while the frame's GPU
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

The prototype, `bregman_engine.cc` with `bvd.h` (the lift, hyperplanes, Bregman Delaunay triangulation) and `scan.h`
(topology, scan, patch depths), built by `build_bregman.py` against XPU2's headers, runs both phases as XPU2 frames on
the unchanged CPU and GPU lanes: no GPU program change. Its one change to XPU2 is host-side: the sample audit lets a
pixel planned no sample take none (`async_render.h`), which no plan of XPU2's own makes.

Results, pictures and what they say: `RESULTS.md`. In short, on this scene it does not beat XPU2 at equal time (12%
slower without diffuse bounces, about 1.7 times with them); the trusted reconstruction is as good as XPU2 at 36 to 64
samples a pixel and the bias vanishes on average; the losses are sparse-frame overhead on XPU2's grid and, with
indirect light, the noise phase 1 does not touch. Open items are listed there.
