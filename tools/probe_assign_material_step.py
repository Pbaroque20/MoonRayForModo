# python
"""Used by probe_added_material_live.py: what moonray.material.assign does for the selected mesh once its dialog is
answered, run as a script so that Modo makes the material's items inside a command."""
from moonray_modo.materials import assign
assign('DwaBaseMaterial', name='Probe', color=(0.6, 0.16, 0.22), smoothing=True, angle=40.0)
