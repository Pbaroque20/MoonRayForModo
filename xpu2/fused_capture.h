// Pointer-free Lambert capture for a single live native sample window.
#include <array>
#include <cstring>
#include <cstdlib>
#include <stdexcept>
namespace fusedcapture {
struct Slot {bool open=false,sampling=false,collected=false;unsigned calls=0,mask=0;std::array<float,192> input{};std::array<float,64> native{};};
thread_local std::array<Slot,16> slots;
thread_local int selected=0;
bool enabled(){static const bool on=[] {const char* f=std::getenv("XPU2_FUSED_FILM");const char* m=std::getenv("XPU2_FILM_CONTRIBUTION");return f&&!std::strcmp(f,"1")&&m&&(!std::strcmp(m,"audit")||!std::strcmp(m,"replace")||!std::strcmp(m,"fast")||!std::strcmp(m,"sentinel"));}();return on;}
void select(int slot){if(slot<0||slot>=16)throw std::runtime_error("Fused slot outside window");selected=slot;}
void begin(int slot){select(slot);auto& s=slots[slot];if(s.open)throw std::runtime_error("Nested fused slot");s=Slot{};s.open=s.sampling=true;}
void sample(const float* input,const float* output,const int* lanes,int count){
 auto& s=slots[selected];if(!s.open||!s.sampling)return;
 if(++s.calls!=1){s.mask=0;return;}
 if(count<1||count>8)throw std::runtime_error("Invalid fused sample count");
 for(int i=0;i<count;++i){int lane=lanes[i];if(lane<0||lane>7||(s.mask&(1u<<lane)))throw std::runtime_error("Invalid fused lane");s.mask|=1u<<lane;
  std::memcpy(s.input.data()+lane*24,input+i*24,24*sizeof(float));std::memcpy(s.native.data()+lane*8,output+i*8,8*sizeof(float));}
}
void collect(const float* post,int mask,int slot){
 select(slot);auto& s=slots[slot];if(!s.open||s.sampling||s.collected)throw std::runtime_error("Fused collect lifetime");
 // Retain the existing all-packet wrapper guard. A transformed Lambert answer
 // cannot supply the raw lobe data used by the fused kernel.
 for(int lane=0;lane<8;++lane)if(s.mask&(1u<<lane))if(!(mask&(1<<lane))||std::memcmp(post+lane*8,s.native.data()+lane*8,7*sizeof(float))){s.mask=0;break;}
 s.collected=true;
}
}
extern "C" __declspec(dllexport) int xpu2FusedEnabled(){return fusedcapture::enabled();}
extern "C" __declspec(dllexport) void xpu2FusedTake(float* input,float* reference,int* mask,int slot){
 fusedcapture::select(slot);auto& s=fusedcapture::slots[slot];if(!s.open||!s.collected)throw std::runtime_error("Fused take lifetime");
 std::memcpy(input,s.input.data(),192*sizeof(float));std::memcpy(reference,s.native.data(),64*sizeof(float));*mask=int(s.mask);s=fusedcapture::Slot{};
}
