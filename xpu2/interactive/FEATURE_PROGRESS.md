# XPU2 feature progress (kit test build)

Every MoonRay feature the Modo kit can produce, ported to XPU2 and checked against MoonRay (CPU XPU2 at 256 samples
a pixel against MoonRay vector mode, block error and mean ratio against MoonRay's own seed-to-seed noise), then on the
GPU in the final build. A scene with anything not listed as done still renders, by fallback to MoonRay.

## Lights

| Feature | State | Check |
|---|---|---|
| Rect, disk, sphere, spot, distant, env lights | done | earlier rounds |
| Light textures (all mappings, filters, mips, colour controls, transforms) | done | rect, disk, sphere, spot, distant, env cases within noise; circular-mapped textures 0.3% off vector mode at 256 spp, which converges to scalar mode (= XPU2) as samples grow (1.2% at 36 spp) |
| Spread (rect, disk) | done | within noise |
| Camera-visible lights, spot black level | done | |
| Cylinder light (with texture) | done | pending check |
| Mesh light (QuadMesh, TriMesh, parts) | done | quads within noise; triangles: MoonRay's in-place ear clipping reproduced (pending check) |
| Mesh light map shader | fallback | the kit never writes one |
| Clear radius, clear radius falloff | done | radius within noise; falloff 0.25% (mirror reflection of the light), under study |
| Min and max shadow distance | done | within noise |
| Two-sided sphere light | done | pending check |
| Portal light | done | pending check |
| More than 32 lights (light sets as bitsets) | done | pending check (48 lights) |
| Adaptive light sampling (light tree) | done | pending check (48 lights) |
| The scene's lights are those of the layer's light sets (Scene::updateLightList) | done | an environment light in no set is not seen (as MoonRay) |
| Light culling (Light::canIlluminate, computeActiveLights), culled lights left out of the tree's choice | done | visibility AOVs within noise |
| Light visibility flags, presence shadows | done | within noise |
| Light filters, ray termination, shadow linking, lobe light sets | todo | |

## Surfaces and shading

| Feature | State |
|---|---|
| MoonRay's TriMesh ear clipping, in place (its corrupted triangles) | done, pending check |
| Partial presence, presence continuation, presence shadows, cutouts | done, within noise |
| Quad meshes without UVs: MoonRay's per-quad default ST (getQuadST), st/uv primitive attributes | done, within noise |
| Geometry outside the layer is not rendered (MoonRay renders the layer's geometry) | done |
| A hit missing an attribute its shading requires: the fatal colour alone (no AOV, LPE or Cryptomatte) | done |
| Normalized diffusion and dipole subsurface | done; 0.3-0.6% bright on a DwaBase ball (SS.albedo 1.0 x albedo, MoonRay 0.997 x), open |
| Modo switches: USD specular | done |
| Modo switches: opaque alpha, transmission roughness, toon terminator, fog alpha | todo |

## Outputs

| Feature | State |
|---|---|
| Beauty, alpha | done |
| Files, parts, channel names and order (the scene's declaration order), compression, DWA level, metadata, windows | done, headers match MoonRay's |
| Depth, state variables (P, Ng, N, St, dPds, dPdt, dSdx, dSdy, dTdx, dTdy, Wp), wireframe, primitive attributes | done, within noise |
| Math filters (average, sum, min, max, closest, force consistent) | done, within noise |
| Material AOVs (albedo, color, emission, matte, roughness, normal, radius, factor, PBR validity, fresnel, state, labels, SS.*) | done, within noise (fresnel.factor: MoonRay writes uninitialized values) |
| Light AOVs: LPEs with aliases, labels (lights, materials, lobes, 'M:'), unoccluded prefix, subsurface <TD> events | done, within noise |
| Visibility AOVs (incl. culled lights and failed samples counted through every lobe, MoonRay's discarded insert) | done, within noise |
| Weight, heat map (time per pixel), beauty aux, alpha aux | done (aux and heat: values follow each renderer's own sampling) |
| Cryptomatte (categories, P0, extras, presence, multi presence, resume data; Modo count-once) | done on the CPU, within noise; GPU written, to compile |
| Display filters (all 18 of MoonRay's, run as MoonRay's own DSOs over XPU2's buffers) | done, within noise (deterministic ones exact) |
| AOV previews (view.txt) and held keys at a stop (beauty, denoiser guides) | done, to check in Modo |
| GPU AOV film (atomics, min/max, closest under a lock, heat) | written, to compile |
| Extra AOVs ('U:' from ExtraAovMap/ListMap, post-scatter) | todo |
| Motion vectors | todo (with motion blur) |
| Deep output, checkpoint and resume | todo |

## MoonRay quirks found (vector mode)

| Quirk | XPU2 |
|---|---|
| Light-sample Russian roulette biases dim bounce light dark (0.1-4%, constant in spp) | not reproduced (tests use russian_roulette_threshold 0); XPU2 = scalar mode |
| A BSDF ray meeting two lights picks one from a non-uniform sequence: 3% dark there (mirror reflecting a light in front of the environment) | not reproduced; XPU2 = scalar mode = exact |
| Visibility misses counted once per lobe (insert's result discarded in accumVisibilityAovsOccluded) | reproduced |
| A camera ray seeing a light past every surface adds nothing to light AOVs (case 1 redeclares lpeStateId) | reproduced |
| Subsurface light samples give unoccluded LPEs the attenuated value and count visibility at any depth | reproduced |
| Random walk rescales its light and visibility AOVs with its radiance (MOONRAY-3352) | reproduced |
| A max filter on a light AOV is unsupported (warned) | as MoonRay |

## Cameras, motion, geometry, volumes, sampling, sessions

| Feature | State |
|---|---|
| Perspective camera: film offsets, pixel aspect, stereo eyes (MoonRay's projection matrices, inverted in floats as MoonRay's) | done, within noise |
| Depth of field: disk, polygon and image bokeh, perspective and orthographic (createDOFRay, modifyForDofOrtho, LensDistribution) | done, mean within 0.1%; lens samples moved from random to Sobol (MoonRay's are stratified), recheck |
| Orthographic camera (its rays' own origins as texture differentials) | done, within noise |
| Spherical camera (legacy, ranges, zoom offsets, inside out) | done, within noise |
| Fisheye camera (all four mappings, three formats; rays outside the field of view add nothing, as vector mode drops them) | done, within noise |
| DomeMaster3D camera (stereo eyes, zenith mode, flips, parallax; MoonRay never reads its interocular map) | done, within noise |
| Bake camera (position map from the mesh's UVs as MoonRay's mesh classes rasterize it, UDIM tiles, uv attribute, normal map, four modes) | written; relative bias now measured in render space, recheck |
| Aperture and region windows (overscan), sub viewport (render region), resolution divisor, texture blur | done, within noise |
| Depth AOV: MoonRay takes the least of the camera depth and -volumeT * ray z (volumeT the largest float without a volume), so rays toward the camera's +z give huge negative depths that sum to -inf | reproduced (volume surface depth itself: with volumes) |
| Camera pixel sample map, medium material | todo |
| Motion blur | todo |
| Subdivision surfaces, displacement on quads and parts | todo |
| VDB volumes, cutout volumes | todo |
| Adaptive sampling: XPU2 takes 27% more samples than MoonRay at target error 10 (aov-adaptive scene) | open |
| Cellular-generation adaptive sampling as default | todo |
| Checkpoint save and resume | todo |
