// Included once in Film.cc, after MoonRay headers and before its namespace.
#include "deferred_film.h"
#include "native_deferred_film.h"
#include <atomic>
#include <cstdio>
#include <cstdlib>
namespace xpu2::nativefilm {
using namespace moonray;
using deferredfilm::Sample;using deferredfilm::Samples;using deferredfilm::Packet;
namespace {
std::unique_ptr<deferredfilm::Queue> queue;
uint64_t epoch=0;
std::atomic<uint64_t> fallback{0},suspended{0},resumed{0};
bool enabled(){const char* s=std::getenv("XPU2_DEFERRED_FILM");return s&&std::strcmp(s,"1")==0;}
thread_local bool publishing=false;
void publish(mcrt_common::ThreadLocalState* tls,unsigned n,pbr::BundledRadiance** entries,rndr::Film* film){
    struct Guard {Guard(){publishing=true;}~Guard(){publishing=false;}} guard;
    rndr::Film::addSampleBundleHandler(tls,n,entries,film);
}
uint64_t owner(mcrt_common::ThreadLocalState* tls){return reinterpret_cast<uintptr_t>(tls);}
void resume(mcrt_common::ThreadLocalState* tls,rndr::Film* film,bool wait){
    if(!queue)return;Packet packet;
    while(queue->take(owner(tls),wait,packet)){
        if(packet.revoked)continue;
        const Samples& values=packet.failed?packet.original:packet.result;
        std::vector<pbr::BundledRadiance> entries(values.size());std::vector<pbr::BundledRadiance*> ptrs(values.size());
        for(size_t i=0;i<values.size();++i){const auto& s=values[i];auto& b=entries[i];
            b.mRadiance=scene_rdl2::math::Vec4f(s.rgba[0],s.rgba[1],s.rgba[2],s.rgba[3]);b.mPathPixelWeight=s.weight;
            b.mPixel=s.pixel;b.mSubPixelIndex=s.subpixel;b.mTilePass=s.tilePass;
            b.mDeepDataHandle=pbr::nullHandle;b.mCryptomatteDataHandle=pbr::nullHandle;ptrs[i]=&b;
        }
        publish(tls,unsigned(ptrs.size()),ptrs.data(),film);resumed+=values.size();
    }
}
}
void begin(){
    if(!enabled())return;
    if(queue)throw std::logic_error("Previous film frame not closed");
    fallback=0;suspended=0;resumed=0;
    queue=std::make_unique<deferredfilm::Queue>([](Samples& samples){
        if(const char* delay=std::getenv("XPU2_DEFERRED_DELAY_MS")){
            int ms=std::atoi(delay);if(ms>0&&ms<=250)std::this_thread::sleep_for(std::chrono::milliseconds(ms));
        }
        if(std::getenv("XPU2_DEFERRED_INVALID")){
            const uint32_t bits=0x7fc00000u;std::memcpy(&samples[0].rgba[0],&bits,sizeof(bits));
        }
        // Transport validation backend; no shading work or GPU acceleration claimed.
        if(std::getenv("XPU2_DEFERRED_FAIL"))throw std::runtime_error("Injected film backend failure");
        if(std::getenv("XPU2_DEFERRED_SENTINEL"))for(auto& s:samples)for(unsigned c=0;c<3;++c)s.rgba[c]*=0.5f;
    });++epoch;queue->begin(epoch,epoch);
}
void drain(mcrt_common::ThreadLocalState* tls,rndr::Film* film){resume(tls,film,true);}
void finish(){
    if(!queue)return;
    if(queue->outstanding())throw std::logic_error("Undrained native film continuation");
    queue->shutdown();auto s=queue->stats();
    if(const char* path=std::getenv("XPU2_DEFERRED_PROFILE"))if(FILE* f=std::fopen(path,"a")){
        std::fprintf(f,"{\"epoch\":%llu,\"jobs\":%llu,\"resumed_jobs\":%llu,\"failed_jobs\":%llu,\"revoked_jobs\":%llu,\"declined\":%llu,\"peak_jobs\":%zu,\"peak_bytes\":%zu,\"suspended_samples\":%llu,\"resumed_samples\":%llu,\"fallback_batches\":%llu,\"outstanding\":0}\n",
            (unsigned long long)epoch,(unsigned long long)s.admitted,(unsigned long long)s.resumed,(unsigned long long)s.failed,(unsigned long long)s.revoked,(unsigned long long)s.declined,s.peakJobs,s.peakBytes,(unsigned long long)suspended.load(),(unsigned long long)resumed.load(),(unsigned long long)fallback.load());std::fclose(f);
    }queue.reset();
}
bool defer(mcrt_common::ThreadLocalState* tls,unsigned n,pbr::BundledRadiance** entries,rndr::Film* film,bool adaptive){
    if(publishing||!queue||!n)return false;
    // Adaptive convergence reads the film before the pass drain. Until its
    // cross-owner completion barrier is integrated, preserve native visibility.
    if(adaptive){++fallback;return false;}
    resume(tls,film,false);
    Samples samples;samples.reserve(n);
    for(unsigned i=0;i<n;++i){const auto& b=*entries[i];
        if(b.mDeepDataHandle!=pbr::nullHandle||b.mCryptomatteDataHandle!=pbr::nullHandle){
            drain(tls,film);++fallback;return false; // native handles stay on original stack
        }
        samples.push_back({{b.mRadiance.x,b.mRadiance.y,b.mRadiance.z,b.mRadiance.w},b.mPathPixelWeight,b.mPixel,b.mSubPixelIndex,b.mTilePass});
    }
    if(!queue->submit(epoch,epoch,owner(tls),samples)){
        drain(tls,film);
        if(!queue->submit(epoch,epoch,owner(tls),samples)){++fallback;return false;}
    }
    if(suspended.fetch_add(n)==0){std::fprintf(stderr,"XPU2_FILM_SUSPENDED %llu\n",(unsigned long long)epoch);std::fflush(stderr);}
    return true;
}
} // namespace
