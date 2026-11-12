# python
"""Headless: which part of handing a Scene Proxy's scene to Python leaves Modo crashing as it quits. MODE: none (no
listener), drop (the listener keeps nothing), wrap (it wraps the scene and drops it), keep (it keeps the wrapper,
released before quitting)."""
import ctypes, gc, json, os, traceback
import lx, lxifc
out = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\catcher.json'
result = {}
try:
    lx.eval(r'!scene.open {C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\proxy2-test.lxo} normal')
    import modo
    from moonray_modo import evaluated
    mode = os.environ.get('MODE', 'none')
    kept = []

    class Catcher(lxifc.SceneItemListener):
        def sil_SceneCreate(self, scene):
            if mode == 'wrap':
                result['file'] = lx.object.Scene(scene).Filename()
            elif mode == 'keep':
                kept.append(lx.object.Scene(scene))
    if os.environ.get('CAPTURE'):
        evaluated.capture(lx.service.Selection().GetTime())
    if os.environ.get('TIME0'):
        lx.service.Selection().GetTime = lambda: 0.0
    evaluated._adapter().MR_foreign_probe(int(os.environ.get('PROBE', 0)))
    if os.environ.get('TIMING'):
        timing = evaluated._adapter().MR_geometry_cache_timing
        timing.argtypes = [ctypes.c_double, ctypes.c_uint, ctypes.c_int, ctypes.c_int]; timing.restype = ctypes.c_char_p
        flags = lx.symbol.fRENDERCACHE_TRACK_CURRENT_SCENE | lx.symbol.fRENDERCACHE_TURN_OFF_AUTO_UPDATES | lx.symbol.fRENDERCACHE_FORCE_FULL_UPDATE | lx.symbol.fRENDERCACHE_GEOCACHE_DISPLACE
        result['timing'] = timing(float(lx.service.Selection().GetTime()), flags, 0, int(os.environ['TIMING']) - 1)
        open(out, 'w').write(json.dumps(result, default=str))
        raise SystemExit
    call = evaluated._adapter().MR_foreign_layers
    call.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double, ctypes.c_int]
    call.restype = ctypes.c_char_p
    handle = lx.object.Unknown(Catcher()) if mode != 'none' else None
    answer = call(ctypes.c_void_p(modo.Scene().scene.__peekobj__()), ctypes.c_void_p(handle.__peekobj__()) if handle else None,
                  float(lx.service.Selection().GetTime()), int(os.environ.get('DISPLACED', 1)))
    result['answer'] = answer[-40:]
    result['kept'] = len(kept)
    del kept[:], handle
    gc.collect()
except Exception:
    result['error'] = traceback.format_exc()
open(out, 'w').write(json.dumps(result, default=str))
