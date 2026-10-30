# Opt-in early admission and ready-only grouped result claiming on native owner.
from pathlib import Path
from . import native_owned_depth as base
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=base.adapter
cpp=base.cpp
profile=base.profile
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver
handler=base.handler
bundled=base.bundled

def queue(text):
    text=base.queue(text)
    text=once(text,'bool done=false,cancelled=false,consumed=false,credit=false;',
        'bool done=false,cancelled=false,consumed=false,credit=false;\n    bool coordClaimed=false; // Only read/written by the native owner after queue publication.')
    text=once(text,'    Collect tryCollect(const Ticket& request,uint64_t revision,float* output) {\n        std::lock_guard<std::mutex> lock(mutex);',
        '''    Collect tryCollect(const Ticket& request,uint64_t revision,float* output) {
        std::lock_guard<std::mutex> lock(mutex);
        return tryCollectLocked(request,revision,output);
    }
    // Caller holds mutex. A null output reserves the completed immutable result
    // for its existing owner; the Ticket keeps storage alive until native use.
    Collect tryCollectLocked(const Ticket& request,uint64_t revision,float* output) {''')
    return once(text,'        std::memcpy(output,request->output,request->count*32);',
        '        if(output)std::memcpy(output,request->output,request->count*32);')

def header(text):
    text=base.header(text)
    text=once(text,'inline void ownedReset(){','inline void ownedReset(){coordReset();')
    text=once(text,'inline void ownedFinish(){','inline void ownedFinish(){coordFinish();')
    text=once(text,'        if(ticket->done)++stageReady;else ++stagePending;',r'''        if(ticket->done){
            ++stageReady;
            if(coordClaim){
                if(shaderQueue->tryCollectLocked(ticket,epoch,nullptr)!=Collect::Ready)throw std::logic_error("Cannot claim ready material result");
                ticket->coordClaimed=true;++coordClaimed;
            }
        }else ++stagePending;''')
    anchor='    const auto& ticket=*owner;const auto deadline='
    text=once(text,anchor,r'''    const auto& ticket=*owner;
    if(ticket->coordClaimed){
        // Completion was synchronized once for this material group. The worker
        // never writes this result again; its original owner retains storage.
        ticket->coordClaimed=false;++coordConsumed;
        if(ticket->revision!=epoch || !ticket->consumed)throw std::logic_error("Invalid claimed material result");
        if(tls->isCanceled()){earlyFallback+=8;return;}
        std::memcpy(result,ticket->output,64*sizeof(float));
        for(unsigned lane=0;lane<8;++lane){if(finiteBits(result[lane*8+3]))++earlyCollected;else ++earlyFallback;}
        return;
    }
    const auto deadline=''')
    return (HERE/'native_coordination.inc').read_text(encoding='utf-8')+'\n'+text

def ispc(text,bsdf_header):
    text=base.ispc(text,bsdf_header)
    anchor='    for(uniform int k=0;k<BSDF_MAX_LOBE*16;++k)tokens[k]=0;'
    # Rejected calls expose no arrays: the caller reads only on a true result.
    text=once(text,anchor,'''    uniform bool admitted=all(pv.nonMirrorDepth==0) && CPP_gpuMaterialStageMode(pbrTls)!=0;
    if(!admitted && CPP_gpuCoordEarly())return false;
'''+anchor)
    text=once(text,'    if(!CPP_gpuMaterialStageMode(pbrTls) || !all(pv.nonMirrorDepth==0))return false;',
        '    if(!admitted)return false;')
    return 'extern "C" uniform bool CPP_gpuCoordEarly();\n'+text

def multisampler(text):
    text=base.multisampler(text)
    anchor='    uniform bool xpu2Staged=xpu2SubmitMaterial(pbrTls,bSampler,rs->mSubpixel,pv,sequenceID,xpu2Tokens,xpu2Prepared);'
    text=once(text,anchor,'''    uniform bool xpu2Staged=false;
    if(all(pv.nonMirrorDepth==0) || !CPP_gpuCoordEarly())
        xpu2Staged=xpu2SubmitMaterial(pbrTls,bSampler,rs->mSubpixel,pv,sequenceID,xpu2Tokens,xpu2Prepared);''')
    return 'extern "C" uniform bool CPP_gpuCoordEarly();\n'+text
