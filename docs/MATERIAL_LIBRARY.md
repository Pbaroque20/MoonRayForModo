# Native MoonRay material library

> **Written for an earlier version.** The materials listed here are the same, but as of 0.3.50.1 each has its own properties form and its own kind of layer in the Shader Tree's Add Layer list, and the type dropdown described below is gone. See [What's new in 0.3.50.1](WHATS_NEW_0350.md).

This development update compiles all 20 materials in the vendored MoonShine source, plus the four core MoonRay materials (24 selectable types). The AVX CPU runtime is staged separately from the previous runtimes. Build succeeded; rendering and Modo interaction tests are deferred.

Select meshes and choose Assign MoonShine Material to choose a type. The first choice preserves the existing Modo-controlled DwaBase workflow. Select a Shader Tree material and open **MoonRay Material Type and Parameters...** in its MoonShine properties to choose a native type and edit its attributes. Search filters parameters. Empty fields retain the upstream defaults; numbers and arrays use JSON syntax. Colors are linear RGB arrays. Save stores settings with the scene through an undoable Modo command. Changing the Modo-controls checkbox removes the native type and overrides.

Native controls are separate from the legacy Modo constant controls. Shader Tree textures still feed compatible native channels. Unsupported channel bindings report an error rather than silently changing the material type. For compound materials, create native input materials first, then select their names in material-input fields. Referenced inputs are exported before the parent; missing inputs, incompatible interfaces, and cycles fail explicitly. Shader Tree BSDF stacking requires Dwa-layerable shaders.

Available MoonShine families: base, solid dielectric, refractive, metal, fabric, velvet, skin, emissive, toon, hair, diffuse hair, toon hair, adjustment, color correction, layer, mix, switch, two-sided, hair color correction and hair layer. Core choices include UsdPreviewSurface, RaySwitchMaterial, SwitchMaterial and the diagnostic TestInputsMaterial.

## Limits

- Hair shaders are included, but complete Modo strand/fur geometry translation is not implemented by this update.
- Non-material SceneObject inputs (trace sets, light sets and arbitrary native map nodes) are not editable as material references. Texture layers use the existing Modo graph translation.
- Native parameters are static scene-tag values; this editor does not add animatable Modo channels for every upstream parameter.
- Native material transport uses upstream shader controls; legacy Modo glass absorption controls are not automatically applied to these native types.
- Upstream conditional visibility rules are described in source schemas but all parameters remain visible in this editor.
- This is not a claim of full Modo parity or validated production readiness.

## Deferred validation

Run `tools/check_material_library.py` explicitly for offline schema, export and reference checks. It was not run during implementation. In Modo 16.1v9, separately check type selection, Save/Cancel/Undo, scene save/reload, image and normal maps, compound material references, evaluated-geometry UVs and representative renders for each material family. Compare native parameter values against MoonRay reference renders before production use.
