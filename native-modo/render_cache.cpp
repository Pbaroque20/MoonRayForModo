// Read-only evaluated geometry export. All host calls run on Modo's main thread.
#include <lx_item.hpp>
#include <lx_rendercache.hpp>
#include <lx_vertex.hpp>
#include <lx_listener.hpp>
#include <lxw_rendercache.hpp>
#include <lx_wrap.hpp>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <fstream>
#include <filesystem>
#include <locale>
#include <map>
#include <set>
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
// A segment Modo does not give (LXe_NOTAVAILABLE), as for a fur's strands where they cannot be made from their
// points (see strands): left out of the reading and counted, rather than the whole reading failing.
bool ready(LxResult result,const char* operation) {
    if(result==LXe_NOTAVAILABLE) return false;
    check(result,operation);return true;
}
// Modo gives no corner indices for its fur's strands (LXe_NOTAVAILABLE), only each point's strand and how far along
// it the point is (LXiRENDERCACHE_GEOVERT_FUR: u, v along the strand, strand id). The strands' pieces are made from
// those: a strand's points in order along it, each with the next. False where they do not come to the segment's
// count of pieces.
bool strands(CLxLoc_GeoCacheSegment& segment,int vertices,int polygons,std::vector<int>& indices) {
    int held=0;segment.VertexFeatureCount(LXiRENDERCACHE_GEOVERT_FUR,&held);
    if(!held || !vertices) return false;
    std::vector<std::array<float,3>> fur(vertices);
    if(LXx_FAIL(segment.GetVertexFeature(LXiRENDERCACHE_GEOVERT_FUR,fur.data(),vertices,0))) return false;
    // The id is not a strand's own (strands share it); a strand's points come one after another, from its root
    // (v 0) to its tip (v 1), so a point joins the one before it unless it starts a strand again.
    indices.clear();
    for(int v=1;v<vertices;++v) if(fur[v][2]==fur[v-1][2] && fur[v][1]>fur[v-1][1]) {indices.push_back(v-1);indices.push_back(v);}
    return int(indices.size())==polygons*2;
}
static int skippedSegments=0;static std::ostringstream skippedWhere;
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
// MR_geometry_snapshot_merged: a surface's polygon segments are handed over joined, one for each kind (with or
// without normals, the number of UV sets), as the plugin joins them (evaluated._merged_segments): Modo's render
// cache cuts a mesh into many segments (41,940 for the 16 surfaces of one test scene), and handing over each one,
// and the plugin turning each into lists of its own, was most of a reading. The faces come as one row of corners
// and one of each face's corner count. Segments of curves and points (fewer than three corners) are as before.
bool merging=false;
struct Joined {
    bool normals=false;int uvCount=0;
    std::vector<std::array<float,3>> positions,normalValues;
    std::vector<int> corners,sizes;
    std::vector<std::vector<std::array<float,2>>> uvs;
};
void finite(const float* values,std::size_t count) {
    for(std::size_t i=0;i<count;++i) if(!std::isfinite(double(values[i]))) throw std::runtime_error("Non-finite evaluated geometry");
}
void joined(std::ostream& out,Joined& kind) {
    finite(kind.positions.empty()?nullptr:kind.positions[0].data(),kind.positions.size()*3);
    out<<"{\"face_varying\":true,\"joined\":true,\"vertices\":";
    row(out,kind.positions.empty()?nullptr:kind.positions[0].data(),kind.positions.size(),3,false);
    out<<",\"faces\":";row(out,kind.corners.data(),kind.corners.size(),1,true);
    out<<",\"sizes\":";row(out,kind.sizes.data(),kind.sizes.size(),1,true);
    out<<",\"radii\":[],\"velocities\":[],\"normals\":";
    if(kind.normals){finite(kind.normalValues.empty()?nullptr:kind.normalValues[0].data(),kind.normalValues.size()*3);
        row(out,kind.normalValues.empty()?nullptr:kind.normalValues[0].data(),kind.normalValues.size(),3,false);}
    else out<<"[]";
    out<<",\"uv_sets\":[";
    for(int u=0;u<kind.uvCount;++u) {
        if(u)out<<',';
        auto& values=kind.uvs[u];finite(values.empty()?nullptr:values[0].data(),values.size()*2);
        row(out,values.empty()?nullptr:values[0].data(),values.size(),2,false);
    }
    out<<"]}";
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
// Whether this reading is of the live cache (MR_geometry_snapshot_live).
bool readLive=false;
void prototype(std::ostream& out,CLxLoc_GeoCacheSurface& surface,const std::string& owner) {
    double mark=clockNow();
    if(readLive && LXx_FAIL(surface.LoadSegments())) {
        // A surface the live cache has just made again can refuse its segments: let go of what it held and ask again,
        // and failing that, read a cache made anew (the plugin does so on "live:").
        surface.UnloadSegments();
        if(!surface.IsValid() || LXx_FAIL(surface.LoadSegments())) throw std::runtime_error("live: segments not given");
    } else if(!readLive) check(surface.LoadSegments(),"Load geometry segments");
    spentLoading+=clockNow()-mark;
    // The short-lived cache owns its segments; retain borrowed interface refs.
    // Which surface it is, for a later reading that keeps it (only).
    out<<"{\"item\":";text(out,owner.c_str());
    out<<",\"material\":";text(out,surface.MaterialPTag());out<<",\"part\":";text(out,surface.PartPTag());
    out<<",\"features\":[";
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
    std::vector<Joined> kinds;bool written=false;
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
        if((vertices && !ready(segment.GetVertexFeature(LXiRENDERCACHE_GEOVERT_OPOS,positions.data(),vertices,0),"Positions")) ||
           (corners && !ready(segment.GetPolygonVertexInds(indices.data(),corners,0),"Polygon indices") &&
            !(perFace==2 && strands(segment,vertices,polygons,indices)))) {
            ++skippedSegments;skippedWhere<<(skippedWhere.tellp()>0?",":"")<<"["<<surface.ID()<<','<<vertices<<','<<polygons<<','<<perFace<<']';spentFetching+=clockNow()-mark;continue;
        }
        for(int index:indices) if(index<0 || index>=vertices) throw std::runtime_error("Evaluated polygon index out of bounds");
        if(merging && blob && perFace>=3 && polygons) {
            const bool held=corners && LXx_OK(segment.GetPolygonVertexFeature(LXiRENDERCACHE_GEOVERT_ONRM,normals.data(),corners,0));
            int uvCount=0;segment.VertexFeatureCount(LXiRENDERCACHE_GEOVERT_UV,&uvCount);
            std::vector<std::vector<std::array<float,2>>> uvs(std::max(uvCount,0),std::vector<std::array<float,2>>(corners));
            bool fetched=true;
            for(int u=0;u<uvCount && fetched;++u)
                fetched=ready(segment.GetPolygonVertexFeature(LXiRENDERCACHE_GEOVERT_UV+u,uvs[u].data(),corners,0),"UV coordinates");
            if(!fetched) {++skippedSegments;skippedWhere<<(skippedWhere.tellp()>0?",":"")<<"["<<surface.ID()<<','<<vertices<<','<<polygons<<','<<perFace<<']';spentFetching+=clockNow()-mark;continue;}
            Joined* kind=nullptr;
            for(auto& k:kinds) if(k.normals==held && k.uvCount==uvCount) {kind=&k;break;}
            if(!kind) {kinds.emplace_back();kind=&kinds.back();kind->normals=held;kind->uvCount=uvCount;kind->uvs.resize(uvCount);}
            const int offset=int(kind->positions.size());
            if(offset>2147483647-vertices) throw std::runtime_error("Evaluated mesh too large");
            kind->positions.insert(kind->positions.end(),positions.begin(),positions.end());
            for(int index:indices) kind->corners.push_back(index+offset);
            kind->sizes.insert(kind->sizes.end(),std::size_t(polygons),perFace);
            if(held) kind->normalValues.insert(kind->normalValues.end(),normals.begin(),normals.end());
            for(int u=0;u<uvCount;++u) kind->uvs[u].insert(kind->uvs[u].end(),uvs[u].begin(),uvs[u].end());
            spentFetching+=clockNow()-mark;
            continue;
        }
        spentFetching+=clockNow()-mark;mark=clockNow();
        if(written)out<<',';written=true;
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
        std::vector<std::vector<std::array<float,2>>> uvs;
        for(int u=0;u<uvCount;++u) {
            std::vector<std::array<float,2>> values(corners);
            if(perFace>=3) check(segment.GetPolygonVertexFeature(LXiRENDERCACHE_GEOVERT_UV+u,values.data(),corners,0),"UV coordinates");
            else {
                // Fur's strands give theirs per point, not per corner; a strand left without them where Modo gives
                // none at all.
                std::vector<std::array<float,2>> points(vertices);
                if(LXx_FAIL(segment.GetPolygonVertexFeature(LXiRENDERCACHE_GEOVERT_UV+u,values.data(),corners,0))) {
                    if(LXx_FAIL(segment.GetVertexFeature(LXiRENDERCACHE_GEOVERT_UV+u,points.data(),vertices,0))) {uvs.clear();break;}
                    for(int c=0;c<corners;++c) values[c]=points[indices[c]];
                }
            }
            uvs.push_back(std::move(values));
        }
        for(std::size_t u=0;u<uvs.size();++u) {if(u)out<<',';vectors(out,uvs[u]);}
        out<<"]}";
        spentWriting+=clockNow()-mark;
    }
    mark=clockNow();
    for(auto& kind:kinds) {if(written)out<<',';written=true;joined(out,kind);}
    spentWriting+=clockNow()-mark;
    out<<"]}";
    surface.UnloadSegments();
}
}

