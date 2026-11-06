// environment_layers.texture's blend, for the plugin's Python: an environment's layers, bottom first, laid over one
// another in every direction of a latitude/longitude map, as its Python loop lays them (the same arithmetic in
// doubles, the same order). Done here over the machine's threads with Python's lock let go: in Python a car's
// four-layer environment took 15 s of a scene's first preview. Only layers without groups or masks: image (its pixels
// already shrunk to the map's size, and its alpha), colour, and Modo's sky gradients; any other layer is Python's.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <thread>
#include <vector>

namespace {

const double PI=3.14159265358979323846;

// environment_layers.blend's modes, by their place in MODES (environment_layers.py).
enum Mode {Normal,Multiply,Add,Subtract,Screen,Divide,Difference,Darken,Lighten,Overlay,Hardlight,Exclusion,Softlight,Colordodge,Colorburn};

double component(int mode,double a,double b) {
    switch(mode) {
        case Normal: return b;
        case Multiply: return a*b;
        case Add: return a+b;
        case Subtract: return a-b;
        case Screen: return 1-(1-a)*(1-b);
        case Divide: return a/std::max(1e-6,b);
        case Difference: return std::fabs(a-b);
        case Darken: return std::min(a,b);
        case Lighten: return std::max(a,b);
        case Overlay: return a<.5?2*a*b:1-2*(1-a)*(1-b);
        case Hardlight: return b<.5?2*a*b:1-2*(1-a)*(1-b);
        case Exclusion: return a+b-2*a*b;
        case Softlight: {
            const double d=a<=.25?((16*a-12)*a+4)*a:std::sqrt(std::max(0.0,a));
            return b<=.5?a-(1-2*b)*a*(1-a):a+(2*b-1)*(d-a);
        }
        case Colordodge: return b>=1?1:std::min(1.0,a/std::max(1e-6,1-b));
        case Colorburn: return b<=0?0:1-std::min(1.0,(1-a)/std::max(1e-6,b));
    }
    return b;
}

// environments.gradient_color: kind 0 constant, 1 overcast, 2 two colours, 3 four colours. g: zenith, sky, ground,
// nadir (3 each), the sky's and the ground's exponents.
void gradient(int kind,const double* g,double height,double* out) {
    height=std::max(-1.0,std::min(1.0,height));
    const double* zenith=g; const double* sky=g+3; const double* ground=g+6; const double* nadir=g+9;
    if(kind==0) { for(int k=0;k<3;++k) out[k]=zenith[k]; return; }
    if(kind==1) {
        for(int k=0;k<3;++k) out[k]=height>=0?zenith[k]*(1+2*height)/3:nadir[k];
        return;
    }
    const double *a,*b; double t;
    if(kind==2) { a=nadir; b=zenith; t=(height+1)/2; }
    else if(height>=0) { a=sky; b=zenith; t=1-std::pow(1-height,std::max(.001,g[12])); }
    else { a=ground; b=nadir; t=1-std::pow(1+height,std::max(.001,g[13])); }
    for(int k=0;k<3;++k) out[k]=a[k]+(b[k]-a[k])*t;
}

}  // namespace

