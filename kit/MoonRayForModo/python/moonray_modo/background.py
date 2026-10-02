"""Independent camera background; surface lighting remains on scene environments."""
import math
from pathlib import Path

DEFAULTS={'mode':'environment','color':'#000000','image':'','intensity':1.0,'rotation':0.0}

def apply(scene, settings):
    values=dict(DEFAULTS,**settings);mode=values['mode']
    if mode=='environment': return
    if mode not in ('black','color','image'): raise ValueError('Unknown background mode')
    for environment in scene.get('environments',[]): environment['camera']=False
    if mode=='black': return
    intensity=float(values['intensity'])
    if not math.isfinite(intensity) or intensity<0: raise ValueError('Invalid background intensity')
    entry={'camera':True,'indirect':False,'reflection':False,'refraction':False,'intensity':intensity,'name':'Camera background override'}
    if mode=='color':
        text=values['color'].lstrip('#')
        if len(text)!=6: raise ValueError('Background color must be #RRGGBB')
        try: rgb=[int(text[i:i+2],16)/255 for i in (0,2,4)]
        except ValueError: raise ValueError('Background color must be #RRGGBB')
        entry.update(kind='constant',zenith=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in rgb])
    else:
        path=Path(values['image']).expanduser()
        if not path.is_file(): raise ValueError('Select a background environment image')
        angle=math.radians(float(values['rotation']))
        if not math.isfinite(angle): raise ValueError('Invalid background rotation')
        c,s=math.cos(angle),math.sin(angle)
        entry.update(kind='image',path=str(path.resolve()),mtime=path.stat().st_mtime_ns,size=path.stat().st_size,
                     srgb=path.suffix.lower() not in ('.exr','.hdr','.tx'),matrix=[c,0,-s,0,0,1,0,0,s,0,c,0,0,0,0,1])
    scene.setdefault('environments',[]).append(entry)
