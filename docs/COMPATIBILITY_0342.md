# Shader Tree compatibility update — 0.3.42

This update expands translation; it does **not** complete all Modo Shader Tree semantics. The existing native runtime is unchanged. Edited Python source was parsed for syntax; no automated tests, renders, or Modo UI checks were run, as requested.

## Implemented

- Layer Mask texture effects retain the identity of the directly preceding visible Shader Tree row. The generated texture graph applies the mask only to that target, including translated material rows and nested texture groups. Missing/skipped targets do not transfer masks to unrelated layers. Group Mask remains a separate group-wide control.
- Checker and Noise color/value patterns now preserve their alpha1/alpha2 contribution when blending layers.
- Grid and Dots layers capture named UVs or the existing locator projections, color/value pairs, alpha, width, transition, bias, and gain. Their 2D patterns are sampled to cached 512px linear images; they use existing native image filtering. Line/square/triangle/hexagon grids and square/triangle/hexagon dots have translation paths. These are deterministic approximations, not copies of Modo's procedural evaluator; cube patterns remain unsupported.
- Normal Map Blend on image normal layers uses reoriented normal mapping after conversion to the mesh tangent basis. Normal layer opacity and alpha remain separate blend weights. Exact Modo numerical equivalence is unverified. Normal Multiply is still unsupported.
- Clearcoat normal and bump effects now have a distinct map path into DwaBaseMaterial's independent clearcoat normal. Diffuse roughness is bound to native diffuse_roughness. The Shader Tree anisotropic effect now maps to the existing anisotropy input.
- Environments traverse nested groups instead of only direct children. Group blend/opacity/invert, Group Mask, and Layer Mask are applied during environment-map generation. Constant color/value layers and the supported Grid/Dots patterns can participate. Item/tag masks that cannot be evaluated from an environment direction are reported instead of being widened to the whole environment. Environment identities remain those of the host environment item for light linking.
- Shader light-link controls inside disabled Shader Tree ancestors no longer override lower active rules. Existing per-light include/exclude rules still take precedence over shader rules, and explicit MoonRay object links retain their priority.
- Unsupported active texture item types now produce notices instead of silently disappearing where their material scope can be resolved.

## Deferred verification

Run the prepared source checks only when testing is authorized:

```powershell
python -m unittest discover -s tests -p test_shader_tree_0342.py
```

The script covers target-specific masks, skipped targets, group masks across channels, coat-normal separation, diffuse roughness, procedural repetition/alpha, and light-link precedence. It has not been executed.

In a disposable Modo 16.1v9 scene, compare: a texture with a Layer Mask directly below it; a masked group affecting both color and roughness; normal/coat-normal images on different UV sets; each Grid/Dots pattern at several widths; a nested environment group with partial opacity; and a disabled upper shader with a lower light-link rule. Compare images against Modo before claiming visual parity. Save the original scene before doing these manual checks.

## Still needed to finish the requested scope

- Arbitrary gradients, driver channels, texture offsets, falloffs, all 3D/animated procedurals and third-party texture evaluators.
- Normal Multiply, every Modo group scaling/subgroup option, and mask behavior across arbitrary native material graph boundaries.
- Remaining shader-level effects, fog, independent reflection/specular Fresnel semantics, and ray-dependent shading controls.
- Full native light-link inheritance/instance behavior and arbitrary environment shader graphs.
- Visual comparison in Modo, including alpha conventions and procedural pattern scale.

The current subset must not be described as complete Modo parity.

## Reference

Foundry's [Shader Tree](https://learn.foundry.com/modo/16.1/content/help/pages/shading_lighting/shader_items/shading.html), [blend modes](https://learn.foundry.com/modo/16.1/content/help/pages/shading_lighting/layers/blendmodes.html), and [texture effects](https://learn.foundry.com/modo/14.2/content/help/pages/shading_lighting/layers/effect_texture_item.html) describe layer ordering, blending, and mask scopes. Channel and enum names were also read from the installed Modo 16.1v9 resources; no Foundry resources are redistributed by this change.
