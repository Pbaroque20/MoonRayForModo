# Installing MoonRay for Modo

These instructions are for **0.5.3.2**, **Modo 16.1v9**, and **Windows x64**. The runtime is MoonRay [2026.29.1](https://github.com/dreamworksanimation/openmoonray/releases/tag/v2026.29.1) (MoonRay 18.4), built for Windows with the plugin's own patches. This is a pre-production release, not a production-certified build.

## Requirements

- An installed copy of Modo 16.1v9. The supported executable is `C:\Program Files\Modo16.1v9\modo\modo.exe`.
- An AVX-capable x64 CPU for the bundled CPU runtime.
- Optional: a compatible NVIDIA GPU and installed NVIDIA driver for XPU, XPU2 and OptiX. The runtime includes CUDA runtime libraries; a CUDA development toolkit is not required. XPU has been exercised on an RTX 3090; compatibility with every GPU/driver combination is not established.

## Download and install

1. Open the [0.5.3.2 release](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.5.3.2). Download **MoonRayForModo-0.5.3.2-kit.zip** and **MoonRayForModo-0.5.3.2-windows-runtime.zip** from Assets, and, if you want MoonRay's ten example scenes in the asset library, **MoonRayForModo-0.5.3.2-content.zip** (about 300 MB). GitHub's automatic Source code ZIP does not include the runtime.
2. Save your scene and close all Modo instances.
3. Extract the ZIPs into the **same temporary folder**. Merge their `MoonRayForModo` folders (the content ZIP adds to `assets/library`). The resulting folder must contain `index.cfg`, `bin/MoonRayGeometry.lx`, `runtime/moonray.exe` and `runtime-xpu2`.
4. In Windows Explorer, enter `%APPDATA%\Luxology\Kits`. Create the `Kits` folder if needed. If a `MoonRayForModo` folder already exists, move it to a backup location **outside Kits**; do not merge a new release into the old installation.
5. Copy the combined `MoonRayForModo` folder into `Kits`. Avoid an extra nested folder: `index.cfg` should be directly inside `Kits\MoonRayForModo`.
6. Start **Modo 16.1v9**. Open **MoonRay > Open Preview** (or enter `moonray.open`). The plugin discovers its bundled `runtime` folder automatically. For XPU2, the default GPU renderer for previews, choose **Compile XPU2 Shaders** once in System > Preferences > MoonRay > XPU2; until then the preview says so instead of rendering, or choose MoonRay XPU on that page.
7. If upgrading from a development installation, check the runtime path in MoonRay settings. If it still points to an older folder, select `%APPDATA%\Luxology\Kits\MoonRayForModo\runtime`. Use Auto execution for XPU → Vector → Scalar fallback, or choose a CPU mode explicitly.

Do not install the runtime ZIP alone: the kit ZIP contains the Modo integration and geometry adapter. Keep the runtime files, shaders, and licenses together. Do not install or copy the Modo SDK.

## Using the plugin

![The MoonRay Preview window](images/preview-window.png)

- Open **MoonRay > Open Preview**. **Render** starts a MoonRay render. The preview can dock as a Modo custom viewport; it does not populate Modo's built-in Render View slots.
- Choose the engine in the preview's toolbar: **MoonRay** for the full render, **MoonRay LS** for a quick low-sample one, or **MoonLightIPR** for an approximate GPU preview (NVIDIA GPU required). With MoonLightIPR, press **RT Off** to switch realtime on; it then updates after each edit. Output renders always use MoonRay.
- Render settings are on the Render item's **MoonRay** tab and under **MoonRay > Render Settings**: sampling, depths, denoising, view transform (ACES by default) and outputs.
- To give a mesh a MoonRay material, select it and choose **MoonRay > Assign MoonShine Material to Mesh**, or add one from the Shader Tree's **Add Layer** list. Its form has **Open Graph**.
- **MoonRay > Import MaterialX Material...** and **MoonRay > Import MoonRay Scene (RDL)...** bring in materials and whole MoonRay scenes. For a scene kept as `scene.rdlb` and `scene.rdla`, choose either file.
- **MoonRay > Add MoonRay Item** adds MoonRay's own lights, light filters, cameras, shapes and volumes.
- **MoonRay > Asset Library** shows saved materials, models and scenes as pictures; double-click one to use it. **Draft** in the preview window shows the scene as outlines until you drag a **Region** to render.
- **System > Preferences > MoonRay** holds the plugin's own options, among them having the M key open MoonRay's Assign Material.
- Choose **Denoised Beauty** in the buffer list to see the picture denoised; **Beauty** is the default. Right-click the picture for **Smart Render**, which stops a MoonRay render once it is clean enough and denoises it, or **Safe Denoising**, with which a render stopped part way is kept and denoised and **Continue** takes it up again.
- **Options > Compositor** in the preview window grades and filters a finished render; **MoonRay > MoonLightIPR Playblast** renders a quick animation on the graphics card.

## Checksums and troubleshooting

`SHA256SUMS.txt` contains checksums for the ZIPs and the installation guide. Compare a download with PowerShell `Get-FileHash -Algorithm SHA256 'path-to-download.zip'` if needed.

If the MoonRay menu is missing, check the folder nesting and restart Modo. If the runtime cannot be found, select the folder containing `moonray.exe`. For render errors, open Render Log; avoid replacing individual DLLs with files from other runtime versions.

If every preview and every `.rdla` fails at once with "filesystem error: directory iterator cannot open directory: Not a directory [...]", your Windows PATH names a file where it should name a folder (often `c:\Windows\System32\cmd.exe`). Releases up to 0.5.2 stop on it; 0.5.2.1 and later start anyway. On an older release, remove that entry from PATH (System Properties > Environment Variables, in both lists) and restart Modo.

To roll back, close Modo, move the new kit outside `Kits`, and restore your backed-up kit. If you changed the runtime path, restore that path too. Only one MoonRay kit should remain under `Kits`.

See the [README](../README.md) for current limitations. This release was packaged with file-integrity checks, and the packaged files were unpacked into an empty folder and rendered from there with no environment set; it has been run on one machine only, and no clean-machine install was tested.

## Rendering headless (no Modo window)

A headless render takes two steps: write the Modo scene as a MoonRay scene, then render that file with the kit's `moonray.exe`. Neither step needs Modo's window, so both can run on a farm.

### 1. Write the MoonRay scene

From Modo: **MoonRay > Export as MoonRay Scene** (RDLA, RDLB or both; one scene per frame if you like).

Without a window, from Modo's command-line version `modo_cl.exe` and the kit's `scripts/export_moonray.py`. Put the commands in a text file and give it to `modo_cl` as its input. A plain PowerShell pipe does not work: `modo_cl` misreads its first line. Put quotes, not braces, around the two paths. In PowerShell, adjust these paths:

```powershell
Set-Content -Encoding ascii "$env:TEMP\export.txt" '@{kit_MoonRayForModo:scripts/export_moonray.py} "C:\scenes\shot.lxo" "C:\scenes\shot.rdlb"', 'app.quit'
Start-Process -Wait -NoNewWindow 'C:\Program Files\Modo16.1v9\modo\modo_cl.exe' -RedirectStandardInput "$env:TEMP\export.txt"
```

The script writes RDLB if the name ends in `.rdlb` and RDLA otherwise. Add `"frames"` after the two paths to write one scene for each frame of the frame range (`shot.0001.rdlb`, `shot.0002.rdlb`...). Each scene uses the Modo scene's own MoonRay render settings and keeps its render outputs.

### 2. Render it with MoonRay

```powershell
& 'C:\path\MoonRayForModo\runtime\moonray.exe' -in 'C:\scenes\shot.rdlb' -out 'C:\renders\shot.exr' -exec_mode xpu 2>&1 | Tee-Object "$env:USERPROFILE\Desktop\moonray-log.txt"
```

`-exec_mode` is `xpu` (graphics card and processor), `vector` or `scalar` (processor only). A glowing VDB volume, or a light with a cookie filter, needs `scalar` in this build. For a sequence, render each frame's scene:

```powershell
Get-ChildItem 'C:\scenes\shot.*.rdlb' | ForEach-Object { & 'C:\path\MoonRayForModo\runtime\moonray.exe' -in $_.FullName -out ('C:\renders\' + $_.BaseName + '.exr') -exec_mode xpu }
```

The runtime finds `shaders/OptixGPUPrograms.ptx` and the shader libraries in the folder that holds `moonray.exe`, so keep the runtime folder whole. The bundled layout needs no environment setup. If `REZ_MOONRAY_ROOT`, `RDL2_DSO_PATH` or `TMPDIR` is already set, it takes precedence; clear it if it points to another installation.

### XPU2 does not render headless

XPU2 renders only inside Modo: the MoonRay preview, and Render and Render Animation in the preview window. `runtime-xpu2\moonray_xpu2.exe` cannot render a scene file on its own. Run without Modo, it hands its command line to the MoonRay named in `MOONRAY_XPU2_MOONRAY` and stops if that is not set. For a headless or farm render, use MoonRay's `xpu` mode above. It is slower than XPU2.

A GPU render with many outputs has four times the room it had for what each ray owes them; `MOONRAY_MODO_CL1_POOL_SCALE` (1 to 8, default 4) sets another size if a render still reports that it could not allocate a CacheLine1.

If OptiX still fails, report the complete log and NVIDIA driver version. Automatic file discovery does not resolve an incompatible driver or invalid PTX program.
