"""Exercise the actual generated replay function with deterministic queue states."""
import argparse,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PRE=r'''
#include <atomic>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <vector>
#include <cassert>
#include <iostream>
namespace xpu2::nativepath {
struct Request { bool done=false,canceled=false; int id=0; };
struct Queue { using Ticket=std::shared_ptr<Request>; std::mutex mutex; unsigned cancels=0;
 void cancelLocked(const Ticket& t){t->canceled=true;++cancels;}
};
struct WindowPacket {float input[192]{};uint32_t pixels[8]{};std::unique_ptr<Queue::Ticket> owner;};
struct WindowBlock {std::vector<WindowPacket> packets;unsigned cursor=0;};
struct WindowScope {WindowBlock* record=nullptr;WindowBlock* replay=nullptr;};
WindowScope* currentWindow=nullptr;Queue queue;Queue* shaderQueue=&queue;
bool replayGrouped=true,windowMismatch=false,windowDrop=false;
uint64_t replayGroups=0,replayPackets=0,replayLocks=0,replayReuse=0,replayFallback=0,windowChanged=0,windowDiscarded=0,windowReady=0,windowReused=0;
struct IntegrationTimer {explicit IntegrationTimer(unsigned){}};
bool recordingWindow(){return currentWindow && currentWindow->record;}
}
using namespace xpu2::nativepath;
unsigned raw=0,scalar=0,groups=0;bool reject=false;
uint64_t CPP_gpuEarlySubmitRaw(const float* p,const uint32_t* ids){
 assert(queue.mutex.try_lock());queue.mutex.unlock();++raw;
 assert(p[0]==float(ids[0]));
 if(reject)return 0;
 return reinterpret_cast<uint64_t>(new Queue::Ticket(std::make_shared<Request>(Request{true,false,int(ids[0])})));
}
uint64_t CPP_gpuEarlySubmit(const float*,const uint32_t*){++scalar;return 0;}
void CPP_gpuEarlySubmitGroupRaw(const float*,const uint32_t*,unsigned n,uint64_t* t){++groups;for(unsigned i=0;i<n;++i)t[i]=0;}
'''
POST=r'''
int main(){
 // Cases: all ready, mixed ready/pending, numeric mismatch, pixel mismatch,
 // forced mismatch, forced discard, empty owners, exhausted replay, rejection.
 for(int mode=0;mode<9;++mode){
  WindowBlock b;WindowScope s;s.replay=&b;currentWindow=&s;
  float input[4*192]{};uint32_t pixels[4*8]{};uint64_t tokens[4]{};
  std::vector<Queue::Ticket> expected;
  unsigned size=mode==7?2:4;
  for(unsigned i=0;i<4;++i){input[i*192]=float(i);pixels[i*8]=i;}
  for(unsigned i=0;i<size;++i){b.packets.emplace_back();auto& p=b.packets.back();
   std::memcpy(p.input,input+i*192,sizeof p.input);std::memcpy(p.pixels,pixels+i*8,sizeof p.pixels);
   auto t=std::make_shared<Request>(Request{mode!=1 || i%2==0,false,int(i)});expected.push_back(t);
   if(mode!=6 && mode!=8)p.owner=std::make_unique<Queue::Ticket>(t);
  }
  if(mode==2)b.packets[1].input[191]=1.f;
  if(mode==3)b.packets[1].pixels[7]=42;
  windowMismatch=mode==4;windowDrop=mode==5;reject=mode==8;
  uint64_t reused=windowReused,ready=windowReady,changed=windowChanged,discarded=windowDiscarded,rawBefore=raw,lockBefore=replayLocks;
  CPP_gpuEarlySubmitGroup(input,pixels,4,tokens);
  unsigned reuse=(mode==0 || mode==1)?4:(mode==2 || mode==3)?3:mode==7?2:0;
  assert(windowReused-reused==reuse && raw-rawBefore==4-reuse && replayLocks-lockBefore==1);
  assert(windowReady-ready==(mode==1?2:reuse));
  assert(windowChanged-changed==(mode==4?4:(mode==2 || mode==3)?1:0));
  assert(windowDiscarded-discarded==((mode==4 || mode==5)?4:(mode==2 || mode==3)?1:0));
  assert(b.cursor==size);
  for(unsigned i=0;i<4;++i){
   if(mode==8){assert(tokens[i]==0);continue;}
   std::unique_ptr<Queue::Ticket> owner(reinterpret_cast<Queue::Ticket*>(tokens[i]));
   assert(owner && (*owner)->id==int(i));
   bool kept=i<size && mode!=4 && mode!=5 && mode!=6 && !((mode==2 || mode==3) && i==1);
   if(kept)assert(*owner==expected[i]);else if(i<size && mode!=6)assert(expected[i]->canceled);
  }
  for(auto& p:b.packets)assert(!p.owner);
 }
 assert(replayPackets==replayReuse+replayFallback && replayGroups==replayLocks);
 WindowBlock b;WindowScope s;s.replay=&b;currentWindow=&s;float p[192]{};uint32_t id[8]{};uint64_t t[1]{};
 replayGrouped=false;CPP_gpuEarlySubmitGroup(p,id,1,t);assert(scalar==1);
 replayGrouped=true;s.record=&b;CPP_gpuEarlySubmitGroup(p,id,1,t);assert(scalar==2);
 currentWindow=nullptr;CPP_gpuEarlySubmitGroup(p,id,1,t);assert(groups==1);
 for(unsigned n:{0u,17u}){bool threw=false;try{CPP_gpuEarlySubmitGroup(p,id,n,t);}catch(const std::invalid_argument&){threw=true;}assert(threw);}
 std::cout<<"14 replay routing/ownership cases passed\n";
}
'''
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=Path,required=True);p.add_argument('--compiler',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 text=(a.build/'native_gpu_early.h').read_text();start=text.index('extern "C" void CPP_gpuEarlySubmitGroup(');end=text.index('\nextern "C" unsigned CPP_gpuIntegrationSubmitPhase()',start)
 a.output.mkdir(parents=True,exist_ok=False);src=a.output/'replay.cpp';exe=a.output/'replay.exe';src.write_text(PRE+text[start:end]+POST)
 env=os.environ.copy();env['PATH']=str(a.compiler.parent)+os.pathsep+env.get('PATH','')
 subprocess.run([str(a.compiler),'-std=c++17','-O2',str(src),'-o',str(exe)],check=True,env=env,timeout=60)
 subprocess.run([str(exe.resolve())],check=True,env=env,timeout=15)
if __name__=='__main__':main()
