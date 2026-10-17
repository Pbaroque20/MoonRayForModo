"""Stereo cameras: which eye a render draws, and where that eye is, by MoonRay's own rules (PerspectiveCamera).

MoonRay draws one eye a render: its camera moves sideways by half the interocular distance, to the left for the left
eye, and its film moves the other way by that half times the focal length over the convergence distance, so that the
two eyes' pictures meet at the convergence distance. A Modo camera set to both eyes is rendered twice to a file, once
for each eye; a preview draws the left."""
import math

VIEWS = {'left': 1, 'right': 2}
COMPOSITES = ('anaRedCyan', 'anaGrayscale', 'anaRedCyanHalf', 'anaRedCyanOpt')


def view(camera, scene=None):
    """'left' or 'right' for a camera that renders an eye, None for one that renders from the middle. A render may
    ask for an eye (scene['_stereo_eye']); otherwise both eyes show the left."""
    held = camera.get('stereo')
    if not held:
        return None
    chosen = (scene or {}).get('_stereo_eye') or held.get('eye', 'both')
    return chosen if chosen in VIEWS else 'left'


def both(camera):
    """Whether a render to a file makes a picture for each eye."""
    held = camera.get('stereo')
    return bool(held) and held.get('eye', 'both') == 'both' and camera.get('projection', 'persp') == 'persp'


def offset(eye, interocular):
    """MoonRay's interocular offset (computeInterocularOffset): half the distance, positive for the left eye."""
    return (0.5 if eye == 'left' else -0.5) * float(interocular)


def lines(camera, scene=None):
    """What MoonRay's PerspectiveCamera is told for the eye this render draws."""
    from .rdla import number
    eye = view(camera, scene)
    if eye is None or camera.get('projection', 'persp') != 'persp':
        return []
    held = camera['stereo']
    return ['  ["stereo_view"] = %d,' % VIEWS[eye],
            '  ["stereo_interocular_distance"] = %s,' % number(max(0.0, float(held.get('interocular', .065)))),
            '  ["stereo_convergence_distance"] = %s,' % number(max(1e-5, float(held.get('convergence', 2.0))))]


def placed(camera, scene=None):
    """The camera moved to the eye, as MoonLightIPR is to see it: its place moved along its own x by the opposite of
    the offset, and its horizontal film offset, in millimetres, increased by the offset times the focal length over the
    convergence distance. The camera as it was for one that draws no eye."""
    eye = view(camera, scene)
    if eye is None or camera.get('projection', 'persp') != 'persp':
        return camera
    held = camera['stereo']
    shift = offset(eye, held.get('interocular', .065))
    convergence = max(1e-5, float(held.get('convergence', 2.0)))

    def moved(matrix):
        matrix = list(matrix)
        across = matrix[0:3]
        length = math.sqrt(sum(v * v for v in across)) or 1.0
        for i in range(3):
            matrix[12 + i] -= shift * across[i] / length
        return matrix

    film = list(camera.get('film_offset', [0.0, 0.0]))
    result = dict(camera, film_offset=[film[0] + shift * float(camera['focal_mm']) / convergence, film[1]])
    from .rdla import IDENTITY
    result['matrix'] = moved(camera.get('matrix', IDENTITY))
    if camera.get('matrix_close'):
        result['matrix_close'] = moved(camera['matrix_close'])
    return result


def eye_path(path, eye):
    """Where one eye of a render to a file is written: beside the file chosen, named for the eye."""
    from pathlib import Path
    path = Path(path)
    return path.with_name('%s_%s%s' % (path.stem, eye, path.suffix))


LUMA = '--chsum:weight=.299,.587,.114'


def composite_arguments(kind, left, right, path):
    """oiiotool's arguments for Modo's anaglyph composites of the two eyes: red from the left eye, green and blue from
    the right; in grey, each eye's brightness; half colour, the left in grey and the right in colour; optimized, the
    left's red made from its green and blue, which keeps reds from flickering between the eyes."""
    left, right, path = str(left), str(right), str(path)
    if kind == 'anaRedCyan':
        recipe = [left, '--ch', 'R', right, '--ch', 'G,B']
    elif kind == 'anaGrayscale':
        recipe = [left, '--ch', 'R,G,B', LUMA, '--ch', 'R=0', right, '--ch', 'R,G,B', LUMA, '--ch', 'G=0,B=0']
    elif kind == 'anaRedCyanHalf':
        recipe = [left, '--ch', 'R,G,B', LUMA, '--ch', 'R=0', right, '--ch', 'G,B']
    elif kind == 'anaRedCyanOpt':
        recipe = [left, '--ch', 'G,B', '--chsum:weight=.7,.3', '--ch', 'R=0', right, '--ch', 'G,B']
    else:
        raise ValueError('Unknown stereo composite: ' + str(kind))
    return recipe + ['--chappend', '-o', path]


def composite(runtime, kind, left, right, path):
    """Write the two eyes' composite to path with the runtime's oiiotool."""
    import subprocess
    from pathlib import Path
    from .native import environment
    tool = Path(runtime) / 'oiiotool.exe'
    if not tool.is_file():
        raise ValueError('This runtime has no oiiotool for the stereo composite: ' + str(tool))
    done = subprocess.run([str(tool)] + composite_arguments(kind, left, right, path), env=environment(runtime),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
    if done.returncode != 0:
        raise ValueError('The stereo composite failed: ' + done.stdout.decode(errors='replace')[-300:])
