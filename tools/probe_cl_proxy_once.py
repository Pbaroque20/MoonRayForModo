# python
"""Headless: the two-proxy scene, one kit reading (capture) and proxies, then quit: whether Modo quits cleanly. TWICE
reads twice first."""
import os
import lx
lx.eval('!scene.open {%s} normal' % os.path.join(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references',
                                                   os.environ.get('SCENE', 'proxy2-test.lxo')))
if os.environ.get('OPEN_ONLY'):
    raise SystemExit
if os.environ.get('PY_CACHE'):
    # A render cache made, updated and let go from Python alone, with no adapter.
    flags = lx.symbol.fRENDERCACHE_TRACK_CURRENT_SCENE | lx.symbol.fRENDERCACHE_TURN_OFF_AUTO_UPDATES | lx.symbol.fRENDERCACHE_FORCE_FULL_UPDATE
    cache = lx.object.RenderCache(lx.service.RenderCache().CreateRenderCache(flags))
    cache.Update(float(lx.service.Selection().GetTime()), 0)
    count = cache.GeoSurfaceCount()
    del cache
    raise SystemExit
import modo
from moonray_modo import evaluated
if os.environ.get('NO_CATCH'):
    evaluated._proxied = lambda scene: set()
if os.environ.get('TWICE'):
    evaluated.capture(lx.service.Selection().GetTime())
data = evaluated.capture(lx.service.Selection().GetTime())
if not os.environ.get('NO_PROXIES'):
    evaluated.proxies(data, modo.Scene(), lx.service.Selection().GetTime(), [])