// The live cache (MR_geometry_live_*): a render cache kept while a preview follows the scene, which Modo keeps up to
// date itself, updating only what an edit changed, and which says what it changed (Listener: each surface's item,
// by what changed of it). A reading of it lists the surfaces and loads only those asked for: a cache made anew is
// evaluated whole first, 2.8 s of every reading of a car of 334 surfaces. One kept without a listener was tried
// before: it was a moment behind each edit, and failed to give its segments just after a mesh had changed shape.
// So the plugin reads it only when the listener has said every item it asks for changed since the last reading,
// never while Modo is updating it, and on any failure reads a cache made anew (evaluated.capture).
class Listener : public CLxImpl_RenderCacheListener {
public:
    std::set<std::string> shaped,placed,shaded,added,removed;
    bool updating=false,cleared=false,destroyed=false;
    static std::string owner(ILxUnknownID object) {
        CLxLoc_GeoCacheSurface surface;
        if(!object || !surface.set(object)) return {};
        void* found=nullptr;
        if(LXx_FAIL(surface.SourceItem(&found)) || !found) return {};
        CLxLoc_Item item;item.set(found);
        const char* name=nullptr;
        return LXx_OK(item.Ident(&name)) && name?name:"";
    }
    void rli_RenderCacheDestroy() override {destroyed=true;}
    void rli_RenderCacheClear() override {cleared=true;}
    void rli_UpdateBegin() override {updating=true;}
    void rli_UpdateEnd() override {updating=false;}
    void rli_GeoCacheSurfaceAdd(ILxUnknownID surface) override {added.insert(owner(surface));}
    void rli_GeoCacheSurfaceRemove(ILxUnknownID surface) override {removed.insert(owner(surface));}
    void rli_GeoCacheSurfaceGeoUpdate(ILxUnknownID surface) override {shaped.insert(owner(surface));}
    void rli_GeoCacheSurfaceXformUpdate(ILxUnknownID surface) override {placed.insert(owner(surface));}
    void rli_GeoCacheSurfaceShaderUpdate(ILxUnknownID surface) override {shaded.insert(owner(surface));}
};
struct Live {
    CLxUser_RenderCache cache;
    ILxUnknownID listening=nullptr;
    Listener* listener=nullptr;
    int displaced=-1;
    bool usable() const {return listener && cache.test() && !listener->destroyed && !listener->cleared;}
};
static Live live;
static CLxPolymorph<Listener>* listeners=nullptr;

