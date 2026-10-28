"""How XPU2 samples a preview, worked out from the scene's settings as its plan does (cpu_scene.h, the generations'
UserData): for the render settings, which show it in MoonRay's own sampling fields while XPU2 renders the preview
(greyed there), and for the picture's sampling label (panel.py). XPU2's sampling generations are on whenever XPU2 is
the engine (Preferences > MoonRay > XPU2): their switch is greyed then (private test build, 2026-10-28)."""
import math

ADAPTIVE = 2
# MoonRay's own sampling fields, which show what XPU2 takes while it renders the preview.
SHOWN = ('sampling_mode', 'samples', 'min_adaptive_samples', 'max_adaptive_samples', 'target_adaptive_error')


def active():
    """Whether XPU2 renders the preview."""
    try:
        from . import native
        return bool(native.xpu2())
    except Exception:
        return False


def plan(held):
    """What XPU2's generations make of a scene's complete settings (scene_settings.complete): a dict of generations
    (whether they choose where samples go), adaptive (the scene's own sampling is adaptive), average (samples a pixel on
    average, or None where an adaptive scene has no budget), low and high (the fewest and most a pixel), noise (where a
    part of the picture halts, in Target Error's units; 0: none) and exact (every pixel gets the average)."""
    render = held.get('render', {})
    g = held.get('xpu2_generations') or {}
    samples, seed, most = int(g.get('samples', 0)), int(g.get('seed', 0)), int(g.get('most', 0))
    noise, exact = float(g.get('noise', 0.0)), g.get('spend') == 'samples'
    if render.get('sampling_mode') == ADAPTIVE:
        low = max(2, min(16384, seed)) if seed else int(render.get('min_adaptive_samples', 16))
        high = max(low, min(16384, most) if most else int(render.get('max_adaptive_samples', 4096)))
        return dict(generations=True, adaptive=True, average=samples or None, low=low, high=high,
                    noise=noise or float(render.get('target_adaptive_error', 10.0)), exact=exact and bool(samples))
    n = samples or int(held.get('samples', 4)) ** 2
    if not (n > 16 or samples):
        # Few samples and no budget of their own: uniform, as MoonRay samples it.
        return dict(generations=False, adaptive=False, average=n, low=n, high=n, noise=0.0, exact=True)
    return dict(generations=True, adaptive=False, average=n, low=min(n, seed or max(16, n // 8)),
                high=min(16384, max(n, most or n * 16)), noise=noise, exact=exact)


def shown(held, key, value):
    """The value one of the render settings' sampling fields shows while XPU2 renders the preview: what XPU2 takes."""
    if key == 'xpu2_generations':
        return True
    if key not in SHOWN:
        return value
    p = plan(held)
    if key == 'sampling_mode':
        return ADAPTIVE if p['generations'] or p['adaptive'] else value
    if key == 'samples':
        # Pixel Samples is a side of MoonRay's square grid: the average's square root.
        return max(1, int(round(math.sqrt(p['average'])))) if p['average'] else value
    if key == 'min_adaptive_samples':
        return p['low']
    if key == 'max_adaptive_samples':
        return p['high']
    return p['noise'] if p['noise'] else value


def words(held):
    """The picture's sampling label while XPU2 renders the preview."""
    p = plan(held)
    if not p['generations']:
        return 'XPU2 Uniform %d ps' % p['average']
    text = 'XPU2 Gen. '
    text += ('%d ps avg%s (%d-%d)' % (p['average'], ' exact' if p['exact'] else '', p['low'], p['high'])) if p['average'] else '%d-%d ps' % (p['low'], p['high'])
    return text + (', noise %g' % p['noise'] if p['noise'] else '')
