"""Compare two/four separately owned native chunks without widening native math."""
from . import native_owned_mixed as base
from .native_gpu_paths import once
adapter=base.adapter
cpp=base.cpp
queue=base.queue
profile=base.profile
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver
ispc=base.ispc
multisampler=base.multisampler
bundled=base.bundled

def header(text):
    text=base.header(text)
    return once(text,'ownedDepth=mode && !std::strcmp(mode,"2")?2:0;', 'ownedDepth=mode && !std::strcmp(mode,"2")?2:mode && !std::strcmp(mode,"4")?4:0;')

def handler(text):
    text=base.handler(text)
    text=once(text,'    bool xpu2OwnedEligible=CPP_gpuOwnedChunks(pbrTls)==2', '    const unsigned xpu2Depth=CPP_gpuOwnedChunks(pbrTls);\n    bool xpu2OwnedEligible=(xpu2Depth==2 || xpu2Depth==4)')
    text=once(text,'        } chunks[2];','        } chunks[4];')
    text=once(text,'        for(unsigned i=0;i<2;++i){','        for(unsigned i=0;i<xpu2Depth;++i){')
    return once(text,'for(;prepared<2 && numRemaining;++prepared)', 'for(;prepared<xpu2Depth && numRemaining;++prepared)')
