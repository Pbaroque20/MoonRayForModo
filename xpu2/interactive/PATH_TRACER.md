# XPU2: MoonRay's path tracer, then its shader library

The asynchronous renderer's integrator (`async_integrator.h`) began as the prototype's: a camera hit, its emission,
and one cosine-sampled ray to a constant environment. MoonRay's shader library needs MoonRay's path tracer under it:
its lights, light and BSDF sampling combined by multiple importance sampling, bounces with per-lobe depth limits and
Russian roulette. This is the plan and the reference for that port. The source is the MoonRay the reference runtime
was built from (`upstream/openmoonray/moonray`, with its Modo changes); file names below are relative to
`moonray/lib/rendering`.

## MoonRay's estimator (pbr/integrator)

XPU mode runs the bundled ISPC integrator, with the same structure as the scalar one
(`PathIntegratorMultiSampler.cc`, `PathIntegratorUtil.cc`). At every surface hit:

- **Self-emission**: `radiance += throughput × bsdf.selfEmission` at every depth.
- **Which lobes continue** (`PathIntegrator.cc`, recurse): if `ray depth < max_depth`, a lobe's indirect ray is
  allowed when its type's counter is below `max_diffuse_depth`, `max_glossy_depth` or `max_mirror_depth` (hair:
  `max_hair_depth`). A child vertex adds one to the counter of its lobe's type, one to `nonMirrorDepth` unless the lobe
  is a mirror, and one to the ray depth.
- **Sample counts**: at `nonMirrorDepth == 0` each lobe takes `bsdf_samples²` samples and each light
  `light_samples²` (the scene variables are square roots: `mLightSamples = lightSamplesSqrt²`, PathIntegrator.cc);
  deeper, one each. A first hit with several samples splits the path. MoonRay's defaults (2 and 2) are four of each.
- **BSDF samples** (`drawBsdfSamples`, `integrateBsdfSample`), for lobe i with n_i samples: draw wi, f, pdf;
  `pt = T f / (n_i pdf)`. The ray is tested against every light of the light set (not only the nearest): one hit
  light is chosen uniformly by reservoir and its radiance multiplied by the number hit (`LightSet::intersect`). Its
  direct contribution is `Li pt w`, with `w = powerHeuristic(n_i pdf, n_l pdf_light)`, or 1 for a mirror lobe; it
  counts only if a shadow ray to the light's distance is unoccluded. `tIndirect = pt` when the lobe continues.
- **Light samples** (`drawLightSamples`, `integrateLightSetSample`), per light with n_l samples: the light draws a
  point from 3 random numbers (`Light::sample`), `eval` gives Li and its solid-angle pdf; `factor = T Li / (n_l pdf)`;
  for every lobe k that matches the side of wi: `t_k = factor f_k powerHeuristic(n_l pdf, n_k pdf_k)`; the sample
  adds `Σ t_k` if a shadow ray to the light is unoccluded. MIS weights are per lobe, not over the mixture.
- **Russian roulette**, only past `nonMirrorDepth > 0` with `russian_roulette_threshold > 0`: a sample whose
  luminance (BSDF: the larger of direct and indirect) is below the threshold survives with probability
  `lum / threshold` and is scaled by its inverse.
- **Sample clamping** (`smartClamp`) past `sample_clamping_depth`, with `sample_clamping_value` divided by the
  BSDF sample count (`bsdf_samples` squared), as `PathIntegrator::initPrimaryRay` sets the subpixel's clamp.
- **Misses** add nothing: lights, the environment too, are reached through BSDF samples that hit them. Camera rays see
  lights only with `lights_visible_in_camera`.
- **Shadow rays** start at the hit offset by the ray epsilon (`modoShadowOrigin`) and end just short of the light
  (`distance × sHitEpsilonEnd`). Lights do not occlude each other.

## Lights (pbr/light)

Radiance is `color × intensity × 2^exposure`, divided by the area when `normalized` (`LightUtil.h`,
`computeLightRadiance`). Every light can `sample(P, N, r[3])` (direction, distance, light normal), `eval` (Li and
the solid-angle pdf) and `intersect(P, wi)` (for BSDF samples). Area pdfs become solid-angle pdfs by `d² / cos`
(`areaToSolidAngleScale`). Phase 1 admits: `EnvLight` (constant colour), `RectLight`, `DiskLight`, `SphereLight`,
`SpotLight` and `DistantLight`, each without image maps, light filters or clear radius; `CylinderLight`, `MeshLight`,
`PortalLight`, textured lights and light filters follow. Anything not admitted renders by fallback, as now.

## XPU2's design

- **Shared code.** Lights (`async_lights.h`) and the integrator are `X2_HD`: the CPU lane and the GPU lane run the
  same estimator, operation for operation, so the device split, the parity of identities and the audits hold.
