# python
"""Headless Modo probe: the scene in MOONRAY_PROBE_SCENES opened (the command line answers the unknown-items question itself) and saved as
MOONRAY_PROBE_OUT, so that a GUI probe without the plugin that made them opens it with no question to wait on."""
import os
import lx

lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENES'])
lx.eval('!scene.saveAs {%s} $LXOB false' % os.environ['MOONRAY_PROBE_OUT'])
print('saved', os.environ['MOONRAY_PROBE_OUT'], os.path.getsize(os.environ['MOONRAY_PROBE_OUT']))
