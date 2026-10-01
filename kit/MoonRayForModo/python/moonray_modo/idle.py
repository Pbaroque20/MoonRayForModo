"""Run host work only from Modo's safe main-loop idle callback."""
from collections import OrderedDict
import traceback
import lx
import lxifc

# ALL_IDLE, excluding APP_MUST_BE_ACTIVE (renders may continue in background).
FLAGS=0x0fff

class Dispatcher(lxifc.Visitor):
    def __init__(self):
        self.platform=lx.service.Platform()
        self.visitor=lx.object.Visitor(self)
        self.pending=OrderedDict()
        self.armed=False
        self.closed=False

    def submit(self,key,callback):
        if self.closed: return
        self.pending[key]=callback
        if not self.armed:
            self.armed=True
            self.platform.DoWhenUserIsIdle(self.visitor,FLAGS)

    def vis_Evaluate(self):
        self.armed=False
        pending=list(self.pending.values())
        self.pending.clear()
        for callback in pending:
            if self.closed: break
            try: callback()
            except Exception: lx.out(traceback.format_exc())

    def close(self):
        self.closed=True
        self.pending.clear()
        if self.armed:
            self.platform.CancelDoWhenUserIsIdle(self.visitor,FLAGS)
            self.armed=False

class Timer(lxifc.Visitor):
    def __init__(self,callback,interval=1200,repeat=True):
        self.platform=lx.service.Platform()
        self.visitor=lx.object.Visitor(self)
        self.callback=callback
        self.interval=interval
        self.repeat=repeat
        self.active=False
        self.armed=False

    def start(self):
        if self.active: return
        self.active=True
        self._arm()

    def _arm(self):
        self.armed=True
        self.platform.TimerStart(self.visitor,self.interval,FLAGS)

    def vis_Evaluate(self):
        self.armed=False
        if not self.active: return
        try: self.callback()
        finally:
            if self.active and self.repeat: self._arm()
            else: self.active=False

    def stop(self):
        self.active=False
        if self.armed:
            self.platform.TimerCancel(self.visitor,FLAGS)
            self.armed=False
