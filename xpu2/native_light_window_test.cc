#include "native_local_tile_policy.h"
#include "native_light_window.h"
#include <atomic>
#include <cstdlib>
#include <new>
#include <iostream>
#include <mutex>
#include <thread>
std::atomic<unsigned long long> allocations{0};
void* operator new(std::size_t n){++allocations;if(void* p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void operator delete(void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}
using Window=xpu2::LightWindow<xpu2tile::Policy>;
void require(bool ok){if(!ok)throw std::runtime_error("Light descriptor contract failed");}
template<class F> void rejected(F f){bool bad=false;try{f();}catch(const std::logic_error&){bad=true;}require(bad);}
int main(){
    uint32_t masks[32],tiles[32];for(unsigned i=0;i<32;++i){masks[i]=255;tiles[i]=(i/4)<<16|(i%4);}
    Window invalid(true);masks[0]=256;
    rejected([&]{invalid.open(masks,tiles,255,32,8,1);});require(!invalid.active && !invalid.stats.windows);masks[0]=255;
    rejected([&]{invalid.open(nullptr,tiles,255,32,8,1);});require(!invalid.active);
    Window local(true);auto before=allocations.load();auto token=local.open(masks,tiles,0,32,8,1);
    local.reserveGpu();require(local.stats.gpu==0);
    unsigned done=0;for(int action=local.next(token,1);action>=0;action=local.next(token,1)){require(action<32);++done;}
    require(done==32);local.close(token,1);require(allocations==before);
    rejected([&]{local.next(token,1);});
    auto second=local.open(masks,tiles,255,32,8,2);local.reserveGpu();
    require(local.stats.gpu==32 && local.stats.gpuSteals==16);
    rejected([&]{local.next(token,2);});rejected([&]{local.next(second,1);});rejected([&]{local.close(second,2);});
    done=0;for(int action=local.next(second,2);action>=0;action=local.next(second,2)){
        require(action>=32);unsigned i=unsigned(action-32);local.prepared(second,2,i,true);
        rejected([&]{local.prepared(second,2,i,true);});local.completed(second,2,i);rejected([&]{local.completed(second,2,i);});++done;
    }
    require(done==32);local.close(second,2);
    auto third=local.open(masks,tiles,255,32,32,3);local.reserveGpu();require(local.reserved==512);
    while(int action=local.next(third,3)+1){--action;if(action>=32)local.prepared(third,3,unsigned(action-32),false);}
    local.close(third,3);require(!local.reserved);
    require(local.cpuPolicy.inspected<=16*local.cpuPolicy.claims && local.gpuPolicy.inspected<=16*local.gpuPolicy.claims);
    // Race reservation against native-owner claims; only copied metadata is shared.
    Window raced(true);std::mutex lock;std::atomic<bool> stop{false};
    std::thread gpu([&]{while(!stop.load()){std::lock_guard<std::mutex> held(lock);raced.reserveGpu();}});
    for(unsigned n=1;n<=1000;++n){
        uint64_t t;{std::lock_guard<std::mutex> held(lock);t=raced.open(masks,tiles,255,32,8,n);}
        std::array<bool,32> seen{};unsigned count=0;
        for(;;){int action;{std::lock_guard<std::mutex> held(lock);action=raced.next(t,n);}if(action<0)break;
            unsigned i=unsigned(action%32);require(!seen[i]);seen[i]=true;++count;
            if(action>=32){std::lock_guard<std::mutex> held(lock);raced.prepared(t,n,i,true);raced.completed(t,n,i);}
            std::this_thread::yield();
        }
        require(count==32);{std::lock_guard<std::mutex> held(lock);raced.close(t,n);}
    }
    stop=true;gpu.join();require(raced.stats.cpu+raced.stats.gpu==32000 && raced.stats.windows==raced.stats.closed);
    require(raced.cpuPolicy.inspected+raced.gpuPolicy.inspected<=16*(raced.cpuPolicy.claims+raced.gpuPolicy.claims));
    std::cout<<"passed: zero-allocation CPU path, stale/duplicate rejection, bounded reservations, fallback, 32000 raced exclusive claims\n";
}
