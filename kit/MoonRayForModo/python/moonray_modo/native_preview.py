"""Main-thread controller for the C++ external-render server and linear EXR frames."""
import ctypes
import hashlib
import json
from pathlib import Path
from PySide2 import QtCore
from . import host,native,properties
from .render import Renderer

_controller=None

class Controller(QtCore.QObject):
    def __init__(self,path,parent=None):
        super().__init__(parent)
        self.bridge=ctypes.CDLL(str(path))
        self.bridge.MR_preview_ids.argtypes=[ctypes.POINTER(ctypes.c_uint),ctypes.c_uint]
        self.bridge.MR_preview_ids.restype=ctypes.c_uint
        self.bridge.MR_preview_state.argtypes=[ctypes.c_uint,ctypes.POINTER(ctypes.c_uint)]
        self.bridge.MR_preview_state.restype=ctypes.c_int
        self.bridge.MR_preview_status.argtypes=[ctypes.c_uint,ctypes.c_char_p]
        self.bridge.MR_preview_status.restype=ctypes.c_int
        self.bridge.MR_preview_publish.argtypes=[ctypes.c_uint,ctypes.c_char_p,ctypes.c_int]
        self.bridge.MR_preview_publish.restype=ctypes.c_int
        self.bridge.MR_preview_diagnostic.argtypes=[ctypes.c_uint]
        self.bridge.MR_preview_diagnostic.restype=ctypes.c_char_p
        self.sessions={}
        self.errors={}
        self.timer=QtCore.QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        QtCore.QCoreApplication.instance().aboutToQuit.connect(self.close)

    def status(self,identity,message):
        self.bridge.MR_preview_status(identity,message.encode('utf-8'))

    def publish(self,identity,path):
        session=self.sessions.get(identity)
        completed=int(bool(session) and not session['renderer'].passes)
        result=self.bridge.MR_preview_publish(identity,str(path).encode('utf-8'),completed)
        if result!=1:
            self.errors[identity]='Native preview image transfer failed (%d)' % result
            detail=self.bridge.MR_preview_diagnostic(identity)
            if detail:
                self.errors[identity]+=': '+detail.decode('utf-8',errors='replace')
            self.status(identity,self.errors[identity])
        else:
            self.errors.pop(identity,None)

    def capture(self):
        scene=host.snapshot()
        values=properties.scene_settings()
        scene['render_settings']=values.get('render',{})
        if values.get('region_enabled'): scene['region']=values.get('region',[0,0,1,1])
        if not values.get('modo_environment',True): scene['environments']=[]
        for light in scene.get('environments',[]): light['intensity']*=values.get('environment_multiplier',1)
        for light in scene['lights']: light['intensity']*=values.get('light_multiplier',1)
        for mesh in scene['meshes']:
            if mesh.get('object_override'): continue
            if values.get('surface',0)==1: mesh['subdivision']=True
            mesh['subdivision_level']=values.get('subdivision_level',3)
        settings=QtCore.QSettings('MoonRayForModo','NativePreview')
        runtime=str(settings.value('runtime',native.default_runtime()))
        return scene,values,runtime

    def tick(self):
        count=self.bridge.MR_preview_ids(None,0)
        ids=(ctypes.c_uint*max(1,count))()
        found=self.bridge.MR_preview_ids(ids,count)
        current=set(ids[:min(found,count)])
        for identity in set(self.sessions)-current:
            self.sessions.pop(identity)['renderer'].close()
            self.errors.pop(identity,None)
        captured=None
        for identity in current:
            revision=ctypes.c_uint()
            running=self.bridge.MR_preview_state(identity,ctypes.byref(revision))==1
            session=self.sessions.get(identity)
            if not running:
                if session and session['running']:
                    session['renderer'].stop(); session['running']=False
                continue
            if session is None:
                renderer=Renderer(self)
                renderer.status.connect(lambda text,i=identity:self.status(i,text))
                renderer.failed.connect(lambda text,i=identity:self.failure(i,text))
                renderer.image_ready.connect(lambda path,i=identity:self.publish(i,path))
                renderer.finished.connect(lambda path,i=identity:self.completed(i))
                session={'renderer':renderer,'digest':None,'running':False}
                self.sessions[identity]=session
            try:
                if captured is None: captured=self.capture()
                scene,values,runtime=captured
                digest=hashlib.sha256(json.dumps([scene,values,runtime,revision.value],sort_keys=True).encode()).hexdigest()
                if digest!=session['digest'] or not session['running']:
                    self.errors.pop(identity,None)
                    width=min(640,scene['width']); height=max(16,round(width*scene['height']/scene['width']))
                    session['renderer'].submit(scene,runtime,width,height,values.get('samples',4),
                        values.get('environment',0),values.get('threads',4),linear_preview=True)
                    session.update(digest=digest,running=True)
            except Exception as exc: self.failure(identity,str(exc))

    def failure(self,identity,text):
        self.errors[identity]=text
        self.status(identity,text)

    def completed(self,identity):
        if identity not in self.errors:
            self.status(identity,'Preview complete')

    def close(self):
        self.timer.stop()
        for session in self.sessions.values(): session['renderer'].close()
        self.sessions.clear()

def start(path=None):
    global _controller
    if _controller is not None: return _controller
    if QtCore.QCoreApplication.instance() is None: return None
    path=Path(path) if path else Path(__file__).resolve().parents[2]/'bin/MoonRayPreview.lx'
    if not path.is_file(): return None
    _controller=Controller(path,QtCore.QCoreApplication.instance())
    return _controller
