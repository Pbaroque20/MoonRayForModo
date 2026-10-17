// Isolated native capture diagnostic; no renderer scheduling or state restoration.
#pragma once
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <vector>
namespace xpu2 {
struct SurfaceState {
    std::array<uint32_t,24> ids{};
    std::array<float,64> values{};
};
inline SurfaceState captureSurface(const moonray::pbr::RayState& rs,float presence) {
    SurfaceState s;
    const auto& r=rs.mRay;const auto& pv=rs.mPathVertex;const auto& sp=rs.mSubpixel;
    if(!rs.mAOSIsect)throw std::runtime_error("XPU2 capture missing intersection");
    const auto& is=*rs.mAOSIsect;
    unsigned deps=0;
    if(rs.mDeepDataHandle!=moonray::pbr::nullHandle)deps|=1;
    if(rs.mCryptomatteDataHandle!=moonray::pbr::nullHandle || sp.mCryptomatteBuffer || sp.mCryptomatteResultsArray)deps|=2;
    if(sp.mDeferredNodesHead || sp.mDeferredNodesTailPtr || sp.mNumDeferredNodes)deps|=4;
    if(rs.mParentLobeLightSets.mNumLightSets)deps|=8;
    if(pv.volumeDepth || rs.mVolHit)deps|=16;
    s.ids={sp.mPixel,uint32_t(sp.mSubpixelIndex),rs.mSequenceID,rs.mTilePass,
           uint32_t(r.getDepth()),uint32_t(r.getMask()),uint32_t(r.hasDifferentials()),
           uint32_t(is.hasGeometryDerivatives()),uint32_t(is.getLayerAssignmentId()),
           r.geomID,r.primID,r.instID,deps,uint32_t(pv.diffuseDepth),uint32_t(pv.glossyDepth),
           uint32_t(pv.mirrorDepth),uint32_t(pv.nonMirrorDepth),uint32_t(pv.presenceDepth),
           uint32_t(pv.hairDepth),uint32_t(pv.subsurfaceDepth),uint32_t(pv.volumeDepth),
           uint32_t(pv.lpeStateId),uint32_t(pv.lobeType),uint32_t(sp.mPixelSamples)};
    auto v3=[&](unsigned offset,const auto& v){s.values[offset]=v.x;s.values[offset+1]=v.y;s.values[offset+2]=v.z;};
    v3(0,r.getOrigin());v3(3,r.getDirection());
    s.values[6]=r.getStart();s.values[7]=r.getEnd();s.values[8]=r.getTime();
    if(r.hasDifferentials()){v3(9,r.getOriginX());v3(12,r.getDirX());v3(15,r.getOriginY());v3(18,r.getDirY());}
    v3(21,is.getP());v3(24,is.getNg());v3(27,is.getN());
    s.values[30]=is.getSt().x;s.values[31]=is.getSt().y;
    if(is.hasGeometryDerivatives()){v3(32,is.getdPds());v3(35,is.getdPdt());}
    s.values[38]=pv.pathThroughput.r;s.values[39]=pv.pathThroughput.g;s.values[40]=pv.pathThroughput.b;
    s.values[41]=pv.pathPixelWeight;s.values[42]=pv.aovPathPixelWeight;s.values[43]=pv.pathDistance;
    s.values[44]=pv.totalPresence;s.values[45]=pv.accumOpacity;
    s.values[46]=pv.minRoughness.x;s.values[47]=pv.minRoughness.y;
    s.values[48]=sp.mSubpixelX;s.values[49]=sp.mSubpixelY;s.values[50]=sp.mSampleClampingValue;
    s.values[51]=sp.mPrimaryRayDiffScale;s.values[52]=sp.mTextureDiffScale;s.values[53]=presence;
    return s;
}
inline bool surfaceCaptureEnabled() {
    const char* p=std::getenv("XPU2_SURFACE_CAPTURE");return p && *p;
}
inline std::vector<SurfaceState> captureSurfaces(unsigned count,moonray::pbr::RayState** states,const float* presences) {
    std::vector<SurfaceState> result;
    if(!surfaceCaptureEnabled())return result;
    for(unsigned i=0;i<count;++i) {
        const auto pixel=states[i]->mSubpixel.mPixel;
        if(pixel==((77u<<16)|96u) || pixel==((96u<<16)|132u))result.push_back(captureSurface(*states[i],presences[i]));
    }
    return result;
}
inline void publishSurfaceCopies(const std::vector<SurfaceState>& states) {
    if(states.empty())return;
    struct Output {
        std::mutex mutex;FILE* file=nullptr;unsigned count=0;
        ~Output(){if(file)std::fclose(file);}
    };
    static Output out;std::lock_guard<std::mutex> lock(out.mutex);
    if(!out.file){out.file=std::fopen(std::getenv("XPU2_SURFACE_CAPTURE"),"wb");
        if(!out.file || std::fwrite("XNS1",1,4,out.file)!=4)throw std::runtime_error("XPU2 cannot open surface capture");}
    for(const auto& s:states){
        if(++out.count>1024)throw std::runtime_error("XPU2 surface capture limit exceeded");
        if(std::fwrite(s.ids.data(),4,s.ids.size(),out.file)!=s.ids.size() ||
           std::fwrite(s.values.data(),4,s.values.size(),out.file)!=s.values.size())
            throw std::runtime_error("XPU2 surface capture write failed");
    }
    if(std::fflush(out.file))throw std::runtime_error("XPU2 surface capture flush failed");
}
} // namespace xpu2
