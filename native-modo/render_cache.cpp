// Read-only evaluated geometry export. All host calls run on Modo's main thread.
#include <lx_item.hpp>
#include <lx_rendercache.hpp>
#include <lx_vertex.hpp>
#include <array>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <fstream>
#include <filesystem>
#include <locale>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void check(LxResult result,const char* operation) {
    if(LXx_FAIL(result)) {
        std::ostringstream error; error<<operation<<" failed (0x"<<std::hex<<result<<")";
        throw std::runtime_error(error.str());
    }
}
void text(std::ostream& out,const char* value) {
    out<<'"';
    for(const unsigned char* p=reinterpret_cast<const unsigned char*>(value?value:"");*p;++p) {
        if(*p=='"' || *p=='\\') out<<'\\'<<char(*p);
        else if(*p<32) {
            const char hex[]="0123456789abcdef";
            out<<"\\u00"<<hex[*p>>4]<<hex[*p&15];
        } else out<<char(*p);
    }
    out<<'"';
}
template<class T> void number(std::ostream& out,T value) {
    if(!std::isfinite(double(value))) throw std::runtime_error("Non-finite evaluated geometry");
    out<<value;
}
// Where the long rows of numbers go when they are handed over as they are and not written out as text: written as
// text they took nine tenths of the time of a reading (0.55 s of 0.58 for 392,000 numbers). The text then says
// only where in this each row is, how many entries it has and how wide each is.
std::ostream* blob=nullptr;
unsigned long long blobAt=0;
template<class T> void row(std::ostream& out,const T* values,std::size_t count,std::size_t width,bool whole) {
    const std::size_t bytes=count*width*sizeof(T);
    if(bytes) blob->write(reinterpret_cast<const char*>(values),std::streamsize(bytes));
    out<<"{\"at\":"<<blobAt<<",\"count\":"<<count<<",\"width\":"<<width<<",\"whole\":"<<(whole?1:0)<<'}';
    blobAt+=bytes;
}
template<std::size_t N> void vectors(std::ostream& out,const std::vector<std::array<float,N>>& values) {
    if(blob) {
        for(const auto& value:values) for(float v:value) if(!std::isfinite(double(v))) throw std::runtime_error("Non-finite evaluated geometry");
        row(out,values.empty()?nullptr:values[0].data(),values.size(),N,false);return;
    }
    out<<'[';
    for(std::size_t i=0;i<values.size();++i) {
        if(i)out<<','; out<<'[';
        for(std::size_t k=0;k<N;++k) {if(k)out<<',';number(out,values[i][k]);}
        out<<']';
    }
    out<<']';
}
void transform(std::ostream& out,CLxLoc_GeoCacheSurface& surface,int endpoint) {
    LXtVector position,scale; LXtMatrix rotation;
    check(surface.GetXfrm(position,rotation,scale,endpoint),"Surface transform");
    out<<'[';
    for(int r=0;r<3;++r) {
        // Modo 16.1's returned 3x3 already includes non-uniform scale.
        // GetXfrm exposes column vectors; RDL and worldMatrix use row vectors.
        for(int c=0;c<3;++c) {number(out,rotation[c][r]);out<<',';}
        out<<"0,";
    }
    for(int c=0;c<3;++c) {number(out,position[c]);out<<',';}
    out<<"1]";
}
// Where the handing over of a mesh spends its time: Modo making its segments, fetching what is in them, and
// writing it out.
static double spentLoading=0,spentFetching=0,spentWriting=0;
static double clockNow(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
void prototype(std::ostream& out,CLxLoc_GeoCacheSurface& surface) {
    double mark=clockNow();
    check(surface.LoadSegments(),"Load geometry segments");
    spentLoading+=clockNow()-mark;
    // The short-lived cache owns its segments; retain borrowed interface refs.
    out<<"{\"features\":[";
    CLxLoc_TableauVertex descriptor;descriptor.set(surface.GetVertexDesc());
    if(descriptor.test()) for(unsigned i=0;i<descriptor.Count();++i) {
        LXtID4 type; const char* name=nullptr; unsigned offset;
        check(descriptor.ByIndex(i,&type,&name,&offset),"Vertex feature description");
        if(i)out<<',';
        out<<"{\"type\":"<<type<<",\"offset\":"<<offset<<",\"name\":";
        text(out,name);out<<'}';
    }
    out<<"],\"segments\":[";
    int count=0;surface.SegmentCount(&count);
    for(int s=0;s<count;++s) {
        mark=clockNow();
        void* object=nullptr;check(surface.SegmentAt(s,&object),"Geometry segment");
        CLxLoc_GeoCacheSegment segment;segment.set(object);
        int vertices=0,polygons=0,perFace=0;
        segment.VertexCount(&vertices);segment.PolygonCount(&polygons);segment.VertsPerPoly(&perFace);
        if(vertices<0 || polygons<0 || perFace<0 || (polygons && perFace>2147483647/polygons))
            throw std::runtime_error("Invalid evaluated mesh dimensions");
        const int corners=polygons*perFace;
        std::vector<std::array<float,3>> positions(vertices),normals(corners);
        std::vector<int> indices(corners);
        if(vertices) check(segment.GetVertexFeature(LXiRENDERCACHE_GEOVERT_OPOS,positions.data(),vertices,0),"Positions");
        if(corners) check(segment.GetPolygonVertexInds(indices.data(),corners,0),"Polygon indices");
        for(int index:indices) if(index<0 || index>=vertices) throw std::runtime_error("Evaluated polygon index out of bounds");
        spentFetching+=clockNow()-mark;mark=clockNow();
        if(s)out<<',';
        out<<"{\"face_varying\":true,\"vertices\":";vectors(out,positions);
        if(blob) {
            out<<",\"faces\":";row(out,indices.data(),std::size_t(polygons),std::size_t(perFace),true);
            out<<",\"radii\":";
            int held=0;segment.VertexFeatureCount(LXiRENDERCACHE_GEOVERT_RAD,&held);
            std::vector<float> radii(vertices && held?vertices:0);
            if(!radii.empty()) check(segment.GetVertexFeature(LXiRENDERCACHE_GEOVERT_RAD,radii.data(),vertices,0),"Vertex radii");
            for(float v:radii) if(!std::isfinite(double(v))) throw std::runtime_error("Non-finite evaluated geometry");
            row(out,radii.data(),radii.size(),1,false);
            out<<",\"skip\":[";
        } else {
        out<<",\"faces\":[";
        for(int f=0;f<polygons;++f) {
            if(f)out<<',';out<<'[';
            for(int k=0;k<perFace;++k){if(k)out<<',';out<<indices[f*perFace+k];}
            out<<']';
        }
        out<<"],\"radii\":[";
        }
        int radiusCount=0;segment.VertexFeatureCount(LXiRENDERCACHE_GEOVERT_RAD,&radiusCount);
        if(!blob && vertices && radiusCount) {
            std::vector<float> radii(vertices);
            check(segment.GetVertexFeature(LXiRENDERCACHE_GEOVERT_RAD,radii.data(),vertices,0),"Vertex radii");
            for(int v=0;v<vertices;++v) { if(v)out<<',';number(out,radii[v]); }
        }
        out<<"],\"velocities\":";
        int velocityCount=0;segment.VertexFeatureCount(LXiRENDERCACHE_GEOVERT_OVEL,&velocityCount);
        if(vertices && velocityCount) {
            std::vector<std::array<float,3>> velocities(vertices);
            check(segment.GetVertexFeature(LXiRENDERCACHE_GEOVERT_OVEL,velocities.data(),vertices,0),"Vertex velocities");
            vectors(out,velocities);
        } else out<<"[]";
        out<<",\"normals\":";
        if(corners && LXx_OK(segment.GetPolygonVertexFeature(LXiRENDERCACHE_GEOVERT_ONRM,normals.data(),corners,0))) vectors(out,normals);
        else out<<"[]";
        out<<",\"uv_sets\":[";
        int uvCount=0;segment.VertexFeatureCount(LXiRENDERCACHE_GEOVERT_UV,&uvCount);
        for(int u=0;u<uvCount;++u) {
            std::vector<std::array<float,2>> values(corners);
            check(segment.GetPolygonVertexFeature(LXiRENDERCACHE_GEOVERT_UV+u,values.data(),corners,0),"UV coordinates");
            if(u)out<<',';vectors(out,values);
        }
        out<<"]}";
        spentWriting+=clockNow()-mark;
    }
    out<<"]}";
    surface.UnloadSegments();
}
}

