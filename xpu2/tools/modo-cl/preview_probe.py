# python
"""Headless Modo probe: each scene in MOONRAY_PROBE_SCENES (';') read as the preview reads it (host.snapshot, the
scene's render settings applied as the preview window applies them) and written as the preview hands it to the
renderer: text with the geometry's long lists as binary (rdlb.py's split scene), and as text alone, into
MOONRAY_PROBE_OUT/<scene name>/ (preview.rdla + preview.rdlb, text.rdla), at the scene's size."""
import json
import os
import pathlib
import traceback
import lx

out_root = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
for source in [pathlib.Path(s) for s in os.environ['MOONRAY_PROBE_SCENES'].split(';') if s]:
    out = out_root / source.stem
    out.mkdir(parents=True, exist_ok=True)
    result = {'scene': str(source)}
    try:
        lx.eval('scene.open {%s} normal' % source)
        from moonray_modo import host, rdla, rdlb
        snapshot = host.snapshot()
        try:
            from moonray_modo import scene_settings, properties
            from moonray_modo.scene_setup import configure
            values = scene_settings.complete(properties.scene_settings())
            values['preview_buffer'] = 'beauty'
            configure(snapshot, values)
            result['configured'] = True
        except Exception:
            result['configure_error'] = traceback.format_exc()[-600:]
        snapshot['_geometry_revision'] = 'probe-1'
        width, height = snapshot.get('width', 640), snapshot.get('height', 360)
        result['size'] = [width, height]
        with rdlb.collecting() as sink:
            split = rdla.scene_text(snapshot, width, height, 2, 0.15, str(out / 'preview.exr'))
        (out / 'preview.rdla').write_text(split, encoding='utf-8')
        sink.write(out / 'preview.rdlb')
        text = rdla.scene_text(snapshot, width, height, 2, 0.15, str(out / 'text.exr'))
        (out / 'text.rdla').write_text(text, encoding='utf-8')
        result['warnings'] = list(snapshot.get('warnings', []))[:40]
    except Exception:
        result['error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    try:
        lx.eval('scene.close')
    except Exception:
        pass
