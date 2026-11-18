# python
"""Export a Modo scene as a MoonRay scene with no window, for modo_cl (docs/INSTALLATION.md, "Rendering headless"):
    @{kit_MoonRayForModo:scripts/export_moonray.py} "scene.lxo" "out.rdla" [frames] [format=rdla|rdlb|split] [outputs=0|1] [collect=0|1] ["report=file.txt"]
out.rdla writes RDLA, out.rdlb writes RDLB, unless format= says (split: settings as RDLA, geometry as RDLB, MoonRay's
split scene); "frames" writes one scene for each frame of the frame range; outputs=0 leaves the AOVs, Cryptomatte and
deep out; collect=1 copies the pictures the scene reads into a folder beside it. The scene is written with its render
outputs, as Export as MoonRay Scene writes it, by the scene's own MoonRay render settings.

report= names a text file the script writes what came of it in, a line each, its kind and a tab before it: "wrote" and a
file, "notice" and what the export said, "error" and why it failed (modo_cl does not pass on what a script says). MoonRay
> Convert LXO to RDL and the kit's bin/lxo2rdl.exe run it so for batches of scenes (lxo_convert.py, lxo2rdl.cpp)."""
import traceback
import lx

args = [a.strip('{}"') for a in lx.args()]
if len(args) < 2:
    raise SystemExit('export_moonray.py "scene.lxo" "out.rdla" [frames] [format=rdla|rdlb|split] [outputs=0|1] [collect=0|1] ["report=file.txt"]')
words = args[2:]
# A word's name in any case, its value as given (a report's path keeps its own).
named = {word.split('=', 1)[0].lower(): word.split('=', 1)[1] for word in words if '=' in word}
report = named.get('report')
said = []
try:
    from moonray_modo import scene_export
    kind = named.get('format', '').lower() or ('rdlb' if args[1].lower().endswith('.rdlb') else 'rdla')
    if kind not in ('rdla', 'rdlb', 'split'):
        raise ValueError('format must be rdla, rdlb or split, not ' + kind)
    # Opened without its dialogs (a missing colour configuration, an unknown item): no one is there to answer them.
    lx.eval('!scene.open {%s}' % args[0])
    warnings = []
    written = scene_export.export({'path': args[1], 'format': kind, 'frames': 'frames' in [w.lower() for w in words],
                                   'outputs': named.get('outputs', '1') != '0', 'collect': named.get('collect', '0') == '1'}, warnings)
    said = [('wrote', str(p)) for p in written] + [('notice', w) for w in warnings]
except Exception as exc:
    said.append(('error', '%s: %s' % (type(exc).__name__, exc)))
    lx.out(traceback.format_exc())
for kind_said, text in said:
    lx.out('%s %s' % ('Wrote' if kind_said == 'wrote' else kind_said.capitalize() + ':', text))
if report:
    with open(report, 'w', encoding='utf-8') as file:
        for kind_said, text in said:
            file.write('%s\t%s\n' % (kind_said, str(text).replace('\r', ' ').replace('\n', ' ')))
