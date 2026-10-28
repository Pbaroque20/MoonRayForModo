"""Read only an existing immutable renderer mapping; acknowledge in every exit path."""
import ctypes,re
from ctypes import wintypes
MAX_BYTES=64*1024*1024

class Withdrawn(OSError):
 """A frame the renderer has already taken back: it waits five seconds for a frame to be read, and Modo's thread was
 busy for longer (a fast drag of a heavy scene). Newer frames follow; nothing is wrong with the render."""

def receive(line,pid):
 parts=line.split()
 if len(parts)!=6 or parts[0]!='@@MODO_SHARED':raise ValueError('Malformed image publication')
 _,generation,key,width,height,name=parts
 generation,width,height=int(generation),int(width),int(height)
 if not re.fullmatch(r'Local\\MoonRayForModo_'+str(int(pid))+r'_\d+',name):raise ValueError('Unexpected image mapping owner')
 api=ctypes.WinDLL('kernel32',use_last_error=True)
 api.OpenFileMappingW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR];api.OpenFileMappingW.restype=wintypes.HANDLE
 api.OpenEventW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR];api.OpenEventW.restype=wintypes.HANDLE
 api.MapViewOfFile.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.c_size_t];api.MapViewOfFile.restype=ctypes.c_void_p
 api.UnmapViewOfFile.argtypes=[ctypes.c_void_p];api.CloseHandle.argtypes=[wintypes.HANDLE];api.SetEvent.argtypes=[wintypes.HANDLE]
 ack=api.OpenEventW(2,False,name+'_ack');mapping=None;view=None
 try:
  size=width*height*12
  if generation<0 or not 0<width<=16384 or not 0<height<=16384 or not 0<size<=MAX_BYTES or not re.fullmatch('[A-Za-z0-9_]{1,64}',key):raise ValueError('Invalid image dimensions or buffer key')
  if not ack:raise Withdrawn('Image acknowledgment event unavailable')
  mapping=api.OpenFileMappingW(4,False,name)
  if not mapping:raise Withdrawn('Image mapping unavailable')
  view=api.MapViewOfFile(mapping,4,0,0,size)
  if not view:raise OSError('Cannot map image pixels')
  return generation,key,width,height,ctypes.string_at(view,size)
 finally:
  if view:api.UnmapViewOfFile(view)
  if mapping:api.CloseHandle(mapping)
  if ack:api.SetEvent(ack);api.CloseHandle(ack)
