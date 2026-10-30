// Observation only: every queued radiance contribution at the selected pixels.
{
    static const bool trace = []() { const char* p=std::getenv("XPU2_TRACE_CONTRIBUTIONS"); return p && std::strcmp(p,"1")==0; }();
    if (trace) for (unsigned j=0;j<numEntries;++j) {
        const auto &e=entries[j];
        if (e.mPixel!=pixelLocationToUint32(96,77) && e.mPixel!=pixelLocationToUint32(132,96)) continue;
        std::fprintf(stderr,"XPU2_RADIANCE {\"pixel\":%u,\"sample\":%u,\"tile_pass\":%u,\"weight\":%.9g,\"rgba\":[%.9g,%.9g,%.9g,%.9g]}\n",
                     e.mPixel,e.mSubPixelIndex,e.mTilePass,e.mPathPixelWeight,e.mRadiance.x,e.mRadiance.y,e.mRadiance.z,e.mRadiance.w);
    }
}
