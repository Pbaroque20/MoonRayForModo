// geometry.prepare's smoothing, for the plugin's Python (moonray_modo/rows.py smooth_normals): each polygon corner's
// normal, the polygons about its point joined across the edges where they bend less than their smoothing limit. The
// same steps as geometry.py's (Newell's normal for each polygon, an edge joining exactly two polygons, the sharper of
// their two limits holding between them, each corner the sum of the joined polygons' unscaled normals, made unit), on
// whole meshes, split over the machine's threads, with Python's lock let go: in Python a car's 6 million corners took
// a minute of every first scene written, on one core.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <thread>
#include <vector>

namespace {

// Runs work(begin, end) over [0, count) in as many pieces as there are threads, joined before it returns.
template<class Work> void split(long long count, int threads, Work work) {
    if(threads<=1 || count<65536) { work(0LL,count); return; }
    std::vector<std::thread> pool;
    const long long step=(count+threads-1)/threads;
    for(int t=0;t<threads;++t) {
        const long long begin=t*step, end=std::min(count,begin+step);
        if(begin>=end) break;
        pool.emplace_back([=]{work(begin,end);});
    }
    for(auto& thread:pool) thread.join();
}

struct Edge {
    uint32_t low, high;     // its two points, the lower first
    uint32_t face;          // the polygon it is an edge of
    bool operator<(const Edge& other) const {
        if(low!=other.low) return low<other.low;
        if(high!=other.high) return high<other.high;
        return face<other.face;
    }
};

uint32_t root(std::vector<uint32_t>& parent, uint32_t at) {
    while(parent[at]!=at) { parent[at]=parent[parent[at]]; at=parent[at]; }
    return at;
}

void join(std::vector<uint32_t>& parent, uint32_t a, uint32_t b) {
    a=root(parent,a); b=root(parent,b);
    if(a!=b) { if(a<b) parent[b]=a; else parent[a]=b; }
}

}  // namespace

