#include "native_cpu_cost.h"
#include <cassert>
#include <cstdlib>
#include <iostream>
int main(){
 _putenv_s("XPU2_CPU_COST","cpu-cost-test.csv");_putenv_s("XPU2_CPU_COST_RATE","1");
 xpu2cpu::reset();assert(xpu2cpu::enabled);
 for(unsigned i=0;i<1000;++i){auto t=CPP_xpu2CpuCostBegin(0,8);assert(t);CPP_xpu2CpuCostEnd(t);}
 auto& s=xpu2cpu::local();assert(s.rows[0].calls==1000 && s.rows[0].lanes==8000 && s.rows[0].sampledLanes==8000 && s.rows[0].ticks>0 && !s.active && !s.errors);
 assert(!CPP_xpu2CpuCostBegin(6,1));assert(!CPP_xpu2CpuCostBegin(0,0));
 auto t=CPP_xpu2CpuCostBegin(1,4);assert(!CPP_xpu2CpuCostBegin(2,4));CPP_xpu2CpuCostEnd(t);assert(s.errors==1); // Reject overlap, never silently double count.
 xpu2cpu::finish();assert(!CPP_xpu2CpuCostBegin(0,8));
 _putenv_s("XPU2_CPU_COST_RATE","64");_putenv_s("XPU2_CPU_COST_SEED","173");
 uint64_t expected=0;
 for(unsigned round=0;round<2;++round){
  xpu2cpu::reset();for(unsigned i=0;i<64000;++i){auto token=CPP_xpu2CpuCostBegin(0,3);CPP_xpu2CpuCostEnd(token);}
  auto& r=xpu2cpu::local().rows[0];assert(r.calls==64000 && r.lanes==192000 && r.samples>850 && r.samples<1150 && r.sampledLanes==r.samples*3);
  if(!round)expected=r.samples;else assert(expected==r.samples);xpu2cpu::finish();
 }
 _putenv_s("XPU2_CPU_COST_RATE","0");xpu2cpu::reset();assert(!xpu2cpu::enabled && !CPP_xpu2CpuCostBegin(0,8));
 std::cout<<"sampled CPU accounting passed\n";
}
