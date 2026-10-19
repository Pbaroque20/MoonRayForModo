#include "owner_stage.h"
#include <cassert>
#include <iostream>
int main(){
 for(unsigned depth=1;depth<=4;++depth)for(unsigned count=1;count<1024;++count){
  xpu2::OwnerStage q(depth);unsigned slots[4]={},issued=0,retired=0;
  while(issued<count||q.size()){
   while(issued<count&&!q.full()){auto i=q.tail();assert(!slots[i]);slots[i]=++issued;q.push();assert(q.size()<=depth);}
   auto i=q.front();assert(slots[i]==++retired);slots[i]=0;q.pop();
  }
  assert(issued==retired);for(auto value:slots)assert(!value);
 }
 bool rejected=false;try{xpu2::OwnerStage q(0);}catch(const std::logic_error&){rejected=true;}assert(rejected);
 xpu2::OwnerStage q(1);q.push();rejected=false;try{q.push();}catch(const std::logic_error&){rejected=true;}assert(rejected);
 q.pop();rejected=false;try{q.pop();}catch(const std::logic_error&){rejected=true;}assert(rejected);
 std::cout<<"PASS: bounded owner FIFO, wraparound and exact retirement order\n";
}
