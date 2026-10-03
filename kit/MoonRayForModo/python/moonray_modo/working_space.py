"""Linear RGB working primaries at renderer-facing color boundaries.

Modo texture/channel graphs retain their authored Rec.709 math. Their color
outputs, lights and environment maps convert before entering MoonRay shading.
Coordinates, normals, masks, IORs and identification buffers are never transformed.
"""
import hashlib,os,subprocess,tempfile,uuid
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager
_settings=ContextVar('moonray_working_space',default={})

def mul(a,b):return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def inverse(a):
    rows=[list(map(float,row))+[float(i==j) for j in range(3)] for i,row in enumerate(a)]
    for i in range(3):
        pivot=max(range(i,3),key=lambda r:abs(rows[r][i]));rows[i],rows[pivot]=rows[pivot],rows[i]
        d=rows[i][i]
        if abs(d)<1e-12:raise ValueError('Singular color matrix')
        rows[i]=[v/d for v in rows[i]]
        for j in range(3):
            if j!=i:
                d=rows[j][i];rows[j]=[v-d*w for v,w in zip(rows[j],rows[i])]
    return [row[3:] for row in rows]
def xyz(xy):
    x,y=xy;return [x/y,1,(1-x-y)/y]
def product(a,v):return [sum(x*y for x,y in zip(row,v)) for row in a]
def rgb_to_xyz(primaries,white):
    columns=[xyz(p) for p in primaries];m=[[columns[j][i] for j in range(3)] for i in range(3)]
    scale=product(inverse(m),xyz(white));return [[v*scale[j] for j,v in enumerate(row)] for row in m]
# Academy ACEScg AP1 primaries and D60 white, with Bradford D65->D60 adaptation.
REC709=rgb_to_xyz(((.64,.33),(.30,.60),(.15,.06)),(.3127,.3290))
AP1=rgb_to_xyz(((.713,.293),(.165,.830),(.128,.044)),(.32168,.33767))
BRADFORD=[[.8951,.2664,-.1614],[-.7502,1.7135,.0367],[.0389,-.0685,1.0296]]
_src=product(BRADFORD,xyz((.3127,.3290)));_dst=product(BRADFORD,xyz((.32168,.33767)))
ADAPT=mul(mul(inverse(BRADFORD),[[(_dst[i]/_src[i]) if i==j else 0 for j in range(3)] for i in range(3)]),BRADFORD)
TO_AP1=mul(mul(inverse(AP1),ADAPT),REC709);TO_REC709=inverse(TO_AP1)

@contextmanager
def configuration(settings):
    token=_settings.set(settings)
    try:yield
    finally:_settings.reset(token)
def enabled():return _settings.get().get('working_space','rec709')=='acescg'
def label(settings):return 'ACEScg' if settings.get('working_space','rec709')=='acescg' else 'linear Rec.709'
def color(value):return product(TO_AP1,value) if enabled() else value

def expression(value,path,lines):
    if not enabled():return value
    from .rdla import string,vector
    lines.append('ModoTextureMap(%s) { ["mode"] = 10, ["foreground"] = %s, ["background"] = %s, ["normal"] = %s, ["coordinates"] = %s }'%(string(path),value,vector(TO_AP1[0],'Rgb'),vector(TO_AP1[1],'Rgb'),vector(TO_AP1[2],'Rgb')))
    return 'bind(ModoTextureMap(%s), Rgb(1,1,1))'%string(path)

def surface(attributes,path,lines,keys):
    if not enabled():return attributes
    return {key:expression(value,path+'/working/'+key,lines) if key in keys else value for key,value in attributes.items()}

def matrix_argument(matrix):
    # OIIO uses a row-vector homogeneous matrix; transpose our column-vector form.
    return ','.join(str(matrix[j][i] if i<3 and j<3 else int(i==j)) for i in range(4) for j in range(4))

def texture(source):
    if not enabled():return source
    from . import native,textures
    source=Path(source);signature=[str(source),source.stat().st_mtime_ns,source.stat().st_size,TO_AP1]
    digest=hashlib.sha256(repr(signature).encode()).hexdigest()
    folder=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'MoonRayForModo/Textures';folder.mkdir(parents=True,exist_ok=True)
    target=folder/(digest+'.tx')
    if target.is_file():return textures.register(target)
    runtime=Path(native.default_runtime());staged=folder/(digest+'.'+uuid.uuid4().hex+'.tx')
    try:
        args=[str(runtime/'oiiotool.exe'),'--no-autopremult',str(source),'--colormatrix',matrix_argument(TO_AP1),'-d','float','-o',str(staged)]
        result=subprocess.run(args,env=native.environment(runtime),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or not staged.is_file():raise ValueError('Environment working-space conversion failed: '+result.stdout.decode(errors='replace')[-800:])
        staged.replace(target)
    finally:
        if staged.exists():staged.unlink()
    return textures.register(target)
