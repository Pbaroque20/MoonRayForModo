"""Bounded native display conversion in a worker thread; no renderer restart."""
import ctypes,os
from pathlib import Path
from PySide2 import QtCore
from . import display,working_space

KINDS={'beauty':0,'normal':1,'geometric_normal':1,'alpha':2,'wireframe':2,'uv':3,'diffuse_direct':0,'glossy_direct':0,'emission':0,'transmission':0}

def supported(kind,settings,runtime):
 v=display.values(settings)
 return kind in KINDS and v['view']!='ocio' and not v['lut'] and (Path(runtime)/'modo_display.dll').is_file()

class Worker(QtCore.QThread):
 result=QtCore.Signal(object)
 def __init__(self,pixels,width,height,kind,settings,runtime,parent=None):
  super().__init__(parent);self.pixels=pixels;self.width=width;self.height=height;self.kind=kind;self.settings=settings;self.runtime=Path(runtime)
 def run(self):
  try:
   v=display.values(self.settings);size=self.width*self.height*4
   if len(self.pixels)!=self.width*self.height*12 or len(self.pixels)>64*1024*1024:raise ValueError('Invalid float image size')
   # Loading by absolute path and scoping dependency lookup avoids Modo DLL collisions.
   with os.add_dll_directory(str(self.runtime)):
    lib=ctypes.CDLL(str(self.runtime/'modo_display.dll'))
   fn=lib.modoDisplay;fn.argtypes=[ctypes.c_void_p,ctypes.c_uint64,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint64,ctypes.c_int,ctypes.c_int,ctypes.c_float,ctypes.POINTER(ctypes.c_float)];fn.restype=ctypes.c_int
   matrix=working_space.TO_REC709 if v['working_space']=='acescg' and v['view']!='raw' else [[1,0,0],[0,1,0],[0,0,1]]
   matrix=(ctypes.c_float*9)(*[x for row in matrix for x in row]);output=ctypes.create_string_buffer(size)
   source=ctypes.c_char_p(self.pixels)
   if not fn(source,len(self.pixels),self.width,self.height,output,size,KINDS[self.kind],{'raw':0,'srgb':1,'reinhard':2}[v['view']],v['exposure'],matrix):raise ValueError('Native display rejected image')
   self.outcome=(output.raw,self.width,self.height,'')
  except Exception as exc:self.outcome=(None,0,0,str(exc))
