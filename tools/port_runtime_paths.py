"""Make standalone Windows MoonRay locate its bundled runtime without shell setup."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'upstream/openmoonray/moonray/moonray/cmd/raas_cmd/moonray/moonray.cc'
s=p.read_text(encoding='utf-8')
if '#include "modo_runtime_paths.h"' not in s:
    old='    moonray::RaasCommandLineApplication app;\n    try {'
    if old not in s:raise RuntimeError('Unknown MoonRay entry point')
    s='#include "modo_runtime_paths.h"\n'+s.replace(old,'    try {\n        modoRuntimePaths();\n        moonray::RaasCommandLineApplication app;',1)
    p.write_bytes(s.encode('utf-8'))
print('Executable-relative Windows runtime defaults enabled')
