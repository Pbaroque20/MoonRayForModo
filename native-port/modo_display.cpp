#include <cmath>
#include <cstdint>
#include <algorithm>
// Explicit dimensions and buffer sizes are checked before touching caller memory.
extern "C" __declspec(dllexport) int modoDisplay(const float* source,uint64_t sourceBytes,
    unsigned width,unsigned height,unsigned char* destination,uint64_t destinationBytes,
    int kind,int view,float exposure,const float* matrix) noexcept {
    const uint64_t count=uint64_t(width)*height;
    if(!source || !destination || !matrix || !width || !height || count>64*1024*1024/12 ||
       sourceBytes!=count*12 || destinationBytes!=count*4 || kind<0 || kind>3 || view<0 || view>2 || !std::isfinite(exposure))return 0;
    const float gain=std::exp2(exposure);
    for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x){
        const float* input=source+(uint64_t(y)*width+x)*3;
        unsigned char* out=destination+(uint64_t(height-1-y)*width+x)*4;
        float v[3];for(int c=0;c<3;++c)v[c]=std::isfinite(input[c])?input[c]:0;
        if(kind==0){
            float t[3];for(int c=0;c<3;++c)t[c]=(matrix[c*3]*v[0]+matrix[c*3+1]*v[1]+matrix[c*3+2]*v[2])*gain;
            for(int c=0;c<3;++c){
                v[c]=t[c];
                if(view==2){v[c]=std::max(0.f,v[c]);v[c]=v[c]/(1.f+v[c]);}
                if(view!=0)v[c]=v[c]<=0.0031308f?12.92f*v[c]:1.055f*std::pow(v[c],1.f/2.4f)-0.055f;
            }
        }else if(kind==1){for(float& c:v)c=c*.5f+.5f;}
        else if(kind==2){v[1]=v[2]=v[0];}
        else if(kind==3){v[2]=0;}
        for(int c=0;c<3;++c)out[c]=static_cast<unsigned char>(std::clamp(std::isfinite(v[c])?v[c]:0.f,0.f,1.f)*255.f+.5f);
        out[3]=255;
    }
    return 1;
}
