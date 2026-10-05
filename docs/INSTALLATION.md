# Installing MoonRay for Modo

These instructions are for **0.3.49**, **Modo 16.1v9**, and **Windows x64**. This is an experimental development release, not a production-certified build.

## Requirements

- An installed copy of Modo 16.1v9. The supported executable is `C:\Program Files\Modo16.1v9\modo\modo.exe`.
- An AVX-capable x64 CPU for the bundled CPU runtime.
- Optional: a compatible NVIDIA GPU and installed NVIDIA driver for XPU/OptiX. The runtime includes CUDA runtime libraries; a CUDA development toolkit is not required. XPU has been exercised on an RTX 3090; compatibility with every GPU/driver combination is not established.

## Download and install

1. Open the [0.3.49 release](https://github.com/Pbaroque20/MoonRayForModo/releases/tag/v0.3.49). Download **MoonRayForModo-0.3.49-kit.zip** and **MoonRayForModo-0.3.49-windows-runtime.zip** from Assets. GitHub's automatic Source code ZIP does not include the runtime.
2. Save your scene and close all Modo instances.
3. Extract both ZIPs into the **same temporary folder**. Merge their `MoonRayForModo` folders. The resulting folder must contain `index.cfg`, `bin/MoonRayGeometry.lx`, and `runtime/moonray.exe`.
4. In Windows Explorer, enter `%APPDATA%\Luxology\Kits`. Create the `Kits` folder if needed. If a `MoonRayForModo` folder already exists, move it to a backup location **outside Kits**; do not merge a new release into the old installation.
5. Copy the combined `MoonRayForModo` folder into `Kits`. Avoid an extra nested folder: `index.cfg` should be directly inside `Kits\MoonRayForModo`.
6. Start **Modo 16.1v9**. Open **MoonRay > Render Setup** (or enter `moonray.open`). The plugin discovers its bundled `runtime` folder automatically.
7. If upgrading from a development installation, check the runtime path in MoonRay settings. If it still points to an older folder, select `%APPDATA%\Luxology\Kits\MoonRayForModo\runtime`. Use Auto execution for XPU → Vector → Scalar fallback, or choose a CPU mode explicitly.

Do not install the runtime ZIP alone: the kit ZIP contains the Modo integration and geometry adapter. Keep the runtime files, shaders, and licenses together. Do not install or copy the Modo SDK.

## Using the plugin

- **Render** starts a preview; **IPR** updates it after scene changes. The preview can dock as a Modo custom viewport; it does not populate Modo's built-in Render View slots.
- In the Shader Tree, add **MoonShine Material Override** above a Modo material. Enable the override and choose **Edit Material Graph**.
- After a preview pass completes, enable **Beauty denoiser** with **Denoise beauty preview** checked to denoise cached pixels without rerendering. Select **Beauty** or **Denoised Beauty** in the render-buffer dropdown.

## Checksums and troubleshooting

`SHA256SUMS.txt` contains checksums for both ZIPs and the installation guide. Compare a download with PowerShell `Get-FileHash -Algorithm SHA256 'path-to-download.zip'` if needed.

If the MoonRay menu is missing, check the folder nesting and restart Modo. If the runtime cannot be found, select the folder containing `moonray.exe`. For render errors, open Render Log; avoid replacing individual DLLs with files from other runtime versions.

To roll back, close Modo, move the new kit outside `Kits`, and restore your backed-up kit. If you changed the runtime path, restore that path too. Only one MoonRay kit should remain under `Kits`.

See the [README](../README.md) for current limitations. This release was packaged with file-integrity checks; no new render, Modo UI, or clean-machine tests were run.

## Standalone command-line rendering

Version 0.3.49 defaults to the folder containing `moonray.exe` when locating `shaders/OptixGPUPrograms.ptx` and shader libraries. Keep the complete runtime folder together. No environment setup is required for the bundled layout. Existing `REZ_MOONRAY_ROOT`, `RDL2_DSO_PATH`, and `TMPDIR` settings take precedence; clear stale values if they point to another installation.

In PowerShell, adjust these paths:

```powershell
& 'C:\path\MoonRayForModo\runtime\moonray.exe' -in 'C:\scenes\scene.rdla' -out 'C:\renders\beauty.exr' -exec_mode xpu 2>&1 | Tee-Object "$env:USERPROFILE\Desktop\moonray-log.txt"
```

If OptiX still fails, report the complete log and NVIDIA driver version. Automatic file discovery does not resolve an incompatible driver or invalid PTX program.
