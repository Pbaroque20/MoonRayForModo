# Installing MoonRay for Modo

These instructions are for **0.3.50.2**, **Modo 16.1v9**, and **Windows x64**. This is an experimental development release, not a production-certified build.

## Requirements

- An installed copy of Modo 16.1v9. The supported executable is `C:\Program Files\Modo16.1v9\modo\modo.exe`.
- An AVX-capable x64 CPU for the bundled CPU runtime.
- Optional: a compatible NVIDIA GPU and installed NVIDIA driver for XPU/OptiX. The runtime includes CUDA runtime libraries; a CUDA development toolkit is not required. XPU has been exercised on an RTX 3090; compatibility with every GPU/driver combination is not established.

## Download and install

1. Open the [0.3.50.2 release](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.3.50.2). Download **MoonRayForModo-0.3.50.2-kit.zip** and **MoonRayForModo-0.3.50.2-windows-runtime.zip** from Assets. GitHub's automatic Source code ZIP does not include the runtime.
2. Save your scene and close all Modo instances.
3. Extract both ZIPs into the **same temporary folder**. Merge their `MoonRayForModo` folders. The resulting folder must contain `index.cfg`, `bin/MoonRayGeometry.lx`, and `runtime/moonray.exe`.
4. In Windows Explorer, enter `%APPDATA%\Luxology\Kits`. Create the `Kits` folder if needed. If a `MoonRayForModo` folder already exists, move it to a backup location **outside Kits**; do not merge a new release into the old installation.
5. Copy the combined `MoonRayForModo` folder into `Kits`. Avoid an extra nested folder: `index.cfg` should be directly inside `Kits\MoonRayForModo`.
6. Start **Modo 16.1v9**. Open **MoonRay > Render Setup** (or enter `moonray.open`). The plugin discovers its bundled `runtime` folder automatically.
7. If upgrading from a development installation, check the runtime path in MoonRay settings. If it still points to an older folder, select `%APPDATA%\Luxology\Kits\MoonRayForModo\runtime`. Use Auto execution for XPU → Vector → Scalar fallback, or choose a CPU mode explicitly.

Do not install the runtime ZIP alone: the kit ZIP contains the Modo integration and geometry adapter. Keep the runtime files, shaders, and licenses together. Do not install or copy the Modo SDK.

## Using the plugin

![The MoonRay Preview window](images/preview-window.png)

- Open **MoonRay > Render Setup**. **Render** starts a preview; with **IPR** ticked it keeps following the scene until Stop. The preview can dock as a Modo custom viewport; it does not populate Modo's built-in Render View slots.
- Choose the preview engine beside IPR: **MoonRay**, or **MoonLightIPR** for an approximate GPU preview that follows edits as they are made (NVIDIA GPU required). Output renders always use MoonRay.
- Render settings are on the Render item's **MoonRay** tab and under **MoonRay > Render Settings**: sampling, depths, denoising, view transform (ACES by default) and outputs.
- To give a mesh a MoonRay material, select it and choose **MoonRay > Assign MoonShine Material to Mesh**, or add one from the Shader Tree's **Add Layer** list. Its form has **Open Graph**.
- **MoonRay > Import MaterialX Material...** and **MoonRay > Import MoonRay Scene (RDL)...** bring in materials and whole MoonRay scenes. For a scene kept as `scene.rdlb` and `scene.rdla`, choose either file.
- **MoonRay > Add MoonRay Item** adds MoonRay's own lights, light filters, cameras, shapes and volumes.
- With a **Beauty denoiser** chosen and **Denoise Preview** on, a finished preview shows **Denoised Beauty**; choose **Beauty** in the buffer list to compare. The denoised view is off while IPR is following the scene.

## Checksums and troubleshooting

`SHA256SUMS.txt` contains checksums for both ZIPs and the installation guide. Compare a download with PowerShell `Get-FileHash -Algorithm SHA256 'path-to-download.zip'` if needed.

If the MoonRay menu is missing, check the folder nesting and restart Modo. If the runtime cannot be found, select the folder containing `moonray.exe`. For render errors, open Render Log; avoid replacing individual DLLs with files from other runtime versions.

To roll back, close Modo, move the new kit outside `Kits`, and restore your backed-up kit. If you changed the runtime path, restore that path too. Only one MoonRay kit should remain under `Kits`.

See the [README](../README.md) for current limitations. This release was packaged with file-integrity checks, and the packaged files were unpacked into an empty folder and rendered from there with no environment set; it has been run on one machine only, and no clean-machine install was tested.

## Standalone command-line rendering

The runtime defaults to the folder containing `moonray.exe` when locating `shaders/OptixGPUPrograms.ptx` and shader libraries. Keep the complete runtime folder together. No environment setup is required for the bundled layout. Existing `REZ_MOONRAY_ROOT`, `RDL2_DSO_PATH`, and `TMPDIR` settings take precedence; clear stale values if they point to another installation.

In PowerShell, adjust these paths:

```powershell
& 'C:\path\MoonRayForModo\runtime\moonray.exe' -in 'C:\scenes\scene.rdla' -out 'C:\renders\beauty.exr' -exec_mode xpu 2>&1 | Tee-Object "$env:USERPROFILE\Desktop\moonray-log.txt"
```

A GPU render with many outputs has four times the room it had for what each ray owes them; `MOONRAY_MODO_CL1_POOL_SCALE` (1 to 8, default 4) sets another size if a render still reports that it could not allocate a CacheLine1.

If OptiX still fails, report the complete log and NVIDIA driver version. Automatic file discovery does not resolve an incompatible driver or invalid PTX program.
