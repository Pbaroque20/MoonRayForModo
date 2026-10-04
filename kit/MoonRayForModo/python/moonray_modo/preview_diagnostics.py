"""Keep a per-process Python stack log for native material-preview failures."""
import faulthandler,os,tempfile,time
from pathlib import Path
_stream=None

def record(event):
    global _stream
    try:
        if _stream is None:
            folder=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'MoonRayForModo/Diagnostics'
            folder.mkdir(parents=True,exist_ok=True)
            _stream=(folder/('material-preview-%d.log'%os.getpid())).open('a',encoding='utf-8',buffering=1)
            # Preserve a handler already installed by Modo or another plugin.
            if not faulthandler.is_enabled():faulthandler.enable(file=_stream,all_threads=True)
        _stream.write(time.strftime('%Y-%m-%d %H:%M:%S')+' '+str(event)+'\n')
        _stream.flush()
    except (OSError,RuntimeError):pass
