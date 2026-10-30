// Diagnostic only: replay owned requests while this native handler holds its
// scene synchronously. Never migrate BundledOcclRay/TLS handles to another worker.
std::vector<unsigned char> xpu2SavedShadow;
if (const char* flag=std::getenv("XPU2_PROBE_SHADOW_REQUESTS")) {
    if (std::strcmp(flag,"1")==0) {
        xpu2SavedShadow.assign(isOccluded,isOccluded+numRays);
        std::vector<xpu2::ShadowRequest> requests;
        std::vector<uint64_t> lights;
        for(unsigned i=0;i<numRays;++i) {
            const auto& src=rays[i];
            if(src.mOcclTestType!=OcclTestType::STANDARD || src.mDataPtrHandle==nullHandle) continue;
            const auto& ray=gpuRays[i];
            auto found=std::find(lights.begin(),lights.end(),ray.mLightId);
            const auto slot=unsigned(found-lights.begin());
            if(found==lights.end()) lights.push_back(ray.mLightId);
            xpu2::ShadowRequest q{};
            // This synchronous adapter has one borrowed scene and one batch.
            q.scene=1;q.revision=1;q.request=uint64_t(i)+1;q.light=slot;
            q.mask=ray.mMask;q.receiver=ray.mShadowReceiverId;
            q.origin[0]=ray.mOriginX;q.origin[1]=ray.mOriginY;q.origin[2]=ray.mOriginZ;
            q.direction[0]=ray.mDirX;q.direction[1]=ray.mDirY;q.direction[2]=ray.mDirZ;
            q.nearT=ray.mMinT;q.farT=ray.mMaxT;q.time=ray.mTime;
            requests.push_back(q);
        }
        xpu2::ShadowBindings bindings(1,1,lights);
        std::vector<rt::GPURay> replay;
        std::vector<int> cpu;
        unsigned rejected=0, stale=0, fieldMismatch=0;
        // Reverse delivery verifies result mapping by request identity, not position.
        std::reverse(requests.begin(),requests.end());
        for(const auto& q:requests) {
            uint64_t light=0;auto old=q;++old.revision;
            if(!bindings.resolve(old,light)) ++stale;
            if(!bindings.resolve(q,light)) {++rejected;continue;}
            rt::GPURay ray{};
            ray.mOriginX=q.origin[0];ray.mOriginY=q.origin[1];ray.mOriginZ=q.origin[2];
            ray.mDirX=q.direction[0];ray.mDirY=q.direction[1];ray.mDirZ=q.direction[2];
            ray.mMinT=q.nearT;ray.mMaxT=q.farT;ray.mTime=q.time;
            ray.mMask=q.mask;ray.mShadowReceiverId=q.receiver;ray.mLightId=light;
            const auto& orig=gpuRays[q.request-1];
            // Compare individual fields, never struct padding.
            if(std::memcmp(&ray.mOriginX,&orig.mOriginX,9*sizeof(float)) ||
               ray.mMask!=orig.mMask || ray.mShadowReceiverId!=orig.mShadowReceiverId ||
               ray.mLightId!=orig.mLightId) ++fieldMismatch;
            mcrt_common::Ray c;
            c.org=scene_rdl2::math::Vec3f(q.origin[0],q.origin[1],q.origin[2]);
            c.dir=scene_rdl2::math::Vec3f(q.direction[0],q.direction[1],q.direction[2]);
            c.tnear=q.nearT;c.tfar=q.farT;c.time=q.time;c.mask=q.mask;c.geomID=RT_INVALID_RAY_ID;
            c.ext.instance0OrLight=reinterpret_cast<const scene_rdl2::rdl2::Light*>(light);
            c.ext.shadowReceiverId=q.receiver;c.ext.volumeInstanceState=0;
            cpu.push_back(fs.mEmbreeAccel->occluded(c)?1:0);replay.push_back(ray);
        }
        unsigned gpuMismatch=0,cpuMismatch=0,blocked=0,cpuReferenceMismatch=0;
        if(!replay.empty() && !rejected) {
            // Windows OptiX ignores UMA arguments. Count never exceeds original batch.
            accel->occluded(tls->mThreadIdx,unsigned(replay.size()),replay.data(),nullptr,0);
            const auto* answers=accel->getOutputOcclusionBuf(tls->mThreadIdx);
            for(unsigned j=0;j<replay.size();++j) {
                const auto original=xpu2SavedShadow[requests[j].request-1];
                gpuMismatch+=(bool(answers[j])!=bool(original));
                cpuMismatch+=(bool(answers[j])!=bool(cpu[j]));blocked+=bool(answers[j]);
                if(bool(answers[j])!=bool(cpu[j])) {
                    // Recheck through the original TLS light lookup and BundledOcclRay.
                    const auto& src=rays[requests[j].request-1];mcrt_common::Ray c;
                    c.org=src.mOrigin;c.dir=src.mDir;c.tnear=src.mMinT;c.tfar=src.mMaxT;c.time=src.mTime;
                    c.mask=scene_rdl2::rdl2::SHADOW;c.geomID=RT_INVALID_RAY_ID;
                    c.ext.instance0OrLight=static_cast<BundledOcclRayData*>(pbrTls->getListItem(src.mDataPtrHandle,0))->mLight->getRdlLight();
                    c.ext.shadowReceiverId=src.mShadowReceiverId;c.ext.volumeInstanceState=0;
                    const bool reference=fs.mEmbreeAccel->occluded(c);
                    cpuReferenceMismatch+=(reference!=bool(cpu[j]));
                    std::fprintf(stderr,"XPU2_SHADOW_DISAGREEMENT {\"request\":%llu,\"pixel\":%u,\"sample\":%d,\"depth\":%d,\"cpu\":%d,\"native_cpu\":%d,\"gpu\":%d,\"native_gpu\":%d,\"receiver\":%d,\"light_slot\":%u,\"near\":%.9g,\"far\":%.9g,\"time\":%.9g,\"origin\":[%.9g,%.9g,%.9g],\"direction\":[%.9g,%.9g,%.9g]}\n",
                        (unsigned long long)requests[j].request,src.mPixel,src.mSubpixelIndex,int(src.mDepth),cpu[j],int(reference),int(bool(answers[j])),int(bool(original)),src.mShadowReceiverId,requests[j].light,src.mMinT,src.mMaxT,src.mTime,src.mOrigin.x,src.mOrigin.y,src.mOrigin.z,src.mDir.x,src.mDir.y,src.mDir.z);
                }
            }
        }
        std::fprintf(stderr,"XPU2_SHADOW_REQUEST {\"requests\":%u,\"rejected\":%u,\"stale_rejected\":%u,\"field_mismatches\":%u,\"gpu_mismatches\":%u,\"cpu_mismatches\":%u,\"cpu_reference_mismatches\":%u,\"blocked\":%u,\"lights\":%u}\n",
            unsigned(requests.size()),rejected,stale,fieldMismatch,gpuMismatch,cpuMismatch,cpuReferenceMismatch,blocked,unsigned(lights.size()));
        isOccluded=xpu2SavedShadow.data();
    }
}
