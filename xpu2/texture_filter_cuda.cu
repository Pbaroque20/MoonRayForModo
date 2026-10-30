// Experimental raw-channel 2D point/bilinear filter. No mip choice/derivatives.
// Explicit FP32 arithmetic avoids hardware texture interpolation quantization.
struct Query {float s,t;int mode,wrap;};
struct Answer {int status;float value[4];};
__device__ int address(int p,int n,int wrap){
    if(wrap==0)return p<0||p>=n?-1:p;
    if(wrap==1)return p<0?0:(p>=n?n-1:p);
    if(wrap==2){p%=n;return p<0?p+n:p;}
    p%=2*n;if(p<0)p+=2*n;return p<n?p:2*n-1-p;
}
__device__ int texel(const unsigned long long* pages,int w,int h,int nc,int tw,int th,int x,int y,int wrap,float* v){
    x=address(x,w,wrap);y=address(y,h,wrap);for(int c=0;c<4;++c)v[c]=0;
    if(x<0||y<0)return 0;
    unsigned long long pointer=pages[(y/th)*((w+tw-1)/tw)+x/tw];if(!pointer)return 3;
    const float* tile=reinterpret_cast<const float*>(pointer);
    for(int c=0;c<nc;++c)v[c]=tile[(static_cast<unsigned long long>(y%th)*tw+x%tw)*nc+c];return 0;
}
extern "C" __global__ void texture_filter(const unsigned long long* pages,int w,int h,int nc,int tw,int th,unsigned pageCount,const Query* queries,Answer* answers,unsigned count){
    unsigned id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    Query q=queries[id];Answer a={2,{0,0,0,0}};
    if(w<1||h<1||w>1048576||h>1048576||nc<1||nc>4||tw<1||th<1||tw>65536||th>65536||!isfinite(q.s)||!isfinite(q.t)){answers[id]=a;return;}
    unsigned long long needed=static_cast<unsigned long long>((w+tw-1)/tw)*((h+th-1)/th);
    if(needed!=pageCount||pageCount>1048576){answers[id]=a;return;}
    a.status=1;
    if(q.mode<0||q.mode>1||q.wrap<0||q.wrap>3||fabsf(q.s)>8||fabsf(q.t)>8){answers[id]=a;return;}
    float sx=__fmul_rn(q.s,float(w)),ty=__fmul_rn(q.t,float(h));
    sx=__fsub_rn(sx,.5f);ty=__fsub_rn(ty,.5f);int x=int(floorf(sx)),y=int(floorf(ty));
    float fx=__fsub_rn(sx,float(x)),fy=__fsub_rn(ty,float(y));float p[4][4];
    // OIIO closest selects the lower texel at exactly half a pixel.
    if(q.mode==0){a.status=texel(pages,w,h,nc,tw,th,x+(fx>.5f),y+(fy>.5f),q.wrap,a.value);answers[id]=a;return;}
    a.status=0;
    for(int j=0;j<4;++j)if(texel(pages,w,h,nc,tw,th,x+(j&1),y+(j>>1),q.wrap,p[j])){a.status=3;answers[id]=a;return;}
    // OIIO-compatible pixel-center convention. Filtering order is measured,
    // not assumed bitwise equivalent to OIIO's SIMD implementation.
    for(int c=0;c<nc;++c){
        float lo=__fadd_rn(__fmul_rn(__fsub_rn(1.f,fx),p[0][c]),__fmul_rn(fx,p[1][c]));
        float hi=__fadd_rn(__fmul_rn(__fsub_rn(1.f,fx),p[2][c]),__fmul_rn(fx,p[3][c]));
        a.value[c]=__fadd_rn(__fmul_rn(__fsub_rn(1.f,fy),lo),__fmul_rn(fy,hi));
    }
    answers[id]=a;
}
