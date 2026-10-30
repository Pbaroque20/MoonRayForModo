"""Compile and exercise the actual bounded C++ selection policy."""
import os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
COMPILER=Path(r"C:\Users\Raphael Tobar\MoonRayForModo\toolchain\msys64\ucrt64\bin\g++.exe")
SOURCE=r"""
#include "native_tile_policy.h"
#include <deque>
#include <memory>
#include <cassert>
struct R {uint32_t tile;uint64_t queuedClaim;};
using Q=std::deque<std::shared_ptr<R>>;
void add(Q& q,uint32_t t,uint64_t c=0){q.push_back(std::make_shared<R>(R{t,c}));}
int main(){
    bool mixed;
    uint32_t px[8]={0xffffffffu, (32u<<16)|16u, (47u<<16)|31u,
        0xffffffffu,0xffffffffu,0xffffffffu,0xffffffffu,0xffffffffu};
    assert(xpu2tile::tileFor(px,mixed)==((2u<<16)|1u) && !mixed);
    px[2]=(48u<<16)|32u;assert(xpu2tile::tileFor(px,mixed)==((2u<<16)|1u) && mixed);
    assert(xpu2tile::tileFor(nullptr,mixed)==xpu2tile::unknown && !mixed);
    Q q;add(q,100);add(q,1);add(q,2);
    xpu2tile::Policy fifo;fifo.previous=0;assert(fifo.choose(q)==0);
    xpu2tile::Policy near;near.neighbor=true;near.previous=0;
    assert(near.choose(q)==1 && near.reordered==1 && near.local==1);
    near.previous=500;assert(near.choose(q)==0 && near.shared==1);
    // Replenish local work forever; the distant head must win by its age bound.
    Q arrivals;add(arrivals,100);near={};near.neighbor=true;near.previous=0;
    unsigned attempts=0;
    for(;;){add(arrivals,0,near.claims);auto i=near.choose(arrivals);
        auto picked=arrivals[i];arrivals.erase(arrivals.begin()+i);
        if(picked->tile==100)break;assert(++attempts<=64);}
    assert(near.aged==1 && attempts==64);
    // Adjacent corners, unknown packets and distant fallback are all conserved.
    Q jobs;for(unsigned i=0;i<4096;++i)add(jobs,i%5?((i%31)<<16)|(i%47):xpu2tile::unknown);
    near={};near.neighbor=true;unsigned count=0;
    while(!jobs.empty()){auto i=near.choose(jobs);assert(i<jobs.size());jobs.erase(jobs.begin()+i);++count;}
    assert(count==4096 && near.claims==4096);
}
"""
class NativeTilePolicy(unittest.TestCase):
    def test_native_policy(self):
        self.assertTrue(COMPILER.exists(),"Native compiler required")
        with tempfile.TemporaryDirectory() as name:
            out=Path(name);src=out/'test.cc';src.write_text(SOURCE)
            env=os.environ.copy();env['PATH']=str(COMPILER.parent)+os.pathsep+env['PATH']
            subprocess.run([str(COMPILER),'-std=c++17','-O2','-I'+str(ROOT/'xpu2'),str(src),'-o',str(out/'test.exe')],env=env,check=True,capture_output=True,timeout=60)
            subprocess.run([str(out/'test.exe')],env=env,check=True,capture_output=True,timeout=30)
if __name__=='__main__':unittest.main()
