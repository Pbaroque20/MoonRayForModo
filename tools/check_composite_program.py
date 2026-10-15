"""The compositor program against the image tool, node by node, and the graphics card against the processor.

For each kind of node (with settings that reach its edge cases), a graph is made over a render's beauty: the buffer,
the node, the output. Its picture is made three ways: by the image tool, step after step, as the compositor did; by the
compositor program on the graphics card; and by it on the processor. Printed for each: the largest and the mean
difference between the image tool's picture and the program's, and between the program's two. The program on the two
must agree; with the image tool, Blur and Glow above a radius of 4, and Grain, are expected to differ (the image tool
shrank the picture for a wide blur, and its noise is its own).

check_composite_program.py <runtime folder> <beauty.exr> [<program folder>]"""
import pathlib
import struct
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import compositor, native

runtime = pathlib.Path(sys.argv[1]).resolve()
beauty = pathlib.Path(sys.argv[2]).resolve()
program = pathlib.Path(sys.argv[3]).resolve() / 'modo_composite.exe' if len(sys.argv) > 3 else root / 'build/moonlightipr/stage/modo_composite.exe'
env = native.environment(runtime)


def graph(**nodes):
    return {'nodes': {key: {'type': kind, 'parameters': held, 'inputs': inputs, 'position': [0, 0]} for key, (kind, held, inputs) in nodes.items()},
            'root': 'out'}


def single(kind, **held):
    return graph(a=('input', {'buffer': 'beauty'}, {}), n=(kind, held, {'image': 'a'}), out=('output', {}, {'image': 'n'}))


CASES = [
    ('grade', single('grade', exposure=0.7, gamma=1.6, saturation=1.4, tint=[1.0, 0.9, 0.8])),
    ('grade, gamma 1', single('grade', exposure=-0.5, gamma=1.0, saturation=0.3, tint=[1.0, 1.0, 1.0])),
    ('levels', single('levels', black=0.05, white=0.9, gamma=1.3, out_black=0.02, out_white=0.95)),
    ('contrast', single('contrast', contrast=1.6, pivot=0.18)),
    ('invert', single('invert')),
    ('clamp', single('clamp', least=0.1, most=0.6)),
    ('tonemap', single('tonemap', exposure=1.0)),
    ('math power', single('math', operation='power', value=0.7)),
    ('math divide', single('math', operation='divide', value=3.0)),
    ('math most of', single('math', operation='most of', value=0.3)),
    ('blur 1', single('blur', radius=1.0)),
    ('blur 3.5', single('blur', radius=3.5)),
    ('blur 4', single('blur', radius=4.0)),
    ('blur 10 (image tool shrinks)', single('blur', radius=10.0)),
    ('glow 3', single('glow', threshold=0.5, radius=3.0, strength=0.8)),
    ('glow 12 (image tool shrinks)', single('glow', threshold=0.5, radius=12.0, strength=0.8)),
    ('sharpen 1.5', single('sharpen', amount=0.7, radius=1.5)),
    ('sharpen 0.75', single('sharpen', amount=1.2, radius=0.75)),
    ('sharpen 4.2', single('sharpen', amount=0.5, radius=4.2)),
    ('median 1', single('median', radius=1.0)),
    ('median 3', single('median', radius=3.0)),
    ('grow 2', single('grow', pixels=2.0)),
    ('shrink 3', single('grow', pixels=-3.0)),
    ('edges', single('edges', strength=2.0)),
    ('grain (own noise)', single('grain', amount=0.05, seed=3.0)),
    ('vignette', single('vignette', amount=0.6, falloff=0.7)),
    ('flip both', single('flip', direction='both')),
    ('flip top to bottom', single('flip', direction='top to bottom')),
    ('brightness matte', single('luma_matte', low=0.1, high=0.7, take='the dark')),
    ('channel green', single('channel', channel='green')),
    ('channel brightness', single('channel', channel='brightness')),
    ('colour', graph(c=('constant', {'color': [0.2, 0.5, 0.9]}, {}), out=('output', {}, {'image': 'c'}))),
    ('ramp down', graph(r=('ramp', {'direction': 'top to bottom', 'start': [0, 0, 0], 'end': [1, 0.5, 0.2]}, {}), out=('output', {}, {'image': 'r'}))),
]
for mode in compositor.MODES:
    CASES.append(('merge %s, masked' % mode, graph(
        a=('input', {'buffer': 'beauty'}, {}), g=('grade', {'exposure': 1.0, 'gamma': 1.0, 'saturation': 1.0, 'tint': [0.4, 0.8, 1.0]}, {'image': 'a'}),
        f=('flip', {'direction': 'left to right'}, {'image': 'g'}), k=('luma_matte', {'low': 0.0, 'high': 0.5, 'take': 'the bright'}, {'image': 'a'}),
        m=('merge', {'mode': mode, 'mix': 0.8}, {'a': 'a', 'b': 'f', 'mask': 'k'}), out=('output', {}, {'image': 'm'}))))


def run(steps, extra=()):
    for args, target in steps:
        command = ([args[1]] + args[2:] + list(extra)) if args[0] == '@run' else [str(runtime / 'oiiotool.exe')] + args
        done = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=0x08000000)
        if done.returncode or not pathlib.Path(target).is_file():
            raise RuntimeError(' '.join(map(str, command))[:300] + '\n' + done.stdout.decode(errors='replace')[-800:])
        if args[0] == '@run':
            run.said = done.stdout.decode(errors='replace').strip()


def pixels(path, folder):
    pfm = pathlib.Path(folder) / (pathlib.Path(path).stem + '-read.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(path), '--ch', '0,1,2', '-d', 'float', '-o', str(pfm)], env=env, check=True, creationflags=0x08000000)
    data = pfm.read_bytes()
    header = data.split(b'\n', 3)
    width, height = map(int, header[1].split())
    return struct.unpack(('<' if float(header[2]) < 0 else '>') + '%df' % (width * height * 3), header[3])


def compare(a, b):
    worst = max(abs(x - y) for x, y in zip(a, b))
    return worst, sum(abs(x - y) for x, y in zip(a, b)) / len(a)


# MOONRAY_CHECK_ONLY: only the cases whose names hold it.
import os
if os.environ.get('MOONRAY_CHECK_ONLY'):
    CASES = [case for case in CASES if os.environ['MOONRAY_CHECK_ONLY'] in case[0]]
print('%-32s %26s   %26s' % ('', 'image tool vs program (gpu)', 'program gpu vs cpu'))
for name, built in CASES:
    with tempfile.TemporaryDirectory() as old_folder, tempfile.TemporaryDirectory() as gpu_folder, tempfile.TemporaryDirectory() as cpu_folder:
        files, kinds = {'beauty': beauty}, {'beauty': 'beauty'}
        steps, old = compositor.jobs(built, files, kinds, old_folder)
        run(steps)
        steps, gpu = compositor.jobs(built, files, kinds, gpu_folder, composite=program)
        run(steps)
        on_gpu = run.said
        steps, cpu = compositor.jobs(built, files, kinds, cpu_folder, composite=program)
        run(steps, ['--cpu'])
        a, g, c = pixels(old, old_folder), pixels(gpu, gpu_folder), pixels(cpu, cpu_folder)
        print('%-32s largest %9.2e mean %9.2e   largest %9.2e mean %9.2e   %s' % ((name,) + compare(a, g) + compare(g, c) + (on_gpu.split('\n')[-1][:24],)), flush=True)
