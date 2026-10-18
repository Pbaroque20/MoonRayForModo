"""Diagnostic bounded native queue helping at an unresolved GPU dependency."""
from pathlib import Path
from . import native_material_stage as stage
from .native_gpu_paths import once
adapter=stage.adapter
cpp=stage.cpp
queue=stage.queue
profile=stage.profile
cuda=stage.cuda
ispc=stage.ispc
multisampler=stage.multisampler

def header(text):
    text=stage.header(text)
    text=once(text,'extern "C" void CPP_gpuEarlyCollect', 'bool xpu2HelpMaterial(moonray::pbr::TLState* tls);\nextern "C" void CPP_gpuEarlyCollect')
    text=once(text,'bool waited=false;', 'bool waited=false,helped=false;')
    text=once(text,'        if(!waited){', '        if(!helped){helped=true;if(xpu2HelpMaterial(tls))continue;}\n        if(!waited){')
    text=once(text,'inline void stageReset(){', 'inline void helpReset();inline void helpFinish();\ninline void stageReset(){helpReset();')
    text=once(text,'inline void stageFinish(){', 'inline void stageFinish(){helpFinish();')
    return text+'\n'+Path(__file__).with_suffix('.inc').read_text()
