# python
"""Isolated GUI test: Export AOVs. A group's own checkbox, clicked, unticks and ticks what is under it; the window's
writers save a beauty with the render's alpha as PNG and as OpenEXR, and the outputs as one multilayer OpenEXR. The
buffers are small made-up files in test-results/export-alpha. Writes report.json there and a picture of the window."""
import json
import pathlib
import subprocess
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/export-alpha'
out.mkdir(parents=True, exist_ok=True)
runtime = root / 'dist/personal-kit/Luxology/Kits/MoonRayForModo/runtime'
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def tool(args):
    from moonray_modo import native
    return subprocess.run([str(runtime / 'oiiotool.exe')] + [str(a) for a in args], env=native.environment(runtime), capture_output=True, text=True,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout


def check():
    try:
        from moonray_modo.panel import Panel
        from moonray_modo.export_dialog import ExportAOVs
        panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        entries = [('beauty', 'Beauty', 'Pictures', 'beauty'), ('denoised_beauty', 'Denoised Beauty', 'Pictures', 'beauty'),
                   ('albedo', 'Albedo', 'Surface data', 'color'), ('alpha', 'Alpha', 'Surface data', 'alpha')]
        dialog = ExportAOVs(panel, entries, QtCore.QSettings('MoonRayForModo', 'ProbeExportAlpha'))
        dialog.show()
        whole, boxes = dialog.groups['Pictures']
        result['pictures at first'] = [whole.isChecked(), [b.isChecked() for b in boxes]]
        whole.click()
        result['pictures unticked'] = [whole.isChecked(), [b.isChecked() for b in boxes]]
        whole.click()
        result['pictures ticked'] = [whole.isChecked(), [b.isChecked() for b in boxes]]
        dialog.kind.setCurrentIndex(dialog.kind.findData('exr16'))
        dialog.layers.setChecked(True)
        result['multilayer files'] = dialog.names.text()
        dialog.grab().save(str(out / 'dialog.png'))
        dialog.kind.setCurrentIndex(dialog.kind.findData('png8'))
        result['multilayer offered for png'] = dialog.layers.isEnabled()
        dialog.reject()
        # The writers on made-up buffers: a beauty premultiplied by an alpha of one half.
        made = out / 'buffers'
        made.mkdir(exist_ok=True)
        for name, colour in (('beauty', '0.25,0.25,0.25'), ('alpha', '0.5,0.5,0.5'), ('albedo', '0.8,0.1,0.1')):
            tool(['--create', '8x8', '3', '--fill:color=' + colour, '0,0,8,8', '-d', 'float', '-o', made / (name + '.exr')])
        frame = {'files': {key: str(made / (key + '.exr')) for key in ('beauty', 'alpha', 'albedo')}, 'runtime': str(runtime), 'snapshot': {}}
        written = {}
        for kind, name in (('png8', 'beauty.png'), ('exr16', 'beauty_out.exr')):
            target = panel.write_buffer(frame, 'beauty', out / name, kind)
            written[name] = tool(['--info', '-v', target]).splitlines()[1:2] + [line.strip() for line in tool(['--no-autopremult', target, '--printstats']).splitlines() if 'Avg' in line]
        layered, failed = panel.write_layered(frame, ['albedo', 'beauty', 'alpha'], out / 'render.exr', 'exr16')
        written['render.exr'] = [line.strip() for line in tool(['--info', '-v', out / 'render.exr']).splitlines() if 'channel list' in line] + [failed]
        result['written'] = written
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(300, lambda: lx.eval('!app.quit'))


try:
    lx.eval('moonray.open')
except Exception:
    result['open'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(6000, check)