- **Scene preparation** (`cpu_scene.h`) reads the lights of the layer's light sets into flat records in render space
  (transforms, radiance, sizes, sidedness, spread, visibility flags), gives each mesh a mask of its light set's lights
  (up to 32), and admits `max_depth`, `max_diffuse_depth`, `max_glossy_depth`, `max_mirror_depth`, `bsdf_samples`,
  `light_samples`, `russian_roulette_threshold` and `lights_visible_in_camera`.
- **Random numbers.** Camera dimensions 0-1 and the first BSDF sample (16-17) keep their Sobol nets; every other
  dimension comes from the per-bounce Philox stream (`sample::next`) in a fixed order: per vertex, the BSDF samples,
  their light choices, the light samples (3 each), then Russian roulette.
- **Splitting.** A first hit with several samples continues each as its own branch, depth first, on a small stack.
- **Shadow rays** get a finite end (`visible(origin, direction, distance)`).

## Curves and hair

- **Curves** (`curve_core.h`, `curve_embree.h`): `RdlCurveGeometry` (linear, Bézier and B-spline; ray-facing or
  round) and the plugin's `ModoFurGeometry` become plan meshes whose spans take the place of triangles, numbered as
  MoonRay's `LineSegments`, `BezierSpanChains` and `BSpline` number them. Both lanes run MoonRay XPU's own curve
  programs (`OptixGPUPrograms.cu`'s `__intersection__` programs and the Embree 4 code MoonRay ported for round
  curves, vendored by `vendor_curves.py`): the GPU from a custom-primitive hit group, the CPU from an Embree user
  geometry. A hit reports only its span; each lane works the hit out again from it, as for triangles. As in XPU,
  Bézier curves are drawn flat whatever their subtype; normal-oriented curves and Bézier radii per span end are
  refused.
- **The hit** (`curveState`): `LineSegments::postIntersect` and `CubicSpline::postIntersect`: St from the "st" or
  "uv" primitive attribute, else the span's share of its curve; dPds the tangent; N faces the ray (a round B-spline:
  its geometric normal); a linear curve's dNdt is its dPdt. Primitive attributes interpolate per curve, per point
  (linear ends or the cubic basis) or per span end.
- **Rays from a curve** start at the hit and skip MoonRay's epsilon hint, 1.5 × the radius there: shadow rays from
  it (and reach at least twice it), bounces from it over the cosine to Ng, presence continuations from it.
- **Hair** (`shade_hair.h`): `HairMaterial_v3` and `HairDiffuseMaterial` through DwaBase (`DWABASE_addHairLobes`):
  the one-sampler lobe or the separate R, TT, TRT and TRRT lobes (the latter three under R's hair attenuator, as
  MoonRay places them), glints from each strand's `scatter_tag`, and hair diffuse, which also replaces the hair on a
  caustic path the material does not cast. Subsurface scattering on curves, hair in a layer and `HairLayerMaterial`
  are refused.
- **Hair toon** (`HairToonMaterial`): hair diffuse at its weight and up to three toon specular sets, each MoonRay's
  surface toon specular or its hair toon specular (`HairToonSpecularBsdfLobe`: a hair R lobe's value through the
  ramp by its luminance, sampled by a second R lobe at the indirect roughness when indirect reflections are on).

## Glitter

`shade_glitter.h` is moonshine's `Glitter.ispc` (the vector path XPU runs) for DwaBase's glitter: the shading point
in object space or in reference space (`ref_P`, its st derivatives and `ref_N`, with the deformation compensation),
the Worley flake search over glitter's static noise tables (built on the host with MoonRay's own generator,
`glitterTables`), up to four macro flakes as glitter GGX lobes, the rest of the footprint's flakes as one stochastic
flakes lobe (`shade_flakes.h`, `BsdfStochasticFlakes.ispc`) blended toward a GGX lobe of their average colour, and
the debug modes. The flakes found are kept as ids in a per-thread scratch, so the lobe reads them back rather than
caching up to 2,000 normals and colours. A mesh without `ref_P` under a reference-space glitter shades as MoonRay's
fatal colour. Flake textures and glitter on both inputs of a layer (the layer's own Glitter object) are refused.

MoonRay's vector mode (and so XPU) cannot render glitter on Windows: `StochasticFlakesBsdfLobe_eval` keeps two
reflection caches of 2,000 varying entries on the stack (1.4 MB at eight lanes) and overflows a worker thread's stack
(exit 0xC00000FD). Scalar mode renders it; glitter's fixtures are measured against scalar MoonRay.

## Volumes

`volume_core.h` and the volume part of `async_integrator.h` are MoonRay's `PathIntegratorVolume.cc` for BaseVolumes
bound to closed meshes, with or without a surface material (a mesh with no material bounds a volume alone):

- A ray's crossings of the volume meshes along its whole length (`collectVolumeIntervals`: entry or exit by the
  triangle's geometric normal, the outermost entry and exit of each volume kept counting back from the far end), so
  the regions it starts in are known without tracking them along the path. The GPU keeps volume meshes in the same
  instance tree under visibility 2 (surfaces 1); the CPU keeps them in an Embree scene of their own.
- Homogeneous volumes only (no attribute bound): one step a stretch of the ray (`decoupledRayMarching`), with
  BaseVolume's ramps over the stretch's length; overlapping volumes summed, the thickest taken, or one picked by its
  extinction (`volume_overlap_mode`).
- Single scattering per light (`integrateVolumeScatteringDirect`): equi-angular samples about a point on bounded
  lights and distance samples, with MIS; the light sample's shadow ray goes through the volumes' transmittance. With
  `max_volume_depth` above one, Wrenninge's multiple scattering approximation with the attenuation, contribution and
  phase attenuation factors. Surface light samples and lights met by BSDF samples go through the transmittance too.
- The volume depth goes up by one at every BSDF bounce as well as after a ray's own scattering (MoonRay's
  multi-sampler sets a child's to its parent's plus one), so with the default `max_volume_depth` of one only camera
  rays gather in-scattered light; later rays only take the transmittance.
