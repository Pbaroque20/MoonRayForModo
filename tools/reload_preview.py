# python
"""Reload the updated preview without closing Modo or changing scene geometry."""
import importlib
import json
from pathlib import Path
import traceback
import lx
from PySide2 import QtWidgets
from moonray_modo import host, rdla, panel

root = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
result_path = root / 'test-results/shadow-terminator/installed-preview.json'
report = {'app_version': lx.eval('query platformservice appversion ?'), 'passed': False}

try:
    previous = next((w for w in QtWidgets.QApplication.allWidgets()
                     if isinstance(w, panel.Panel) and w.isVisible()), None)
    settings = None
    if previous is not None:
        settings = (previous.runtime.text(), previous.size.currentIndex(), previous.samples.value(),
                    previous.environment.value(), previous.threads.value())
        previous.stop()
        lx.eval('moonray.open')
    for module in (host, rdla, panel):
        importlib.reload(module)
    lx.eval('moonray.open')
    current = next(w for w in QtWidgets.QApplication.allWidgets()
                   if isinstance(w, panel.Panel) and w.isVisible())
    if settings:
        runtime, size, samples, environment, threads = settings
        current.runtime.setText(runtime)
        current.size.setCurrentIndex(size)
        current.samples.setValue(samples)
        current.environment.setValue(environment)
        current.threads.setValue(threads)
    # A preview-only override for this shadow investigation; never edit the model.
    current.surface.setCurrentIndex(1)
    current.subdivision_level.setValue(3)

    def completed(output):
        try:
            image = root / 'test-results/shadow-terminator/installed-preview.png'
            if current.preview.image.isNull():
                raise RuntimeError('No rendered image in the updated panel')
            current.preview.image.save(str(image), 'PNG')
            report.update(passed=True, image=str(image), visible=current.isVisible(),
                          surface=current.surface.currentText(), live=current.live.isChecked())
        except Exception:
            report['error'] = traceback.format_exc()
        result_path.write_text(json.dumps(report, indent=2), encoding='utf-8')

    def failed(message):
        report.update(passed=False, error=str(message))
        result_path.write_text(json.dumps(report, indent=2), encoding='utf-8')

    current.renderer.finished.connect(completed)
    current.renderer.failed.connect(failed)
    current.live.setChecked(True)
except Exception:
    report['error'] = traceback.format_exc()
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
