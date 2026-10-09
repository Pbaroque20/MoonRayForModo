"""Reusable isolated display processor; binary pipes, no temporary image encoding."""
import atexit,struct,subprocess,threading
from functools import lru_cache
from pathlib import Path
from . import display,native,working_space
_lock=threading.Lock()
_process=None
_signature=None

@lru_cache(maxsize=4)
def _crypto_capability(path,mtime,size):
 return b'No Cryptomatte ID/coverage channel pairs found' in Path(path).read_bytes()

def available(runtime):return (Path(runtime)/'modo_display_stream.exe').is_file()

def _close():
 global _process,_signature
 process=_process;_process=None;_signature=None
 if process:
  if process.poll() is None:process.kill()
  try:process.wait(timeout=2)
  except subprocess.TimeoutExpired:pass
  for stream in (process.stdin,process.stdout):
   if stream:stream.close()
atexit.register(_close)

def close():
 with _lock:_close()

def _read(stream,size):
 result=bytearray()
 while len(result)<size:
  block=stream.read(size-len(result))
  if not block:raise RuntimeError('Display processor stopped before completing the image')
  result.extend(block)
 return bytes(result)

def convert(pixels,width,height,kind,settings,runtime,source=None):
 global _process,_signature
 if kind=='cryptomatte':
  helper=Path(runtime)/'modo_display_stream.exe';stat=helper.stat()
  if not _crypto_capability(str(helper),stat.st_mtime_ns,stat.st_size):raise ValueError('Selected runtime needs the updated Cryptomatte display processor')
  if source is None:raise ValueError('Cryptomatte preview requires a completed multichannel buffer')
 v=display.values({'view':'raw'}) if kind=='cryptomatte' else display.values(settings)
 for key in ('lut','config'):
  if v[key] and not display.built_in(v[key]) and not Path(v[key]).is_file():raise ValueError('Missing '+key+' file: '+v[key])
 if v['view']=='ocio' and not all(v[k] for k in ('source','display','ocio_view')):raise ValueError('OCIO source, display and view are required')
 args=[str(Path(runtime)/'modo_display_stream.exe'),kind,v['view'],str(v['exposure']),v['working_space'],v['lut'],v['lut_space'],v['config'],v['source'],v['display'],v['ocio_view'],' '.join(str(x) for row in working_space.TO_REC709 for x in row)]
 # Rebuild processors if the user edits the configuration or LUT in place.
 stamp=tuple((str(Path(v[k]).resolve()),Path(v[k]).stat().st_mtime_ns,Path(v[k]).stat().st_size) for k in ('lut','config') if v[k] and not display.built_in(v[k]))
 signature=(tuple(args),stamp)
 if source is None and (width<=0 or height<=0 or len(pixels)!=width*height*12 or len(pixels)>64*1024*1024):raise ValueError('Invalid float image size')
 with _lock:
  if _signature!=signature or _process is None or _process.poll() is not None:
   _close();_process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=native.environment(runtime),creationflags=subprocess.CREATE_NO_WINDOW);_signature=signature
  process=_process
  watchdog=threading.Timer(60,process.kill);watchdog.daemon=True;watchdog.start()
  try:
   if source is not None:
    path=str(Path(source).resolve()).encode('utf-8')
    if not 0<len(path)<=32768:raise ValueError('Image path too long')
    process.stdin.write(struct.pack('<III',0,0,len(path)));process.stdin.write(path)
   else:
    process.stdin.write(struct.pack('<III',width,height,0));process.stdin.write(pixels)
   process.stdin.flush()
   status,w,h=struct.unpack('<III',_read(process.stdout,12))
   if not status:
    if w>4096:raise RuntimeError('Invalid display error response')
    raise RuntimeError(_read(process.stdout,w).decode('utf-8',errors='replace'))
   if status!=1 or not w or not h or w*h*12>512*1024*1024:raise RuntimeError('Invalid display image response')
   return _read(process.stdout,w*h*4),w,h
  except Exception:
   _close();raise
  finally:watchdog.cancel()
