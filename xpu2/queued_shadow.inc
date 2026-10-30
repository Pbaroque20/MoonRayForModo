// Observation only: light contribution before visibility and transmittance.
{
    static const bool trace = []() { const char* p=std::getenv("XPU2_TRACE_CONTRIBUTIONS"); return p && std::strcmp(p,"1")==0; }();
    if (trace) for (unsigned j=0;j<numEntries;++j) {
        const auto &e=entries[j];
        if (e.mPixel!=pixelLocationToUint32(96,77) && e.mPixel!=pixelLocationToUint32(132,96)) continue;
        std::fprintf(stderr,"XPU2_SHADOW_QUEUED {\"pixel\":%u,\"sample\":%d,\"sequence\":%u,\"depth\":%d,\"type\":%u,\"origin\":[%.9g,%.9g,%.9g],\"direction\":[%.9g,%.9g,%.9g],\"near\":%.9g,\"far\":%.9g,\"rgb\":[%.9g,%.9g,%.9g]}\n",
                     e.mPixel,e.mSubpixelIndex,e.mSequenceID,e.mDepth,e.mOcclTestType,
                     e.mOrigin.x,e.mOrigin.y,e.mOrigin.z,e.mDir.x,e.mDir.y,e.mDir.z,e.mMinT,e.mMaxT,e.mRadiance.r,e.mRadiance.g,e.mRadiance.b);
    }
}
