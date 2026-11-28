# python
"""Isolated GUI test: Shader Tree -> MoonShine and MoonShine -> Shader Tree switch realtime off first. The round-3 scene
(MOONRAY_PROBE_SCENE) opened, the preview opened with MoonLightIPR and RT on, the conversion run (shader_tree_dialog.run,
no window), RT read back; RT on again, the revert run, RT read back. report.json in MOONRAY_PROBE_OUT (else
test-results/convert-rt-off)."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\convert-rt-off')
out.mkdir(parents=True, exist_ok=True)
scene = os.environ.get('MOONRAY_PROBE_SCENE') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results\shader-tree-round3\round3.lxo'
result = {'errors': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def later(call, ms=1500):
    def run():
        try:
            call()
        except Exception:
            result['errors'].append(traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(ms, run)


def finish():
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


def panel():
    from moonray_modo.panel import live_panels
    found = live_panels()
    return found[0] if found else None


def rt_state(p):
    return {'rt_button': p.rt.isChecked(), 'ipr': p.ipr_mode.isChecked(), 'following': bool(getattr(p, '_following', False)),
            'status': p.status.text()}


def rt_on():
    p = panel()
    result.setdefault('panels', len(__import__('moonray_modo.panel', fromlist=['live_panels']).live_panels()))
    index = p.preview_engine.findData('moonlightipr')
    p.preview_engine.setCurrentIndex(index)
    later(lambda: (p.rt.setChecked(True), later(convert, 6000)), 1500)


def convert():
    from moonray_modo import shader_tree_dialog
    p = panel()
    result['before_convert'] = rt_state(p)
    result['convert_lines'] = shader_tree_dialog.run('current', show=False)
    result['after_convert'] = rt_state(p)
    p.rt.setChecked(True)
    later(revert, 6000)


def revert():
    from moonray_modo import shader_tree_dialog
    p = panel()
    result['before_revert'] = rt_state(p)
    result['revert_lines'] = shader_tree_dialog.revert(show=False, ask=False)
    result['after_revert'] = rt_state(p)
    p.rt.setChecked(False)
    later(finish, 2000)


try:
    lx.eval('!scene.open {%s} normal' % scene)
    lx.eval('moonray.page preview')
    later(rt_on, 4000)
except Exception:
    result['errors'].append(traceback.format_exc())
    save()
    lx.eval('!app.quit')