- Refused: heterogeneous volumes (bound attributes; MoonRay bakes them), emissive volumes, other volume shaders
  (VDB, amorphous), `volume_indirect_samples` above zero, more than 32 volumes.

## Displacement

`mesh_displacement.h` is MoonRay's `PolyMesh::tessellate` and `displaceMesh` for triangle meshes, done on the host
when the scene is prepared; the renderers get an ordinary mesh:

- Uniform tessellation to `mesh_resolution` (each edge cut into that many pieces; 1 or less displaces the mesh as it
  is): `TriMesh::generateIndexBufferAndSurfaceSamples` with `MeshTessellationUtil`'s vertex lookups and ring
  stitching, in MoonRay's order, so each vertex is displaced from the same face as MoonRay's. Each quad becomes the
  two triangles Embree splits it into, with its corners' texture coordinates and primitive attributes taken from
  its base face.
- Each vertex displaced once, by the state of the first face that has it (its geometric normal, its texture
  coordinates' partials, half its corners' differences as the texture footprint, the primitive attributes at its
  place), through a NormalDisplacement or a tangent-space VectorDisplacement whose maps run on the host.
- Smooth shading normals over the displaced faces (`PolyMeshCalcNv`); the mesh's own normals are discarded. A mesh
  with `smooth_normal` and no normals of its own gets the same smoothing undisplaced.
- Refused: adaptive tessellation (`adaptive_error` above zero needs the camera's frustum), subdivision meshes,
  object-space VectorDisplacement, CombineDisplacement and SwitchDisplacement, `mesh_resolution` above 64.

## Maps

`shade_mapnodes.h` runs a material's maps as a program (`map_admission.h` builds it): ImageMap (with UDIM sets),
UsdUVTexture, UsdTransform2d and UsdPrimvarReader, AttributeMap, the projections (ProjectPlanarMap,
ProjectSphericalMap, ProjectCylindricalMap, ProjectTriplanarMap_v2 with its random per-face transforms,
ProjectCameraMap_v2 from a perspective or orthographic camera), UVTransformMap, NoiseMap_v2, NoiseWorleyMap_v2 and
_v3, GradientMap, RampMap, the colour corrects (ColorCorrect, Contrast, GainOffset, Gamma, Hsv, HueShift, Saturation,
TMI and Legacy), BlendMap, ClampMap, RemapMap, OpMap, the conversions, Switch maps, TwoSidedMap and LODMap; the normal
maps ImageNormalMap, ProjectPlanarNormalMap, ProjectTriplanarNormalMap_v2, ProjectCameraNormalMap, CombineNormalMap,
SwitchNormalMap and RgbToNormalMap; and the kit's ModoTextureMap and ModoNormalMap. Projections read P and N
(reference space, ref_P and ref_N, is refused); textures must be complete stored mip pyramids. Not ported:
ProjectTriplanarUdimMap, DistortNormalMap, RandomNormalMap, the hair and toon maps, RandomMap, CurvatureMap,
DirectionalMap, WireframeMap; nor HairLayerMaterial and HairColorCorrectMaterial among the materials.

## Gates

Each light type and depth setting gets a fixture: the gallery geometry with the light added through an override, as
the adaptive benchmark does. Against MoonRay XPU at 1024 samples: maximum pixel 0.08, maximum 8×8 block mean 0.015,
alpha 0.015. At 64 samples, relative MSE at or below XPU's own. The existing uniform and adaptive benchmarks keep
passing.

## Phases

1. Path tracer: lights, MIS, bounces, Russian roulette, splitting. Lambert only.
2. BSDF lobes and `BsdfBuilder` (shading/bsdf): Cook-Torrance/GGX with energy compensation, transmission, Oren-Nayar,
   Ward, iridescence, fabric and velvet, clearcoat layering, flakes, Fresnel; ray differentials through lobes
   (`scatterAndScale`) and roughness clamping.
3. Materials: DwaBase and its family, the combinators, UsdPreviewSurface.
4. Maps and normal maps.
5. Subsurface, hair, glitter, toon, volumes, displacement.
