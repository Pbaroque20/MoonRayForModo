# Shader Tree and graph editor — 0.3.43

This is an unverified development update. No tests, render checks, or Modo UI probes were run. Source syntax and patch whitespace were checked. It does not establish complete Modo parity.

## Changes

- Graph-editor property values are black when they match their declared defaults and cyan otherwise. Numeric, vector, color, enum, boolean, file, and scene-reference controls use the same comparison. Connected inputs are cyan. Reset, undo/redo, and node selection rebuild the state from the effective graph. Labels remain black. Text colors use native item foreground and widget palette roles, without custom Qt painting or style lookups.
- Scalar Shader Tree gradients read Modo's evaluated GradientFilter, including the evaluated modifier stack. Driver A–D, supported scalar surface channels, and Group Mask inputs generate native RampMap nodes. Color gradients retain alpha when available. Constant-valued gradient channels also work. Sampling uses 257 positions over 0..1 with clamped endpoints: this is a bounded approximation, not arbitrary gradient parity. Unsupported sample sources are reported.
- Driver A–D remain internal channels instead of becoming invalid material attributes. Driver-based gradients also work in the environment compositor.
- Layer Masks directly below a material are included in its capture and placed before that material in evaluation order. A masked or partially opaque native override retains the material below it instead of clearing the stack. Native normal-blend groups use scoped BSDF compositing so group opacity applies once when leaving the group.
- Nested group scale controls affect translated UV frequency, projected locator size, bump amplitude, absorption distance, and subsurface distance. Ignore Scale Group bypasses them. Invalid nonpositive/nonfinite scales are rejected. Displacement and distance-driven gradient scaling are not added here.
- Apply to Item Instances now determines whether an item mask may match an instance's prototype. Apply to Subgroup requests Modo's evaluated surface membership; this may make scene capture more expensive.

## Remaining limits

3D/animated procedural equivalence, arbitrary gradient domains and ray-dependent inputs, texture offsets/falloffs, Normal Multiply, arithmetic/inverted native BSDF groups, some masks spanning material/group boundaries, shader fog, independent Fresnel semantics, and complete environment/light-link inheritance remain incomplete. BSDF blending and Modo's parameter blending can differ even with the same weights. Host capture and rendering require deferred validation.

## Deferred checks

Run only when testing is authorized:

```powershell
python -m unittest discover -s tests -p test_shader_tree_0343.py
python -m unittest discover -s tests -p test_parameter_state.py
```

Manual Modo 16.1v9 checks: default black → changed cyan → reset black for Metallic, RGB, boolean, enum, image path, and camera reference; accept a color-picker change; verify undo/redo and graph override layers; ensure there is no crash editing Metallic with preview off/on. Compare a masked native override and a group containing two native materials at 50% opacity against Modo. Check nested scale opt-out, instance mask opt-out, and driver gradients including sharp/discontinuous curves.

SDK reference: supplied lxenvelope.h documents evaluated GradientFilter.Generate; lxidef.h declares gradient param/value/color and Driver A–D effects. Bundled MoonRay RampMap and DwaLayer declarations provide the target interfaces. No SDK files are redistributed.

IPR bypasses Beauty denoising and denoiser guide outputs, including cached post-processing. Selecting Denoised Beauty during IPR displays Beauty. Regular preview/final denoiser preferences remain unchanged. Deferred checks: tests/test_ipr.py.
