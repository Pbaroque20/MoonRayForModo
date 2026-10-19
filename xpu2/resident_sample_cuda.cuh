// Typed/revisioned records feed the unchanged native-parity sampler.
extern "C" __global__ void lambert_sample_resident_vector(const unsigned char* input,const U*,
 unsigned char* output,U* results,const float* resident,const float*,U count){
 U id=blockIdx.x*blockDim.x+threadIdx.x;
 const U* packed=reinterpret_cast<const U*>(input);U* table=(U*)resident;
 const bool header=packed[0]==0x32525358u && packed[1]==count && count>0 && count<=512 && packed[2]<=64;
 if(!header){if(id<count){for(U k=0;k<9;++k)results[id*9+k]=0;results[id*9]=2;}return;}
 const U* updates=packed+5+count*5;
 // Updated slots are read from the upload, never from the table being written.
 // Each word has one writer; the next batch on this flight waits for retirement.
 U stride=gridDim.x*blockDim.x;
 for(U k=id;k<packed[2]*197;k+=stride){U entry=k/197,word=k%197;const U* src=updates+entry*198;
  if(src[0]<128)table[src[0]*197+word]=src[1+word];}
 if(id>=count)return;
 const U* d=packed+5+id*5;U words[24]={};const U index=d[0];
 if(index!=0xffffffffu){
  U group=(index&0x7fffffffu)/8,lane=index&7u;const U* source=nullptr;
  if(index&0x80000000u){if(group<packed[2] && updates[group*198]<128)source=updates+group*198+1;}
  else if(group<128)source=table+group*197;
  if(source && source[0]==packed[3] && source[1]==packed[4] && source[2]==d[1] && source[3]==d[2] && source[4]==0x32525358u){
   for(U k=0;k<24;++k)words[k]=source[5+lane*24+k];words[11]=d[3];words[12]=d[4];
  }
 }
 shadeSample<true>(reinterpret_cast<const unsigned char*>(words),output+id*96,results+id*9,96);
}
