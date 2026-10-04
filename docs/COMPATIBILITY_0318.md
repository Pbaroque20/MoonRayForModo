# 0.3.18: right-click material output

Right-click a material node (body, title, or socket) and choose Set as Material
Output. The action targets the clicked node even if another node was selected.
The current output is indicated and disabled in the menu. Texture/map nodes do
not offer material output. Disconnect, Add node and Frame all remain available.
The change participates in graph Undo/Redo and opt-in live preview. Apply/Save
commits it to the scene. Pending field edits are committed before switching.

Syntax checked; no UI/render tests run. Deferred checks: right-click a second
material while the first is selected, body/title/input/output socket hit targets,
current output, texture nodes, canceled menus, Undo/Redo and live preview.

## Native MoonShine Shader Tree layer

New advancedMaterial subtype: material.moonrayMoonShine. Modo registers it in
its native Shader Tree Add Layer menu as MoonShine Material Override. Raw Add
Layer starts inactive until Enable is checked; the MoonRay menu shortcut creates
an enabled DwaBase graph. Place the layer above the standard material in its mask.
Its enable channel and override checkbox both gate export. Disabled layers are
excluded from both ordinary and evaluated material stacks. An active override
replaces lower materials within the existing mask scope at 100% layer opacity;
partial override opacity retains the explicit unsupported warning.

Selection, evaluated export, incremental classification, named material inputs,
and widget references include the new subtype. Existing standard-material and
MaterialX overrides remain supported. The new layer has its own stable properties
sheet. Commands register real NotifyAddClient/NotifyRemoveClient callbacks using
Modo 16.1's NotifierHost; MRAY writes broadcast property-change notifications.
The redundant searchable material editor button was removed from all generated
native property sheets and their generator. Its command remains for old configs.

Deferred host checks (not run): Add Layer placement within a material mask;
enable/disable and visibility; graph Apply/Save and output type changes; texture
above override; independent masks; ordinary and evaluated meshes; property
refresh without reselection; Undo/Redo; save/reopen and opt-in widget preview.
