#pragma once
#include "sample_fixture.h"
namespace xpu2::interactive::qmctest {
using namespace sample;
X2_HD inline Words fixture(U64 i) {
 Identity id{U32((i>>12)*0x9e3779b9u),i&4095,0x8e1076d9e24a326bull,i>>20};
 // Exercise nonzero high index bits and all per-pixel/branch/frame identities.
 if(i&0x10000)id.index|=(i>>16)<<32;
 Words w{};for(U32 d=0;d<4;++d)w.v[d]=samplingWord(id,d<2?d:d+14,3);return w;
}
X2_HD inline U32 checks() {
 U32 failed=sampletest::checks();
 const U32 expected[4][8]={{0,4,6,2,3,7,5,1},{0,4,2,6,3,7,1,5},{0,4,2,6,5,1,7,3},{0,4,2,6,7,3,5,1}};
 for(U32 d=0;d<4;++d)for(U32 i=0;i<8;++i)if(sobol(i,d)!=(expected[d][i]<<29))failed|=1u<<17;
 // Each power-of-two prefix fills every 1D stratum exactly once, after shift.
 for(U32 pixel=0;pixel<4;++pixel)for(U32 m=1;m<=10;++m)for(U32 d=0;d<4;++d){
  bool seen[1024]{};U32 dimension=d<2?d:d+14;
  for(U32 i=0;i<(1u<<m);++i){Identity id{pixel,i,19,3};U32 cell=samplingWord(id,dimension,3)>>(32-m);if(seen[cell])failed|=1u<<18;seen[cell]=true;}
 }
 Identity id{12,0xfedcba9876543210ull,713,17};
 for(U32 d=0;d<32;++d){
  if(samplingWord(id,d,0)!=word(id,d))failed|=1u<<19;
  if(d!=0&&d!=1&&d!=16&&d!=17&&samplingWord(id,d,3)!=word(id,d))failed|=1u<<20;
  if(draw(id,d,3)<0||draw(id,d,3)>=1)failed|=1u<<21;
 }
 auto other=id;other.index^=1ull<<32;if(samplingWord(id,16,3)==samplingWord(other,16,3))failed|=1u<<22;
 // Lower-dimensional net: every elementary camera rectangle has one point.
 for(U32 k=0;k<=8;++k){bool seen[256]{};
  for(U32 i=0;i<256;++i){Identity v{19,i,713,0};U32 a=k?samplingWord(v,0,3)>>(32-k):0,b=k<8?samplingWord(v,1,3)>>(24+k):0;U32 cell=(a<<(8-k))|b;if(seen[cell])failed|=1u<<23;seen[cell]=true;}
 }
 return failed;
}
}
