// Integration of background texture readiness, actual CUDA shading, owned CPU resume.
// Does not reconstruct a native MoonRay path or publish a rendered image.
#include "native_lambert_queue.cc"
#include "shading_dispatch.h"
#include <fstream>
#include <iostream>
using namespace xpu2;using namespace xpu2::texture;
using Dispatch=ShadingDispatch<Queue>;
static void require(bool ok,const char* why){if(!ok){std::cerr<<why<<std::endl;std::exit(2);}}
template<class F>static void until(F f){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(10);while(!f()){require(std::chrono::steady_clock::now()<end,"Stage timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
struct Gate {std::mutex mutex;std::condition_variable cv;bool entered=false,open=false;
    void wait(){std::unique_lock<std::mutex> lock(mutex);entered=true;cv.notify_all();if(!cv.wait_for(lock,std::chrono::seconds(10),[&]{return open;}))throw std::runtime_error("Decode gate timeout");}
    void release(){std::lock_guard<std::mutex> lock(mutex);open=true;cv.notify_all();}
    bool started(){std::lock_guard<std::mutex> lock(mutex);return entered;}
};
struct RamOnly:Backend {std::shared_ptr<DevicePage> upload(const Bytes&)override{throw std::logic_error("Dispatcher attempted synchronous GPU tile upload");}void drain()override{}};
static Key key(){return {"synthetic-half-albedo.tx","linear-float-rgb",1};}
static DependencyView dependencies(){indexed::SceneIndex index;auto initial=emptyDependencies(index.acquire());auto candidate=index.prepare(index.acquire(),{{"file",indexed::Kind::Attribute,{},std::set<std::string>{},{}},{"material",indexed::Kind::Material,{},std::set<std::string>{"file"},{}}},{},[](auto,auto,const auto& b){return b;});auto result=prepareDependencies(initial,candidate,{{"file",{{key()},{}}}},{});require(index.commit(candidate),"Index commit failed");return result;}
static ShadingJob packet(const std::vector<uint8_t>& raw,unsigned n){ShadingJob job;job.count=8;
    for(unsigned lane=0;lane<8;++lane){auto src=raw.data()+4+(n*8+lane)*164;std::memcpy(job.input.data()+lane*24,src,96);std::memcpy(job.native.data()+lane*8,src+96,28);uint32_t valid;std::memcpy(&valid,src+124,4);job.native[lane*8+7]=float(valid);job.paths[lane]=1000+n*8+lane;}
    for(unsigned i=0;i<224;++i)job.context[i]=n*224+i;return job;
}
static void tint(ShadingJob& job,float f){for(int lane=0;lane<job.count;++lane)for(int c=0;c<3;++c){job.input[lane*24+14+c]*=f;job.native[lane*8+3+c]*=f;}}
static Dispatch::Lease take(Dispatch& d,const Dispatch::Token& token){Dispatch::Lease lease;until([&]{d.pump();return d.claim(token,lease);});return lease;}
static void verify(const Dispatch::Lease& lease,ShadingJob expected,uint64_t attempt,uint64_t revision,bool gpu=true){
    auto values=expected.native;if(gpu)for(int lane=0;lane<expected.count;++lane)for(int c=3;c<6;++c)values[lane*8+c]*=0.5f;
    require(bool(lease.result)&&lease.result->failure.empty(),"Unexpected stage failure");
    require(lease.result->job.paths==expected.paths&&lease.result->job.context==expected.context&&lease.result->job.input==expected.input&&lease.result->job.native==expected.native&&lease.result->job.count==expected.count,"Owned payload or sample identity corrupted");
    require(lease.result->values==values&&lease.result->attempt==attempt&&lease.result->revision==revision,"Shader output/generation mismatch");
}
int main(int argc,char** argv){try{
    require(argc==3,"Expected scenario and fixture");const std::string mode=argv[1];
    std::ifstream input(argv[2],std::ios::binary);std::vector<uint8_t> raw((std::istreambuf_iterator<char>(input)),{});require(raw.size()>=4+66*8*164&&!std::memcmp(raw.data(),"XNI1",4),"Bad native fixture");
    const bool missing=mode=="missing_ptx",fallback=mode=="admission_fallback";
    Gate gate;RamOnly backend;Cache cache(backend,{128,128,128});
    const auto owner=std::this_thread::get_id();
    AsyncTextureLoader loader([&]{require(std::this_thread::get_id()!=owner,"Decoder factory on coordinator");return [&](const Key&,size_t n){gate.wait();if(mode=="decode_failure")throw std::runtime_error("Injected decode failure");Bytes data(n);float half=0.5f;for(size_t i=0;i<n;i+=4)std::memcpy(data.data()+i,&half,4);return data;};},128,4);
    Queue q;
    unsigned prepared=0;
    Dispatch d(cache,loader,q,[&](ShadingJob& job,const TextureWorkQueue::Ready& ready,Cache& c){
        ++prepared;if(mode=="prepare_failure")throw std::runtime_error("Injected preparation failure");
        if(mode=="nonfinite"){uint32_t bits=0x7fc00000u;std::memcpy(&job.native[3],&bits,4);return;}
        if(mode=="identity_failure"){++job.paths[0];return;}
        if(!ready.pages.empty()){require(ready.pages.size()==1&&!ready.pages[0].device,"Wrong tile ownership");const auto& bytes=c.cpu(ready.pages[0]);require(bytes.size()==12,"Wrong tile size");float half;std::memcpy(&half,bytes.data(),4);require(half==0.5f,"Wrong decoded tint");tint(job,half);}
    },mode=="leased_restart"?1:32);
    auto deps=dependencies();d.begin(1,17,deps);auto original=packet(raw,0);
    if(mode=="nonfinite"){
        auto invalid=original;uint32_t bits=0x7fc00000u;std::memcpy(&invalid.input[14],&bits,4);
        require(!d.submit(88,"",invalid),"NaN input admitted");invalid=original;bits=0x7f800000u;std::memcpy(&invalid.native[3],&bits,4);
        require(!d.submit(88,"",invalid),"Infinite oracle admitted");
        auto token=d.submit(88,"",original);require(bool(token),"Invalid input consumed logical identity");
        auto result=take(d,token);require(result.result->route==Dispatch::Route::Failed&&d.finish(result)==Dispatch::Finish::Failed,"NaN preparation reached film");gate.release();
    }else if(mode=="pipeline"||missing||fallback){
        auto blocked=d.submit(1,"material",original,{{key(),12}});require(bool(blocked),"Texture job refused");d.pump();until([&]{return gate.started();});
        std::unique_lock<std::mutex> gpuHeld(q.device.mutex);
        auto caller=packet(raw,1);auto expected=caller;auto ready=d.submit(2,"",caller);caller={};require(bool(ready),"Ready job refused");d.pump();
        Dispatch::Lease noWrite;
        if(!fallback)require(!d.claim(ready,noWrite)&&!noWrite.result,"GPU wait blocked or prematurely published");
        // The submit/pump caller has returned and can perform independent work.
        uint64_t cpu=0;for(unsigned i=0;i<10000;++i)cpu+=i;require(cpu==49995000,"CPU continuation work failed");
        gpuHeld.unlock();auto first=take(d,ready);verify(first,expected,1,17,!missing&&!fallback);
        require(!gate.open&&d.finish(first)==Dispatch::Finish::Accepted,"Ready shading did not bypass blocked decode");
        require(d.finish(first)==Dispatch::Finish::Invalid,"Duplicate film admission");
        gate.release();auto second=take(d,blocked);tint(original,0.5f);verify(second,original,1,17,!missing&&!fallback);
        require(d.finish(second)==Dispatch::Finish::Accepted,"Textured stage resume rejected");require(cache.discard(key(),false),"RAM tile lease leaked after dispatch");
        require(!d.submit(2,"",expected),"Duplicate sample ownership admitted");
    }else if(mode=="restart"){
        auto blocked=d.submit(1,"material",original,{{key(),12}});d.pump();until([&]{return gate.started();});
        std::unique_lock<std::mutex> gpuHeld(q.device.mutex);auto old=d.submit(2,"",original);d.pump();
        until([&]{std::lock_guard<std::mutex> lock(q.mutex);return q.pending.empty();});
        d.begin(2,18,deps);require(loader.stats().heldBytes==12,"Cancelled decode reservation released early");Dispatch::Lease empty;
        require(!d.claim(blocked,empty)&&!d.claim(old,empty)&&!empty.result,"Old attempt resumed");
        auto fresh=d.submit(2,"",original);require(bool(fresh)&&fresh.serial!=old.serial,"New attempt alias");d.pump();gate.release();gpuHeld.unlock();
        auto next=take(d,fresh);verify(next,original,2,18);require(d.finish(next)==Dispatch::Finish::Accepted,"Restart did not recover");
    }else if(mode=="leased_restart"){
        auto token=d.submit(1,"",original);auto lease=take(d,token);verify(lease,original,1,17);
        d.begin(2,17,deps);d.begin(3,18,deps);require(!d.submit(1,"",original)&&d.outstanding()==1,"CPU resume lease escaped capacity on restart");
        require(!d.close(),"Close ignored live consumer");require(d.finish(lease)==Dispatch::Finish::Revoked,"Old CPU result allowed publication");
        d.begin(4,18,deps);auto fresh=d.submit(1,"",original);auto result=take(d,fresh);verify(result,original,4,18);require(d.finish(result)==Dispatch::Finish::Accepted,"New CPU resume refused");gate.release();
    }else if(mode=="decode_failure"||mode=="prepare_failure"||mode=="identity_failure"){
        auto token=d.submit(1,"material",original,{{key(),12}});gate.release();auto result=take(d,token);
        require(result.result->route==Dispatch::Route::Failed&&!result.result->failure.empty(),"Failed job manufactured shading");
        require(d.finish(result)==Dispatch::Finish::Failed,"Failed job allowed into film");require(d.stats().dispatched==0,"Failed job reached GPU");
    }else if(mode=="capacity"){
        std::unique_lock<std::mutex> gpuHeld(q.device.mutex);std::array<Dispatch::Token,32> tokens;std::array<Dispatch::Lease,32> leases;
        for(unsigned n=0;n<32;++n){auto job=packet(raw,n);tokens[n]=d.submit(n,"",job);require(bool(tokens[n]),"Bounded admission refused");job={};}d.pump(32);
        require(!d.submit(33,"",original),"Dispatch capacity exceeded");gpuHeld.unlock();
        for(int n=31;n>=0;--n){leases[n]=take(d,tokens[n]);verify(leases[n],packet(raw,n),1,17);}
        require(!d.submit(33,"",original),"Claimed CPU work lost capacity charge");
        bool foreignRejected=false;std::thread foreign([&]{try{d.pump();}catch(const std::logic_error&){foreignRejected=true;}});foreign.join();require(foreignRejected,"Foreign coordinator accepted");
        for(auto& lease:leases){auto forged=lease;forged.result=std::make_shared<Dispatch::Result>(*lease.result);require(d.finish(forged)==Dispatch::Finish::Invalid,"Forged result accepted");require(d.finish(lease)==Dispatch::Finish::Accepted,"Reverse CPU drain failed");}
        gate.release();
    }else if(mode=="ready_restart"){
        auto old=d.submit(1,"",original);d.pump();until([&]{std::lock_guard<std::mutex> lock(q.mutex);return q.merged==1;});d.pump();
        d.begin(2,18,deps);Dispatch::Lease empty;require(!d.claim(old,empty),"Ready old result survived restart");
        auto fresh=d.submit(1,"",original);auto lease=take(d,fresh);verify(lease,original,2,18);require(d.finish(lease)==Dispatch::Finish::Accepted,"Ready restart did not recover");gate.release();
    }else if(mode=="close_pending"){
        std::unique_lock<std::mutex> gpuHeld(q.device.mutex);auto old=d.submit(1,"",original);d.pump();until([&]{std::lock_guard<std::mutex> lock(q.mutex);return q.pending.empty();});
        require(d.close(),"Close retained unclaimed CPU work");Dispatch::Lease empty;require(!d.claim(old,empty),"Closed job resumed");
        {std::lock_guard<std::mutex> lock(q.mutex);require(q.retainedAsync==1,"In-flight cancellation released GPU credit early");}
        require(!q.stop(std::chrono::milliseconds(1)),"Blocked GPU stop incorrectly completed");gpuHeld.unlock();gate.release();
    }else throw std::runtime_error("Unknown case");
    require(d.close()&&d.outstanding()==0,"Dispatcher did not drain");require(q.stop(std::chrono::seconds(5)),"GPU cleanup failed");
    loader.close();require(cache.close(),"Texture cache leaked");
    {std::lock_guard<std::mutex> lock(q.mutex);require(!q.retainedAsync&&!q.failed&&!q.device.cleanupErrors,"GPU terminal state invalid");q.snapshot();}
    const auto stats=d.stats();std::cout<<"{\"case\":\""<<mode<<"\",\"passed\":true,\"accepted\":"<<stats.accepted<<",\"revoked\":"<<stats.revoked<<",\"failed\":"<<stats.failed<<",\"dispatched\":"<<stats.dispatched<<",\"admitted\":"<<stats.admitted<<",\"cancelled\":"<<stats.cancelled<<",\"peak_jobs\":"<<stats.peak<<",\"prepared\":"<<prepared<<",\"outstanding\":0}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