// The cache is made anew and evaluated whole for every reading, which takes Modo a few thousandths of a second. One
// kept between readings and left for Modo to keep up to date was tried: it was a moment behind each edit, and
// failed to give its segments just after a mesh had changed shape.
static void write_snapshot(std::ostream& out,double time,int displaced) {
        blobAt=0;
        const auto began=std::chrono::steady_clock::now();
        spentLoading=spentFetching=spentWriting=0;
        auto since=[&](){return std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count();};
        CLxLoc_RenderCacheService service;
        void* object=nullptr;
        unsigned flags=LXfRENDERCACHE_TRACK_CURRENT_SCENE|LXfRENDERCACHE_TURN_OFF_AUTO_UPDATES|
                       LXfRENDERCACHE_FORCE_FULL_UPDATE;
        if(displaced) flags|=LXfRENDERCACHE_GEOCACHE_DISPLACE;
        check(service.CreateRenderCache(&object,flags),"Create render cache");
        CLxLoc_RenderCache cache;cache.take(object);
        check(cache.Update(time,1),"Evaluate render cache");
        const double evaluated=since();
        int count=0;check(cache.GeoSurfaceCount(&count),"Surface count");
        std::map<int,CLxLoc_GeoCacheSurface> sources;
        out<<"{\"surfaces\":[";
        for(int i=0;i<count;++i) {
            object=nullptr;check(cache.GeoSurfaceAt(i,&object),"Render surface");
            // These accessors return borrowed objects (see lx_rendercache.hpp
            // User helpers). take() would consume the cache's own reference.
            CLxLoc_GeoCacheSurface surface;surface.set(object);
            CLxLoc_GeoCacheSurface source;
            if(surface.IsInstanced()) {
                object=nullptr;check(surface.SourceSurface(&object),"Instance source");source.set(object);
            }
            else source.set(surface);
            // Keep the cache's original prototype. Instance reference wrappers
            // may expose the same ID without owning populated segments.
            sources.emplace(source.ID(),source);
            object=nullptr;check(surface.SourceItem(&object),"Surface source item");
            CLxLoc_Item item;item.set(object);
            const char* name=nullptr;check(item.Ident(&name),"Item identifier");
            LXtGeoCacheSrfVisibility visibility{};check(surface.VisibilityFlags(&visibility),"Surface visibility");
            if(i)out<<',';
            out<<"{\"id\":"<<surface.ID()<<",\"source_id\":"<<source.ID()<<",\"source_item\":";text(out,name);
            out<<",\"instance_index\":"<<surface.InstanceIndex();
            out<<",\"instanced\":"<<surface.IsInstanced()<<",\"source_instanced\":"<<source.IsInstanced();
            out<<",\"material\":";text(out,surface.MaterialPTag());
            out<<",\"part\":";text(out,surface.PartPTag());
            out<<",\"matrix\":";transform(out,surface,0);
            out<<",\"matrix_close\":";transform(out,surface,1);
            out<<",\"visibility\":["<<visibility.camera<<','<<visibility.indirect<<','<<visibility.reflection<<','
               <<visibility.refraction<<','<<visibility.subscatter<<','<<visibility.occlusion<<']';
            unsigned layers=0;check(surface.ShaderLayerCount(&layers),"Surface shader layers");
            out<<",\"layers\":[";
            for(unsigned n=0;n<layers;++n) {
                object=nullptr;check(surface.ShaderLayerAt(n,&object),"Surface shader layer");
                CLxLoc_Item layer;layer.set(object);check(layer.Ident(&name),"Shader identifier");
                if(n)out<<',';text(out,name);
            }
            out<<"]}";
        }
        const double listed=since();
        out<<"],\"prototypes\":{";bool first=true;
        for(auto& entry:sources) {
            if(!first)out<<',';first=false;text(out,std::to_string(entry.first).c_str());out<<':';prototype(out,entry.second);
        }

        out<<"},\"timing\":["<<evaluated<<','<<listed-evaluated<<','<<since()-listed<<"],\"handing\":["<<spentLoading<<','<<spentFetching<<','<<spentWriting<<"]}";
}

