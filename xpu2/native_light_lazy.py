"""Select descriptor ownership before preparing native direct-light GPU payloads."""
from .native_gpu_paths import once


def patch(out):
 p=out/'native_gpu_early.h';s=p.read_text()
 s=once(s,'namespace xpu2::lightqueue {\nusing Clock=', '#include "native_tile_policy.h"\n#include "native_light_window.h"\nnamespace xpu2::lightqueue {\nusing Clock=')
 s=once(s,'    unsigned tilePolicy=0;', '''    unsigned tilePolicy=0,lazyMode=0;
    xpu2::LightWindow<xpu2tile::Policy> lazy;
    std::thread::id lazyOwner;
''')
 s=once(s,'Queue(unsigned m):mode(m){', '''Queue(unsigned m):mode(m){
        const char* lazyValue=std::getenv("XPU2_LIGHT_LAZY");lazyMode=lazyValue&&!std::strcmp(lazyValue,"shared")?1:lazyValue&&!std::strcmp(lazyValue,"neighbor")?2:0;
        lazy.cpuPolicy.neighbor=lazy.gpuPolicy.neighbor=lazyMode==2;
''')
 pos=s.index('    void publishTiles(')
 s=s[:pos]+'''    uint64_t lazyOpen(const uint32_t* masks,const uint32_t* tiles,uint32_t eligible,unsigned samples,unsigned lanes,uint64_t revision){
        uint64_t token;
        {std::lock_guard<std::mutex> lock(mutex);lazyOwner=std::this_thread::get_id();token=lazy.open(masks,tiles,eligible,samples*2,lanes,revision);changed.notify_all();}
        if(token==1&&std::getenv("XPU2_TILE_HOLD_CPU"))std::this_thread::sleep_for(std::chrono::milliseconds(150));
        return token;
    }
    void lazyCheck(){if(lazyOwner!=std::this_thread::get_id())throw std::logic_error("Lazy light owner mismatch");}
    int lazyNext(uint64_t token,uint64_t revision){std::lock_guard<std::mutex> lock(mutex);lazyCheck();return lazy.next(token,revision);}
    uint64_t lazySubmit(uint64_t token,uint64_t revision,unsigned index,const float* input,unsigned count){
        {std::lock_guard<std::mutex> lock(mutex);lazyCheck();lazy.check(token,revision);if(index>=lazy.count||lazy.items[index].phase!=decltype(lazy)::Phase::Preparing||count!=lazy.lanes)throw std::logic_error("Invalid lazy submission");}
        uint64_t handle=input?submit(input,count,revision):0;
        {std::lock_guard<std::mutex> lock(mutex);lazy.prepared(token,revision,index,handle!=0);}
        return handle;
    }
    void lazyDone(uint64_t token,uint64_t revision,unsigned index){std::lock_guard<std::mutex> lock(mutex);lazyCheck();lazy.completed(token,revision,index);changed.notify_all();}
    void lazyClose(uint64_t token,uint64_t revision){std::lock_guard<std::mutex> lock(mutex);lazyCheck();lazy.close(token,revision);changed.notify_all();}
''' + s[pos:]
 s=once(s,'                    fillSlot(s);','''                    {std::lock_guard<std::mutex> lock(mutex);if(lazyMode&&!broken&&!stopping){lazy.reserveGpu();changed.notify_all();}}
                    fillSlot(s);''')
 s=once(s,'if(!active&&pending.empty())changed.wait(lock,[&]{return stopping||!pending.empty();});','if(!active&&pending.empty())changed.wait(lock,[&]{return stopping||!pending.empty()||(lazyMode&&!broken&&lazy.readyToReserve());});')
 s=once(s,'        if(const char* p=std::getenv("XPU2_LIGHT_PROFILE"))',r'''        if(lazy.active)throw std::logic_error("Lazy native owner did not retire its window");
        if(const char* p=std::getenv("XPU2_LAZY_PROFILE"))if(FILE* f=std::fopen(p,"a")){
            const auto& t=lazy.stats;const auto& c=lazy.cpuPolicy;const auto& g=lazy.gpuPolicy;
            std::fprintf(f,"{\"mode\":%u,\"windows\":%llu,\"closed\":%llu,\"descriptors\":%llu,\"cpu\":%llu,\"gpu\":%llu,\"cpu_steals\":%llu,\"gpu_steals\":%llu,\"packed\":%llu,\"fallback\":%llu,\"active\":%u,\"reserved\":%u,\"inspected\":%llu,\"policy_claims\":%llu,\"local\":%llu}\n",lazyMode,(unsigned long long)t.windows,(unsigned long long)t.closed,(unsigned long long)t.descriptors,(unsigned long long)t.cpu,(unsigned long long)t.gpu,(unsigned long long)t.cpuSteals,(unsigned long long)t.gpuSteals,(unsigned long long)t.packed,(unsigned long long)t.fallback,unsigned(lazy.active),lazy.reserved,(unsigned long long)(c.inspected+g.inspected),(unsigned long long)(c.claims+g.claims),(unsigned long long)(c.local+g.local));std::fclose(f);
        }
        if(const char* p=std::getenv("XPU2_LIGHT_PROFILE"))''')
 s+='''
extern "C" unsigned CPP_lightLazyMode(){auto& q=xpu2::lightqueue::queue;return q?q->lazyMode:0;}
extern "C" uint64_t CPP_lightLazyOpen(const uint32_t* masks,const uint32_t* tiles,uint32_t eligible,unsigned samples,unsigned lanes){return xpu2::lightqueue::queue->lazyOpen(masks,tiles,eligible,samples,lanes,xpu2::nativepath::epoch);}
extern "C" int CPP_lightLazyNext(uint64_t token){return xpu2::lightqueue::queue->lazyNext(token,xpu2::nativepath::epoch);}
extern "C" uint64_t CPP_lightLazySubmit(uint64_t token,unsigned index,const float* input,unsigned count){return xpu2::lightqueue::queue->lazySubmit(token,xpu2::nativepath::epoch,index,input,count);}
extern "C" void CPP_lightLazyDone(uint64_t token,unsigned index){xpu2::lightqueue::queue->lazyDone(token,xpu2::nativepath::epoch,index);}
extern "C" void CPP_lightLazyClose(uint64_t token){xpu2::lightqueue::queue->lazyClose(token,xpu2::nativepath::epoch);}
'''
 p.write_text(s)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text()
 s=once(s,'extern "C" uniform bool CPP_lightGroup();','''extern "C" uniform unsigned int CPP_lightLazyMode();
extern "C" uniform uint64 CPP_lightLazyOpen(const uniform unsigned int *uniform masks,const uniform unsigned int *uniform tiles,uniform unsigned int eligible,uniform unsigned int samples,uniform unsigned int lanes);
extern "C" uniform int CPP_lightLazyNext(uniform uint64 token);
extern "C" uniform uint64 CPP_lightLazySubmit(uniform uint64 token,uniform unsigned int index,const uniform float *uniform input,uniform unsigned int count);
extern "C" void CPP_lightLazyDone(uniform uint64 token,uniform unsigned int index);
extern "C" void CPP_lightLazyClose(uniform uint64 token);
extern "C" uniform bool CPP_lightGroup();
inline uniform unsigned int xpu2LightEligible(const varying BsdfSampler &bSampler){
    uniform unsigned int mask=0;
    const varying BsdfSlice *uniform slice=BsdfSampler_getBsdfSlice(&bSampler);
    for(uniform int k=0;k<BsdfSampler_getLobeCount(&bSampler);++k){
        const varying BsdfLobe *uniform lobe=BsdfSampler_getLobe(&bSampler,k);
        if(!isActive(lobe))continue;
        if(lobe->mName!=BSDF_LOBE_LAMBERT && lobe->mName!=BSDF_LOBE_FLAT_DIFFUSE)continue;
        bool eligible=!isActive(BsdfLobe_getFresnel(lobe)) && !BsdfLobe_getIsSpherical(lobe) && slice->mShadowTerminatorFix==0;
        if(lobe->mName==BSDF_LOBE_FLAT_DIFFUSE){
            const varying FlatDiffuseBsdfLobe *uniform flat=(const varying FlatDiffuseBsdfLobe *uniform)lobe;
            eligible &= flat->mFlatness==0.f && flat->mTerminatorShift==0.f && flat->mFlatnessFalloff>=0.f && flat->mFlatnessFalloff<=1.f;
        }
        foreach_active(lane)if(extract(eligible,lane))mask|=1u<<lane;
    }
    return mask;
}
''')
 s=once(s,'    uniform bool tileWork=groupLight && CPP_lightTilePolicy()!=0;', '    uniform bool lazyWork=groupLight && CPP_lightLazyMode()!=0;\n    uniform bool tileWork=groupLight && CPP_lightTilePolicy()!=0;')
 s=once(s,'    if(groupLight)for(uniform int j=0;j<groupLanes*32;++j)groupInput[j]=0.f;', '    if(groupLight&&!lazyWork)for(uniform int j=0;j<groupLanes*32;++j)groupInput[j]=0.f;')
 s=once(s,'            if(groupLight){\n                if(xpu2PackDirectLight', '            if(lazyWork){ /* Metadata first; payload is prepared only after a GPU claim. */ }else if(groupLight){\n                if(xpu2PackDirectLight')
 s=once(s,'    if(tileWork){\n        // Stable checkerboard', '''    if(lazyWork){
        uniform unsigned int tileIds[32];for(uniform int i=0;i<32;++i)tileIds[i]=0xffffffff;
        varying bool preferGpu=(((sp.mPixel>>4)^(sp.mPixel>>20))&1)!=0;
        uniform int samples=reduce_max(lightSampleCount);
        for(uniform int i=0;i<samples;++i)foreach_active(lane)if(extract(lightValid[i],lane)){
            uniform int index=i*2+(extract(preferGpu,lane)?1:0);
            tileMasks[index]|=1u<<lane;
            if(tileIds[index]==0xffffffff){uniform unsigned int pixel=extract(sp.mPixel,lane);tileIds[index]=((pixel>>20)<<16)|((pixel&0xffff)>>4);}
        }
        uniform uint64 token=CPP_lightLazyOpen(tileMasks,tileIds,xpu2LightEligible(bSampler),samples,lightLanes);
        uniform int action=CPP_lightLazyNext(token);
        while(action>=0){
            uniform int index=action%32;
            if(action<32){
                if((tileMasks[index]&(1u<<programIndex))!=0)integrateLightSetSample(lSampler,lightIndex,bSampler,pv,lsmp[index/2],clampingDepth,clampingValue,parentLobeLightSets,NULL,lightMode);
            }else{
                uniform float input[16*8*32];uniform bool prepared=false;
                if((tileMasks[index]&(1u<<programIndex))!=0)prepared=xpu2PackDirectLight(lSampler,lightIndex,bSampler,pv,lsmp[index/2],parentLobeLightSets,input);
                tileHandles[index]=CPP_lightLazySubmit(token,index,prepared?input:NULL,lightLanes);
                if(!tileHandles[index])if((tileMasks[index]&(1u<<programIndex))!=0)integrateLightSetSample(lSampler,lightIndex,bSampler,pv,lsmp[index/2],clampingDepth,clampingValue,parentLobeLightSets,NULL,lightMode);
            }
            action=CPP_lightLazyNext(token);
        }
        for(uniform int index=0;index<samples*2;++index)if(tileHandles[index]){
            uniform float results[16*8*9];CPP_lightCollect(pbrTls,tileHandles[index],results,lightLanes);
            if((tileMasks[index]&(1u<<programIndex))!=0)integrateLightSetSample(lSampler,lightIndex,bSampler,pv,lsmp[index/2],clampingDepth,clampingValue,parentLobeLightSets,results,lightMode);
            CPP_lightLazyDone(token,index);
        }
        CPP_lightLazyClose(token);
    }else if(tileWork){
        // Stable checkerboard''')
 p.write_text(s)
