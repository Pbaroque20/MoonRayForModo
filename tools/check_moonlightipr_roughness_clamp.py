"""MoonRay's Roughness Clamp in MoonLightIPR: check_moonlightipr_session.py's scene (gold balls, a cube, sun and sky) with
roughness_clamping_factor 0 and 1, rendered by MoonRay and by MoonLightIPR, three times: with its plain materials (which go to
MoonRay as UsdPreviewSurface, which the clamp leaves alone), with them made DwaBaseMaterial (which it roughens), and
as DwaBaseMaterial with rough gold balls among near-mirror metal, where the clamp blurs what the balls reflect.
What the clamp changes in one engine should be what it changes in the other.
check_moonlightipr_roughness_clamp.py <runtime folder>"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import compare_moonlightipr as compare
from moonray_modo import native

runtime = native.find_runtime(sys.argv[1])
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
folder = ROOT / 'test-results/moonlightipr-roughness-clamp'
folder.mkdir(parents=True, exist_ok=True)
session = compare.fixture.Session(folder)
session.runtime = runtime


def mean(values):
    return sum(values) / len(values)


def scene(kind, factor):
    held = compare.fixture.snapshot()
    held['render_settings'] = dict(held.get('render_settings', {}), roughness_clamping_factor=factor)
    if kind in ('dwabase', 'mirrors'):
        held['materials'] = {tag: dict(material, shader='DwaBaseMaterial') for tag, material in held['materials'].items()}
    if kind == 'mirrors':
        # Where the clamp shows: rough gold balls that see near-mirror metal cubes and floor, which the clamp blurs
        # in their reflections.
        held['materials']['gold'].update(roughness=0.6)
        for tag in ('', 'red', 'blue'):
            held['materials'][tag].update(roughness=0.02, metallic=1)
    return held


pictures = {}
try:
    for kind in ('plain', 'dwabase', 'mirrors'):
        for factor in (0.0, 1.0):
            name = '%s_clamp%g' % (kind, factor)
            pictures['moonray', kind, factor] = compare.moonray(scene(kind, factor), runtime, folder, name)
            pictures['moonlightipr', kind, factor] = compare.moonlightipr(scene(kind, factor), session, name)[0]
finally:
    if session.process.poll() is None:
        session.process.kill()

for kind in ('plain', 'dwabase', 'mirrors'):
    print('== %s materials' % kind)
    changes = {}
    for engine in ('moonray', 'moonlightipr'):
        off, on = pictures[engine, kind, 0.0], pictures[engine, kind, 1.0]
        changes[engine] = [y - x for x, y in zip(compare.blocks(off), compare.blocks(on))]
        print('   %-12s mean %.4f -> %.4f with the clamp; blocks changed by %.4f on average, at most %.4f'
              % (engine, mean(off), mean(on), mean([abs(v) for v in changes[engine]]), max(abs(v) for v in changes[engine])))
    for factor in (0.0, 1.0):
        a, b = compare.blocks(pictures['moonray', kind, factor]), compare.blocks(pictures['moonlightipr', kind, factor])
        print('   clamp %g: MoonLightIPR against MoonRay, blocks mean |difference| %.4f' % (factor, mean([abs(x - y) for x, y in zip(a, b)])))
    moved = [i for i, v in enumerate(changes['moonray']) if abs(v) > 0.01]
    if moved:
        print('   blocks the clamp changes in MoonRay by over 0.01: %d; there MoonLightIPR changes them by %+.4f on average against MoonRay\'s %+.4f'
              % (len(moved), mean([changes['moonlightipr'][i] for i in moved]), mean([changes['moonray'][i] for i in moved])))