extern "C" __declspec(dllexport) const char* MR_geometry_snapshot(double time,int displaced) {
    static thread_local std::string result;
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(9);
    try {
        write_snapshot(out,time,displaced);
        result=out.str();
    } catch(const std::exception& error) {
        std::ostringstream failure;failure<<"{\"error\":";text(failure,error.what());failure<<'}';result=failure.str();
    } catch(...) {result="{\"error\":\"Unknown render cache error\"}";}
    return result.c_str();
}

// File export avoids retaining a second complete JSON string in the adapter.
// Python owns the temporary path and removes partial output on error.
extern "C" __declspec(dllexport) const char* MR_geometry_snapshot_file(double time,int displaced,const char* path) {
    static thread_local std::string error;
    try {
        if(!path || !*path) throw std::runtime_error("Missing geometry output path");
        std::ofstream out(std::filesystem::u8path(path),std::ios::binary|std::ios::trunc);
        out.exceptions(std::ios::badbit|std::ios::failbit);
        out.imbue(std::locale::classic());out<<std::setprecision(9);
        write_snapshot(out,time,displaced);
        out.close();
        return nullptr;
    } catch(const std::exception& failure) { error=failure.what(); }
      catch(...) { error="Unknown render cache file error"; }
    return error.c_str();
}

// As MR_geometry_snapshot_file, with the meshes' long rows of numbers put into a second file as they are: 32-bit
// floats and whole numbers, in the order the text names them. Reading a scene this way takes a small part of the time.
extern "C" __declspec(dllexport) const char* MR_geometry_snapshot_binary(double time,int displaced,const char* path,const char* rows) {
    static thread_local std::string error;
    try {
        if(!path || !*path || !rows || !*rows) throw std::runtime_error("Missing geometry output path");
        std::ofstream out(std::filesystem::u8path(path),std::ios::binary|std::ios::trunc);
        std::ofstream held(std::filesystem::u8path(rows),std::ios::binary|std::ios::trunc);
        out.exceptions(std::ios::badbit|std::ios::failbit);held.exceptions(std::ios::badbit|std::ios::failbit);
        out.imbue(std::locale::classic());out<<std::setprecision(9);
        struct Rows { Rows(std::ostream* to){blob=to;} ~Rows(){blob=nullptr;} } use(&held);
        write_snapshot(out,time,displaced);
        out.close();held.close();
        return nullptr;
    } catch(const std::exception& failure) { error=failure.what(); }
      catch(...) { error="Unknown render cache file error"; }
    return error.c_str();
}
