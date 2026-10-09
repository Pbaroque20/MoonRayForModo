# Material nodes and MaterialX Override (0.2.0 development)

> **Superseded in large part by 0.3.50.1.** The MoonShine and MaterialX override layers described below are no longer offered: a MoonRay material is assigned to a mesh or added from the Shader Tree's Add Layer list, has its own form, and opens in a redesigned graph editor with a control for every property; a MaterialX file is brought in with **MoonRay > Import MaterialX Material...** as a material of its own kind. Scenes that hold override layers still load and render. See [What's new in 0.3.50.1](WHATS_NEW_0350.md).

Select a standard Shader Tree material. In its **MoonShine Material** properties,
choose the material type from the dropdown at the top. The corresponding controls
appear underneath in the same pane. **Open Node Editor** opens a separate visual
canvas for the selected material. Choose nodes, connect output and input sockets,
select a surface output, and Save. Cancel leaves the scene unchanged. All 24
installed material definitions are available; appropriate geometry is still
required (for example, hair materials need strands).

## A separate Shader Tree layer

Use Shader Tree **Add Layer > MaterialX Override**, or **MoonRay > Add MaterialX
Override**. This creates a dedicated material layer at the current shader scope.
Select it and check **Enable MaterialX Override** in its properties to open the
node editor. Save activates the override. Uncheck to restore the underlying
material while retaining the graph. **Edit Node Graph** reopens the saved graph.
This checkbox belongs only to the dedicated layer, not every MoonShine material.

The override replaces the complete surface in its selection scope. It currently
requires 100% layer opacity. Fractional blending of an arbitrary surface override
is not supported. Use compatible Dwa layer materials inside the graph for material
mixing. Item/tag selection still uses the existing Shader Tree translation.

## Authoring and interchange

Nodes include the installed native materials, image, constant, checker, normalmap,
add, subtract, multiply, divide and mix. The property table accepts JSON values:
`0.5`, `[1, 0.5, 0]`, `true`, or a quoted file path using forward slashes. Blank
uses the default. Image nodes expose named UV sets, scale, input sRGB conversion,
and RGB/component/alpha selection. Connect input accesses ports not drawn on the
node. Add override in the editor creates a non-destructive parameter/connection
edit over one node; Toggle layer restores or reapplies that edit. These editor
edits are distinct from the Shader Tree MaterialX Override item.

Graphs and their edits are stored in the LXO. Image files remain external.
Imported relative image paths are resolved against the MaterialX document.
External MaterialX edits are not automatically reloaded.

MaterialX import is an explicit subset translator, not a MaterialX SDK integration.
It accepts one selected surface material, local nodegraph outputs, supported
standard_surface inputs, the listed map operations, and this plugin's native
NodeDefs. Unsupported inputs, nodes, UV coordinate graphs and color spaces raise
an error rather than being silently omitted. Standard Surface appearance is an
approximation using DwaBaseMaterial, not a promise of identical shading.

Export definitions writes vendor `moonray_*` NodeDefs and instances. These require
MoonRayForModo; they contain no portable BSDF implementations for other renderers.
Export rejects connected sockets with different MaterialX types and external
scene-material references. Such graphs can still be saved and rendered locally.
Native vector-array parameters are not yet supported by MaterialX export.
Export flattens enabled editor overrides; the LXO retains their editable layers.
DTD/entities and external code execution are disabled.

## About and licenses

**MoonRay > About MoonRay for Modo** displays the supplied MoonRay artwork above a
black credits panel, developer Raphael Tobar, and the installed plugin version.
The plugin uses the **MIT License** (MIT has no numbered 2.0 version). MoonRay's
upstream source uses **Apache License 2.0**. The About window also exposes the
bundled MIT license and third-party notices. This is an independent integration.

## Deferred validation

No renderer or Modo UI tests were run for this update, as requested. Run
`python tools/test_material_nodes.py` later for standalone graph/MaterialX checks.
In Modo 16.1v9, verify Add Layer visibility, Undo, same-pane dropdown refresh,
Save/Cancel, save/reopen LXO persistence, checkbox off/on restoration, image/normal
connections, and preview refresh. Compare the supported Standard Surface examples
against reference images before relying on this development build in production.
