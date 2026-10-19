#include "prepared_records.h"
#include <iostream>
#include <thread>
#include <future>
using namespace xpu2::prepared;
void check(bool ok){if(!ok)throw std::runtime_error("Contract failure");}
template<class F>void throws(F f){bool caught=false;try{f();}catch(const std::exception&){caught=true;}check(caught);}
int main(){
 float common[192],samples[256],output[192],coordinates[16];uint32_t masks[16],pixels[8],ids[8];
 for(unsigned i=0;i<192;++i){uint32_t bits=i%3==0?0x7fc01234u:i%3==1?0x80000000u:0x3f000000u+i;std::memcpy(common+i,&bits,4);}
 for(unsigned i=0;i<256;++i){uint32_t bits=0x3e000000u+i;std::memcpy(samples+i,&bits,4);}
 for(unsigned i=0;i<16;++i)masks[i]=(i*17u)&255;
 for(unsigned i=0;i<8;++i)pixels[i]=100+i;
 Group g;g.capture(common,samples,masks,pixels,16,1);
 for(unsigned p=0;p<16;++p){g.expand(p,output,ids);g.coordinates(p,coordinates);
  for(unsigned l=0;l<8;++l){bool active=masks[p]&(1u<<l);check(ids[l]==(active?pixels[l]:0xffffffffu));
   for(unsigned w=0;w<24;++w){float expected=0;if(active)std::memcpy(&expected,w==11||w==12?samples+p*16+l*2+w-11:common+l*24+w,4);check(!std::memcmp(&expected,output+l*24+w,4));}
   check(!std::memcmp(coordinates+l*2,output+l*24+11,8));}}
 throws([&]{g.expand(16,output);});throws([&]{g.coordinates(16,coordinates);});
 throws([&]{g.capture(common,samples,masks,pixels,0,1);});throws([&]{g.capture(common,samples,masks,pixels,17,1);});
 throws([&]{g.capture(common,samples,masks,pixels,16,0);});masks[0]=256;
 throws([&]{g.capture(common,samples,masks,pixels,16,1);});masks[0]=255;
 Pool zero(0);check(!zero.acquire(common,samples,masks,pixels,16,1));check(zero.exhausted==1);
 Pool pool(1);auto first=pool.acquire(common,samples,masks,pixels,16,1);auto address=first.get();check(first&&first->serial==1&&pool.retained()==1);
 std::promise<void> held,release;auto future=release.get_future();
 std::thread reader([copy=first,&held,&future](){held.set_value();future.wait();check(copy->revision==1&&copy->serial==1);});
 first.reset();held.get_future().wait();check(!pool.acquire(common,samples,masks,pixels,16,2));release.set_value();reader.join();
 check(pool.retained()==0);auto second=pool.acquire(common,samples,masks,pixels,16,2);check(second.get()==address&&second->revision==2&&second->serial==2&&pool.reused==1);
 second.reset();std::shared_ptr<const Group> survivor;
 {Pool shortLived(1);survivor=shortLived.acquire(common,samples,masks,pixels,16,3);}
 survivor->expand(0,output);check(survivor->revision==3);check(pool.retained()==0);
 throws([]{Pool oversized(129);});
 std::cout<<"PASS: masked bit-exact expansion, sample coordinates, bounds, exhaustion, reuse, concurrent retention, pool destruction\n";
}