static void stopLive() {
    if(live.cache.test() && live.listening) {
        CLxUser_ListenerPort port(live.cache);
        if(port.test()) port.RemoveListener(live.listening);
    }
    if(live.cache.test()) live.cache.clear();
    if(live.listening) lx::ObjRelease(live.listening);
    live.listening=nullptr;live.listener=nullptr;live.displaced=-1;
}

// What a render cache's evaluation costs, by how it is asked (a probe's question, tools/probe_cl_cache_timing.py): made
// with these flags, updated at time (forced or not), listed (each surface's item), and each surface's bounding box asked
// (which may evaluate its geometry). A JSON line of seconds. Reads nothing else.
extern "C" __declspec(dllexport) const char* MR_geometry_cache_timing(double time,unsigned flags,int force,int boxes) {
    static thread_local std::string result;
    std::ostringstream out;
    try {
        const auto began=std::chrono::steady_clock::now();
        auto since=[&](){return std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count();};
        CLxLoc_RenderCacheService service;
        void* object=nullptr;
        check(service.CreateRenderCache(&object,flags),"Create render cache");
        CLxLoc_RenderCache cache;cache.take(object);
        const double made=since();
        const LxResult updated=cache.Update(time,force);
        const double evaluated=since();
        int count=0;cache.GeoSurfaceCount(&count);
        for(int i=0;i<count;++i){
            object=nullptr;if(LXx_FAIL(cache.GeoSurfaceAt(i,&object)))continue;
            CLxLoc_GeoCacheSurface surface;surface.set(object);
            void* item=nullptr;surface.SourceItem(&item);
        }
        const double listed=since();
        if(boxes)
            for(int i=0;i<count;++i){
                object=nullptr;if(LXx_FAIL(cache.GeoSurfaceAt(i,&object)))continue;
                CLxLoc_GeoCacheSurface surface;surface.set(object);
                LXtBBox box;surface.GetBBox(&box);
            }
        out<<"{\"made\":"<<made<<",\"update\":"<<evaluated-made<<",\"update_result\":"<<updated<<",\"surfaces\":"<<count
           <<",\"listed\":"<<listed-evaluated<<",\"boxes\":"<<since()-listed<<"}";
    } catch(const std::exception& error) {out.str("");out<<"{\"error\":";text(out,error.what());out<<"}";}
    result=out.str();
    return result.c_str();
}

