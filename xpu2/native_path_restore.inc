// Included once in the copied PathIntegratorUtil.cc. Native post-shading bounce
// restoration only; no arena, sampler, BSDF, light or RayState pointer is retained.
#include "native_path_restore.h"
#include <moonray/rendering/pbr/core/Aov.h>
#include <array>
#include <atomic>
#include <cstring>
#include <map>
#include <mutex>
#include <thread>
#include <vector>
#include <cstdio>
#include <cstdlib>
namespace xpu2::nativepath {
using namespace moonray;
using scene_rdl2::math::Vec3f;
struct Path {
    Vec3f org,dir,originX,dirX,originY,dirY;
    float start,end,time,origEnd;
    int depth,mask;
    uint32_t flags,sequence,tile,pixel;
    int subpixel,pixelSamples;
    float subpixelX,subpixelY,clamp,primaryScale,textureScale;
    pbr::PathVertex vertex; // Numeric fields only, no native resources.
};
struct Owner {
    std::thread::id thread=std::this_thread::get_id();
    std::vector<Path> paths;
    std::vector<unsigned> sizes;
    std::atomic<unsigned> pendingCount{0};
    bool draining=false;
};
namespace {
std::mutex registryMutex;
std::map<pbr::TLState*,std::unique_ptr<Owner>> owners;
uint64_t epoch=0;
bool enabled=false,fixed=false,immediate=false,sentinel=false,poison=false;
std::atomic<uint64_t> captured{0},restored{0},cancelled{0},fallback{0},batches{0},peak{0},poisoned{0};
// Frame-stop code may query/drain from the controlling thread. Only the owner
// may touch its vectors or native pools; foreign emptiness checks use an atomic.
Owner* state(pbr::TLState* tls,bool create){
    std::lock_guard<std::mutex> lock(registryMutex);auto i=owners.find(tls);
    if(i==owners.end()){if(!create||owners.size()>=64)return nullptr;i=owners.emplace(tls,std::make_unique<Owner>()).first;}
    return i->second.get();
}
bool supported(const pbr::RayState& r){
    const auto& x=r.mRay.ext;const auto& pv=r.mPathVertex;
    return r.mRay.getDepth()==1&&pv.diffuseDepth==1&&pv.nonMirrorDepth==1&&pv.glossyDepth==0&&pv.mirrorDepth==0&&pv.hairDepth==0&&pv.subsurfaceDepth==0&&pv.presenceDepth==0&&pv.lobeType==5&&
        r.mDeepDataHandle==pbr::nullHandle&&r.mCryptomatteDataHandle==pbr::nullHandle&&r.mParentLobeLightSets.mNumLightSets==0&&
        !x.userData&&!x.geomTls&&!x.priorityMaterial0&&!x.priorityMaterial1&&!x.priorityMaterial2&&!x.priorityMaterial3&&
        !x.instance0OrLight&&!x.instance1&&!x.instance2&&!x.instance3&&!x.instanceAttributesDepth;
}
Path capture(const pbr::RayState& source){
    const auto& r=source.mRay;const auto& sp=source.mSubpixel;Path p{};
    p.org=r.org;p.dir=r.dir;p.originX=r.getOriginX();p.dirX=r.getDirX();p.originY=r.getOriginY();p.dirY=r.getDirY();
    p.start=r.tnear;p.end=r.tfar;p.time=r.time;p.origEnd=r.getOrigTfar();p.depth=r.getDepth();p.mask=r.mask;p.flags=r.mFlags.getAll();
    p.sequence=source.mSequenceID;p.tile=source.mTilePass;p.pixel=sp.mPixel;p.subpixel=sp.mSubpixelIndex;p.pixelSamples=sp.mPixelSamples;
    p.subpixelX=sp.mSubpixelX;p.subpixelY=sp.mSubpixelY;p.clamp=sp.mSampleClampingValue;p.primaryScale=sp.mPrimaryRayDiffScale;p.textureScale=sp.mTextureDiffScale;
    std::memcpy(&p.vertex,&source.mPathVertex,sizeof(p.vertex));return p;
}
void restore(pbr::RayState& r,const Path& p){
    // Explicit construction, never a raw RayState copy from old pooled storage.
    // Legacy deferred-node/cryptomatte Subpixel pointers are not initialized or
    // consumed by the bundled beauty path. Never inspect or copy those fields.
    // Deep/Cryptomatte handles and nonempty AOV schemas are excluded at admission.
    r=pbr::RayState{};
    r.mRay=mcrt_common::RayDifferential(p.org,p.dir,p.originX,p.dirX,p.originY,p.dirY,p.start,p.end,p.time,p.depth);
    r.mRay.setOrigTfar(p.origEnd);r.mRay.mask=p.mask;r.mRay.mFlags.setBits(p.flags);
    std::memcpy(&r.mPathVertex,&p.vertex,sizeof(p.vertex));
    if(sentinel)r.mPathVertex.pathThroughput*=0.5f;
    r.mSequenceID=p.sequence;r.mTilePass=p.tile;r.mDeepDataHandle=pbr::nullHandle;r.mCryptomatteDataHandle=pbr::nullHandle;
    auto& sp=r.mSubpixel;sp.mPixel=p.pixel;sp.mSubpixelIndex=p.subpixel;sp.mPixelSamples=p.pixelSamples;sp.mSubpixelX=p.subpixelX;sp.mSubpixelY=p.subpixelY;
    sp.mSampleClampingValue=p.clamp;sp.mPrimaryRayDiffScale=p.primaryScale;sp.mTextureDiffScale=p.textureScale;
}
}
void begin(bool fixedSamples){
    if(enabled||!owners.empty())throw std::logic_error("Previous native path frame still open");
    const char* mode=std::getenv("XPU2_NATIVE_PATH_RESTORE");enabled=mode&&std::strcmp(mode,"0");if(!enabled)return;
    fixed=fixedSamples;immediate=!std::strcmp(mode,"immediate");sentinel=!std::strcmp(mode,"sentinel");poison=std::getenv("XPU2_NATIVE_PATH_POISON")!=nullptr;
    captured=0;restored=0;cancelled=0;fallback=0;batches=0;peak=0;poisoned=0;++epoch;
}
unsigned drain(pbr::TLState* tls){
    if(!enabled)return 0;auto* s=state(tls,false);if(!s||s->thread!=std::this_thread::get_id())return 0;
    if(s->draining||s->paths.empty())return 0;
    if(tls->isCanceled()){cancelled+=s->paths.size();s->paths.clear();s->sizes.clear();s->pendingCount=0;return 0;}
    struct Guard{bool& value;Guard(bool& v):value(v){value=true;}~Guard(){value=false;}} guard(s->draining);
    // Remove from the queue before native allocation, which may recursively flush.
    auto paths=std::move(s->paths);auto sizes=std::move(s->sizes);s->paths.clear();s->sizes.clear();s->pendingCount=0;
    size_t offset=0;
    for(unsigned count:sizes){
        SCOPED_MEM(tls->mArena);
        auto** rays=tls->allocRayStates(count);
        for(unsigned i=0;i<count;++i)restore(*rays[i],paths[offset+i]);
        offset+=count;restored+=count;tls->addRayQueueEntries(count,rays);
    }
    if(offset!=paths.size())throw std::logic_error("Lost native child batch boundary");
    return unsigned(paths.size());
}
bool pending(pbr::TLState* tls){if(!enabled)return false;auto* s=state(tls,false);return s&&s->pendingCount.load()!=0;}
bool defer(pbr::TLState* tls,unsigned n,pbr::RayState** rays){
    if(!enabled||!n)return false;
    if(!fixed||tls->mFs->mExecutionMode!=mcrt_common::ExecutionMode::XPU||!tls->mFs->mAovSchema->empty()||n>4096){if(fallback.fetch_add(1)==0)std::fprintf(stderr,"XPU2_PATH_FRAME_BYPASS fixed=%d aovs=%u count=%u\n",int(fixed),tls->mFs->mAovSchema->size(),n);return false;}
    auto* s=state(tls,true);if(!s||s->thread!=std::this_thread::get_id()||s->draining){++fallback;return false;}
    for(unsigned i=0;i<n;++i)if(!supported(*rays[i])){if(fallback.fetch_add(1)==0){const auto& r=*rays[i];std::fprintf(stderr,"XPU2_PATH_PAYLOAD_BYPASS depth=%d diffuse=%d nonmirror=%d glossy=%d mirror=%d hair=%d sss=%d presence=%d lobe=%d links=%d\n",r.mRay.getDepth(),r.mPathVertex.diffuseDepth,r.mPathVertex.nonMirrorDepth,r.mPathVertex.glossyDepth,r.mPathVertex.mirrorDepth,r.mPathVertex.hairDepth,r.mPathVertex.subsurfaceDepth,r.mPathVertex.presenceDepth,r.mPathVertex.lobeType,r.mParentLobeLightSets.mNumLightSets);}return false;}
    if(n>4096-s->paths.size())drain(tls);
    if(n>4096-s->paths.size()){++fallback;return false;}
    // Complete all potentially throwing allocations before relinquishing native rays.
    s->paths.reserve(s->paths.size()+n);s->sizes.reserve(s->sizes.size()+1);for(unsigned i=0;i<n;++i)s->paths.push_back(capture(*rays[i]));s->sizes.push_back(n);
    s->pendingCount=unsigned(s->paths.size());
    auto used=s->paths.size();auto old=peak.load();while(used>old&&!peak.compare_exchange_weak(old,used)){}
    if(poison)for(unsigned i=0;i<n;++i){std::memset(rays[i],0xa5,sizeof(*rays[i]));rays[i]->mDeepDataHandle=pbr::nullHandle;rays[i]->mCryptomatteDataHandle=pbr::nullHandle;++poisoned;}
    tls->freeRayStates(n,rays);captured+=n;++batches;
    if(captured==n){std::fprintf(stderr,"XPU2_PATH_SUSPENDED %llu\n",(unsigned long long)epoch);std::fflush(stderr);}
    if(immediate)drain(tls);return true;
}
void finish(){
    if(!enabled)return;
    // Render driver has stopped. Leftover owned numerical packets can be revoked
    // without touching native pools, scene handles or a foreign owner's arena.
    for(auto& kv:owners){cancelled+=kv.second->paths.size();kv.second->paths.clear();}
    owners.clear();enabled=false;
    if(captured!=restored+cancelled)throw std::logic_error("Lost native restored path");
    if(const char* file=std::getenv("XPU2_NATIVE_PATH_PROFILE"))if(FILE* f=std::fopen(file,"a")){
        std::fprintf(f,"{\"epoch\":%llu,\"captured\":%llu,\"restored\":%llu,\"cancelled\":%llu,\"batches\":%llu,\"fallback_batches\":%llu,\"peak_owner_paths\":%llu,\"poisoned\":%llu,\"outstanding\":0}\n",
        (unsigned long long)epoch,(unsigned long long)captured.load(),(unsigned long long)restored.load(),(unsigned long long)cancelled.load(),(unsigned long long)batches.load(),(unsigned long long)fallback.load(),(unsigned long long)peak.load(),(unsigned long long)poisoned.load());std::fclose(f);
    }
}
}
