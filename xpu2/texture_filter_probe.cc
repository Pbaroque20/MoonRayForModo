// Standalone CUDA/OIIO filtering validation; not connected to MoonRay shading.
#include "texture_oiio_loader.h"
#include "texture_residency.h"
#include "texture_async.h"
#include "texture_work.h"
#include "texture_cuda_backend.h"
#include <OpenImageIO/texture.h>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
using namespace xpu2::texture;
struct Query {float s,t;int mode,wrap;};struct Answer {int status;float value[4];};
static_assert(sizeof(Query)==16&&sizeof(Answer)==20);
struct DecodeGate {
    std::mutex mutex;std::condition_variable cv;bool entered=false,open=false;
    void wait(){std::unique_lock<std::mutex> lock(mutex);entered=true;cv.notify_all();if(!cv.wait_for(lock,std::chrono::seconds(10),[&]{return open;}))throw std::runtime_error("Decode gate timeout");}
    void release(){std::lock_guard<std::mutex> lock(mutex);open=true;cv.notify_all();}
    bool blocked(){std::lock_guard<std::mutex> lock(mutex);return entered&&!open;}
};
struct ReleaseGate {DecodeGate& gate;~ReleaseGate(){gate.release();}};
struct Completed:Fence {bool ready()override{return true;}void wait()override{}};
static void require(bool ok,const std::string& message){if(!ok)throw std::runtime_error(message);}
struct Kernel {
    CudaBackend& d;CUmodule module=nullptr;CUfunction function=nullptr;
    decltype(&cuModuleLoadData) load=nullptr;decltype(&cuModuleGetFunction) get=nullptr;
    decltype(&cuModuleUnload) unload=nullptr;decltype(&cuLaunchKernel) launch=nullptr;
    explicit Kernel(CudaBackend& driver,const std::filesystem::path& p):d(driver){
#define LOAD(n,f) f=reinterpret_cast<decltype(f)>(GetProcAddress(d.library,#n));require(f!=nullptr,"Missing CUDA " #n);
        LOAD(cuModuleLoadData,load) LOAD(cuModuleGetFunction,get) LOAD(cuModuleUnload,unload) LOAD(cuLaunchKernel,launch)
#undef LOAD
        std::ifstream file(p,std::ios::binary);require(bool(file),"Missing PTX");std::string code{std::istreambuf_iterator<char>(file),{}};
        CudaBackend::check(load(&module,code.c_str()));try{CudaBackend::check(get(&function,module,"texture_filter"));}catch(...){unload(module);module=nullptr;throw;}
    }
    ~Kernel(){if(module){d.cleanup(d.cuStreamSynchronize_(d.consumers));d.cleanup(unload(module));}}
    struct Buffer {
        CudaBackend& d;CUdeviceptr pointer=0;void* host=nullptr;size_t bytes;
        Buffer(CudaBackend& device,size_t n):d(device),bytes(n){CudaBackend::check(d.cuMemAlloc_v2_(&pointer,n));try{CudaBackend::check(d.cuMemAllocHost_v2_(&host,n));}catch(...){d.cuMemFree_v2_(pointer);throw;}}
        ~Buffer(){d.cleanup(d.cuStreamSynchronize_(d.consumers));if(host)d.cleanup(d.cuMemFreeHost_(host));if(pointer)d.cleanup(d.cuMemFree_v2_(pointer));}
        void write(const void* src){std::memcpy(host,src,bytes);CudaBackend::check(d.cuMemcpyHtoDAsync_v2_(pointer,host,bytes,d.consumers));}
    };
    std::vector<Answer> run(const std::vector<uint64_t>& pages,OiioTileLoader::Level s,const std::vector<Query>& q,Cache& cache,std::vector<Cache::Lease>& leases,bool retire=true){
        Buffer pointers(d,pages.size()*8),input(d,q.size()*sizeof(Query)),output(d,q.size()*sizeof(Answer));pointers.write(pages.data());input.write(q.data());
        unsigned count=unsigned(q.size()),pageCount=unsigned(pages.size());void* args[]={&pointers.pointer,&s.width,&s.height,&s.channels,&s.tileWidth,&s.tileHeight,&pageCount,&input.pointer,&output.pointer,&count};
        CudaBackend::check(launch(function,(count+127)/128,1,1,128,1,1,0,d.consumers,args,nullptr));
        CudaBackend::check(d.cuMemcpyDtoHAsync_v2_(output.host,output.pointer,output.bytes,d.consumers));
        auto done=std::make_shared<CudaBackend::Event>(d,d.consumers);
        if(retire)for(const auto& lease:leases)cache.retire(lease,done);leases.clear();done->wait();cache.poll();
        std::vector<Answer> result(q.size());std::memcpy(result.data(),output.host,output.bytes);return result;
    }
};
static void image(const std::filesystem::path& p,const std::vector<float>& data){
    auto out=OIIO::ImageOutput::create(p.u8string());require(bool(out),"Cannot create image writer");
    require(out->open(p.u8string(),OIIO::ImageSpec(96,64,4,OIIO::TypeDesc::FLOAT)),"Cannot open test image");
    require(out->write_image(OIIO::TypeDesc::FLOAT,data.data())&&out->close(),"Cannot write test image");
}
int main(int argc,char** argv){try{
    require(argc==4,"Expected fixtures, PTX, output");std::filesystem::path fixtures(argv[1]),out(argv[3]);
    OIIO::attribute("threads",1);OIIO::attribute("exr_threads",-1);
    auto ref=OIIO::TextureSystem::create(false);
    require(ref->attribute("automip",0)&&ref->attribute("autotile",0)&&ref->attribute("accept_untiled",0)&&ref->attribute("accept_unmipped",0)&&ref->attribute("gray_to_rgb",1),"OIIO reference configuration failed");
    CudaBackend device(32768,65536);unsigned cases=0,statusChecks=0;uint64_t sampleCount=0,exact=0,components=0,policyEvictions=0;double pointMax=0,bilinearMax=0,sumSquared=0;bool passed=true;AsyncTextureLoader::Stats decodeStats;uint64_t scheduled=0,readyGpuBypasses=0;
    std::ofstream detail(out/"cases.jsonl");require(bool(detail),"Cannot write case log");
    {
        Kernel kernel(device,argv[2]);OiioTileLoader loader;Cache cache(device,{262144,32768,65536});
        DecodeGate gate;const auto coordinator=std::this_thread::get_id();
        AsyncTextureLoader worker([coordinator,&gate]{
            require(std::this_thread::get_id()!=coordinator,"Decoder created on coordinator");
            auto decoder=std::make_shared<OiioTileLoader>();
            return [decoder,&gate,registered=std::set<std::pair<std::string,uint64_t>>{}](const Key& key,size_t bytes)mutable{
                auto identity=std::make_pair(key.asset,key.revision);
                if(!registered.count(identity)){
                    auto base=decoder->registerFile(std::filesystem::u8path(key.asset),key.revision);
                    require(base.asset==key.asset&&base.interpretation==key.interpretation,"Worker interpretation mismatch");registered.insert(identity);
                }
                if(std::filesystem::u8path(key.asset).filename()=="rgba.tx"&&(key.x||key.y))gate.wait();
                return decoder->load(key,bytes);
            };
        },65536,64);
        for(const auto* name:{"rgba.tx","rgb.tx","gray.tx","rg.tx"}){
            Key base=loader.registerFile(fixtures/name,1);auto s=loader.level(base);require(s.x==0&&s.y==0,"This filter requires a zero-origin window");
            const int cols=(s.width+s.tileWidth-1)/s.tileWidth,rows=(s.height+s.tileHeight-1)/s.tileHeight;
            std::vector<TextureRequest> requests;
            for(int y=0;y<rows;++y)for(int x=0;x<cols;++x){auto key=base;key.x=x;key.y=y;requests.push_back({name,key,loader.tile(key).bytes,true,true,1,8,.0001,.00001,0});}
            auto plan=planTextures(cache.residency(),requests,{262144,65536,32768,65536});
            require(!plan.pinnedOverBudget&&plan.defer.empty()&&plan.gpu<=32768,"Policy failed to admit fixture within reserved budget");
            auto evictions=cache.stats().gpuEvictions;require(trimTextures(cache,plan),"Policy trim failed");policyEvictions+=cache.stats().gpuEvictions-evictions;
            xpu2::indexed::SceneIndex sceneIndex;auto initial=emptyDependencies(sceneIndex.acquire());
            auto candidate=sceneIndex.prepare(sceneIndex.acquire(),{{"source",xpu2::indexed::Kind::Attribute,{},std::set<std::string>{},{}},{name,xpu2::indexed::Kind::Material,{},std::set<std::string>{"source"},{}}},{},[](auto,auto,const auto& bytes){return bytes;});
            auto dependencies=prepareDependencies(initial,candidate,{{"source",{{base},{}}}},{});require(sceneIndex.commit(candidate),"Dependency scene commit failed");
            TextureWorkQueue queue(cache,worker);ReleaseGate release{gate};queue.begin(1,dependencies);uint64_t nextJob=0;TextureWorkQueue::Lease active;
            bool proveBypass=std::string(name)=="rgba.tx";
            if(proveBypass){auto first=loader.tile(base);auto end=std::chrono::steady_clock::now()+std::chrono::seconds(10);std::optional<Cache::Lease> warm;
                while(!(warm=cache.acquire(base,first.bytes,[&](const Key& k,size_t n){return loader.load(k,n);},true))){require(std::chrono::steady_clock::now()<end,"Warm page timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
                cache.retire(*warm,std::make_shared<Completed>());
            }
            auto resident=[&](std::vector<Cache::Lease>& leases){
                std::vector<TextureWorkQueue::Need> needs;for(const auto& r:requests)needs.push_back({r.key,r.bytes});
                auto id=++nextJob;require(queue.submit(id,name,{},needs,true),"Texture work admission failed");
                if(proveBypass)require(queue.submit(UINT64_MAX,name,{},{{base,loader.tile(base).bytes}},true),"Warm bypass admission failed");
                auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
                for(;;){require(std::chrono::steady_clock::now()<deadline,"Texture work timeout");auto ready=queue.claim();if(!ready){std::this_thread::sleep_for(std::chrono::milliseconds(1));continue;}
                    require(ready->failure.empty(),"Queued texture failed: "+ready->failure);
                    if(ready->id==UINT64_MAX){
                        while(!gate.blocked()){require(std::chrono::steady_clock::now()<deadline,"Decoder did not enter gate");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
                        std::vector<uint64_t> pages(cols*rows,0);pages[0]=cache.gpu(ready->pages[0]);auto holds=ready->pages;
                        auto sampled=kernel.run(pages,s,{{.5f/s.width,.5f/s.height,0,1}},cache,holds,false);auto expected=loader.load(base,loader.tile(base).bytes);
                        require(sampled[0].status==0&&std::memcmp(sampled[0].value,expected.data(),s.channels*sizeof(float))==0,"Ready GPU bypass sample mismatch");
                        require(gate.blocked()&&queue.finish(ready,std::make_shared<Completed>())==TextureWorkQueue::Finish::Accepted,"GPU bypass did not finish during blocked decode");
                        ++readyGpuBypasses;proveBypass=false;gate.release();continue;
                    }
                    require(ready->id==id,"Unexpected work identity");active=ready;leases=ready->pages;std::vector<uint64_t> pages;for(const auto& p:leases)pages.push_back(cache.gpu(p));return pages;
                }
            };
            auto execute=[&](const std::vector<uint64_t>& pages,OiioTileLoader::Level level,const std::vector<Query>& queries,std::vector<Cache::Lease>& leases){
                auto result=kernel.run(pages,level,queries,cache,leases,false);
                require(queue.finish(active,std::make_shared<Completed>())==TextureWorkQueue::Finish::Accepted,"Scheduled contribution rejected");active.reset();return result;
            };
            for(int mode=0;mode<2;++mode)for(int wrap=0;wrap<4;++wrap){
                std::vector<Query> q;
                for(int y=0;y<64;++y)for(int x=0;x<96;++x)q.push_back({-0.25f+1.5f*(x+.5f)/96,-0.25f+1.5f*(y+.5f)/64,mode,wrap});
                // Dense edge/tile-boundary cases plus deterministic irregular UVs.
                for(float u:{-2.f,-1.f,-.001f,0.f,.00001f,.5f,1.f,1.00001f,2.f,4.f})for(float v:{-.1f,0.f,.5f,1.f,1.1f})q.push_back({u,v,mode,wrap});
                for(int edge=0;edge<=s.width;++edge)for(float offset:{-.0001f,0.f,.0001f,.5f})q.push_back({(edge+offset)/s.width,.371f,mode,wrap});
                uint32_t seed=7351;for(int i=0;i<1024;++i){seed=1664525u*seed+1013904223u;float u=float(seed>>8)/16777216.f;seed=1664525u*seed+1013904223u;float v=float(seed>>8)/16777216.f;q.push_back({4*u-1.5f,4*v-1.5f,mode,wrap});}
                std::vector<Cache::Lease> leases;auto pages=resident(leases);auto result=execute(pages,s,q,leases);
                OIIO::TextureOpt opt;opt.mipmode=OIIO::TextureOpt::MipModeNoMIP;opt.interpmode=mode?OIIO::TextureOpt::InterpBilinear:OIIO::TextureOpt::InterpClosest;
                const OIIO::TextureOpt::Wrap wraps[]={OIIO::TextureOpt::WrapBlack,OIIO::TextureOpt::WrapClamp,OIIO::TextureOpt::WrapPeriodic,OIIO::TextureOpt::WrapMirror};opt.swrap=opt.twrap=wraps[wrap];
                double maximum=0,sq=0;uint64_t mismatch=0;std::vector<float> gpuImage,refImage;
                for(size_t i=0;i<q.size();++i){float native[4]={};require(ref->texture(OIIO::ustring(base.asset),opt,q[i].s,q[i].t,0,0,0,0,s.channels,native),"OIIO reference lookup failed: "+ref->geterror());require(result[i].status==0,"Unexpected CUDA lookup failure");
                    for(int c=0;c<s.channels;++c){float value=result[i].value[c];require(std::isfinite(value)&&std::isfinite(native[c]),"Nonfinite result");double e=std::abs(double(value)-native[c]);if(e&&mismatch==0)std::cerr<<name<<" mode="<<mode<<" wrap="<<wrap<<" uv="<<q[i].s<<","<<q[i].t<<" channel="<<c<<" gpu="<<value<<" cpu="<<native[c]<<"\n";maximum=std::max(maximum,e);sq+=e*e;mismatch+=std::memcmp(&value,&native[c],4)!=0;++components;}
                    if(i<96*64){gpuImage.insert(gpuImage.end(),result[i].value,result[i].value+4);refImage.insert(refImage.end(),native,native+4);}
                }
                // Threshold fixed before running: exact points; <=2e-6 absolute
                // for bilinear on these [0,1] fixtures. Never relax on failure.
                bool ok=maximum<=(mode?2e-6:0);passed&=ok;if(mode)bilinearMax=std::max(bilinearMax,maximum);else pointMax=std::max(pointMax,maximum);
                sampleCount+=q.size();exact+=uint64_t(q.size())*s.channels-mismatch;sumSquared+=sq;++cases;
                detail<<"{\"asset\":\""<<name<<"\",\"mode\":"<<mode<<",\"wrap\":"<<wrap<<",\"samples\":"<<q.size()<<",\"max_abs\":"<<maximum<<",\"rms\":"<<std::sqrt(sq/(q.size()*s.channels))<<",\"different_components\":"<<mismatch<<",\"passed\":"<<(ok?"true":"false")<<"}\n";detail.flush();
                if(std::string(name)=="rgba.tx"&&mode==1&&wrap==1){image(out/"texture-reference.exr",refImage);image(out/"texture-gpu.exr",gpuImage);}
            }
            std::vector<Query> guards={{.5f/s.width,.5f/s.height,0,1},{.5f,.5f,7,1},{.5f,.5f,0,99},{9.f,0.f,0,1},{std::numeric_limits<float>::quiet_NaN(),0,0,1}};
            std::vector<Cache::Lease> leases;auto pages=resident(leases);pages[0]=0;auto result=execute(pages,s,guards,leases);
            for(size_t i=0;i<result.size();++i){require(result[i].status==(i==0?3:(i==4?2:1)),"Fallback status mismatch");for(auto v:result[i].value)require(v==0,"Failed query published a contribution");++statusChecks;}
            std::vector<Query> one={{.5f/s.width,.5f/s.height,1,1}};
            pages=resident(leases);pages[0]=0;result=execute(pages,s,one,leases);require(result[0].status==3,"Bilinear missing-page fallback failed");++statusChecks;
            pages=resident(leases);pages.pop_back();result=execute(pages,s,one,leases);require(result[0].status==2,"Truncated page table accepted");++statusChecks;
            pages=resident(leases);auto invalid=s;invalid.channels=5;result=execute(pages,invalid,one,leases);require(result[0].status==2,"Unsupported channel count accepted");++statusChecks;
            scheduled+=queue.stats().accepted;require(queue.close(),"Scheduled work failed to close");
        }
        require(readyGpuBypasses==1&&scheduled==49,"Scheduled coverage incomplete");
        require(policyEvictions>0,"Residency policy did not evict GPU pages");require(cache.stats().peakVram<=32768&&device.vramArena->peak<=32768,"Reserved device budget exceeded");
        worker.close();decodeStats=worker.stats();
        require(decodeStats.loads>0&&decodeStats.failures==0&&decodeStats.heldBytes==0&&decodeStats.heldRecords==0&&decodeStats.peakBytes<=65536,"Background decode lifecycle failed");
        require(cache.close(),"Cache did not drain");
    }
    require(device.close()&&!device.cleanupErrors,"CUDA cleanup failed");
    std::cout<<"{\"passed\":"<<(passed?"true":"false")<<",\"cases\":"<<cases<<",\"queries\":"<<sampleCount<<",\"components\":"<<components<<",\"exact_components\":"<<exact<<",\"point_max_abs\":"<<pointMax<<",\"bilinear_max_abs\":"<<bilinearMax<<",\"rms\":"<<std::sqrt(sumSquared/components)<<",\"fallback_checks\":"<<statusChecks<<",\"policy_gpu_evictions\":"<<policyEvictions<<",\"scheduled_jobs\":"<<scheduled<<",\"ready_gpu_jobs_during_blocked_decode\":"<<readyGpuBypasses<<",\"background_decoded_tiles\":"<<decodeStats.loads<<",\"decode_queue_peak_bytes\":"<<decodeStats.peakBytes<<",\"decode_queue_peak_records\":"<<decodeStats.peakRecords<<",\"texture_vram_budget\":32768,\"reserved_device_bytes\":32768,\"point_tolerance\":0,\"bilinear_tolerance\":0.000002,\"cleanup_errors\":0}\n";
    return passed?0:2;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
