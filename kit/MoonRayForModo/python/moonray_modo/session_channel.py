"""One acknowledged command at a time in an event-backed Windows mapping."""
import ctypes,mmap,os,struct,uuid
from ctypes import wintypes

class Channel:
 def __init__(self):
  self.name='Local\\MoonRayForModoCommand_%d_%s'%(os.getpid(),uuid.uuid4().hex)
  self.memory=mmap.mmap(-1,65536,tagname=self.name,access=mmap.ACCESS_WRITE)
  self.api=ctypes.WinDLL('kernel32',use_last_error=True)
  self.api.CreateEventW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR];self.api.CreateEventW.restype=wintypes.HANDLE
  self.api.SetEvent.argtypes=[wintypes.HANDLE];self.api.SetEvent.restype=wintypes.BOOL
  self.api.CloseHandle.argtypes=[wintypes.HANDLE]
  self.event=self.api.CreateEventW(None,True,False,self.name+'_ready')
  if not self.event:self.memory.close();raise OSError('Cannot create scene command event')
 def send(self,text):
  payload=text.encode('utf-8')
  if not 0<len(payload)<=65532:raise ValueError('Scene command is too large')
  self.memory.seek(4);self.memory.write(payload)
  self.memory.seek(0);self.memory.write(struct.pack('<I',len(payload)))
  if not self.api.SetEvent(self.event):raise OSError('Cannot publish scene command')
 def close(self):
  if self.event:self.api.CloseHandle(self.event);self.event=None
  self.memory.close()
