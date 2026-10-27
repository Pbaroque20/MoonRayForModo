// Arithmetic on the rows of numbers the adapter hands over (moonray_modo/rows.py), for the plugin's Python: the same
// operations in the same order as its own code, on whole rows at once, so that the numbers come out the same.
#include <cstdint>

// coordinates.transform_uv: each corner's UV through a texture layer's UV matrix (a..f), rotation and scale, worked
// in doubles as Python works them and kept as 32-bit floats as the scene file keeps them. m: a, b, c, d, e, f,
// cos(rotation), sin(rotation), scale x, scale y.
extern "C" __declspec(dllexport) int MR_uv_transform(const float* in, float* out, long long count, const double* m) {
    const double a=m[0],b=m[1],c=m[2],d=m[3],e=m[4],f=m[5],cosine=m[6],sine=m[7],sx=m[8],sy=m[9];
    for(long long i=0;i<count;++i) {
        const double u=in[2*i],v=in[2*i+1];
        const double x=a*u+b*v+c,y=d*u+e*v+f;
        out[2*i]=float((x*cosine-y*sine)*sx);
        out[2*i+1]=float((x*sine+y*cosine)*sy);
    }
    return 0;
}

// rdlb.int_list's numbers: each value (0 <= value < 2^27) as scene_rdl2's zigzag variable-length number in a fixed
// four bytes, seven bits to a byte, low first, the top bit of the first three set. -1 where a value is out of range.
extern "C" __declspec(dllexport) int MR_zigzag4(const int32_t* in, unsigned char* out, long long count) {
    for(long long i=0;i<count;++i) {
        if(in[i]<0 || in[i]>=(1<<27)) return -1;
        const uint32_t z=uint32_t(in[i])<<1;
        out[4*i]=(unsigned char)((z&0x7f)|0x80);
        out[4*i+1]=(unsigned char)(((z>>7)&0x7f)|0x80);
        out[4*i+2]=(unsigned char)(((z>>14)&0x7f)|0x80);
        out[4*i+3]=(unsigned char)((z>>21)&0x7f);
    }
    return 0;
}
