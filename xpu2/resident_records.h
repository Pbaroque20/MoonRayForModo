// Per-flight immutable numeric records. One dispatch owner serializes access.
#pragma once
#include "prepared_records.h"
#include <array>
namespace xpu2::resident {
constexpr uint32_t magic=0x32525358u,updateBit=0x80000000u,inactive=0xffffffffu;
constexpr unsigned slots=128,entryWords=197,updateWords=198,maxPackets=64;
constexpr unsigned maxWords=5+512*5+maxPackets*updateWords;
struct View {const prepared::Group* group=nullptr;unsigned slot=0,packet=0;};
struct Tag {uint64_t revision=0,serial=0;};
struct Cache {
 std::array<Tag,slots> tags{};
 uint64_t batches=0,updates=0,reusedGroups=0,descriptors=0,bytes=0;
 size_t encode(uint32_t* words,const View* views,unsigned packets,bool flush=false,bool stale=false){
  if(!words||!views||!packets||packets>maxPackets)throw std::invalid_argument("Resident packet shape");
  std::array<const prepared::Group*,slots> unique{};
  const uint64_t revision=views[0].group?views[0].group->revision:0;
  if(!revision)throw std::invalid_argument("Resident revision");
  for(unsigned p=0;p<packets;++p){const auto& v=views[p];const auto* g=v.group;
   if(!g||v.slot>=slots||!g->serial||g->revision!=revision||v.packet>=g->count)throw std::invalid_argument("Resident view");
   if(unique[v.slot] && unique[v.slot]!=g)throw std::invalid_argument("Resident aliased slot");
   unique[v.slot]=g;
  }
  if(flush)tags={};
  unsigned count=packets*8,changed=0;std::array<uint32_t,slots> indices{};uint32_t* output=words+5+count*5;
  for(unsigned slot=0;slot<slots;++slot)if(const auto* g=unique[slot]){
   if(tags[slot].revision==g->revision && tags[slot].serial==g->serial){indices[slot]=slot*8;++reusedGroups;}
   else{indices[slot]=updateBit|(changed*8);auto* dst=output+changed*updateWords;
    dst[0]=slot;dst[1]=uint32_t(g->revision);dst[2]=uint32_t(g->revision>>32);
    dst[3]=uint32_t(g->serial);dst[4]=uint32_t(g->serial>>32);dst[5]=magic;
    std::memcpy(dst+6,g->common,sizeof(g->common));++changed;tags[slot]={g->revision,g->serial};
   }
  }
  words[0]=magic;words[1]=count;words[2]=changed;words[3]=uint32_t(revision);words[4]=uint32_t(revision>>32);
  for(unsigned p=0;p<packets;++p){const auto& v=views[p];const auto& g=*v.group;
   for(unsigned lane=0;lane<8;++lane){auto* d=words+5+(p*8+lane)*5;
    d[0]=(g.masks[v.packet]&(1u<<lane))?(indices[v.slot]+lane):inactive;
    d[1]=uint32_t(g.serial)^(stale?1u:0u);d[2]=uint32_t(g.serial>>32);
    std::memcpy(d+3,g.samples+v.packet*16+lane*2,8);
   }
  }
  size_t size=(5+count*5+changed*updateWords)*sizeof(uint32_t);
  ++batches;updates+=changed;descriptors+=count;bytes+=size;return size;
 }
};
}
