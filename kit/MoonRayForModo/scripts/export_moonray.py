# python
"""Export a Modo scene as a MoonRay scene with no window, for modo_cl (docs/INSTALLATION.md, "Rendering headless"):
    @{kit_MoonRayForModo:scripts/export_moonray.py} "scene.lxo" "out.rdla" [frames]
out.rdla writes RDLA, out.rdlb writes RDLB; "frames" writes one scene for each frame of the frame range. The scene is
written with its render outputs, as Export as MoonRay Scene writes it, by the scene's own MoonRay render settings."""
import lx
from moonray_modo import scene_export

args = [a.strip('{}"') for a in lx.args()]
if len(args) < 2:
    raise SystemExit('export_moonray.py "scene.lxo" "out.rdla" [frames]')
lx.eval('!scene.open {%s}' % args[0])
warnings = []
written = scene_export.export({'path': args[1], 'format': 'rdlb' if args[1].lower().endswith('.rdlb') else 'rdla',
                               'frames': len(args) > 2 and args[2].lower() == 'frames', 'outputs': True, 'collect': False}, warnings)
for line in ['Wrote %s' % p for p in written] + ['Notice: %s' % w for w in warnings]:
    lx.out(line)
