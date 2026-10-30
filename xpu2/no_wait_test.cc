#include "no_wait.h"
#include <cassert>
#include <iostream>
int main(){
 _putenv_s("XPU2_NO_WAIT","0");assert(!xpu2::nowait::enabled());
 _putenv_s("XPU2_NO_WAIT","1");assert(xpu2::nowait::enabled());
 _putenv_s("XPU2_NO_WAIT","");assert(!xpu2::nowait::enabled());
 for(unsigned slots=0;slots<=4;++slots)for(unsigned active=0;active<=5;++active)
 for(unsigned pending=0;pending<=256;++pending)for(unsigned count=1;count<=64;++count){
  bool expected=active<slots && pending+count<=(slots-active)*64;
  assert(xpu2::nowait::admit(active,slots,pending,count,64)==expected);
 }
 assert(!xpu2::nowait::admit(2,2,0,1,512));
 assert(!xpu2::nowait::admit(1,2,511,2,512));
 assert(xpu2::nowait::admit(1,2,511,1,512));
 std::cout<<"PASS: free-flight admission bounds and busy rejection\n";
}
