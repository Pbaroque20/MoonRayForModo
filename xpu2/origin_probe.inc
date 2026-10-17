// Single-render-thread diagnostic only. Preserve the actual GPU results first:
// extra OptiX queries reuse its output buffer, which must never replace the image.
std::vector<unsigned char> xpu2OriginalOcclusion;
{
    const char* enabled=std::getenv("XPU2_PROBE_ORIGINS");
    if (enabled && std::strcmp(enabled,"1")==0) {
        xpu2OriginalOcclusion.assign(isOccluded,isOccluded+numRays);
        std::vector<BundledOcclRay> candidates;
        std::vector<rt::GPURay> gpuCandidates;
        std::vector<unsigned> sourceIndex,policies;
        std::vector<int> cpuAnswers;
        for (unsigned i=0;i<numRays;++i) {
            const auto &original=rays[i]; const int slot=xpu2PixelSlot(original.mPixel);
            if (slot<0 || original.mSubpixelIndex!=0 || original.mDepth!=1 ||
                original.mOcclTestType!=OcclTestType::STANDARD || original.mDataPtrHandle==nullHandle) continue;
            const auto normal=xpu2SurfaceNormals()[slot]; if (!normal.valid) continue;
            const float side=normal.x*original.mDir.x+normal.y*original.mDir.y+normal.z*original.mDir.z>=0 ? 1.f : -1.f;
            const float n[3]={normal.x*side,normal.y*side,normal.z*side};
            for (unsigned policy=0;policy<6;++policy) {
                auto copy=original; auto gpu=gpuRays[i];
                const float magnitude=std::max(std::abs(copy.mOrigin.x),std::max(std::abs(copy.mOrigin.y),std::abs(copy.mOrigin.z)));
                for (int axis=0;axis<3;++axis) {
                    float &coordinate=copy.mOrigin[axis];
                    if (n[axis]==0) continue;
                    const float toward=std::copysign(std::numeric_limits<float>::infinity(),n[axis]);
                    if (policy>=1 && policy<=4) {
                        for (unsigned step=0;step<(1u<<(policy-1));++step) coordinate=std::nextafter(coordinate,toward);
                    } else if (policy==5) {
                        coordinate+=n[axis]*(4.f*std::numeric_limits<float>::epsilon()*magnitude);
                        coordinate=std::nextafter(coordinate,toward);
                    }
                }
                gpu.mOriginX=copy.mOrigin.x;gpu.mOriginY=copy.mOrigin.y;gpu.mOriginZ=copy.mOrigin.z;
                mcrt_common::Ray ray;
                ray.org=copy.mOrigin;ray.dir=copy.mDir;ray.tnear=copy.mMinT;ray.tfar=copy.mMaxT;ray.time=copy.mTime;
                ray.mask=scene_rdl2::rdl2::SHADOW;ray.geomID=RT_INVALID_RAY_ID;
                ray.ext.instance0OrLight=static_cast<BundledOcclRayData*>(pbrTls->getListItem(copy.mDataPtrHandle,0))->mLight->getRdlLight();
                ray.ext.shadowReceiverId=copy.mShadowReceiverId;ray.ext.volumeInstanceState=0;
                cpuAnswers.push_back(fs.mEmbreeAccel->occluded(ray)?1:0);
                candidates.push_back(copy);gpuCandidates.push_back(gpu);sourceIndex.push_back(i);policies.push_back(policy);
            }
        }
        if (!candidates.empty()) {
            // The diagnostic's explicit GPU queries are not included in renderer utilization statistics.
            accel->occluded(tls->mThreadIdx,unsigned(candidates.size()),gpuCandidates.data(),candidates.data(),sizeof(BundledOcclRay));
            const auto *answers=accel->getOutputOcclusionBuf(tls->mThreadIdx);
            for (unsigned j=0;j<candidates.size();++j) {
                const auto &q=candidates[j];const auto normal=xpu2SurfaceNormals()[xpu2PixelSlot(q.mPixel)];
                std::fprintf(stderr,"XPU2_ORIGIN {\"pixel\":%u,\"sample\":%d,\"source_index\":%u,\"policy\":%u,\"cpu\":%d,\"gpu\":%u,\"original_gpu\":%u,\"origin\":[%.9g,%.9g,%.9g],\"direction\":[%.9g,%.9g,%.9g],\"normal\":[%.9g,%.9g,%.9g],\"near\":%.9g}\n",
                    q.mPixel,q.mSubpixelIndex,sourceIndex[j],policies[j],cpuAnswers[j],unsigned(answers[j]),unsigned(xpu2OriginalOcclusion[sourceIndex[j]]),
                    q.mOrigin.x,q.mOrigin.y,q.mOrigin.z,q.mDir.x,q.mDir.y,q.mDir.z,normal.x,normal.y,normal.z,q.mMinT);
            }
        }
        isOccluded=xpu2OriginalOcclusion.data();
    }
}
