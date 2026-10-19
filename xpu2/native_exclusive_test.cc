#include "native_exclusive.h"
#include <cassert>
#include <numeric>
#include <iostream>
int main(){
 static_assert(xpu2cost::Packing==0 && xpu2cost::Fallback==6 && xpu2cost::Native==7 && xpu2cost::Coordination==8,"ISPC stage IDs changed");
 xpu2cost::prepareClock();auto n=xpu2cost::steady(),t=xpu2cost::clock();
 std::this_thread::sleep_for(std::chrono::milliseconds(40));auto elapsed=xpu2cost::nanos(xpu2cost::clock()-t),reference=xpu2cost::steady()-n;
 assert(double(elapsed)/double(reference)>.998 && double(elapsed)/double(reference)<1.002);
 std::cout<<"PASS: "<<(xpu2cost::fastClock?"invariant TSC":"steady")<<" clock checked against steady elapsed time\n";
 xpu2cost::Stats s;s.enter(xpu2cost::Packing,100);s.enter(xpu2cost::Upload,120);s.enter(xpu2cost::Context,125);s.leave(130);s.leave(150);s.leave(180);
 assert(s.ns[xpu2cost::Packing]==50 && s.ns[xpu2cost::Upload]==25 && s.ns[xpu2cost::Context]==5);
 assert(s.covered==80 && std::accumulate(s.ns.begin(),s.ns.end(),uint64_t(0))==s.covered);
 s.enter(xpu2cost::Packing,200);s.enter(xpu2cost::Packing,210);s.leave(220);s.leave(230);
 assert(s.ns[xpu2cost::Packing]==80 && s.covered==110 && !s.depth && !s.errors);
 s.leave(240);assert(s.errors==1);std::cout<<"PASS: nested and same-stage exclusive accounting; gaps excluded; bad retirement rejected\n";
}
