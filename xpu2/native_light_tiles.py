"""Exclusive CPU/GPU claims for direct-light work grouped by tile preference.

Patches the frozen grouped-light runtime. This is not a full GPU integrator.
"""
from .native_gpu_paths import once


def patch(out):
 p=out/'native_gpu_early.h';s=p.read_text()
 s=once(s,'bool done=false,consumed=false,canceled=false,released=false;', 'bool done=false,consumed=false,canceled=false,released=false; bool cooperative=false,preferGpu=true,claimedGpu=false,cpuResolved=false;')
 s=once(s,'    HMODULE lib=nullptr;', '''    unsigned tilePolicy=0;
    std::atomic<uint64_t> tileWindows{0},preferredCpu{0},preferredGpu{0},cpuClaims{0},gpuClaims{0},cpuSteals{0},gpuSteals{0};
    HMODULE lib=nullptr;''')
 s=once(s,'Queue(unsigned m):mode(m){', '''Queue(unsigned m):mode(m){const char* policy=std::getenv("XPU2_LIGHT_TILES");tilePolicy=policy&&!std::strcmp(policy,"alternate")?1:policy&&!std::strcmp(policy,"steal")?2:0;''')
 anchor='    void collect(moonray::pbr::TLState* tls'
 pos=s.index(anchor)
 s=s[:pos]+'''    void publishTiles(const float* input,const unsigned* masks,unsigned samples,unsigned lanes,uint64_t revision,uint64_t* handles){
        if(!samples||samples>16||!lanes||lanes>128||samples*lanes>512)throw std::logic_error("Invalid tile window");
        std::fill(handles,handles+samples*2,uint64_t(0));
        {
            std::lock_guard<std::mutex> lock(mutex);++tileWindows;
            for(unsigned unit=0;unit<samples*2;++unit){
                if(!masks[unit])continue;
                if(stopping||broken||lanes>capacity-std::min(credits,capacity)){++refused;continue;}
                auto j=std::make_shared<Job>();const float* first=input+(unit/2)*lanes*32;
                j->input.assign(first,first+lanes*32);bool useful=false;
                for(unsigned k=0;k<lanes;++k){if(!(masks[unit]&(1u<<(k%8))))j->input[k*32]=0.f;uint32_t kind;std::memcpy(&kind,&j->input[k*32],sizeof(kind));useful|=kind!=0;}
                if(!useful)continue;
                j->output.resize(lanes*9);j->count=lanes;j->revision=revision;j->owner=std::this_thread::get_id();j->id=++next;
                j->cooperative=true;j->preferGpu=bool(unit&1);
                owners.emplace(j->id,j);try{pending.push_back(j);}catch(...){owners.erase(j->id);throw;}
                handles[unit]=j->id;credits+=lanes;++submitted;if(j->preferGpu)++preferredGpu;else ++preferredCpu;
            }
        }
        changed.notify_all();
        if(tileWindows==1 && std::getenv("XPU2_TILE_HOLD_CPU"))std::this_thread::sleep_for(std::chrono::milliseconds(150));
    }
    int nextCpu(const uint64_t* handles,unsigned count,uint64_t revision){
        std::lock_guard<std::mutex> lock(mutex);
        for(unsigned pass=0;pass<(tilePolicy==2?2u:1u);++pass)for(unsigned k=0;k<count;++k){
            auto it=owners.find(handles[k]);if(it==owners.end())continue;auto j=it->second;
            if(j->claimedGpu||j->done||j->canceled)continue;
            if(!j->cooperative||j->revision!=revision||j->owner!=std::this_thread::get_id()||j->consumed)throw std::logic_error("Stale tile CPU claim");
            if(j->preferGpu!=bool(pass))continue;
            // Remove the payload before returning its credit. Leaving it in pending
            // could retain unlimited CPU-resolved packets while the GPU worker stalls.
            auto pendingIt=std::find(pending.begin(),pending.end(),j);
            if(pendingIt==pending.end())throw std::logic_error("Pending tile owner missing");
            pending.erase(pendingIt);
            j->cpuResolved=true;j->done=true;j->consumed=true;owners.erase(it);release(j);++collected;++cpuClaims;if(j->preferGpu)++cpuSteals;
            changed.notify_all();return int(k);
        }
        return -1;
    }
    void fillSlot(Slot& slot){
        std::lock_guard<std::mutex> lock(mutex);
        for(auto it=pending.begin();it!=pending.end();){
            auto j=*it;if(j->canceled||j->cpuResolved){j->done=true;release(j);it=pending.erase(it);}else ++it;
        }
        while(slot.count<512){
            auto chosen=pending.end();
            for(unsigned pass=0;pass<(tilePolicy==2?2u:1u)&&chosen==pending.end();++pass){
                for(auto it=pending.begin();it!=pending.end();++it){auto j=*it;
                    if(j->count>512-slot.count)continue;
                    if(j->cooperative && j->preferGpu!=!bool(pass))continue;
                    chosen=it;break;
                }
            }
            if(chosen==pending.end())break;
            auto j=*chosen;pending.erase(chosen);j->claimedGpu=true;
            if(j->cooperative){++gpuClaims;if(!j->preferGpu)++gpuSteals;}
            slot.jobs.push_back(j);slot.count+=j->count;
        }
    }
''' + s[pos:]
 old='''                    {std::lock_guard<std::mutex> lock(mutex);
                        while(!pending.empty()&&s.count+pending.front()->count<=512){auto j=pending.front();pending.pop_front();if(j->canceled){j->done=true;release(j);continue;}s.jobs.push_back(j);s.count+=j->count;}
                    }'''
 s=once(s,'        bool attempted=false;','        bool attempted=false,heldGpu=false;')
 s=once(s,old,'''                    if(!heldGpu && std::getenv("XPU2_TILE_HOLD_GPU")){heldGpu=true;std::this_thread::sleep_for(std::chrono::milliseconds(150));}
                    fillSlot(s);''')
 s=once(s,'        if(const char* p=std::getenv("XPU2_LIGHT_PROFILE"))',r'''        if(const char* p=std::getenv("XPU2_TILE_CLAIM_PROFILE"))if(FILE* f=std::fopen(p,"a")){
            std::fprintf(f,"{\"policy\":%u,\"windows\":%llu,\"preferred_cpu\":%llu,\"preferred_gpu\":%llu,\"cpu_claims\":%llu,\"gpu_claims\":%llu,\"cpu_steals\":%llu,\"gpu_steals\":%llu}\n",tilePolicy,(unsigned long long)tileWindows.load(),(unsigned long long)preferredCpu.load(),(unsigned long long)preferredGpu.load(),(unsigned long long)cpuClaims.load(),(unsigned long long)gpuClaims.load(),(unsigned long long)cpuSteals.load(),(unsigned long long)gpuSteals.load());std::fclose(f);
        }
        if(const char* p=std::getenv("XPU2_LIGHT_PROFILE"))''')
 s+='''
extern "C" unsigned CPP_lightTilePolicy(){auto& q=xpu2::lightqueue::queue;return q?q->tilePolicy:0;}
extern "C" void CPP_lightTilePublish(const float* input,const unsigned* masks,unsigned samples,unsigned lanes,uint64_t* handles){auto& q=xpu2::lightqueue::queue;if(!q)throw std::logic_error("Missing tile queue");q->publishTiles(input,masks,samples,lanes,xpu2::nativepath::epoch,handles);}
extern "C" int CPP_lightTileNextCpu(const uint64_t* handles,unsigned count){auto& q=xpu2::lightqueue::queue;return q?q->nextCpu(handles,count,xpu2::nativepath::epoch):-1;}
'''
 p.write_text(s)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text()
 s=once(s,'extern "C" uniform bool CPP_lightGroup();','''extern "C" uniform unsigned int CPP_lightTilePolicy();
extern "C" void CPP_lightTilePublish(const uniform float *uniform input,const uniform unsigned int *uniform masks,uniform unsigned int samples,uniform unsigned int lanes,uniform uint64 *uniform handles);
extern "C" uniform int CPP_lightTileNextCpu(const uniform uint64 *uniform handles,uniform unsigned int count);
extern "C" uniform bool CPP_lightGroup();''')
 s=once(s,'    uniform bool groupPrepared=false;','''    uniform bool groupPrepared=false;
    uniform bool tileWork=groupLight && CPP_lightTilePolicy()!=0;
    uniform uint64 tileHandles[32];uniform unsigned int tileMasks[32];
    for(uniform int j=0;j<32;++j){tileHandles[j]=0;tileMasks[j]=0;}
''')
 s=once(s,'    if(lightMode){\n        if(groupLight){','''    if(tileWork){
        // Stable checkerboard preference; claims, not preference, confer ownership.
        varying bool preferGpu=(((sp.mPixel>>4)^(sp.mPixel>>20))&1)!=0;
        uniform int samples=reduce_max(lightSampleCount);
        for(uniform int i=0;i<samples;++i)foreach_active(lane){
            if(extract(lightValid[i],lane))tileMasks[i*2+(extract(preferGpu,lane)?1:0)]|=1u<<lane;
        }
        if(groupPrepared)CPP_lightTilePublish(groupInput,tileMasks,samples,lightLanes,tileHandles);
        // Unsupported or refused tasks remain with their native owner.
        for(uniform int unit=0;unit<samples*2;++unit)if(!tileHandles[unit]){
            if((tileMasks[unit]&(1u<<programIndex))!=0)
                integrateLightSetSample(lSampler,lightIndex,bSampler,pv,lsmp[unit/2],clampingDepth,clampingValue,parentLobeLightSets,NULL,lightMode);
            tileMasks[unit]=0;
        }
        uniform int unit=CPP_lightTileNextCpu(tileHandles,samples*2);
        while(unit>=0){
            if((tileMasks[unit]&(1u<<programIndex))!=0)
                integrateLightSetSample(lSampler,lightIndex,bSampler,pv,lsmp[unit/2],clampingDepth,clampingValue,parentLobeLightSets,NULL,lightMode);
            tileHandles[unit]=0;tileMasks[unit]=0;
            unit=CPP_lightTileNextCpu(tileHandles,samples*2);
        }
        for(uniform int j=0;j<samples*2;++j)if(tileHandles[j]){
            uniform float results[16*8*9];CPP_lightCollect(pbrTls,tileHandles[j],results,lightLanes);
            if((tileMasks[j]&(1u<<programIndex))!=0)
                integrateLightSetSample(lSampler,lightIndex,bSampler,pv,lsmp[j/2],clampingDepth,clampingValue,parentLobeLightSets,results,lightMode);
        }
    }else if(lightMode){
        if(groupLight){''')
 p.write_text(s)
