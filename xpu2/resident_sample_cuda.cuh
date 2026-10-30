// The host and this kernel use resident_wire.h, concatenated by the PTX compiler.
extern "C" __global__ void lambert_sample_resident_vector(const unsigned char* input,const U*,
 unsigned char* output,U* results,const float* resident,const float*,U count){
 namespace w=xpu2::resident::wire;
 U id=blockIdx.x*blockDim.x+threadIdx.x;
 const U* packed=reinterpret_cast<const U*>(input);U* table=(U*)resident;
 const bool header=packed[0]==w::magic && packed[1]==count && count>0 && count<=w::maxSamples && packed[2]<=w::maxPackets;
 if(!header){if(id<count){for(U k=0;k<w::resultWords;++k)results[id*w::resultWords+k]=0;results[id*w::resultWords]=w::rejected;}return;}
 const U* updates=packed+w::headerWords+count*w::descriptorWords;
 // Updated entries are read from this upload. No reader races a table update.
 U stride=gridDim.x*blockDim.x;
 for(U k=id;k<packed[2]*w::entryWords;k+=stride){U entry=k/w::entryWords,word=k%w::entryWords;const U* src=updates+entry*w::updateWords;
  if(src[0]<w::slots)table[src[0]*w::entryWords+word]=src[1+word];}
 if(id>=count)return;
 const U* d=packed+w::headerWords+id*w::descriptorWords;U words[w::sampleWords]={};const U index=d[0];
 bool accepted=false;
 if(index!=w::inactive){
  U group=(index&~w::updateBit)/w::lanes,lane=index%w::lanes;const U* source=nullptr;
  if(index&w::updateBit){if(group<packed[2] && updates[group*w::updateWords]<w::slots)source=updates+group*w::updateWords+1;}
  else if(group<w::slots)source=table+group*w::entryWords;
  if(source && source[0]==packed[3] && source[1]==packed[4] && source[2]==d[1] && source[3]==d[2] && source[4]==w::magic){
   for(U k=0;k<w::sampleWords;++k)words[k]=source[w::tagWords+lane*w::sampleWords+k];words[11]=d[3];words[12]=d[4];accepted=true;
  }
 }
 if(!accepted){
  for(U k=0;k<w::resultWords;++k)results[id*w::resultWords+k]=0;
  results[id*w::resultWords]=index==w::inactive?w::invalid:w::rejected;
  for(U k=0;k<w::sampleWords;++k)reinterpret_cast<U*>(output)[id*w::sampleWords+k]=0;
  return; // Never call the shader or emit a successful black sample on rejection.
 }
 shadeSample<true>(reinterpret_cast<const unsigned char*>(words),output+id*w::sampleWords*sizeof(U),results+id*w::resultWords,w::sampleWords*sizeof(U));
}
