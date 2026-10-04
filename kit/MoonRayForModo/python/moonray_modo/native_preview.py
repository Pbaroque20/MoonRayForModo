"""Main-thread controller for the C++ external-render server and linear EXR frames."""
import ctypes
import hashlib
import json
import time
import lx
import lxifc
from pathlib import Path
from PySide2 import QtCore
from . import host,native,properties,idle
from .render import Renderer

_controller=None
_startup_idle=None

class ShutdownListener(lxifc.SessionListener):
    def sesl_QuittingUI(self):
        if _controller is not None: _controller.close()

    def sesl_ShuttingDown(self):
        if _controller is not None: _controller.close()

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
        self.closed=False
        self.idle=idle.Dispatcher()
        self.shutdown_listener=ShutdownListener()
        self.shutdown_listener_com=lx.object.Unknown(self.shutdown_listener)
        lx.service.Listener().AddListener(self.shutdown_listener_com)
        self.timer=idle.Timer(self.tick)
        self.timer.start()
        QtCore.QCoreApplication.instance().aboutToQuit.connect(self.close)

    def status(self,identity,message):
        if self.closed: return
        self.idle.submit(('status',identity),lambda:self.bridge.MR_preview_status(identity,message.encode('utf-8')))

    def queue_frame(self,identity,path):
        session=self.sessions.get(identity)
        if self.closed or session is None: return
        generation=session['renderer'].generation
        session['awaiting_frame']=generation
        def transfer():
            current=self.sessions.get(identity)
            if not current or current['renderer'].generation!=generation: return
            current.pop('awaiting_frame',None)
            self.publish(identity,path)
        self.idle.submit(('frame',identity),transfer)

    def publish(self,identity,path):
        if self.closed: return
        session=self.sessions.get(identity)
        completed=int(bool(session) and not session['renderer'].passes)
        result=self.bridge.MR_preview_publish(identity,str(path).encode('utf-8'),completed)
        if result==0:
            # A queued frame can arrive after the user pauses/closes PView.
            if session:
                session.pop('pending_frame',None)
                session.pop('pending_since',None)
            return
        if result in (-2,2) and session is not None:
            # PView can withhold its buffer while opening, paused or resizing.
            # Retain the latest frame instead of losing the finished render.
            session['pending_frame']=path
            since=session.setdefault('pending_since',time.monotonic())
            if time.monotonic()-since >= 10:
                detail=(self.bridge.MR_preview_diagnostic(identity) or b'').decode('utf-8',errors='replace')
                self.errors[identity]='PView has not accepted the rendered image: '+detail
                self.status(identity,self.errors[identity])
            else:
                self.status(identity,'Waiting for PView image buffer')
            return
        if result!=1:
            self.errors[identity]='Native preview image transfer failed (%d)' % result
            detail=self.bridge.MR_preview_diagnostic(identity)
            if detail:
                self.errors[identity]+=': '+detail.decode('utf-8',errors='replace')
            self.status(identity,self.errors[identity])
        else:
            self.errors.pop(identity,None)
            if session:
                session.pop('pending_frame',None)
                session.pop('pending_since',None)
                if completed: self.status(identity,'Preview complete')

    def capture(self):
        values=properties.scene_settings()
        scene=host.snapshot(evaluated_geometry=values.get('surface',0)==2)
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
        if self.closed: return
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
                renderer.image_ready.connect(lambda path,i=identity:self.queue_frame(i,path))
                renderer.finished.connect(lambda path,i=identity:self.completed(i))
                session={'renderer':renderer,'digest':None,'running':False}
                self.sessions[identity]=session
            try:
                if session.get('pending_frame'):
                    self.publish(identity,session['pending_frame'])
                if captured is None: captured=self.capture()
                scene,values,runtime=captured
                digest=hashlib.sha256(json.dumps([scene,values,runtime,revision.value],sort_keys=True).encode()).hexdigest()
                if digest!=session['digest'] or not session['running']:
                    session.pop('pending_frame',None)
                    session.pop('pending_since',None)
                    session.pop('awaiting_frame',None)
                    self.errors.pop(identity,None)
                    width=min(640,scene['width']); height=max(16,round(width*scene['height']/scene['width']))
                    session['renderer'].submit(scene,runtime,width,height,values.get('samples',4),
                        values.get('environment',0),values.get('threads',0),linear_preview=True)
                    session.update(digest=digest,running=True)
            except Exception as exc: self.failure(identity,str(exc))

    def failure(self,identity,text):
        self.errors[identity]=text
        self.status(identity,text)

    def completed(self,identity):
        session=self.sessions.get(identity,{})
        if identity not in self.errors and not session.get('pending_frame') and 'awaiting_frame' not in session:
            self.status(identity,'Preview complete')

    def close(self):
        if self.closed: return
        self.closed=True
        self.timer.stop()
        self.idle.close()
        lx.service.Listener().RemoveListener(self.shutdown_listener_com)
        for session in self.sessions.values(): session['renderer'].close()
        self.sessions.clear()
        shutdown=getattr(self.bridge,'MR_preview_shutdown',None)
        if shutdown is not None:
            shutdown.argtypes=[]
            shutdown.restype=None
            shutdown()

def start(path=None):
    global _controller
    if _controller is not None: return _controller
    if QtCore.QCoreApplication.instance() is None: return None
    path=Path(path) if path else Path(__file__).resolve().parents[2]/'bin/MoonRayPreview.lx'
    if not path.is_file(): return None
    # Modo tears down SDK services before Qt's final application destruction.
    # The session listener stops polling before those interfaces disappear.
    _controller=Controller(path)
    return _controller

def start_when_idle():
    global _startup_idle
    if _startup_idle is None: _startup_idle=idle.Dispatcher()
    _startup_idle.submit('start',start)
