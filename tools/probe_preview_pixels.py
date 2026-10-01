# python
"""Inspect the exact EXR pixels Modo supplies to the native preview adapter."""
import ctypes
import json
from pathlib import Path
import lx
import moonray_modo
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
bridge=ctypes.CDLL(str(Path(moonray_modo.__file__).resolve().parents[2]/'bin/MoonRayPreview.lx'))
bridge.MR_preview_image_debug.argtypes=[ctypes.c_char_p]
bridge.MR_preview_image_debug.restype=ctypes.c_char_p
value=bridge.MR_preview_image_debug(str(root/'test-results/pview-kit/source.exr').encode()).decode()
(root/'test-results/pview-pixels.json').write_text(json.dumps({'app_version':lx.eval('query platformservice appversion ?'),'image':value},indent=2))
