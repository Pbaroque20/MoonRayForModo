#include "resident_records.h"
#include <iostream>
using namespace xpu2::resident;
void check(bool b){if(!b)throw std::runtime_error("Resident contract");}
template<class F>void rejects(F f){bool rejected=false;try{f();}catch(const std::exception&){rejected=true;}check(rejected);}
using Table=std::array<uint32_t,slots*entryWords>;
void decode(const uint32_t* w,const Table& table,unsigned id,float* result){
 uint32_t bits[24]{};const auto* d=w+5+id*5;unsigned index=d[0];const uint32_t* src=nullptr;
 if(index!=inactive){unsigned g=(index&~updateBit)/8;
  if(index&updateBit){if(g<w[2])src=w+5+w[1]*5+g*updateWords+1;}
  else if(g<slots)src=table.data()+g*entryWords;
  if(src && src[0]==w[3]&&src[1]==w[4]&&src[2]==d[1]&&src[3]==d[2]&&src[4]==magic){
   std::memcpy(bits,src+5+(index%8)*24,96);bits[11]=d[3];bits[12]=d[4];}}
 std::memcpy(result,bits,96);
}
void commit(const uint32_t* w,Table& table){for(unsigned i=0;i<w[2];++i){const auto* v=w+5+w[1]*5+i*updateWords;std::memcpy(table.data()+v[0]*entryWords,v+1,entryWords*4);}}
int main(){
 xpu2::prepared::Group a,b;float common[192],samples[256];uint32_t masks[16],pixels[8]{};
 for(unsigned k=0;k<192;++k){uint32_t bits=k%3==0?0x80000000u:k%3==1?0x7fc00100u+k:0x3f000000u+k;std::memcpy(common+k,&bits,4);}
 for(unsigned k=0;k<256;++k)samples[k]=float(k)/257;
 for(unsigned k=0;k<16;++k)masks[k]=(k*17)&255;
 a.capture(common,samples,masks,pixels,16,0x100000001ull);a.serial=0x200000001ull;
 b=a;b.serial++;b.common[14]=0.5f;
 Cache cache;Table table{};std::array<uint32_t,maxWords> wire{};View views[]={{&a,3,2},{&a,3,8},{&b,7,1}};
 auto verify=[&]{for(unsigned p=0;p<3;++p){float expanded[192];views[p].group->expand(views[p].packet,expanded);
  for(unsigned lane=0;lane<8;++lane){float restored[24];decode(wire.data(),table,p*8+lane,restored);check(!std::memcmp(restored,expanded+lane*24,96));}}};
 cache.encode(wire.data(),views,3);check(wire[2]==2);verify();commit(wire.data(),table);
 cache.encode(wire.data(),views,3);check(wire[2]==0&&cache.reusedGroups==2);verify();
 ++a.serial;a.common[1]=0.75f;cache.encode(wire.data(),views,3);check(wire[2]==1);verify();commit(wire.data(),table);
 ++a.revision;++b.revision;cache.encode(wire.data(),views,3);check(wire[2]==2);verify();commit(wire.data(),table);
 cache.encode(wire.data(),views,3,true);check(wire[2]==2);verify();commit(wire.data(),table);
 cache.encode(wire.data(),views,3,false,true);float zeros[24]{},stale[24];decode(wire.data(),table,1,stale);check(!std::memcmp(zeros,stale,96));
 auto saved=cache.tags;View bad[]={{&a,3,0},{&b,3,0}};rejects([&]{cache.encode(wire.data(),bad,2);});
 check(!std::memcmp(saved.data(),cache.tags.data(),sizeof(saved)));
 bad[0]={&a,128,0};rejects([&]{cache.encode(wire.data(),bad,1);});
 bad[0]={&a,0,16};rejects([&]{cache.encode(wire.data(),bad,1);});
 rejects([&]{cache.encode(wire.data(),views,0);});rejects([&]{cache.encode(wire.data(),views,65);});
 std::array<xpu2::prepared::Group,64> groups;std::array<View,64> maxViews;
 for(unsigned i=0;i<64;++i){groups[i]=a;groups[i].serial=i+1;maxViews[i]={&groups[i],i,0};}
 check(cache.encode(wire.data(),maxViews.data(),64,true)==maxWords*4);check(wire[2]==64);
 std::cout<<"PASS: cold/reused/replaced records, revisions, masks, stale references, bounds, transactional validation, maximum wire size\n";
}
