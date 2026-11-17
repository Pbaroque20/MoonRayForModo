# python
"""Command line: where an edit's motion work goes in a scene that moves (the Lamborghini unless PROBE_SCENE names
another), read as MoonLightIPR reads it: the frame read once, then each step realtime takes after an edit, timed and
profiled: shutter_moves (whether anything moves), capture_frame from the frame in hand (the scene with its motion), and
MoonLightIPR's packing of that scene with its meshes already sent once. Writes test-results/motion-profile/report.json:
each step's seconds and its 25 costliest calls, by their own time and with what they call."""
import cProfile
import io
import json
import os
import pathlib
import pstats
import time
import traceback
import lx

scene_path = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Lamborghini(1)\Lamborghini_Moonray.lxo')
out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\motion-profile'))
out.mkdir(parents=True, exist_ok=True)
report = {'scene': scene_path, 'steps': {}}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def profiled(name, call):
    profile = cProfile.Profile()
    began = time.monotonic()
    profile.enable()
    try:
        value = call()
    finally:
        profile.disable()
        seconds = round(time.monotonic() - began, 2)
        entry = report['steps'][name] = {'seconds': seconds}
        for order, key in (('tottime', 'own'), ('cumulative', 'with_callees')):
            text = io.StringIO()
            pstats.Stats(profile, stream=text).sort_stats(order).print_stats(25)
            entry[key] = [line for line in text.getvalue().splitlines() if line.strip()][4:32]
        save()
    return value


try:
    lx.eval('!scene.open {%s} normal' % scene_path)
    import modo
    from moonray_modo import host, animation, moonlightipr_scene
    fps = float(modo.Scene().fps)
    now = lx.service.Selection().GetTime()
    with host.by_engine('moonlightipr'):
        began = time.monotonic()
        frame = host.snapshot(evaluated_geometry=False)
        report['first_read_seconds'] = round(time.monotonic() - began, 2)
        frame = profiled('read_again', lambda: host.snapshot(evaluated_geometry=False))
        frame.pop('_evaluated_data', None)
        frame.pop('_full_capture', None)
        report['moving'] = profiled('shutter_moves', lambda: animation.shutter_moves(frame, False))
        moving = profiled('capture_frame', lambda: animation.capture_frame(now, False, True, fps, preview=True, frame=dict(frame)))
    from unittest import mock
    with mock.patch('moonray_modo.native.default_runtime', return_value=str(pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo/runtime')):
        began = time.monotonic()
        _, keys, _ = moonlightipr_scene.pack(dict(frame), 640, 360, environment=0)
        report['first_pack_seconds'] = round(time.monotonic() - began, 2)
        profiled('pack_motion', lambda: moonlightipr_scene.pack(moving, 640, 360, environment=0, known=keys))
        profiled('pack_motion_again', lambda: moonlightipr_scene.pack(moving, 640, 360, environment=0, known=keys))
except Exception:
    report['error'] = traceback.format_exc()
report['done'] = True
save()
