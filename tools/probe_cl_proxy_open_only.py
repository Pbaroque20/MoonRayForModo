# python
"""Headless baseline: the two-proxy scene opened and Modo quit, with no kit code, to see whether Modo itself crashes
at shutdown with Scene Proxies loaded. STEP=capture also runs the kit's render cache capture; STEP=foreign also asks
MR_foreign_layers with no item references."""
import ctypes, os
import lx
lx.eval('!scene.open {C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\proxy2-test.lxo} normal')
step = os.environ.get('STEP', '')
if step:
    import modo
    from moonray_modo import evaluated
    evaluated.capture(lx.service.Selection().GetTime())
if step == 'foreign':
    call = evaluated._adapter().MR_foreign_layers
    call.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_double, ctypes.c_int]
    call.restype = ctypes.c_char_p
    call(ctypes.c_void_p(modo.Scene().scene.__peekobj__()), None, 0, float(lx.service.Selection().GetTime()), 1)
if os.environ.get('IMPORT_HOST'):
    from moonray_modo import host
if os.environ.get('CALL_PROXIES'):
    data = evaluated.capture(lx.service.Selection().GetTime())
    evaluated.proxies(data, modo.Scene(), lx.service.Selection().GetTime(), [])
if os.environ.get('FILENAME'):
    names = [s.scene.Filename() for s in evaluated._FOREIGN]
if os.environ.get('GC'):
    import gc
    gc.collect()
if os.environ.get('KEEP_SCENE'):
    kept_scene = modo.Scene()
