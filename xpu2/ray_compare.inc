// Diagnostic only. Included inside xpuRayBundleHandler after OptiX hit copy.
// Logging leaves the rendered path unchanged. A separate, explicitly enabled
// causal experiment can replace only these pixels' primary hits with Embree.
{
    static const bool enabled = []() {
        const char* value = std::getenv("XPU2_TRACE_RAYS");
        return value && std::strcmp(value, "1") == 0;
    }();
    if (enabled && (rs->mSubpixel.mPixel == pixelLocationToUint32(96, 77) ||
                    rs->mSubpixel.mPixel == pixelLocationToUint32(132, 96))) {
        xpu2RememberNormal(rs->mSubpixel.mPixel, rs->mSubpixel.mSubpixelIndex, rs->mRay.getDepth(),
                           rs->mRay.Ng.x,rs->mRay.Ng.y,rs->mRay.Ng.z);
        const auto incoming = rsCPU.mRay;
        fs.mEmbreeAccel->intersect(rsCPU.mRay);
        const auto &cpu = rsCPU.mRay;
        const auto &gpu = rs->mRay;
        static std::mutex traceMutex;
        std::lock_guard<std::mutex> lock(traceMutex);
        std::fprintf(stderr, "XPU2_RAY {\"pixel\":%u,\"sample\":%d,\"sequence\":%u,\"depth\":%d,\"batch\":%u,"
                     "\"origin\":[%.9g,%.9g,%.9g],\"direction\":[%.9g,%.9g,%.9g],"
                     "\"near\":%.9g,\"far\":%.9g,\"time\":%.9g,\"mask\":%u,",
                     rs->mSubpixel.mPixel, rs->mSubpixel.mSubpixelIndex, rs->mSequenceID,
                     incoming.getDepth(), numEntries,
                     incoming.org.x,incoming.org.y,incoming.org.z,
                     incoming.dir.x,incoming.dir.y,incoming.dir.z,
                     incoming.tnear,incoming.tfar,incoming.time,incoming.mask);
        auto hit = [](const char* label, const mcrt_common::Ray &r) {
            std::fprintf(stderr, "\"%s\":{\"geom\":%u,\"prim\":%u,\"inst\":%u,\"t\":%.9g",
                         label,r.geomID,r.primID,r.instID,r.tfar);
            // Miss-hit attributes are undefined; do not read them.
            if (r.geomID != unsigned(-1)) {
                std::fprintf(stderr, ",\"uv\":[%.9g,%.9g],\"Ng\":[%.9g,%.9g,%.9g]",
                             r.u,r.v,r.Ng.x,r.Ng.y,r.Ng.z);
            }
            std::fprintf(stderr, "}");
        };
        hit("cpu",cpu); std::fprintf(stderr, ","); hit("gpu",gpu);
        const char* replay = std::getenv("XPU2_REPLAY_CPU_PRIMARY");
        const bool replaced = replay && std::strcmp(replay, "1") == 0 && incoming.getDepth() == 0;
        std::fprintf(stderr, ",\"replayed_primary\":%s}\n", replaced ? "true" : "false");
        if (replaced) rs->mRay = rsCPU.mRay;
    }
}
