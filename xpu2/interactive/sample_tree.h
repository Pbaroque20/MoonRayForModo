// Private bounded CPU sample-tree/film adapter. No CUDA transport yet.
#pragma once
#include "path_stage.h"
#include <array>
#include <vector>
#include <mutex>
#include <cmath>
#include <stdexcept>
namespace xpu2 { namespace interactive { namespace film {
using sample::U32;using sample::U64;
struct Handle {path::Epoch epoch;U64 generation;U32 root,node;};
struct Pixel {double sum[4]={};U64 count=0;};
struct Audit {U64 started,completed,active,invalidated;};
enum class Status {Ok,Stale,Replay,Capacity,Invalid};
class Tree {
    static constexpr U32 Nodes=64;
    struct Node {U64 branch=0;bool live=false;};
    struct Root {sample::Identity id{};U64 generation=0;U32 used=0,pending=0;
        double sum[4]={};std::array<Node,Nodes> nodes{};bool live=false;};
    mutable std::mutex mutex_;path::Epoch epoch_;std::vector<Root> roots_;
    std::vector<Pixel> pixels_;std::vector<U64> next_;U64 started_=0,completed_=0,invalidated_=0;
    static U32 bounded(U32 value,U32 maximum){if(!value||value>maximum)throw std::invalid_argument("Film budget");return value;}
public:
    Tree(path::Epoch epoch,U32 pixels,U32 capacity):epoch_(epoch),roots_(bounded(capacity,65536)),pixels_(bounded(pixels,16*1024*1024)),next_(pixels){
        if(!pixels||pixels>16*1024*1024||!capacity||capacity>65536)throw std::invalid_argument("Film budget");
    }
    Status begin(U32 pixel,U64 stream,Handle& out,sample::Identity& id){
        std::lock_guard<std::mutex> lock(mutex_);
        if(pixel>=pixels_.size()||next_[pixel]==~U64(0)||started_==~U64(0))return Status::Invalid;
        for(U32 i=0;i<roots_.size();++i){auto& r=roots_[i];if(r.live||r.generation==~U64(0))continue;
            U64 g=r.generation+1;r=Root{};r.generation=g;r.live=true;r.pending=1;r.used=1;
            r.id={pixel,next_[pixel]++,stream,0};r.nodes[0]={0,true};++started_;
            out={epoch_,g,i,0};id=r.id;return Status::Ok;
        }
        return Status::Capacity; // An unstarted sample consumes no index or count.
    }
    // Effects become visible only after all child slots and numeric inputs pass.
    // A failed commit leaves the original path live; caller must retry/fallback.
    Status finish(Handle h,const path::Effects& e,std::array<Handle,15>& children){
        std::lock_guard<std::mutex> lock(mutex_);
        if(!path::equal(h.epoch,epoch_))return Status::Stale;
        if(h.root>=roots_.size()||h.node>=Nodes)return Status::Invalid;
        auto& r=roots_[h.root];if(h.generation!=r.generation||!r.live||h.node>=r.used||!r.nodes[h.node].live)return Status::Replay;
        if(e.valueCount>16||e.childCount>15)return Status::Invalid;
        if(r.used+e.childCount>Nodes)return Status::Capacity;
        double sum[4];for(int c=0;c<4;++c)sum[c]=r.sum[c];
        for(U32 i=0;i<e.valueCount;++i){if(e.values[i].aov!=0)return Status::Invalid;
            for(int c=0;c<4;++c){if(!std::isfinite(e.values[i].rgba[c]))return Status::Invalid;
                sum[c]+=e.values[i].rgba[c];if(!std::isfinite(sum[c]))return Status::Invalid;}}
        for(U32 i=0;i<e.childCount;++i){auto id=e.children[i].id;
            if(id.pixel!=r.id.pixel||id.index!=r.id.index||id.stream!=r.id.stream||id.branch==0)return Status::Invalid;
            U64 parent=(id.branch-1)/16;if(parent!=r.nodes[h.node].branch)return Status::Invalid;
            // Branch slot 15 is reserved; sample::child exposes only 0..14.
            if(id.branch%16==0)return Status::Invalid;
            for(U32 j=0;j<r.used;++j)if(r.nodes[j].branch==id.branch)return Status::Invalid;
            for(U32 j=0;j<i;++j)if(e.children[j].id.branch==id.branch)return Status::Invalid;
        }
        bool done=(r.pending+e.childCount==1);
        auto& pixel=pixels_[r.id.pixel];double final[4];
        if(done){if(pixel.count==~U64(0))return Status::Invalid;
            for(int c=0;c<4;++c){final[c]=pixel.sum[c]+sum[c];if(!std::isfinite(final[c]))return Status::Invalid;}}
        for(int c=0;c<4;++c)r.sum[c]=sum[c];
        r.nodes[h.node].live=false;
        for(U32 i=0;i<e.childCount;++i){U32 node=r.used++;r.nodes[node]={e.children[i].id.branch,true};children[i]={epoch_,r.generation,h.root,node};}
        r.pending=r.pending-1+e.childCount;
        if(done){for(int c=0;c<4;++c)pixel.sum[c]=final[c];++pixel.count;++completed_;r.live=false;}
        return Status::Ok;
    }
    // Cancelling means invalidating the WHOLE epoch, including completed pixels.
    // No individual slow/shadow/texture path can be selectively discarded.
    bool invalidate(path::Epoch next){
        std::lock_guard<std::mutex> lock(mutex_);if(path::equal(next,epoch_))return false;
        invalidated_+=started_;started_=completed_=0;epoch_=next;
        for(auto& r:roots_)r.live=false;
        for(auto& p:pixels_)p=Pixel{};for(auto& n:next_)n=0;return true;
    }
    Audit audit()const{std::lock_guard<std::mutex> lock(mutex_);U64 live=0;for(auto& r:roots_)live+=r.live;return {started_,completed_,live,invalidated_};}
    std::vector<Pixel> snapshot()const{std::lock_guard<std::mutex> lock(mutex_);return pixels_;}
};
}}}
