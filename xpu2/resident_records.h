// Per-flight immutable numeric records. One dispatch owner serializes access.
#pragma once
#include "prepared_records.h"
#include <array>
#include "resident_wire.h"
namespace xpu2::resident {
using namespace wire;
static_assert(sizeof(prepared::Group::common)==commonWords*sizeof(float),"Resident common layout drift");
inline bool enabled(const char* value){return value && std::strcmp(value,"1")==0;}
struct View {const prepared::Group* group=nullptr;unsigned slot=0,packet=0;};
struct Tag {uint64_t revision=0,serial=0;};
struct Cache {
 std::array<Tag,slots> tags{},pendingTags{};
 bool pending=false;
 uint64_t committed=0,aborted=0;
 void complete(bool success){
  if(!pending)return;
  if(success){tags=pendingTags;++committed;}else{tags={};++aborted;}
  pendingTags={};pending=false;
 }
 static bool valid(const View* views,unsigned packets){
  if(!views||!packets||packets>maxPackets)return false;
  std::array<const prepared::Group*,slots> unique{};
  const uint64_t revision=views[0].group?views[0].group->revision:0;
  if(!revision)return false;
  for(unsigned p=0;p<packets;++p){const auto& v=views[p];const auto* g=v.group;
   if(!g||v.slot>=slots||!g->serial||g->revision!=revision||v.packet>=g->count)return false;
   if(unique[v.slot] && unique[v.slot]!=g)return false;
   unique[v.slot]=g;
  }
  return true;
 }
 uint64_t batches=0,updates=0,reusedGroups=0,descriptors=0,bytes=0;
 size_t encode(uint32_t* words,const View* views,unsigned packets,bool flush=false,bool stale=false){
  if(!words || pending || !valid(views,packets))throw std::invalid_argument("Resident admission");
  std::array<const prepared::Group*,slots> unique{};
  const uint64_t revision=views[0].group->revision;
  for(unsigned p=0;p<packets;++p)unique[views[p].slot]=views[p].group;
  pendingTags=flush?std::array<Tag,slots>{}:tags;
  unsigned count=packets*lanes,changed=0;std::array<uint32_t,slots> indices{};uint32_t* output=words+headerWords+count*descriptorWords;
  for(unsigned slot=0;slot<slots;++slot)if(const auto* g=unique[slot]){
   if(pendingTags[slot].revision==g->revision && pendingTags[slot].serial==g->serial){indices[slot]=slot*lanes;++reusedGroups;}
   else{indices[slot]=updateBit|(changed*lanes);auto* dst=output+changed*updateWords;
    dst[0]=slot;dst[1]=uint32_t(g->revision);dst[2]=uint32_t(g->revision>>32);
    dst[3]=uint32_t(g->serial);dst[4]=uint32_t(g->serial>>32);dst[5]=magic;
    std::memcpy(dst+6,g->common,sizeof(g->common));++changed;pendingTags[slot]={g->revision,g->serial};
   }
  }
  words[0]=magic;words[1]=count;words[2]=changed;words[3]=uint32_t(revision);words[4]=uint32_t(revision>>32);
  for(unsigned p=0;p<packets;++p){const auto& v=views[p];const auto& g=*v.group;
   for(unsigned lane=0;lane<lanes;++lane){auto* d=words+headerWords+(p*lanes+lane)*descriptorWords;
    d[0]=(g.masks[v.packet]&(1u<<lane))?(indices[v.slot]+lane):inactive;
    d[1]=uint32_t(g.serial)^(stale?1u:0u);d[2]=uint32_t(g.serial>>32);
    std::memcpy(d+3,g.samples+v.packet*16+lane*2,8);
   }
  }
  size_t size=(headerWords+count*descriptorWords+changed*updateWords)*sizeof(uint32_t);
  pending=true;++batches;updates+=changed;descriptors+=count;bytes+=size;return size;
 }
};
}
