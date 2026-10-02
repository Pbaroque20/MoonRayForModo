"""Deferred progress and backend-status checks; no Modo or renderer required."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo.progress import Progress
from moonray_modo.native import execution_status
now=[0.];p=Progress(lambda:now[0])
p.feed('GPU utilization = 90%\nRendering [ 10')
assert p.percent is None
p.feed('%]\n');now[0]=10;p.feed('Rendering [ 20%]\n')
assert p.percent==20 and '~1m 20s' in p.display()[1]
assert p.display('denoise')[0]==-1
p.reset_pass();assert p.percent is None
assert execution_status('Executing an XPU render since execution mode was set to auto.\nGPU: Setup complete\nGPU initialization failed, falling back to CPU vector mode') .startswith('Vector active')
assert execution_status('Executing a scalar render since execution mode was set to auto.').startswith('Scalar active')
print('Progress and execution status passed')
