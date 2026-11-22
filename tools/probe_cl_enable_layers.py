# python
"""Command line: a copy of a scene with some of its Shader Tree layers switched on, for the other probes to read.
PROBE_SCENE the .lxo, PROBE_ENABLE the layers' names (separated by |), PROBE_SAVE where the copy goes. The original is
left as it is. Writes PROBE_SAVE + '.json' with what was switched on."""
import json
import os
import traceback

import lx
import modo

report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    wanted = [name for name in os.environ['PROBE_ENABLE'].split('|') if name]
    switched = []
    for item in modo.Scene().items():
        if item.name in wanted:
            item.channel('enable').set(1)
            switched.append(item.name)
    report['switched'] = switched
    lx.eval('!scene.saveAs {%s} $LXOB false' % os.environ['PROBE_SAVE'])
    report['saved'] = os.environ['PROBE_SAVE']
except Exception:
    report['error'] = traceback.format_exc()
with open(os.environ['PROBE_SAVE'] + '.json', 'w') as file:
    json.dump(report, file, indent=1)
