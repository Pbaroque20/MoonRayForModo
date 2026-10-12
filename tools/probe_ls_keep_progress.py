# python
"""Exercise persistent preview keep_progress during a deliberately unfinished pass."""
import json, os, time, traceback
from pathlib import Path
import lx
from PySide2 import QtCore
from moonray_modo import host
from moonray_modo.render import Renderer
root=Path(os.environ['MOONRAY_TEST_SOURCE'])
out=root/'test-results/ls-keep-progress';out.mkdir(parents=True,exist_ok=True)
report={};renderer=None;began=time.monotonic()
def save(): (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
def finish(ok=False):
    report['kept']=bool(ok)
    report['has_frame']=bool(renderer and renderer.buffers.frame)
    report['files']=sorted((renderer.buffers.frame or {}).get('files',{})) if renderer else []
    save()
    # Leave the session's read/kept signal stack before destroying its processes.
    def cleanup():
        if renderer:renderer.close()
        QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
    QtCore.QTimer.singleShot(100,cleanup)
def watch():
    if time.monotonic()-began>70:
        report['error']='Timed out waiting for an unfinished progressive pass';finish();return
    if renderer.failed_message:
        report['error']=renderer.failed_message;finish();return
    if renderer.buffers.progressive is not None and getattr(renderer,'writer',None) is None and renderer.phase=='render':
        report['requested']=renderer.keep_progress()
        report['session']=renderer.using_session
        report['grid']=renderer.sample_grid
        save()
        if report['requested']:
            QtCore.QTimer.singleShot(16000,lambda:finish() if 'kept' not in report else None)
            return
    QtCore.QTimer.singleShot(100,watch)
def begin():
    global renderer
    try:
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on');lx.eval('tool.apply');lx.eval('tool.set prim.sphere off')
        scene=host.snapshot()
        scene['render_settings']={'sampling_mode':2,'min_adaptive_samples':4096,'max_adaptive_samples':4096,'target_adaptive_error':0.001}
        scene['denoising']={'engine':'oidn_cpu','preview':True,'safe':False}
        renderer=Renderer();renderer.failed_message=''
        renderer.failed.connect(lambda text:setattr(renderer,'failed_message',text))
        renderer.kept.connect(finish)
        renderer.submit(scene,os.environ['MOONRAY_PROBE_RUNTIME'],640,360,64,1.0,2,persistent_preview=True)
        QtCore.QTimer.singleShot(200,watch)
    except Exception:
        report['error']=traceback.format_exc();save();QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
QtCore.QTimer.singleShot(1000,begin)
