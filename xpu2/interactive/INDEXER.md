# XPU2's scene indexer: classification, routing and incremental updates

The scene index (`../indexed_scene.h`, `../rdl_scene_index.h`, `../rdl_replica.h`) captures every RDL object and
attribute of a Modo session incrementally, and the router (`routing_index.h`) keeps a decision per entity, redone only
for what an edit touched. Until now no classifier was given: every decision was "fallback", and the plan builder
(`cpu_scene.h`, `cpu::prepare`) did its own admission for the whole scene, refusing it at the first thing XPU2 does
not render, and the GPU refused whole scenes for anything its programs lack (`async_gpu.h`, `cpuOnly`).

This note is the plan to finish it.

## 1. Classification per entity

Each entity (geometry, instance, material, map, light, light filter, volume, displacement, camera) gets:

| Field | Meaning |
|---|---|
| support | `Fallback` (XPU2 does not render it: the scene goes to MoonRay XPU), `Cpu` (the CPU lane alone), `Both` |
| evidence | the conformance identity: the XPU2 feature and the comparison that verified it (for example `volume.vdb:vs1`) |
| families | the GPU feature families it needs (DwaBase, layers, hair, glitter, toon, subsurface, image maps, procedural maps, curves, points, motion, volumes, light filters, ...) |
| cost | a relative cost per hit on each device, from measured shading times per family |

The rules are the plan builder's admission, made per object so both use one source of truth: the class and attribute
checks, map bindings and their programs, and the GPU capability table (what the GPU programs implement, which is
what `cpuOnly` refuses today, family by family).

A material is classified by the shading families its BSDF tree and map graph use, so a scene with one glitter
material and many DwaBase ones is not judged by the glitter.

## 2. Routing by device

- **GPU programs by family.** The GPU program is built from the families the scene's `Both` entities use. With the
  map interpreter split into a function per map type and the families moved into separate modules, a scene compiles
  only what it uses, cached per combination.
- **Deferral to the CPU.** An entity classified `Cpu` is in the GPU scene as a stand-in: a bounding primitive (a
  moving mesh's motion bounds, a VDB's box, points' bounds) or a flag on a light or material. A GPU sample that meets
  one stops and is handed to the CPU lane, which renders that sample whole from its identity (pixel, index, frame).
  Every sample's random numbers come from its identity, so the CPU's result is the one the GPU would have made; no
  path state crosses devices, and the GPU's partial work for it is dropped (its film never sees it). The CPU lane's
  retry queue takes these samples.
- **Cells by suitability.** The work grid's cells start on the device suited to what they see: a cheap first-hit pass
  (the camera rays of one sample a tile) gives each tile the entities it sees first; a tile whose entities are `Cpu`
  or cheaper on the CPU starts CPU-owned. Ownership then follows the deferral rate: a cell whose GPU samples mostly
  defer flips to the CPU (the existing ownership flips, with deferrals counted as the CPU's).
- **Scene mode.** Any `Fallback` entity sends the scene to MoonRay XPU, with the entity and the reason, decided as
  the edit arrives instead of after a failed plan.

## 3. Incremental updates end to end

The router's change set (entities added, removed, changed, and those affected through dependencies) goes to the
renderer with the frame:

- unchanged meshes, tessellations, grids, images and light tables are reused (as today, by signature), and the
  renderer is told which ones changed instead of finding out;
- the CPU's Embree scene and the GPU's acceleration structures are refitted or rebuilt per changed mesh (instances:
  their transforms only), not rebuilt whole;
- material, light and filter records are rewritten in place where their layout allows;
- the RDLB file is written only for MoonRay's fallback, not on every edit.

## Order

1. Classifier from the admission rules, with the GPU capability table; decisions shown in the session's log.
2. Scene mode from the decisions; the plan builder keeps its checks as assertions.
3. Deferral to the CPU (GPU stand-ins, deferral status, the CPU lane's retry queue), replacing `cpuOnly`.
4. Cell seeding by suitability and ownership by deferral rate.
5. GPU program families as separate modules, compiled on demand.
6. The change set to the renderer: partial rebuilds of the scene on both devices.
