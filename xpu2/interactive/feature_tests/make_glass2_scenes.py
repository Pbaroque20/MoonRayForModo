"""DwaBase glass isolated: make_glass2_scenes.py <folder>. The glass scenes' base with the glass ball alone (the skin
and chrome balls and the card removed): DwaBase glass and UsdPreviewSurface glass, with the key light and without, and
DwaBase glass rough (0.2) and thin-walled."""
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
base = (here / 'gl1' / 'gl-base.rdla').read_text(encoding='utf-8')
layer = re.search(r'Layer\("/layer"\) \{.*\}', base).group(0)
entries = re.findall(r'\{ RdlMeshGeometry\("([^"]+)"\)[^}]*\}', layer)
keep = [e for e in re.findall(r'\{ RdlMeshGeometry\("[^"]+"\)[^}]*\}', layer) if '/glass"' in e or '/floor"' in e]
base = base.replace(layer, 'Layer("/layer") { %s }' % ', '.join(keep))
geoms = re.search(r'GeometrySet\("/geometry"\) \{[^}]*\}', base).group(0)
base = base.replace(geoms, 'GeometrySet("/geometry") { RdlMeshGeometry("/glass"), RdlMeshGeometry("/floor") }')
DWA = 'DwaBaseMaterial("/glass_m") { ["transmission"]=1, ["refractive_index"]=1.5, ["roughness"]=0, ["transmission_color"]=Rgb(1,1,1), ["label"]="glass" }'
USD = 'UsdPreviewSurface("/glass_m") { ["diffuseColor"]=Rgb(1,1,1), ["opacity"]=0, ["ior"]=1.5, ["roughness"]=0, ["useSpecularWorkflow"]=0 }'
glass_def = re.search(r'DwaBaseMaterial\("/glass_m"\) \{[^}]*\}', base).group(0)


def variant(material, key=True, usd=False):
    t = base.replace(glass_def, material)
    if usd:
        t = t.replace('DwaBaseMaterial("/glass_m")', 'UsdPreviewSurface("/glass_m")')
    if not key:
        t = t.replace('LightSet("/lights") { EnvLight("/fill"), RectLight("/key") }', 'LightSet("/lights") { EnvLight("/fill") }')
    return t


cases = {
    'g2-dwa': variant(DWA),
    'g2-dwa-env': variant(DWA, key=False),
    'g2-usd': variant(USD, usd=True),
    'g2-usd-env': variant(USD, key=False, usd=True),
    'g2-dwa-rough': variant(DWA.replace('["roughness"]=0', '["roughness"]=0.2')),
    'g2-dwa-thin': variant(DWA.replace('["label"]="glass"', '["thin_geometry"]=true, ["label"]="glass"')),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases', keep)
