# python
"""Run as a command by probe_masked_image.py: choose the test image for the albedo of the material it names, as the
material's properties choose one."""
import json
import pathlib
import modo
from moonray_modo import graph_images, material_override, properties

asked = json.loads((pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo') / 'test-results/masked-image/choose.json').read_text())
material = modo.Scene().item(asked['material'])
settings = properties.read(material)
graph = graph_images.set_image(settings, 'albedo', asked['image'])
properties.write(material, material_override.synchronize(settings, graph))
