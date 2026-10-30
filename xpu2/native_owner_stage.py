"""Rolling owner-scoped material continuations; no foreign queues or escaped arenas."""
from .native_gpu_paths import once
PATCH_HANDLER=True

def patch(out):
 p=out/'native_gpu_early.h';s=p.read_text()
 s=once(s,'inline void ownedReset();inline void ownedFinish();','''inline bool ownerStageEnabled=false,ownerStageHold=false;inline std::atomic<bool> ownerStageHeld{false};
inline std::atomic<uint64_t> ownerStageHandlers{0},ownerStageProduced{0},ownerStageResumed{0},ownerStageRefills{0},ownerStageCanceled{0},ownerStagePeak{0};
inline void ownedReset();inline void ownedFinish();''')
 s=once(s,'inline void ownedReset(){coordReset();','''inline void ownedReset(){coordReset();
    ownerStageEnabled=xpu2::nowait::flag("XPU2_OWNER_STAGE");
    ownerStageHold=xpu2::nowait::flag("XPU2_OWNER_STAGE_HOLD_FIRST");ownerStageHeld=false;
    ownerStageHandlers=0;ownerStageProduced=0;ownerStageResumed=0;ownerStageRefills=0;ownerStageCanceled=0;ownerStagePeak=0;''')
 s=once(s,'inline void ownedFinish(){coordFinish();','''inline void ownedFinish(){coordFinish();
    if(ownerStageProduced!=ownerStageResumed+ownerStageCanceled)throw std::logic_error("Owner stage retained chunks");
    if(const char* name=std::getenv("XPU2_OWNER_STAGE_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\\\"enabled\\\":%s,\\\"handlers\\\":%llu,\\\"produced\\\":%llu,\\\"resumed\\\":%llu,\\\"prepared_while_queued\\\":%llu,\\\"canceled\\\":%llu,\\\"peak_chunks\\\":%llu}\\n",ownerStageEnabled?"true":"false",(unsigned long long)ownerStageHandlers.load(),(unsigned long long)ownerStageProduced.load(),(unsigned long long)ownerStageResumed.load(),(unsigned long long)ownerStageRefills.load(),(unsigned long long)ownerStageCanceled.load(),(unsigned long long)ownerStagePeak.load());std::fclose(f);
    }''')
 s+='''
extern "C" bool CPP_gpuOwnerStageEnabled(){return xpu2::nativepath::ownerStageEnabled && xpu2::nativepath::shaderQueue->noWait;}
extern "C" void CPP_gpuOwnerStageEvent(unsigned event,unsigned live,unsigned pass){
    using namespace xpu2::nativepath;
    if(event==0)++ownerStageHandlers;
    else if(event==1){++ownerStageProduced;if(live>1)++ownerStageRefills;auto peak=ownerStagePeak.load();while(live>peak&&!ownerStagePeak.compare_exchange_weak(peak,live)){};}
    else if(event==2)++ownerStageResumed;
    else if(event==3)ownerStageCanceled+=live;
    else throw std::logic_error("Unknown owner stage event");
    if(event==1 && live==2 && pass>0 && ownerStageHold && !ownerStageHeld.exchange(true)){
        std::fprintf(stdout,"@@XPU2_OWNER_STAGE_HELD\\n");std::fflush(stdout);
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
    }
}
'''
 p.write_text(s)
 p=out/'ShadeBundleHandler.cc';s=p.read_text()
 s='#include "owner_stage.h"\nextern "C" bool CPP_gpuOwnerStageEnabled();\nextern "C" void CPP_gpuOwnerStageEvent(unsigned,unsigned,unsigned=0);\n'+s
 start=s.index('        while(numRemaining){');end=s.index('    }else{\n    while (numRemaining)',start)
 old=s[start:end]
 new='''        if(CPP_gpuOwnerStageEnabled()){
            xpu2::OwnerStage stage(xpu2Depth);
            // Destruction counts outstanding chunks; their existing owners revoke
            // GPU tickets before the handler arena returns. No native pointer escapes.
            struct Guard {xpu2::OwnerStage& queue;~Guard(){CPP_gpuOwnerStageEvent(3,queue.size());}} guard{stage};
            CPP_gpuOwnerStageEvent(0,0);
            while(numRemaining || stage.size()){
                while(numRemaining && !stage.full()){
                    CHECK_CANCELLATION(pbrTls,return);
                    auto& chunk=chunks[stage.tail()];
                    prepareChunk(chunk);
                    if(!chunk.ready)return;
                    stage.push();CPP_gpuOwnerStageEvent(1,stage.size(),pbrTls->mCurrentPassIdx);
                }
                CHECK_CANCELLATION(pbrTls,return);
                auto& chunk=chunks[stage.front()];
                finishChunk(chunk);
                if(chunk.ready)return; // cancellation before native integration
                stage.pop();CPP_gpuOwnerStageEvent(2,stage.size());
            }
        }else{
'''+old+'        }\n'
 s=s[:start]+new+s[end:];p.write_text(s)
