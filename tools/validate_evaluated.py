"""Render Modo's evaluated UV fixture and inspect actual texture colors."""
import json
import os
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
modo=Path(r'C:\Program Files\Modo16.1v9\modo');extra=modo/'resrc/python3kit/extra64'
sys.path[:0]=[str(root/'kit/MoonRayForModo/python'),str(extra/'Python/Scripts')]
dlls=[os.add_dll_directory(str(p)) for p in (modo,extra)]
from PySide2 import QtGui
from moonray_modo import rdla,native
runtime=Path(native.default_runtime());folder=root/'test-results/render-cache'
scene=json.loads((folder/'textured.json').read_text())
source=folder/'textured.rdla';output=folder/'textured.png'
source.write_text(rdla.scene_text(scene,96,96,2,1))
with (folder/'render.log').open('w') as log:
    result=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,output,2),
        env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,
        timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
assert result.returncode==0
image=QtGui.QImage(str(output));assert image.width()==96
red=green=0
for y in range(96):
    for x in range(96):
        c=image.pixelColor(x,y)
        red+=int(c.red()>c.green()*1.5 and c.red()>30)
        green+=int(c.green()>c.red()*1.5 and c.green()>30)
assert red>100 and green>100,(red,green)
(folder/'render-report.json').write_text(json.dumps({'passed':True,'red_pixels':red,'green_pixels':green}))
print('Evaluated named-UV render passed:',red,green)
instance_file=folder/'instance-material.json'
if instance_file.is_file():
    instance_scene=json.loads(instance_file.read_text())
    source=folder/'instance-material.rdla';output=folder/'instance-material.png'
    source.write_text(rdla.scene_text(instance_scene,96,96,2,1))
    with (folder/'instance-render.log').open('w') as log:
        result=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,output,2),
            env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,
            timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0
    picture=QtGui.QImage(str(output))
    left=picture.pixelColor(28,52);right=picture.pixelColor(68,52)
    assert left.red()>30 and abs(left.red()-left.green())<10,left.getRgb()
    assert right.red()>right.green()*1.5 and right.red()>30,right.getRgb()
    (folder/'instance-render-report.json').write_text(json.dumps({'passed':True,
        'source_pixel':left.getRgb(),'instance_pixel':right.getRgb()}))
    print('Instance material render passed')
