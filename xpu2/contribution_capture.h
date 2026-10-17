// Bounded numeric diagnostics. No native light/BSDF/arena pointer is serialized.
namespace {
struct ContributionCapture {
    std::mutex mutex;FILE* file=nullptr;unsigned records=0;
    ContributionCapture(){const char* p=std::getenv("XPU2_CONTRIBUTION_CAPTURE");if(p && *p){file=std::fopen(p,"wb");if(!file || std::fwrite("XCR1",1,4,file)!=4)throw std::runtime_error("Contribution capture open failed");}}
    ~ContributionCapture(){if(file)std::fclose(file);}
};
ContributionCapture& contributionCapture(){static ContributionCapture c;return c;}
}
extern "C" __declspec(dllexport) int xpu2ContributionCaptureEnabled(){static const bool active=[] {const char* p=std::getenv("XPU2_CONTRIBUTION_CAPTURE");return p && *p;}();return active;}
extern "C" __declspec(dllexport) void xpu2CaptureContribution(const uint32_t* ids,const float* input,const float* output,int mask){
    auto& c=contributionCapture();std::lock_guard<std::mutex> lock(c.mutex);
    if(!c.file)throw std::runtime_error("Capture not enabled");
    for(unsigned lane=0;lane<8;++lane)if(mask & (1<<lane)){
        if(++c.records>4096)throw std::runtime_error("Contribution capture capacity exceeded");
        if(std::fwrite(ids+lane*8,32,1,c.file)!=1 || std::fwrite(input+lane*24,96,1,c.file)!=1 || std::fwrite(output+lane*8,32,1,c.file)!=1)throw std::runtime_error("Contribution capture write failed");
    }
    if(std::fflush(c.file))throw std::runtime_error("Contribution capture flush failed");
}
