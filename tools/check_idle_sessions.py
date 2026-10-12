"""Validate idle release and restart with real Qt renderer sessions (no Modo scene).

Run with a PySide2-capable Python; pass --moonray and --moonlight runtime folders.
The timeout is accelerated by aging the idle timestamp; no renderer is mocked.
"""
import argparse,json,os,sys,time,traceback,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'kit/MoonRayForModo/python')]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--moonray',type=Path,required=True)
parser.add_argument('--moonlight',type=Path,required=True)
parser.add_argument('--output',type=Path,default=ROOT/'test-results/idle-sessions')
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
os.environ['MOONRAY_MODO_PREFERENCES']='IdleCheck-'+uuid.uuid4().hex
from PySide2 import QtCore
from moonray_modo import persistent,moonlightipr_session,rdla
from moonray_modo.preferences import Preferences
from check_moonlightipr_session import snapshot
app=QtCore.QCoreApplication(sys.argv)
prefs=Preferences();prefs.set('idle_release_minutes',1)
report={'ok':False,'engines':{}}
scene=snapshot();scene['render_settings']={'sampling_mode':0};scene['preview_buffer']='beauty'
def wait_until(predicate,seconds=120):
    until=time.monotonic()+seconds
    while not predicate():
        app.processEvents()
        if time.monotonic()>until:raise TimeoutError('Renderer event timeout')
        time.sleep(.01)
def exercise(name):
    session=persistent.Session() if name=='MoonRay' else moonlightipr_session.Session()
    state={'done':[],'frames':{},'failures':[],'pids':[],'log':''}
    session.ready.connect(state['done'].append)
    session.failed.connect(state['failures'].append)
    session.output.connect(lambda text:state.update(log=state['log']+text))
    session.memory_image.connect(lambda packet:state['frames'].__setitem__(packet[0],len(packet[4])))
    def submit(generation):
        if name=='MoonRay':
            scene['preview_buffer_file']=str(args.output/('%d.exr'%generation))
            session.submit(rdla.scene_text(scene,64,64,1,1),args.moonray,2,'xpu',generation)
        else:session.submit(scene,args.moonlight,64,64,1,generation,samples=4,denoise=False,runtime=args.moonray)
    try:
        for generation in (1,2,3):
            submit(generation)
            assert not session.idle.release_now(),'Pending render accepted idle release'
            wait_until(lambda:generation in state['done'] or bool(state['failures']))
            assert not state['failures'],state['failures']
            assert session.running(),'Process did not stay alive after completion'
            pid=int(session.process.processId());state['pids'].append(pid)
            assert pid>0 and len(set(state['pids']))==generation,'Released process was reused'
            assert session.idle.since is not None,'Completion did not arm idle release'
            assert state['frames'].get(generation,0)>0,'No progressive frame received'
            if generation==2:
                # Exercise the real timeout handler without spending a minute idle.
                session.idle.since=time.monotonic()-61
                session.idle._tick()
            else:assert session.idle.release_now(),'Completed renderer refused manual release'
            wait_until(lambda:not session.running() and not session.stopping,15)
            assert not state['failures'],state['failures']
            assert session.process.processId()==0,'Child PID still registered after release'
            assert session.idle.since is None,'Idle timer remained armed'
        if name=='MoonRay':assert 'GPU: Setup complete' in state['log'],'MoonRay XPU setup not confirmed'
        report['engines'][name]={'ok':True,'pids':state['pids'],'completed':state['done'],'frame_bytes':state['frames'],'manual_release':True,'accelerated_timeout':True,'restart_after_release':True}
    finally:
        session.close()
        (args.output/(name+'.log')).write_text(state['log'],encoding='utf-8')
try:
    assert persistent.supported(args.moonray),'MoonRay persistent runtime missing/mismatched'
    assert moonlightipr_session.supported(args.moonlight),'MoonLightIPR runtime missing'
    exercise('MoonRay');exercise('MoonLightIPR');report['ok']=True
except Exception:report['error']=traceback.format_exc()
finally:
    prefs.store.clear()
    (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
raise SystemExit(0 if report['ok'] else 1)
