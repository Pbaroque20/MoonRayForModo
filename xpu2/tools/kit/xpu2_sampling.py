"""How XPU2 samples a preview, worked out from the scene's settings as its plan does (cpu_scene.h, the generations'
UserData): for the render settings, which show it in MoonRay's own sampling fields while XPU2 renders the preview
(greyed there), and for the picture's sampling label (panel.py). While XPU2 is the engine (Preferences > MoonRay >
XPU2) its own sampling controls rule (the UserData's form 2): a scene's adaptive sampling is MoonRay's alone, and XPU2
samples from Pixel Samples and its controls (asked 2026-10-28)."""
import math

ADAPTIVE, UNIFORM = 2, 0
# MoonRay's own sampling fields, which show what XPU2 takes while it renders the preview.
SHOWN = ('sampling_mode', 'samples', 'min_adaptive_samples', 'max_adaptive_samples', 'target_adaptive_error')
# The render camera as the last preview's scene had it (rdla.py, camera_kind): 'bake' or 'map', which XPU2 samples
# uniformly as MoonRay does, Pixel Samples a pixel (a map's times its value); '' a camera of the usual kind, or none
# known yet.
CAMERA = ['']


def active():
    """Whether XPU2 renders the preview."""
    try:
        from . import native
        return bool(native.xpu2())
    except Exception:
        return False


def camera_kind(entity):
    """What of the render camera's entity (entities.render_camera) leaves XPU2's generations out: 'bake' for a bake
    camera, 'map' for a pixel sample map, '' for neither (or a Modo camera)."""
    if not entity:
        return ''
    if entity.get('class') == 'BakeCamera':
        return 'bake'
    return 'map' if (entity.get('parameters') or {}).get('pixel_sample_map') else ''


def budget(generations, grid, realtime=False):
    """Generation Samples as XPU2 is given them (rdla.py): while realtime follows the scene, the share of them its
    Realtime Samples says (Pixel Samples squared where Generation Samples is 0), one at least."""
    samples = int(generations.get('samples', 0))
    share = int(generations.get('realtime', 100))
    if not realtime or share >= 100:
        return samples
    return max(1, int(round((samples or int(grid) ** 2) * share / 100.0)))


def plan(held, camera=None, realtime=False):
    """What XPU2 makes of a scene's complete settings (scene_settings.complete): a dict of generations (whether they
    choose where samples go), average (samples a pixel on average), low and high (the fewest and most a pixel), noise
    (where a part of the picture halts, in Target Error's units; 0: none), exact (every pixel gets the average) and
    camera (camera_kind, the last preview's unless given). realtime: as realtime following the scene has it (budget)."""
    camera = CAMERA[0] if camera is None else camera
    g = held.get('xpu2_generations') or {}
    samples, seed, most = budget(g, held.get('samples', 4), realtime), int(g.get('seed', 0)), int(g.get('most', 0))
    noise, exact = float(g.get('noise', 0.0)), g.get('spend') == 'samples'
    grid = int(held.get('samples', 4)) ** 2
    n = samples or grid
    if camera or not (n > 16 or samples):
        # A bake camera or a pixel sample map, or few samples and no budget of their own: uniform, as MoonRay samples
        # it, Pixel Samples a pixel.
        n = grid if camera else n
        return dict(generations=False, average=n, low=n, high=n, noise=0.0, exact=True, camera=camera)
    return dict(generations=True, average=n, low=min(n, seed or max(16, n // 8)),
                high=min(16384, max(n, most or n * 16)), noise=noise, exact=exact, camera='')


def shown(held, key, value):
    """The value one of the render settings' sampling fields shows while XPU2 renders the preview: what XPU2 takes."""
    if key not in SHOWN:
        return value
    p = plan(held)
    if key == 'sampling_mode':
        return ADAPTIVE if p['generations'] else UNIFORM
    if key == 'samples':
        # Pixel Samples is a side of MoonRay's square grid: the average's square root.
        return max(1, int(round(math.sqrt(p['average']))))
    if key == 'min_adaptive_samples':
        return p['low']
    if key == 'max_adaptive_samples':
        return p['high']
    return p['noise'] if p['noise'] else value


def words(held, realtime=False):
    """The picture's sampling label while XPU2 renders the preview (realtime: following the scene)."""
    p = plan(held, realtime=realtime)
    if not p['generations']:
        return 'XPU2 Uniform %d ps%s' % (p['average'], {'map': ', sample map', 'bake': ', bake'}.get(p['camera'], ''))
    text = 'XPU2 Gen. %d ps avg%s (%d-%d)' % (p['average'], ' exact' if p['exact'] else '', p['low'], p['high'])
    return text + (', noise %g' % p['noise'] if p['noise'] else '')
