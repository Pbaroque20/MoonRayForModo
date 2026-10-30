# python
"""Headless Modo probe: for each scene in MOONRAY_PROBE_SCENES (';'), what MoonLightIPR's motion-blurred reading finds:
whether anything moves during the shutter (motion.moves), whether the meshes are rigid (incremental.rigid), which
items are animated, and the reading's time, into MOONRAY_PROBE_OUT/<scene name>/motion.json."""
import json
import os
import pathlib
import time
import traceback
import lx

out_root = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
for source in [pathlib.Path(s) for s in os.environ['MOONRAY_PROBE_SCENES'].split(';') if s]:
    out = out_root / source.stem
    out.mkdir(parents=True, exist_ok=True)
    result = {'scene': str(source)}
    try:
        lx.eval('scene.open {%s} normal' % source)
        import modo
        from moonray_modo import animation, motion, incremental, host, scene_settings, properties
        evaluated = scene_settings.complete(properties.scene_settings()).get('surface') == 2
        began = time.perf_counter()
        snapshot = animation.capture_current(evaluated)
        result['motion_reading'] = round(time.perf_counter() - began, 3)
        began = time.perf_counter()
        host.snapshot(evaluated_geometry=evaluated)
        result['still_reading'] = round(time.perf_counter() - began, 3)
        result['moves'] = motion.moves(snapshot)
        scene = modo.Scene()
        result['rigid'] = incremental.rigid(scene, host.snapshot(evaluated_geometry=evaluated))
        result['not_steady'] = sorted({i.type for i in scene.iterItems() if i.type not in incremental.STEADY
                                       and not i.type.startswith(('material.', 'moonray.'))})[:20]
        chan = scene.chanRead if hasattr(scene, 'chanRead') else None
        animated = []
        began = time.perf_counter()
        read = lx.object.Scene(lx.service.Selection().GetScene() if False else scene).Channels(lx.symbol.s_ACTIONLAYER_EDIT, 0.0) if False else None
        for item in scene.iterItems():
            for channel in item.channels():
                try:
                    if channel.isAnimated:
                        animated.append('%s.%s' % (item.name, channel.name))
                except Exception:
                    pass
            if len(animated) > 40:
                break
        result['animated_channels'] = animated[:40]
        result['animation_scan'] = round(time.perf_counter() - began, 3)
    except Exception:
        result['error'] = traceback.format_exc()[-2000:]
    (out / 'motion.json').write_text(json.dumps(result, indent=1, default=str))
    try:
        lx.eval('scene.close')
    except Exception:
        pass
