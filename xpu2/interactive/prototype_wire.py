"""Private bounded child-process transport; no renderer calls on the host thread."""
import array
from dataclasses import asdict
import json
import math
from pathlib import Path
import struct
import subprocess
import threading
from fallback import environment

MAX_PIXELS=1048576
MAX_HEADER=16384

def exact(stream,n):
    parts=[]
    while n:
        part=stream.read(n)
        if not part:raise EOFError('Native output pipe closed')
        parts.append(part);n-=len(part)
    return b''.join(parts)

def read_packet(stream):
    size=struct.unpack('<I',exact(stream,4))[0]
    if not 0<size<=MAX_HEADER:raise ValueError('Native header exceeds bound')
    header=json.loads(exact(stream,size))
    count=header.get('rgba_bytes')
    if type(count) is not int or count<0 or count>MAX_PIXELS*16:raise ValueError('Native pixel payload exceeds bound')
    if header.get('kind') in ('frame','decoded'):
        w,h=header.get('width'),header.get('height')
        if type(w) is not int or type(h) is not int or min(w,h)<=0 or w*h>MAX_PIXELS or w*h*16!=count:raise ValueError('Native image shape invalid')
    elif header.get('kind')!='error' or count:raise ValueError('Unknown native packet')
    for key in ('gpu_samples','cpu_samples','fine_refills','migrated_paths'):
        if key in header and (type(header[key]) is not int or not 0<=header[key]<2**64):raise ValueError('Invalid native counter')
    data=exact(stream,count)
    values=array.array('f');values.frombytes(data)
    if not all(math.isfinite(v) for v in values):raise ValueError('Nonfinite native pixel')
    return header,data

class NativeProcess:
    def __init__(self,exe,runtime,ptx,folder,*,test_faults=False):
        self.folder=Path(folder);self.folder.mkdir(exist_ok=False)
        self._log=(self.folder/'worker.log').open('wb')
        args=[str(exe),str(runtime),str(ptx)]
        if test_faults:args.append('--test-faults')
        try:
            self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self._log,
                cwd=self.folder,env=environment(runtime,self.folder),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except Exception:
            self._log.close()
            raise
        self._lock=threading.Lock();self._packet=None;self._error=None;self._stop=False;self._closed=False
        self.dropped=0
        self._reader=threading.Thread(target=self._read,name='XPU2-native-pipe',daemon=True);self._reader.start()
    def _read(self):
        try:
            while True:
                packet=read_packet(self.process.stdout)
                with self._lock:
                    if self._stop:continue
                    if self._packet is not None:self.dropped+=1
                    self._packet=packet
        except Exception as error:
            with self._lock:
                if not self._stop:self._error=str(error)
    def send(self,message):
        encoded=json.dumps(message,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()+b'\n'
        if len(encoded)>65536:raise ValueError('Native command exceeds bound')
        self.process.stdin.write(encoded);self.process.stdin.flush()
    def request(self,request,staging):
        self.send(dict(op='render',id=request.ticket*2,scene=str(request.scene),assets=str(request.manifest.parent/'assets'),
            staging=str(staging),epoch=asdict(request.epoch),threads=request.threads,window_ms=request.window_ms,
            fault=request.fault,domain=request.domain,refill_fine=request.refill_fine,publish_ms=request.publish_ms))
    def cancel(self,ticket):self.send(dict(op='cancel',id=ticket))
    def poll(self):
        with self._lock:
            packet=self._packet;self._packet=None
            # Deliver a final packet before observing a subsequent process exit.
            return packet,None if packet is not None else self._error
    def close(self,timeout=5):
        if self._closed:return
        self._closed=True
        with self._lock:self._stop=True;self._packet=None
        try:self.send(dict(op='close'))
        except (OSError,ValueError):pass
        try:self.process.stdin.close()
        except OSError:pass
        try:self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill();self.process.wait(timeout=timeout)
        self._reader.join(timeout)
        self.process.stdout.close();self._log.close()
        if self._reader.is_alive():raise RuntimeError('Native reader failed to retire')

def decode(exe,runtime,image,folder):
    """Decode on the coordinator worker with an independent bounded OIIO child."""
    from io import BytesIO
    result=subprocess.run([str(exe),'--decode',str(image)],cwd=folder,env=environment(runtime,folder),
        capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('Reference display decode: '+result.stderr.decode(errors='replace')[-1000:])
    stream=BytesIO(result.stdout);header,data=read_packet(stream)
    if header['kind']!='decoded' or stream.read(1):raise RuntimeError('Reference display wire invalid')
    return header,data
