# python
"""Headless: what a link file holds (PROBE_FILE): its items by type, and any Scene Proxy in it with its file."""
import json
import os
import pathlib
import lx
import modo
path = os.environ['PROBE_FILE']
lx.eval('!scene.open {%s} normal' % path)
rows = [(i.name, i.type, str(i.channel('scene').get()) if i.type == 'proxy' else (i.geometry.numVertices if i.type == 'mesh' else '')) for i in modo.Scene().items()
        if i.type in ('mesh', 'proxy', 'locator', 'camera', 'sunLight', 'groupLocator')]
lx.eval('!scene.close')
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\file.json').write_text(json.dumps(rows, indent=1))