// The cache is made anew and evaluated whole for every reading but the live cache's (above).
// only, where given: the items whose surfaces' segments are loaded; any other surface's prototype says only which it
// is ("kept": its item, material and part), for the plugin to take from the reading before (evaluated.capture). Loading
// every surface's segments was most of a reading after one mesh was edited (1.24 s of 2.15 for an interior's 25).
static const std::set<std::string>* onlyItems=nullptr;
static bool forcedEvaluation=false;
extern "C" __declspec(dllexport) void MR_geometry_forced(int on) {forcedEvaluation=on!=0;}
static void write_snapshot(std::ostream& out,double time,int displaced) {
        blobAt=0;skippedSegments=0;skippedWhere.str("");skippedWhere.clear();
        const auto began=std::chrono::steady_clock::now();
        spentLoading=spentFetching=spentWriting=0;
        auto since=[&](){return std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count();};
        CLxLoc_RenderCacheService service;
        void* object=nullptr;
        CLxLoc_RenderCache made;
        CLxLoc_RenderCache* chosen=&made;
        if(readLive) {
            // The live cache as Modo keeps it: nothing to evaluate. Refused, for a cache made anew, where it cannot
            // be read now (the plugin reads one made anew on "live:").
            if(!live.usable() || live.displaced!=displaced) throw std::runtime_error("live: no live cache");
            if(live.listener->updating) throw std::runtime_error("live: Modo is updating it");
            double at=0,offsets[2]={0,0};live.cache.Time(&at,offsets);
            if(std::fabs(at-time)>1e-6) throw std::runtime_error("live: another time");
            chosen=&live.cache;
        } else {
            // Made with a full update, the cache evaluates the scene at its current time (a car's 1.4 s); updated forced
            // as well, it evaluated it all again, as long again. Updated unforced, it evaluates only where time is another
            // (a motion blur's shutter end). Made without the full update it crashed now and then (2 of 5 readings of a
            // fur scene). MR_geometry_forced(1): the old way, forced, for a probe's comparison.
            unsigned flags=LXfRENDERCACHE_TRACK_CURRENT_SCENE|LXfRENDERCACHE_TURN_OFF_AUTO_UPDATES|
                           LXfRENDERCACHE_FORCE_FULL_UPDATE;
            if(displaced) flags|=LXfRENDERCACHE_GEOCACHE_DISPLACE;
            check(service.CreateRenderCache(&object,flags),"Create render cache");
            made.take(object);
            check(made.Update(time,forcedEvaluation?1:0),"Evaluate render cache");
        }
        CLxLoc_RenderCache& cache=*chosen;
        const double evaluated=since();
        int count=0;check(cache.GeoSurfaceCount(&count),"Surface count");
        std::map<int,CLxLoc_GeoCacheSurface> sources;
        std::map<int,std::string> sourceItems;
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
            if(sources.emplace(source.ID(),source).second) {
                object=nullptr;check(source.SourceItem(&object),"Source surface item");
                CLxLoc_Item owner;owner.set(object);const char* ident=nullptr;check(owner.Ident(&ident),"Source item identifier");
                sourceItems[source.ID()]=ident?ident:"";
            }
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
            if(!first)out<<',';first=false;text(out,std::to_string(entry.first).c_str());out<<':';
            const std::string& owner=sourceItems[entry.first];
            if(onlyItems && !onlyItems->count(owner)) {
                out<<"{\"kept\":1,\"item\":";text(out,owner.c_str());
                out<<",\"material\":";text(out,entry.second.MaterialPTag());out<<",\"part\":";text(out,entry.second.PartPTag());out<<'}';
                continue;
            }
            prototype(out,entry.second,owner);
        }

        out<<"},\"timing\":["<<evaluated<<','<<listed-evaluated<<','<<since()-listed<<"],\"handing\":["<<spentLoading<<','<<spentFetching<<','<<spentWriting<<"],\"skipped\":"<<skippedSegments<<",\"skipped_where\":["<<skippedWhere.str()<<"]}";
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