// points: 3 floats each (pointCount); corners: each polygon's points in turn (counts gives how many each); limits:
// each polygon's limit as the cosine of its smoothing angle, or null for threshold throughout. out: 3 floats for every
// corner. bend, where given, is set to the most any two polygons sharing an edge bend, in degrees, as geometry.prepare
// works it out for angular tessellation. threads <= 0: all of the machine's. Returns 0, or -1 where a corner names a
// point beyond the points or a polygon's count is below zero.
extern "C" __declspec(dllexport) int MR_smooth_normals(const float* points, long long pointCount, const int32_t* corners,
                                                       const int32_t* counts, long long faceCount, const float* limits,
                                                       double threshold, float* out, double* bend, int threads) {
    if(threads<=0) threads=int(std::max(1u,std::thread::hardware_concurrency()));
    // Where each polygon's corners begin.
    std::vector<long long> start(size_t(faceCount)+1,0);
    for(long long f=0;f<faceCount;++f) {
        if(counts[f]<0) return -1;
        start[size_t(f)+1]=start[size_t(f)]+counts[f];
    }
    const long long cornerCount=start[size_t(faceCount)];
    for(long long c=0;c<cornerCount;++c) if(corners[c]<0 || corners[c]>=pointCount) return -1;
    // Each polygon's normal by Newell's sums (geometry.topology's weighted), and made unit, in doubles.
    std::vector<double> weighted(size_t(faceCount)*3), unit(size_t(faceCount)*3);
    split(faceCount,threads,[&](long long begin,long long end){
        for(long long f=begin;f<end;++f) {
            double n[3]={0,0,0};
            const long long s=start[size_t(f)],k=counts[f];
            for(long long i=0;i<k;++i) {
                const float* p=points+3LL*corners[s+i];
                const float* q=points+3LL*corners[s+(i+1)%k];
                n[0]+=(double(p[1])-q[1])*(double(p[2])+q[2]);
                n[1]+=(double(p[2])-q[2])*(double(p[0])+q[0]);
                n[2]+=(double(p[0])-q[0])*(double(p[1])+q[1]);
            }
            const double length=std::sqrt(n[0]*n[0]+n[1]*n[1]+n[2]*n[2]);
            for(int a=0;a<3;++a) {
                weighted[size_t(f)*3+a]=n[a];
                unit[size_t(f)*3+a]=length>1e-20?n[a]/length:0.0;
            }
        }
    });
    // Every edge, by its two points, with its polygon: sorted, an edge's polygons stand together.
    std::vector<Edge> edges(static_cast<size_t>(cornerCount));
    split(faceCount,threads,[&](long long begin,long long end){
        for(long long f=begin;f<end;++f) {
            const long long s=start[size_t(f)],k=counts[f];
            for(long long i=0;i<k;++i) {
                const uint32_t a=uint32_t(corners[s+i]),b=uint32_t(corners[s+(i+1)%k]);
                edges[size_t(s+i)]={std::min(a,b),std::max(a,b),uint32_t(f)};
            }
        }
    });
    std::sort(edges.begin(),edges.end());
    // A corner's place in its polygon, by its point: the first corner of that point (a polygon passing a point twice
    // has the two as one, as geometry.prepare's (point, polygon) keys have them).
    auto place=[&](uint32_t face,uint32_t point)->uint32_t {
        const long long s=start[face],k=counts[face];
        for(long long i=0;i<k;++i) if(uint32_t(corners[s+i])==point) return uint32_t(s+i);
        return uint32_t(s);
    };
    std::vector<uint32_t> parent(static_cast<size_t>(cornerCount));
    for(long long c=0;c<cornerCount;++c) parent[size_t(c)]=uint32_t(c);
    // The repeated corners of a point in one polygon are one.
    for(long long f=0;f<faceCount;++f) {
        const long long s=start[size_t(f)],k=counts[f];
        for(long long i=0;i<k;++i) {
            const uint32_t first=place(uint32_t(f),uint32_t(corners[s+i]));
            if(first!=uint32_t(s+i)) join(parent,first,uint32_t(s+i));
        }
    }
    double most=0.0;
    const double flatEpsilon=0.0;  // more bend let through as smooth than the limit says
    for(size_t i=0;i<edges.size();) {
        size_t j=i;
        while(j<edges.size() && edges[j].low==edges[i].low && edges[j].high==edges[i].high) ++j;
        // An edge of one polygon, or of more than two, is always sharp.
        if(j-i==2) {
            const uint32_t a=edges[i].face,b=edges[i+1].face;
            double dot=0.0;
            for(int k=0;k<3;++k) dot+=unit[size_t(a)*3+k]*unit[size_t(b)*3+k];
            dot=std::max(-1.0,std::min(1.0,dot));
            most=std::max(most,std::acos(dot)*180.0/3.14159265358979323846);
            const double limit=limits?std::max(double(limits[a]),double(limits[b])):threshold;
            if(dot>=limit-1e-10-flatEpsilon) {
                for(uint32_t point:{edges[i].low,edges[i].high}) join(parent,place(a,point),place(b,point));
            }
        }
        i=j;
    }
    if(bend) *bend=most;
    // Each group of joined corners: the sum of its polygons' normals, each polygon once.
    std::vector<double> sums(size_t(cornerCount)*3,0.0);
    for(long long f=0;f<faceCount;++f) {
        const long long s=start[size_t(f)],k=counts[f];
        for(long long i=0;i<k;++i) {
            if(place(uint32_t(f),uint32_t(corners[s+i]))!=uint32_t(s+i)) continue;
            const uint32_t r=root(parent,uint32_t(s+i));
            for(int a=0;a<3;++a) sums[size_t(r)*3+a]+=weighted[size_t(f)*3+a];
        }
    }
    // Each corner, its group's sum made unit (geometry.unit: none where it has no length).
    for(long long c=0;c<cornerCount;++c) root(parent,uint32_t(c));
    split(cornerCount,threads,[&](long long begin,long long end){
        for(long long c=begin;c<end;++c) {
            const double* n=&sums[size_t(parent[size_t(c)])*3];
            const double length=std::sqrt(n[0]*n[0]+n[1]*n[1]+n[2]*n[2]);
            for(int a=0;a<3;++a) out[c*3+a]=length>1e-20?float(n[a]/length):0.0f;
        }
    });
    return 0;
}
