"""Convert verified saved render output using the same display transform."""
import array,json,math,struct,zlib
from pathlib import Path
from reference_runtime import sha
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'test-results/interactive-ray-hit-benchmark-20261022';r=json.loads((OUT/'report.json').read_text());assert r['status']=='passed';dest=OUT/'images';dest.mkdir(exist_ok=False)
def png(raw,w,h,path):
 a=array.array('f');a.frombytes(raw);assert len(a)==w*h*4 and all(math.isfinite(v) for v in a)
 rows=bytearray()
 for y in reversed(range(h)):
  rows.append(0)
  for x in range(w):
   for c in range(3):
    v=max(0,min(1,a[(y*w+x)*4+c]));v=12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055;rows.append(round(v*255))
 def chunk(t,d):return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
 path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))
manifest={'transform':'fixed linear-to-sRGB, clip only for display, no denoising or exposure change; original float data preserved','images':{}}
for name,c in r['cases'].items():
 n=c['native']['12'];w,h=n['width'],n['height'];reference=c['original']['12']['runs'][1];native=n['runs'][1]
 for label,raw,expected in [('xpu',Path(reference['folder'])/'beauty.rgba',reference['raw_sha256']),('xpu2',Path(native['raw_file']),native['raw_sha256'])]:
  assert sha(raw)==expected;path=dest/(name+'-'+label+'-64spp.png');png(raw.read_bytes(),w,h,path);manifest['images'][name+'-'+label]={'png':str(path),'raw':str(raw),'raw_sha256':expected,'png_sha256':sha(path),'width':w,'height':h}
(dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');print('Saved four verified renderer images',flush=True)