// As MR_geometry_snapshot_binary, with each surface's polygon segments joined (see merging).
extern "C" __declspec(dllexport) const char* MR_geometry_snapshot_merged(double time,int displaced,const char* path,const char* rows) {
    struct Join { Join(){merging=true;} ~Join(){merging=false;} } join;
    return MR_geometry_snapshot_binary(time,displaced,path,rows);
}

// As MR_geometry_snapshot_merged, loading only the surfaces of the items named in only (one identifier a line); the
// others' prototypes are marked kept, to be taken from the reading before. Empty only: every surface, as merged.
extern "C" __declspec(dllexport) const char* MR_geometry_snapshot_some(double time,int displaced,const char* path,const char* rows,const char* only) {
    std::set<std::string> items;
    for(const char* p=only?only:"";*p;) {
        const char* end=p;while(*end && *end!='\n') ++end;
        if(end>p) items.emplace(p,end);
        p=*end?end+1:end;
    }
    struct Only { Only(const std::set<std::string>* to){onlyItems=to;} ~Only(){onlyItems=nullptr;} } use(items.empty()?nullptr:&items);
    return MR_geometry_snapshot_merged(time,displaced,path,rows);
}

// The live cache started (or kept, where it already follows the scene so), for Modo to keep up to date from now on.
extern "C" __declspec(dllexport) const char* MR_geometry_live_start(int displaced) {
    static thread_local std::string error;
    try {
        if(live.usable() && live.displaced==displaced) return nullptr;
        stopLive();
        CLxLoc_RenderCacheService service;
        void* object=nullptr;
        unsigned flags=LXfRENDERCACHE_TRACK_CURRENT_SCENE;
        if(displaced) flags|=LXfRENDERCACHE_GEOCACHE_DISPLACE;
        check(service.CreateRenderCache(&object,flags),"Create live render cache");
        live.cache.take(object);
        if(!listeners) {
            listeners=new CLxPolymorph<Listener>;
            listeners->AddInterface(new CLxIfc_RenderCacheListener<Listener>);
        }
        live.listening=listeners->Spawn();
        live.listener=LXCWxOBJ(live.listening,Listener);
        CLxUser_ListenerPort port(live.cache);
        if(!port.test() || LXx_FAIL(port.AddListener(live.listening))) throw std::runtime_error("Listen to live render cache");
        live.displaced=displaced;
        return nullptr;
    } catch(const std::exception& failure) {error=failure.what();}
      catch(...) {error="Unknown live render cache error";}
    stopLive();
    return error.c_str();
}

extern "C" __declspec(dllexport) void MR_geometry_live_stop() {stopLive();}

// What the live cache changed since this was last asked, by item: {"live":1,"updating":0,"lost":0,"shaped":[...],
// "placed":[...],"shaded":[...],"added":[...],"removed":[...]}; {"live":0} where there is none. Asking clears them.
extern "C" __declspec(dllexport) const char* MR_geometry_live_changes() {
    static thread_local std::string result;
    std::ostringstream out;
    if(!live.listener || !live.cache.test()) out<<"{\"live\":0}";
    else {
        Listener& heard=*live.listener;
        out<<"{\"live\":1,\"updating\":"<<int(heard.updating)<<",\"lost\":"<<int(heard.destroyed||heard.cleared);
        for(auto& entry:{std::make_pair("shaped",&heard.shaped),std::make_pair("placed",&heard.placed),std::make_pair("shaded",&heard.shaded),
                         std::make_pair("added",&heard.added),std::make_pair("removed",&heard.removed)}) {
            out<<",\""<<entry.first<<"\":[";bool first=true;
            for(const auto& name:*entry.second){if(!first)out<<',';first=false;text(out,name.c_str());}
            out<<']';entry.second->clear();
        }
        out<<'}';
    }
    result=out.str();
    return result.c_str();
}

// As MR_geometry_snapshot_some, from the live cache; an error beginning "live:" where it cannot be read now.
extern "C" __declspec(dllexport) const char* MR_geometry_snapshot_live(double time,int displaced,const char* path,const char* rows,const char* only) {
    struct Live { Live(){readLive=true;} ~Live(){readLive=false;} } use;
    return MR_geometry_snapshot_some(time,displaced,path,rows,only);
}
