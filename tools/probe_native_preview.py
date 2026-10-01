# python
"""Check SDK server loading and lifecycle against installed Modo 16.1v9."""
import ctypes
import json
from pathlib import Path
import traceback
import lx
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
report={}
try:
    path=root/'build/modo-bridge/MoonRayPreview.lx'
    lx.eval('plugin.add {%s}' % path)
    host=lx.service.Host()
    report['host_methods']=[n for n in dir(host) if not n.startswith('_')]
    report['lookup_doc']=host.LookupServer.__doc__
    report['factory_methods']=[n for n in dir(lx.object.Factory()) if not n.startswith('_')]
    report['factory_spawn_doc']=lx.object.Factory.Spawn.__doc__
    report['command_methods']=[n for n in dir(lx.service.Command()) if not n.startswith('_')]
    report['external_guid']=lx.symbol.u_EXTERNALRENDER
    bridge=ctypes.CDLL(str(path))
    bridge.MR_preview_ids.argtypes=[ctypes.POINTER(ctypes.c_uint),ctypes.c_uint]
    bridge.MR_preview_ids.restype=ctypes.c_uint
    report['instances']=bridge.MR_preview_ids(None,0)
    factory=lx.object.Factory(host.LookupServer('externalrender','moonray.cpu',1))
    server=lx.object.ExternalRender(factory.Spawn())
    assert server.test()
    ids=(ctypes.c_uint*16)()
    assert bridge.MR_preview_ids(ids,16)>0
    bridge.MR_preview_state.argtypes=[ctypes.c_uint,ctypes.POINTER(ctypes.c_uint)]
    bridge.MR_preview_state.restype=ctypes.c_int
    revision=ctypes.c_uint()
    identity=ids[0]
    server.Start()
    assert bridge.MR_preview_state(identity,ctypes.byref(revision))==1
    first=revision.value
    server.Reset()
    assert bridge.MR_preview_state(identity,ctypes.byref(revision))==1 and revision.value>first
    server.Pause()
    assert bridge.MR_preview_state(identity,ctypes.byref(revision))==0
    server.Start(); server.Stop()
    assert bridge.MR_preview_state(identity,ctypes.byref(revision))==0
    report['lifecycle_passed']=True
    commands=lx.service.Command()
    report['preview_commands']=[]
    for index in range(commands.CommandCount()):
        try:
            command=lx.object.Command(commands.CommandByIndex(index))
            name=command.Name()
        except Exception:
            continue
        if 'preview' in name.lower() or 'pview' in name.lower():
            report['preview_commands'].append(name)
    report['loaded']=True
except Exception:
    report['error']=traceback.format_exc()
folder=root/'test-results/native-preview'; folder.mkdir(parents=True,exist_ok=True)
(folder/'probe.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
