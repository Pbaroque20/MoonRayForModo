// Coordinator-only admission for retained immutable index versions. Shared
// buffers count once; these bytes exclude native scene objects and map metadata.
#pragma once
#include "../indexed_scene.h"
namespace xpu2::interactive {
struct RetainedLimits { size_t versions=8,bytes=size_t(8)*1024*1024*1024; };
struct RetainedUsage { size_t versions=0,bytes=0,buffers=0; };
class SnapshotBudget {
    RetainedLimits limits_;
    std::vector<std::weak_ptr<const indexed::Snapshot>> retained_;
    const std::thread::id thread_=std::this_thread::get_id();
    void thread() const {if(thread_!=std::this_thread::get_id())throw std::logic_error("Foreign budget coordinator");}
    std::vector<indexed::View> live(){
        thread();std::vector<indexed::View> views;
        auto out=retained_.begin();
        for(auto i=retained_.begin();i!=retained_.end();++i)if(auto view=i->lock()){
            views.push_back(std::move(view));*out++=*i;
        }
        retained_.erase(out,retained_.end());return views;
    }
    RetainedUsage measure(const std::vector<indexed::View>& views) const {
        RetainedUsage usage{views.size(),0,0};
        if(usage.versions>limits_.versions)throw std::length_error("Retained scene version budget exceeded");
        std::set<const indexed::Buffer*> buffers;
        for(const auto& view:views)for(const auto& item:view->entities)for(const auto& field:item.second->buffers){
            const auto& buffer=*field.second;
            if(!buffers.insert(&buffer).second)continue;
            for(auto bytes:{buffer.source.size(),buffer.prepared.size()}){
                if(bytes>limits_.bytes-usage.bytes)throw std::length_error("Retained scene byte budget exceeded");
                usage.bytes+=bytes;
            }
            ++usage.buffers;
        }
        return usage;
    }
public:
    explicit SnapshotBudget(RetainedLimits limits={}):limits_(limits){
        if(!limits.versions||!limits.bytes)throw std::invalid_argument("Empty retained-scene budget");
    }
    SnapshotBudget(const SnapshotBudget&)=delete;
    SnapshotBudget& operator=(const SnapshotBudget&)=delete;
    RetainedUsage usage(){return measure(live());}
    RetainedUsage admit(const indexed::View& view){
        if(!view)throw std::invalid_argument("Missing candidate snapshot");
        auto views=live();
        if(std::find(views.begin(),views.end(),view)!=views.end())return measure(views);
        views.push_back(view);auto usage=measure(views);retained_.push_back(view);return usage;
    }
};
}
