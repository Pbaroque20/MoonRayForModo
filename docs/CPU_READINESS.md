# CPU production-readiness work

This is an implementation and verification checklist, not a compatibility claim.
Unchecked items remain required by the requested CPU work.

## Materials
- [x] Standard reflection lobe, strength/color/roughness and texture controls
- [ ] Full Modo specular/reflection Fresnel parity
- [ ] Layered BSDFs and masks
- [x] MoonShine anisotropy strength with native material properties
- [ ] Anisotropy texture/tangent controls and standard-material parity
- [ ] Subsurface scattering
- [ ] Distance-based glass absorption

## Textures
- [ ] Multiple UV sets per material
- [ ] UV transforms and additional projections
- [ ] UDIMs
- [ ] Broader Shader Tree blending

## Environments
- [ ] Reference-render calibration of orientation, brightness and gradients
- [ ] Environment layering
- [ ] Physical daylight

## Geometry
- [ ] Displacement
- [ ] Subdivision creases
- [ ] Render Cache/evaluated geometry fidelity
- [ ] Replicators
- [ ] Instance material overrides

## Render workflow
- [x] Render regions with full-frame output and scene-owned panel controls
- [ ] Translate Modo's own render-region selection
- [ ] Animation output
- [ ] Motion blur
- [ ] Orthographic cameras
- [x] Perspective depth of field: focus distance, f-stop, blade count/rotation
- [ ] Modo bokeh/iris-bias reference parity
- [ ] Native Render View integration
  - Experimental C++ external-render adapter loads in Modo 16.1v9 and transfers
    progressive images into PView. Geometry/color display, docking and shutdown
    validation remain; PView is distinct from the legacy final Render View.

## Production validation
- [ ] Large-scene memory and performance tests
- [ ] Cancellation and recovery under load
- [ ] Color-management reference tests
- [ ] Reproducible packaging and clean installation
- [ ] Installation and rendering on a second Windows machine

No second Windows computer is available. A separate local Modo profile can test
startup isolation but cannot establish second-machine compatibility.

Already verified foundations include native AVX1 CPU rendering, named-UV images,
normal/bump maps, basic texture layers, mesh instances, Moonshine DwaBase,
amount/dissolve maps, basic environment translation and a docked custom preview.
These do not establish full scene parity or production readiness.
