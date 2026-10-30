#include "native_local_tile_policy.h"
#include <deque>
#include <memory>
#include <stdexcept>
#include <iostream>
#include <vector>
struct Item { unsigned id; uint32_t tile; uint64_t queuedClaim; };
using Queue=std::deque<std::shared_ptr<Item>>;
void require(bool ok){if(!ok)throw std::runtime_error("local tile contract failed");}
Queue items(unsigned n){Queue q;for(unsigned i=0;i<n;++i)q.push_back(std::make_shared<Item>(Item{i,uint32_t(100+i),0}));return q;}
int main(){
    using xpu2tile::Policy;
    {Policy p;auto q=items(64);p.previous=0;p.scanLimit=16;require(p.choose(q)==0 && p.inspected==0);}
    {Policy p;p.neighbor=true;p.previous=0;p.scanLimit=16;auto q=items(64);q[15]->tile=1;require(p.choose(q)==15 && p.inspected==16 && q[15]->id==15);}
    {Policy p;p.neighbor=true;p.previous=0;p.scanLimit=16;auto q=items(64);q[16]->tile=1;require(p.choose(q)==0 && p.inspected==16);}
    {Policy p;p.neighbor=true;p.previous=0;p.scanLimit=0;auto q=items(64);q[16]->tile=1;require(p.choose(q)==16 && p.inspected==17);}
    {Policy p;p.neighbor=true;p.previous=0;p.scanLimit=8;auto q=items(64);q[8]->tile=1;require(p.choose(q)==0 && p.inspected==8);}
    {Policy p;p.neighbor=true;p.previous=0;p.scanLimit=16;p.claims=64;auto q=items(64);q[1]->tile=1;require(p.choose(q)==0 && p.aged==1 && p.inspected==0);}
    {Policy p;p.neighbor=true;p.previous=0;p.scanLimit=16;auto q=items(1);q[0]->tile=900;
     for(unsigned k=0;k<64;++k){q.push_back(std::make_shared<Item>(Item{k+1,0,p.claims}));auto i=p.choose(q);require(i==1);q.erase(q.begin()+i);}
     q.push_back(std::make_shared<Item>(Item{65,0,p.claims}));require(p.choose(q)==0 && p.aged==1);}
    {Policy a,b;a.neighbor=b.neighbor=true;a.scanLimit=b.scanLimit=16;a.previous=b.previous=0;auto qa=items(200),qb=items(200);std::vector<bool> seen(200,false);
     for(unsigned i=0;i<200;++i){qa[i]->tile=qb[i]->tile=i%7?i%13:xpu2tile::unknown;}
     while(!qa.empty()){auto before=a.inspected;auto i=a.choose(qa),j=b.choose(qb);require(i==j && a.inspected-before<=16);auto id=qa[i]->id;require(!seen[id]);seen[id]=true;qa.erase(qa.begin()+i);qb.erase(qb.begin()+j);}
     for(bool v:seen)require(v);require(a.claims==200 && a.claims==b.claims);}
    {uint32_t pixels[8];for(auto& v:pixels)v=xpu2tile::unknown;bool mixed=true;require(xpu2tile::tileFor(pixels,mixed)==xpu2tile::unknown && !mixed);pixels[0]=15;pixels[1]=16;require(xpu2tile::tileFor(pixels,mixed)==0 && mixed);}
    std::cout<<"passed: local bounds, cross-tile fallback, aging, exactly-once selection, repeatability and mixed-packet hints\n";
}
