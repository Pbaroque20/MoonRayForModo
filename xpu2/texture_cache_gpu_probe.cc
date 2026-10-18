#include "texture_cuda_backend.h"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
using namespace xpu2::texture;
static void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(int argc,char** argv){try{
    require(argc==2,"Fixture directory required");std::filesystem::path root(argv[1]);
    auto loader=[&](const Key& key,size_t count){std::ifstream f(root/("r"+std::to_string(key.revision)+"m"+std::to_string(key.mip)+".tile"),std::ios::binary);if(!f)throw std::runtime_error("Missing tile fixture");return Bytes(std::istreambuf_iterator<char>(f),{});};
    Key a{"fixture","linear-rgba-f32",1,0},b=a,c=a;b.mip=1;c.revision=2;
    CudaBackend device(65536,65536);Stats stats;unsigned jobs=0;
    {
        Cache cache(device,{131072,65536,65536});
        auto acquire=[&](const Key& key,size_t bytes){auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);for(;;){if(auto lease=cache.acquire(key,bytes,loader,true))return *lease;if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("Texture admission timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}};
        auto cpu=cache.acquire(a,65536,loader,false);require(bool(cpu),"CPU admission failed");
        auto consume=[&](const Key& key,size_t bytes){auto lease=acquire(key,bytes);
            CudaBackend::Consumer job(device,cache.gpu(lease),bytes);
            require(!cache.close(),"GPU use lost its lease");
            if(key==a)require(!cache.prefetch(b,16384,loader),"Prefetch displaced pinned GPU tile");
            cache.retire(lease,job.completion);
            require(job.result()==loader(key,bytes),"CUDA texture byte mismatch");cache.poll();++jobs;
        };
        consume(a,65536);consume(b,16384);
        auto loads=cache.stats().loads;consume(a,65536);require(cache.stats().loads==loads,"RAM hit unexpectedly reloaded disk");
        consume(c,65536);
        require(cache.cpu(*cpu)==loader(a,65536),"Old revision CPU data changed");cache.release(*cpu);
        stats=cache.stats();require(stats.d2hBytes==0,"Clean texture eviction wrote back");
        require(stats.gpuEvictions>=3&&stats.peakRam<=131072&&stats.peakVram<=65536&&stats.peakStaging<=65536,"Cache bounds/eviction not exercised");
        require(cache.close(),"Cache did not drain");
    }
    require(device.vramArena->peak<=65536&&device.stagingArena->peak<=65536,"Actual arena budget exceeded");
    require(device.vramArena->reuses>0&&device.stagingArena->reuses>0,"Allocation reuse not exercised");
    require(device.close()&&!device.cleanupErrors,"CUDA cleanup failed");
    std::cout<<"{\"passed\":true,\"cuda_consumers\":"<<jobs<<",\"loads\":"<<stats.loads<<",\"h2d_bytes\":"<<stats.h2dBytes<<",\"eviction_d2h_bytes\":"<<stats.d2hBytes
    <<",\"verification_d2h_bytes\":"<<device.verificationReadbackBytes<<",\"gpu_evictions\":"<<stats.gpuEvictions<<",\"peak_ram\":"<<stats.peakRam<<",\"peak_vram\":"<<stats.peakVram<<",\"peak_staging\":"<<stats.peakStaging<<",\"upload_milliseconds\":"<<device.uploadMilliseconds<<",\"cpu_hits\":"<<stats.cpuHits<<",\"gpu_hits\":"<<stats.gpuHits<<",\"blocked_admissions\":"<<stats.blocked<<",\"pending_upload_polls\":"<<stats.pendingUploads<<",\"device_allocation_reuses\":"<<device.vramArena->reuses<<",\"pinned_allocation_reuses\":"<<device.stagingArena->reuses<<",\"peak_reserved_device\":"<<device.vramArena->peak<<",\"peak_reserved_pinned\":"<<device.stagingArena->peak<<",\"cleanup_errors\":0}\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
