#include "texture_residency.h"
#include <iostream>
#include <random>
using namespace xpu2::texture;
static unsigned checks=0;
static void check(bool v,const char* why){++checks;if(!v)throw std::runtime_error(why);}
template<class F>static void rejects(F f){bool bad=false;try{f();}catch(const std::exception&){bad=true;}check(bad,"Invalid policy input accepted");}
struct Done:Fence {bool ready()override{return true;}void wait()override{}};
struct Page:DevicePage {Bytes bytes;bool done=false;Page(const Bytes& b):bytes(b){}bool ready()override{return done;}void wait()override{done=true;}uint64_t address()const override{return reinterpret_cast<uint64_t>(bytes.data());}};
struct BackendTest:Backend {std::vector<std::weak_ptr<Page>> pages;std::shared_ptr<DevicePage> upload(const Bytes& b)override{auto p=std::make_shared<Page>(b);pages.push_back(p);return p;}void drain()override{for(auto w:pages)if(auto p=w.lock())p->done=true;}};
static Key key(unsigned x=0,unsigned revision=1,unsigned mip=0){return {"texture","raw-f32",revision,mip,x,0,0};}
static TextureRequest request(unsigned x,bool gpu=true,bool demand=true){return {"material",key(x),16,gpu,demand,0,1,.0001,.00001,0};}
int main(){try{
    ResidencyBudget budget{64,64,32,16};auto a=request(0),b=request(1),c=request(2);c.importance=1;
    auto p=planTextures({}, {a,b,c},budget);check(p.gpu==32&&p.admit.size()==2&&p.defer.size()==1,"Reserve/admission wrong");check(p.admit[0].key==c.key,"Priority not applied");
    auto shared=a;shared.material="other";p=planTextures({}, {a,shared},budget);check(p.gpu==16&&p.admit.size()==1&&p.hierarchy.size()==2,"Shared material page duplicated");
    b.key=key(0,2);c.key=key(0,1,1);p=planTextures({}, {a,b,c},{64,128,0,16});check(p.keep.size()==3&&p.hierarchy.size()==3,"Mip/revision collapsed");
    b=request(1);b.waitingEpochs=10;p=planTextures({}, {a,b},{64,32,16,16});check(p.admit[0].key==b.key,"Aged demand starved");
    a=request(0);b=request(1);b.demand=false;b.importance=1;b.waitingEpochs=100;
    p=planTextures({}, {a,b},{64,32,16,16});check(p.admit[0].key==a.key,"Prefetch displaced demand");
    auto speculation=request(3,true,false);speculation.savedSeconds=0;speculation.uploadSeconds=1;
    p=planTextures({}, {speculation},budget);check(p.admit.empty()&&p.defer.size()==1,"Unprofitable prefetch admitted");
    p=planTextures({}, {a},{64,16,16,16});check(p.admit.empty()&&p.defer.size()==1,"Zero texture budget ignored");
    p=planTextures({}, {a},{8,64,0,16});check(p.defer.size()==1,"Upload without RAM capacity");
    p=planTextures({}, {a},{64,64,0,8});check(p.defer.size()==1,"Upload without staging capacity");
    auto bad=a;bad.bytes=17;rejects([&]{planTextures({}, {a,bad},budget);});bad=a;bad.importance=2;rejects([&]{planTextures({}, {bad},budget);});
    bad=a;bad.savedSeconds=std::numeric_limits<double>::infinity();rejects([&]{planTextures({}, {bad},budget);});rejects([&]{planTextures({}, {a},{64,16,32,16});});
    // Snapshot/eviction honors a page's upload, CPU and consumer lifetime.
    BackendTest d;Cache cache(d,{64,32,16});auto load=[](const Key& k,size_t n){return Bytes(n,uint8_t(k.x+31*k.revision));};
    auto cpu=cache.acquire(a.key,16,load,false);check(bool(cpu),"CPU load failed");check(!cache.discard(a.key,false),"CPU pin discarded");
    check(!cache.acquire(a.key,16,load,true),"Upload returned ready");check(!cache.discard(a.key,true),"In-flight upload discarded");
    p=planTextures(cache.residency(),{request(1)}, {64,16,0,16});check(p.keep.count({a.key,true})&&p.defer.size()==1,"Pending upload not protected");
    d.drain();cache.poll();auto gpu=cache.acquire(a.key,16,load,true);check(bool(gpu),"GPU page not ready");
    p=planTextures(cache.residency(),{request(1)}, {64,8,0,16});check(p.pinnedOverBudget&&p.defer.size()==1&&p.drop.empty(),"Pinned shrink unsafe");
    cache.retire(*gpu,std::make_shared<Done>());cache.release(*cpu);
    p=planTextures(cache.residency(),{request(1)}, {64,16,0,16});check(p.drop.size()==1&&p.drop[0].gpu,"Cold GPU page not chosen");
    // A plan is stale once new work pins a victim. Trimming must refuse it.
    gpu=cache.acquire(a.key,16,load,true);check(!trimTextures(cache,p),"Stale plan evicted active page");cache.retire(*gpu,std::make_shared<Done>());
    check(trimTextures(cache,p),"Trim after completion failed");check(cache.stats().d2hBytes==0,"Clean eviction read back");
    check(cache.close(),"Cache close failed");
    // Reproducible pressure sweep: capacity, pinned resources, exact keys and
    // deterministic priority order are checked independently of CUDA execution.
    std::mt19937 rng(73129);
    for(unsigned run=0;run<5000;++run){
        std::vector<Residency> resident;std::vector<TextureRequest> requests;ResidencyBudget cap{size_t(16*(1+rng()%8)),256,size_t(16*(rng()%16)),32};
        std::set<Placement> pins;std::map<Placement,size_t> bytes;
        for(unsigned i=0;i<12;++i){auto k=key(i,1+rng()%2,rng()%3);size_t n=16*(1+rng()%2);bool cpuHere=rng()%2,gpuHere=rng()%2,cp=cpuHere&&rng()%5==0,gp=gpuHere&&rng()%5==0;
            if(cpuHere||gpuHere)resident.push_back({k,n,cpuHere,gpuHere,cp,gp,false});
            if(cp)pins.insert({k,false});if(gp)pins.insert({k,true});bytes[{k,false}]=n;bytes[{k,true}]=n;
            if(rng()%3){auto r=request(i,rng()%2,rng()%2);r.key=k;r.bytes=n;r.waitingEpochs=rng()%12;r.importance=double(rng()%5)/4;requests.push_back(r);}
        }
        auto plan=planTextures(resident,requests,cap),again=planTextures(resident,requests,cap);
        check(plan.keep==again.keep&&plan.admit==again.admit&&plan.drop==again.drop&&plan.defer==again.defer,"Nondeterministic plan");
        size_t host=0,device=0;for(auto keep:plan.keep)(keep.gpu?device:host)+=bytes.at(keep);
        check(host==plan.ram&&device==plan.gpu,"Incorrect planned byte total");
        check(plan.pinnedOverBudget||(host<=cap.ram&&device<=cap.gpu()),"Budget overcommitted");
        for(auto pin:pins)check(plan.keep.count(pin),"Pinned resource omitted");
        for(auto drop:plan.drop)check(!pins.count(drop),"Pinned eviction requested");
        for(auto deferred:plan.defer)check(!plan.keep.count(deferred),"Deferred resource advertised resident");
    }
    std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"randomized_plans\":5000}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
