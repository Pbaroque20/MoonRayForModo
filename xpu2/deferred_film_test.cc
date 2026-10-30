#include "deferred_film.h"
#include <future>
#include <atomic>
#include <iostream>
#include <limits>
using namespace xpu2::deferredfilm;
unsigned checks=0;
void require(bool yes){++checks;if(!yes)throw std::runtime_error("check "+std::to_string(checks));}
Samples samples(float v=1){return {{{v,v,v,1},1,3,5,7}};}
int main(){try{
    std::promise<void> started,release;auto barrier=release.get_future().share();
    Queue q([&](Samples& s){if(s[0].rgba[0]==1){started.set_value();barrier.wait();}s[0].rgba[0]*=2;},2,2*sizeof(Sample)*2);
    q.begin(1,10);auto s=samples();require(q.submit(1,10,1,s));s[0].rgba[0]=99;
    started.get_future().wait();Packet p;
    require(!q.take(1,false,p));require(q.submit(1,10,2,samples(2)));require(!q.submit(1,10,3,samples(3)));
    q.begin(2,11);require(!q.submit(2,11,3,samples(3))); // old work still consumes capacity
    require(!q.submit(1,10,4,samples()));release.set_value();
    require(q.take(1,true,p)&&p.revoked&&p.original[0].rgba[0]==1&&p.result[0].rgba[0]==2);
    require(!q.take(1,false,p));require(q.take(2,true,p)&&p.revoked);require(q.outstanding()==0);
    require(q.submit(2,11,1,samples(3)));require(q.take(1,true,p)&&!p.revoked&&!p.failed&&p.result[0].rgba[0]==6);
    require(p.epoch==2&&p.revision==11&&p.owner==1&&p.serial==3);
    require(q.stats().revoked==2&&q.stats().resumed==1);q.shutdown();require(!q.submit(2,11,1,samples()));
    for(int fault=0;fault<5;++fault){Queue f([=](Samples& x){
        if(fault==0)throw std::runtime_error("backend");if(fault==1)x[0].pixel++;
        if(fault==2)x[0].rgba[0]=std::numeric_limits<float>::infinity();if(fault==3)x.clear();if(fault==4)x[0].weight=2;
    });f.begin(1,1);require(f.submit(1,1,1,samples()));require(f.take(1,true,p)&&p.failed&&p.original[0].rgba[0]==1);}
    Queue fifo([](Samples&){},16,4096);fifo.begin(1,1);
    for(unsigned i=0;i<16;++i)require(fifo.submit(1,1,1,samples(float(i))));
    for(unsigned i=0;i<16;++i)require(fifo.take(1,true,p)&&p.serial==i+1&&p.result[0].rgba[0]==i);
    require(!fifo.take(1,true,p));require(fifo.stats().peakJobs<=16&&fifo.stats().peakBytes<=4096);
    // Two independently serialized native owners submit and retire concurrently.
    Queue concurrent([](Samples&){},64,8192);concurrent.begin(1,1);std::atomic<unsigned> done{0};
    auto run=[&](unsigned owner){for(unsigned i=0;i<500;++i){
        while(!concurrent.submit(1,1,owner,samples(float(i))))std::this_thread::yield();
        Packet a;if(!concurrent.take(owner,true,a)||a.owner!=owner||a.result[0].rgba[0]!=i)std::terminate();++done;
    }};std::thread a(run,1),b(run,2);a.join();b.join();require(done==1000&&concurrent.outstanding()==0);
    require(concurrent.stats().admitted==1000&&concurrent.stats().resumed==1000);
    std::cout<<"{\"status\":\"passed\",\"assertions\":"<<checks<<",\"concurrent_jobs\":"<<done<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
