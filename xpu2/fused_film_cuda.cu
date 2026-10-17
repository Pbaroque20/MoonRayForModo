// One live kernel: AVX-compatible Lambert sampling, exact audit, contribution.
extern "C" __global__ void film_fused(const float* input,float* output,unsigned count){
 unsigned id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
 const float* a=input+id*64;float* dst=output+id*8;
 for(unsigned j=0;j<8;++j)dst[j]=0;
 if(a[23]!=1.f)return;
 U sample[9]={};filmSample(reinterpret_cast<const unsigned char*>(a+24),sample);
 if(sample[0]!=0)return; // Unsupported lobe uses native contribution.
 for(unsigned j=0;j<7;++j)if(sample[j+1]!=__float_as_uint(a[48+j])){dst[7]=-1.f;return;}
 if(float(sample[8])!=a[55]){dst[7]=-1.f;return;}
 float pdf=__uint_as_float(sample[7]);
 float f=a[0]*pdf,g=a[1]*a[6],inv=1.f/f,weight=(f*f)/(f*f+g*g);
 dst[0]=a[5];dst[7]=1.f;
 for(unsigned c=0;c<3;++c){float pt=(a[8+c]*__uint_as_float(sample[4+c]))*inv;
  dst[1+c]=(a[14+c]*pt)*weight;dst[4+c]=a[2]!=0.f?pt:0.f;}
}
