#include "batch_transport.h"
#include <iostream>
#include <memory>
#include <new>
using namespace xpu2::transport;
void require(bool condition){if(!condition)throw std::runtime_error("Batch contract failed");}
template<class F> void rejected(F f){bool failed=false;try{f();}catch(const std::invalid_argument&){failed=true;}require(failed);}
template<class F> void wrongState(F f){bool failed=false;try{f();}catch(const std::logic_error&){failed=true;}require(failed);}
int main(){
    auto batch=std::make_unique<Batch>(),other=std::make_unique<Batch>();
    float input[192],fallback[64];
    for(unsigned i=0;i<192;++i){uint32_t bits=0x3f000000u+i;std::memcpy(input+i,&bits,4);}
    // Values are opaque: packing must preserve NaN payloads and signed zero.
    uint32_t bits=0x7fc01234u;std::memcpy(input+10,&bits,4);bits=0x80000000u;std::memcpy(input+11,&bits,4);
    for(unsigned i=0;i<64;++i)fallback[i]=float(i);
    PacketView packets[64];for(auto& p:packets)p={input,fallback,8};
    rejected([&]{batch->pack(packets,65,1);});
    packets[1].samples=9;rejected([&]{batch->pack(packets,2,1);});require(batch->phase()==Phase::Empty);packets[1].samples=8;
    auto first=batch->pack(packets,64,1);require(batch->samples()==512 && batch->packets()==64);
    for(unsigned i=0;i<64;++i){require(batch->range(i).first==i*8);require(!std::memcmp(batch->input()+i*192,input,sizeof(input)));require(!std::memcmp(batch->fallback()+i*64,fallback,sizeof(fallback)));}
    wrongState([&]{batch->resultStorage(first);});wrongState([&]{other->resultStorage(first);});
    require(!other->submit(first));require(batch->submit(first));require(!batch->submit(first));
    require(!batch->release(first));require(batch->cancel(first));
    rejected([&]{batch->pack(packets,1,2);});require(batch->phase()==Phase::CancelPending);wrongState([&]{batch->resultStorage(first);});
    auto forged=first;++forged.revision;require(batch->complete(forged,true)==Completion::Rejected);
    require(batch->complete(first,true)==Completion::Retired);require(batch->complete(first,true)==Completion::Rejected);
    auto second=batch->pack(packets,1,2);require(!batch->cancel(first));require(batch->submit(second));
    require(batch->complete(second,false)==Completion::Failed);require(batch->release(second));
    auto third=batch->pack(packets,1,3);require(batch->submit(third));batch->resultStorage(third)[0]=42.f;require(batch->complete(third,true)==Completion::Publish);
    require(batch->fallback()[0]==42.f);wrongState([&]{batch->resultStorage(third);});
    require(batch->complete(third,true)==Completion::Rejected);require(batch->release(third));
    auto fourth=batch->pack(packets,1,4);require(batch->cancel(fourth));require(!batch->submit(fourth));
    // Reusing the same address for a new slot must not resurrect an old token.
    alignas(Batch) unsigned char storage[sizeof(Batch)];
    auto* reused=new(storage) Batch;
    auto old=reused->pack(packets,1,5);require(reused->cancel(old));reused->~Batch();
    reused=new(storage) Batch;auto current=reused->pack(packets,1,5);
    require(!reused->submit(old));require(reused->cancel(current));reused->~Batch();
    std::cout<<"PASS: packing bits, capacity, ownership, stale generations, cancellation, drain, failure and exactly-once publication\n";
}
