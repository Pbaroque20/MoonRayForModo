#include "texture_cache.h"
#include <iostream>
#include <random>
using namespace xpu2::texture;
static unsigned checks=0;
static void check(bool ok,const char* why){++checks;if(!ok)throw std::runtime_error(why);}
struct FakeFence: Fence {bool complete=false;bool ready() override{return complete;}void wait() override{complete=true;}};
struct FakePage: DevicePage {Bytes data;bool complete=false;FakePage(const Bytes& b):data(b){}bool ready() override{return complete;}void wait() override{complete=true;}uint64_t address()const override{return reinterpret_cast<uint64_t>(data.data());}};
struct FakeBackend: Backend {
    std::vector<std::weak_ptr<FakePage>> copies;bool fail=false;
    std::shared_ptr<DevicePage> upload(const Bytes& bytes)override{if(fail)throw std::runtime_error("Injected upload failure");auto p=std::make_shared<FakePage>(bytes);copies.push_back(p);return p;}
    void drain()override{for(auto& weak:copies)if(auto page=weak.lock())page->complete=true;}
};
static Key key(unsigned rev=1,unsigned mip=0,unsigned x=0){return {"fixture","linear-f32",rev,mip,x,0,0};}
static Bytes bytes(const Key& k,size_t size){return Bytes(size,uint8_t(k.revision*17+k.mip*3+k.x));}
int main(){try{
    FakeBackend backend;Cache cache(backend,{32,16,16});
    auto a=key(),b=key(1,1),c=key(2);
    auto cpu=cache.acquire(a,16,bytes,false);check(cpu&&cache.cpu(*cpu)==bytes(a,16),"CPU page mismatch");
    check(!cache.acquire(a,16,bytes,true),"Pending upload exposed");
    check(!cache.acquire(a,16,bytes,true)&&backend.copies.size()==1,"Upload not deduplicated");
    check(!cache.acquire(b,16,bytes,true),"Pending upload evicted");
    backend.drain();cache.poll();auto gpu=cache.acquire(a,16,bytes,true);check(bool(gpu),"Ready upload hidden");
    check(cache.stats().staging==0&&cache.stats().loads==1,"Upload counters wrong");
    auto fence=std::make_shared<FakeFence>();cache.retire(*gpu,fence);
    check(!cache.acquire(b,16,bytes,true),"In-flight consumer evicted");
    check(!cache.close(),"Live leases allowed close");
    fence->complete=true;cache.poll();
    check(!cache.acquire(b,16,bytes,true)&&backend.copies.size()==2,"New mip did not upload");
    check(cache.cpu(*cpu)==bytes(a,16),"Old CPU lease overwritten");
    check(cache.stats().d2hBytes==0&&cache.stats().gpuEvictions==1,"Clean GPU eviction copied back");
    auto revised=cache.acquire(c,16,bytes,false);
    check(revised&&cache.cpu(*revised)==bytes(c,16)&&cache.cpu(*cpu)==bytes(a,16),"Revision isolation lost");
    check(!cache.acquire(key(3),16,bytes,false),"Pinned RAM evicted");
    bool rejected=false;try{cache.acquire(a,17,bytes,false);}catch(const std::invalid_argument&){rejected=true;}check(rejected,"Same-key mutation accepted");
    rejected=false;try{cache.acquire(key(3),33,bytes,false);}catch(const std::length_error&){rejected=true;}check(rejected,"Oversized tile admitted");
    cache.release(*revised);
    rejected=false;try{cache.acquire(key(3),16,[](auto&,size_t){return Bytes(1);},false);}catch(const std::invalid_argument&){rejected=true;}
    check(rejected&&cache.stats().failedLoads==1&&cache.stats().ram==16,"Failed loader retained invalid bytes");
    backend.drain();cache.poll();backend.fail=true;
    rejected=false;try{cache.acquire(a,16,bytes,true);}catch(const std::runtime_error&){rejected=true;}
    check(rejected&&cache.stats().vram==0&&cache.stats().staging==0,"Failed upload leaked budget");backend.fail=false;
    check(!cache.acquire(a,16,bytes,true),"Failed upload prevented retry");backend.drain();cache.poll();
    auto again=cache.acquire(a,16,bytes,true);check(bool(again),"GPU retry failed");
    rejected=false;try{cache.release(*again);}catch(const std::logic_error&){rejected=true;}check(rejected,"GPU released without fence");
    auto done=std::make_shared<FakeFence>();done->complete=true;cache.retire(*again,done);
    rejected=false;try{cache.gpu(*again);}catch(const std::invalid_argument&){rejected=true;}check(rejected,"Stale lease accepted");
    cache.release(*cpu);
    check(cache.stats().peakRam<=32&&cache.stats().peakVram<=16&&cache.stats().peakStaging<=16,"Budget exceeded");
    check(cache.close(),"Drain failed");
    {
        FakeBackend d;Cache small(d,{16,16,16});auto live=small.acquire(a,16,bytes,false);small.release(*live);
        check(!small.prefetch(b,16,bytes),"Prefetch displaced demanded RAM");
        check(small.stats().loads==1,"Blocked prefetch read disk");check(small.close(),"Prefetch cleanup failed");
    }
    {
        FakeBackend d;Cache first(d,{32,32,16}),other(d,{16,16,16});
        check(!first.prefetch(a,16,bytes),"Prefetch completed early");
        check(!first.prefetch(b,16,bytes)&&first.stats().loads==1,"Staging budget failed");
        d.drain();first.poll();auto lease=first.acquire(a,16,bytes,false);
        rejected=false;try{other.release(*lease);}catch(const std::invalid_argument&){rejected=true;}check(rejected,"Foreign lease accepted");
        first.release(*lease);check(first.close()&&other.close(),"Multiple-cache cleanup failed");
    }
    {
        FakeBackend d;alignas(Cache) unsigned char storage[sizeof(Cache)];
        auto* first=new(storage) Cache(d,{16,16,16});auto old=first->acquire(a,16,bytes,false);
        first->release(*old);check(first->close(),"Old cache close failed");first->~Cache();
        auto* second=new(storage) Cache(d,{16,16,16});auto fresh=second->acquire(a,16,bytes,false);
        rejected=false;try{second->cpu(*old);}catch(const std::invalid_argument&){rejected=true;}
        check(rejected,"Reused cache address accepted an old lease");second->release(*fresh);check(second->close(),"Recreated cache close failed");second->~Cache();
    }
    {
        FakeBackend d;Cache randomCache(d,{64,32,16});std::mt19937 rng(617);std::vector<Cache::Lease> held;
        auto release=[&](const Cache::Lease& lease){if(lease.device){auto f=std::make_shared<FakeFence>();f->complete=true;randomCache.retire(lease,f);}else randomCache.release(lease);};
        for(unsigned step=0;step<20000;++step){
            d.drain();randomCache.poll();
            if(!held.empty()&&(rng()%3==0||held.size()>=12)){size_t at=rng()%held.size();release(held[at]);held.erase(held.begin()+at);}
            else{
                auto k=key(1+rng()%3,rng()%4,rng()%4);size_t size=8+(k.mip%2)*8;
                if(rng()%4==0)randomCache.prefetch(k,size,bytes);
                else if(auto lease=randomCache.acquire(k,size,bytes,rng()%2)){
                    auto expected=bytes(k,size);
                    if(lease->device){auto* p=reinterpret_cast<const uint8_t*>(randomCache.gpu(*lease));check(std::equal(expected.begin(),expected.end(),p),"Random GPU content mismatch");}
                    else check(randomCache.cpu(*lease)==expected,"Random CPU content mismatch");
                    held.push_back(*lease);
                }
            }
            const auto& stats=randomCache.stats();check(stats.ram<=64&&stats.vram<=32&&stats.staging<=16,"Random budget overflow");
        }
        for(const auto& lease:held)release(lease);
        check(randomCache.stats().d2hBytes==0&&randomCache.close(),"Random cache failed to drain");
    }
    {
        FakeBackend d;Cache tiny(d,{32,32,32,1,1,1});auto held=tiny.acquire(a,8,bytes,false);
        check(!tiny.acquire(a,8,bytes,false),"Lease cap exceeded");tiny.release(*held);
        auto next=tiny.acquire(b,8,bytes,false);check(bool(next)&&tiny.stats().loads==2,"Record cap failed to replace idle entry");
        check(!tiny.prefetch(c,8,bytes),"Record cap evicted pinned entry");tiny.release(*next);
        check(tiny.close(),"Capped cache close failed");
        Cache uploads(d,{32,32,32,4,4,1});check(!uploads.prefetch(a,8,bytes),"Upload not pending");
        check(!uploads.prefetch(b,8,bytes)&&uploads.stats().loads==1,"Upload count cap exceeded");d.drain();uploads.poll();check(uploads.close(),"Upload cap drain failed");
    }
    {
        FakeBackend d;Cache many(d,{65536,16,16});
        for(unsigned x=0;x<4096;++x){auto lease=many.acquire(key(1,0,x),8,bytes,false);check(bool(lease),"Resident CPU population failed");many.release(*lease);}
        for(unsigned i=0;i<1000;++i){auto lease=many.acquire(a,8,bytes,false);many.release(*lease);}
        check(many.stats().uploadPolls==0&&many.stats().loads==4096,"CPU hits performed upload polling/reloads");check(many.close(),"Resident CPU drain failed");
    }
    std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"random_operations\":20000,\"clean_eviction_d2h_bytes\":0}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
