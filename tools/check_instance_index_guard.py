"""Compile the actual patched index-selection block; this does not rebuild MoonRay."""
import argparse,subprocess,os
from pathlib import Path
from port_instance_indices import patch_text
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('compiler',type=Path);a=p.parse_args()
text=patch_text(a.source.read_text(encoding='utf-8'))
start=text.index('            int index = applyIndex ? indices[i] : 0;')
end=text.index('            shading::PrimitiveAttributeTable primitiveAttributeTable;',start)
block=text[start:end]
folder=Path('test-results/native-index-guard').resolve();folder.mkdir(parents=True,exist_ok=True)
source=folder/'guard.cpp';exe=folder/'guard.exe'
source.write_text('#include <cassert>\n#include <climits>\nint main() {\nint indices[]={INT_MIN,-1,0,1,2,3,INT_MAX};\nint expected[]={11,11,11,22,33,11,11};\nint ref[]={11,22,33}; int maxIndex=2; bool applyIndex=true;\nfor(int i=0;i<7;++i) {\n'+block+'\nassert(ref[index]==expected[i]); }\napplyIndex=false; for(int i=0;i<7;++i) {\n'+block+'\nassert(ref[index]==11); } }',encoding='utf-8')
env=dict(os.environ,PATH=str(a.compiler.resolve().parent)+os.pathsep+os.environ.get('PATH',''))
subprocess.run([str(a.compiler),'-std=c++17','-O2','-Wall','-Werror',str(source),'-o',str(exe)],check=True,env=env,timeout=60)
subprocess.run([str(exe)],check=True,env=env,timeout=15)
print('Patched native index block: seven boundary cases and disabled-index mode passed. Full runtime validation remains required.')
