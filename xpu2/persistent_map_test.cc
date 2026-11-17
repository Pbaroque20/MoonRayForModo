#include "persistent_map.h"
#include <map>
#include <random>
#include <iostream>
#include <thread>
#include <atomic>
#include <cmath>
using xpu2::indexed::PersistentMap;
static void check(bool ok){if(!ok)throw std::runtime_error("Persistent-map contract failed");}
int main(){try{
    PersistentMap<int,int> map;std::map<int,int> reference;
    std::mt19937 rng(12345);unsigned checks=0;
    for(unsigned i=0;i<30000;++i){
        int key=int(rng()%1000),value=int(rng());auto old=map;auto oldReference=reference;
        if(rng()%3){map.set(key,value);reference[key]=value;}
        else check(map.erase(key)==reference.erase(key));
        if(i%37==0){
            auto a=map.begin();auto b=reference.begin();
            for(;b!=reference.end();++a,++b){check(a!=map.end()&&a->first==b->first&&a->second==b->second);++checks;}
            check(a==map.end()&&map.size()==reference.size());
            auto c=old.begin();for(const auto& pair:oldReference){check(c->first==pair.first&&c->second==pair.second);++c;}
            check(c==old.end());
            check(map.height()<=int(2*std::log2(map.size()+1)+1));
        }
        auto found=map.find(key);auto wanted=reference.find(key);
        check((found==map.end())==(wanted==reference.end()));
        if(wanted!=reference.end()){
            check(map.at(key)==wanted->second);auto suffix=wanted;
            for(int n=0;n<3&&suffix!=reference.end();++n,++suffix,++found)check(found->first==suffix->first&&found->second==suffix->second);
            if(suffix==reference.end())check(found==map.end());
        }
    }
    for(int i=0;i<100000;++i)map.set(i,i);
    check(map.size()==100000&&map.height()<30);
    auto snapshot=map;std::atomic<unsigned> reads{0};
    std::thread reader([snapshot,&reads]{for(int i=0;i<100000;++i)if(snapshot.at(i)==i)++reads;});
    for(int i=0;i<100000;++i)map.erase(i);
    reader.join();check(map.empty()&&reads==100000&&snapshot.size()==100000);
    bool rejected=false;try{map.at(1);}catch(const std::out_of_range&){rejected=true;}check(rejected);
    // A map made at once from sorted keys (assignSorted, a scene's first index): the same entries, balanced, and edited
    // as any other afterwards; unsorted or repeated keys, or a map not empty, refused.
    {
        std::vector<std::pair<int,int>> items;std::map<int,int> sorted;
        for(int i=0;i<50000;++i){items.emplace_back(i*3,i);sorted[i*3]=i;}
        PersistentMap<int,int> bulk;bulk.assignSorted(std::move(items));
        check(bulk.size()==sorted.size()&&bulk.height()<=int(std::log2(sorted.size()))+1);
        auto a=bulk.begin();for(const auto& p:sorted){check(a!=bulk.end()&&a->first==p.first&&a->second==p.second);++a;++checks;}check(a==bulk.end());
        for(unsigned i=0;i<20000;++i){
            int key=int(rng()%160000),value=int(rng());
            if(rng()%3){bulk.set(key,value);sorted[key]=value;}else check(bulk.erase(key)==sorted.erase(key));
        }
        auto b=bulk.begin();for(const auto& p:sorted){check(b!=bulk.end()&&b->first==p.first&&b->second==p.second);++b;}check(b==bulk.end());
        check(bulk.size()==sorted.size()&&bulk.height()<=int(2*std::log2(bulk.size()+1)+1));
        bool refused=false;try{bulk.assignSorted({{1,1}});}catch(const std::logic_error&){refused=true;}check(refused);
        PersistentMap<int,int> other;refused=false;try{other.assignSorted({{2,0},{1,0}});}catch(const std::invalid_argument&){refused=true;}check(refused&&other.empty());
        refused=false;try{other.assignSorted({{1,0},{1,0}});}catch(const std::invalid_argument&){refused=true;}check(refused&&other.empty());
    }
    std::cout<<"{\"passed\":true,\"random_operations\":30000,\"checked_entries\":"<<checks<<",\"retained_reader_entries\":"<<reads<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
