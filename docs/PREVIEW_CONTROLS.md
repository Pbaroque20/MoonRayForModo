# Preview controls development update

## Render buffers

The dropdown above the preview offers Beauty and every supported AOV. Selecting an entry starts a new preview, including when Live updates is off. Older queued results are canceled. Data buffers have display-only visualization: normals map -1..1 to 0..1, depth uses logarithmic range compression, world position uses signed logarithmic compression, UV shows U/V in red/green, and alpha is grayscale. EXR AOV checkboxes still control final saved channels independently.

## Material properties

The MoonShine Material properties section now has an inline type dropdown. Native Modo forms beneath it show only the chosen type's parameters. Type changes preserve previous per-type settings for switching back and support Undo. Blank fields and Default enum entries use upstream defaults. Vector/array fields accept JSON arrays. Material input connections remain in the named-input/searchable editor. The legacy Modo controls appear only in Modo-controls mode. Form filtering follows Foundry's command-enable/notifier mechanism: https://learn.foundry.com/modo/developers/latest/sdk/pages/ui/Form%20Filtering.html

## Linear display and LUTs

Beauty now comes from a float linear EXR buffer. The display conversion removes coverage alpha before exposure, view transforms and PNG output; it never unpremultiplies or multiplies the already integrated environment RGB by alpha. This addresses the previous preview path's risk of bright silhouette fringes. Actual fringe removal remains unverified without a render comparison.

The Color / LUT tab provides exposure, highlight compression plus sRGB (default), sRGB without compression, raw linear and an OCIO display/view. A custom OCIO config is optional; source, display and view names must exist in the chosen configuration. The render working space remains linear RGB; these controls do not convert the scene to ACEScg or import every Modo color-management preference.

Optional LUT files can operate on scene-linear RGB before the view or display RGB afterward. Select the placement matching the LUT's intended input. Saved EXRs remain linear and are not baked with these display settings. Display edits trigger a new preview after a short debounce; Stop cancels rendering and conversion. Output renders are not interrupted by selecting another preview buffer.

## Lighting and background

Default: the scene's Modo environments supply lighting and visible background, respecting their visibility flags. Optional camera overrides are black, solid sRGB color, or a latitude-longitude image with brightness and rotation. They do not replace diffuse/reflection/refraction environment lighting. A camera-only EnvLight carries the override, with its six surface-scattering visibility flags disabled.

Physical sky now follows the environment material's linked Sun Light, with an explicit override taking precedence and a single scene Sun Light as fallback. Physical-sun evaluated azimuth/elevation and north orientation are shared by direct light and sky; world-transform mode retains the transformed direction. Haze, RGB ground albedo and clamp/gamma controls feed the atmospheric approximation. The atmosphere is not Modo's proprietary sky model: exact location/time behavior, ozone, solar-disc appearance and photometric brightness still require parity work and validation. A sun below the horizon can correctly produce a dark sky.

## Deferred checks

`tools/check_preview_controls.py` provides offline export/conversion checks and is not run during this implementation. In Modo 16.1v9, verify each buffer, rapid selection changes and Stop during conversion; switch material types and check form refresh, Undo and saved-scene reload; check a bright environment silhouette from linear EXR; verify exposure and an identity LUT; check linked daylight angles and camera-background overrides independently of reflections. No new render or interaction tests were executed.