// width x height directions, rows bottom up (the first row looks straight down), as the PFM the Python writes. For each
// of count layers, bottom first: kinds (0 image, 1 colour, 2 gradient), modes (above), opacities, inverts (1 to invert
// its colour); images: its pixels (width*height*3, or null) and alpha (width*height, or null); turns: 9 numbers of
// its inverse placement (row-major, as coordinates.inverse gives a 4x4's top-left), or all zero for none; uv: a, b, c,
// d, e, f, cos(rotation), sin(rotation), scale x, scale y; colours: 3 numbers; gradients: the gradient kind (as above)
// then 14 numbers. out: width*height*3 floats. Returns 0.
extern "C" __declspec(dllexport) int MR_environment_blend(int width,int height,int count,const int* kinds,const int* modes,
        const double* opacities,const int* inverts,const float* const* images,const float* const* alphas,const double* turns,
        const double* uv,const double* colours,const double* gradients,float* out,int threads) {
    if(threads<=0) threads=int(std::max(1u,std::thread::hardware_concurrency()));
    auto rows=[&](int begin,int end) {
        for(int y=begin;y<end;++y) {
            const double latitude=((y+.5)/height-.5)*PI;
            for(int x=0;x<width;++x) {
                const double longitude=((x+.5)/width-.5)*2*PI;
                const double direction[3]={std::sin(longitude)*std::cos(latitude),std::sin(latitude),std::cos(longitude)*std::cos(latitude)};
                double colour[3]={0,0,0};
                for(int l=0;l<count;++l) {
                    double foreground[3]={0,0,0},coverage=1.0;
                    if(kinds[l]==1) {
                        for(int k=0;k<3;++k) foreground[k]=colours[l*3+k];
                    } else if(kinds[l]==2) {
                        gradient(int(gradients[l*15]),gradients+l*15+1,direction[1],foreground);
                    } else {
                        const double* m=turns+l*9;
                        double d[3]={direction[0],direction[1],direction[2]};
                        bool turned=false;
                        for(int k=0;k<9;++k) if(m[k]!=0) {turned=true;break;}
                        if(turned) for(int i=0;i<3;++i) d[i]=direction[0]*m[0*3+i]+direction[1]*m[1*3+i]+direction[2]*m[2*3+i];
                        const double length=std::max(1e-12,std::sqrt(d[0]*d[0]+d[1]*d[1]+d[2]*d[2]));
                        const double u0=.5+std::atan2(d[0],d[2])/(2*PI);
                        const double v0=.5+std::asin(std::max(-1.0,std::min(1.0,d[1]/length)))/PI;
                        const double* t=uv+l*10;
                        const double tx=t[0]*u0+t[1]*v0+t[2],ty=t[3]*u0+t[4]*v0+t[5];
                        double u=(tx*t[6]-ty*t[7])*t[8],v=(tx*t[7]+ty*t[6])*t[9];
                        u=u*width-.5; v=v*height-.5;
                        const double fx=std::floor(u),fy=std::floor(v);
                        const double ax=u-fx,ay=v-fy;
                        const long long ix=(long long)fx,iy=(long long)fy;
                        const float* pixels=images[l];
                        const float* alpha=alphas[l];
                        coverage=alpha?0.0:1.0;
                        const double weights[4][3]={{0,0,(1-ax)*(1-ay)},{1,0,ax*(1-ay)},{0,1,(1-ax)*ay},{1,1,ax*ay}};
                        for(const auto& w:weights) {
                            const long long row=std::max(0LL,std::min((long long)height-1,iy+(long long)w[1]));
                            long long column=(ix+(long long)w[0])%width; if(column<0) column+=width;
                            const long long index=row*width+column;
                            const double a=alpha?std::max(0.0,std::min(1.0,double(alpha[index]))):1.0;
                            if(alpha) coverage+=a*w[2];
                            for(int k=0;k<3;++k) foreground[k]+=double(pixels[index*3+k])*w[2]*a;
                        }
                        if(alpha) for(int k=0;k<3;++k) foreground[k]/=std::max(1e-12,coverage);
                    }
                    if(inverts[l]) for(int k=0;k<3;++k) foreground[k]=1-foreground[k];
                    const double opacity=std::max(0.0,std::min(1.0,opacities[l]*coverage));
                    for(int k=0;k<3;++k) colour[k]=colour[k]+(component(modes[l],colour[k],foreground[k])-colour[k])*opacity;
                }
                float* to=out+((long long)y*width+x)*3;
                for(int k=0;k<3;++k) to[k]=float(colour[k]);
            }
        }
    };
    std::vector<std::thread> pool;
    const int step=(height+threads-1)/threads;
    for(int t=0;t<threads;++t) {
        const int begin=t*step,end=std::min(height,begin+step);
        if(begin>=end) break;
        pool.emplace_back(rows,begin,end);
    }
    for(auto& thread:pool) thread.join();
    return 0;
}
