// Mirror the existing CPU surface-shadow query setup without changing GPU output.
{
    static const bool trace = []() { const char* p=std::getenv("XPU2_TRACE_CONTRIBUTIONS"); return p && std::strcmp(p,"1")==0; }();
    if (trace && (occlRay.mPixel==pixelLocationToUint32(96,77) || occlRay.mPixel==pixelLocationToUint32(132,96))) {
        int cpu=-1;
        if (occlRay.mOcclTestType==OcclTestType::STANDARD && occlRay.mDataPtrHandle!=nullHandle) {
            mcrt_common::Ray ray;
            ray.org=occlRay.mOrigin;ray.dir=occlRay.mDir;
            ray.tnear=occlRay.mMinT;ray.tfar=occlRay.mMaxT;ray.time=occlRay.mTime;
            ray.mask=scene_rdl2::rdl2::SHADOW;ray.geomID=RT_INVALID_RAY_ID;
            ray.ext.instance0OrLight=static_cast<BundledOcclRayData*>(pbrTls->getListItem(occlRay.mDataPtrHandle,0))->mLight->getRdlLight();
            ray.ext.shadowReceiverId=occlRay.mShadowReceiverId;
            ray.ext.volumeInstanceState=0;
            cpu=fs.mEmbreeAccel->occluded(ray)?1:0;
        }
        std::fprintf(stderr,"XPU2_SHADOW_RESULT {\"pixel\":%u,\"sample\":%d,\"sequence\":%u,\"depth\":%d,\"type\":%u,\"cpu\":%d,\"gpu\":%u,\"disabled\":%d,\"direction\":[%.9g,%.9g,%.9g],\"rgb\":[%.9g,%.9g,%.9g]}\n",
                     occlRay.mPixel,occlRay.mSubpixelIndex,occlRay.mSequenceID,occlRay.mDepth,occlRay.mOcclTestType,cpu,unsigned(isOccluded[i]),int(disableShadowing),
                     occlRay.mDir.x,occlRay.mDir.y,occlRay.mDir.z,occlRay.mRadiance.r,occlRay.mRadiance.g,occlRay.mRadiance.b);
    }
}
