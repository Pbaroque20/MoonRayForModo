#include "shadow_request.h"
#include <limits>
#include <cstring>
#include <iostream>
#include <stdexcept>
void check(bool value) {if(!value) throw std::runtime_error("shadow contract failed");}
int main() {
    xpu2::ShadowRequest q{};q.scene=3;q.revision=2;q.request=1;q.mask=4;
    q.receiver=-7;q.direction[2]=1;q.farT=100;q.time=.25f;
    xpu2::ShadowBindings bindings(3,2,{123,456});uint64_t light=999;
    check(bindings.resolve(q,light)&&light==123);
    auto copied=q;q.origin[0]=8;check(copied.origin[0]==0);
    copied.light=1;check(bindings.resolve(copied,light)&&light==456);
    copied.light=2;check(!bindings.resolve(copied,light)&&light==0);
    copied=q;copied.revision++;check(!bindings.resolve(copied,light));
    copied=q;copied.scene++;check(!bindings.resolve(copied,light));
    copied=q;copied.request=0;check(!bindings.resolve(copied,light));
    copied=q;copied.nearT=-1;check(!bindings.resolve(copied,light));
    copied=q;copied.nearT=101;check(!bindings.resolve(copied,light));
    copied=q;copied.time=std::numeric_limits<float>::quiet_NaN();check(!bindings.resolve(copied,light));
    copied=q;copied.origin[1]=std::numeric_limits<float>::infinity();check(!bindings.resolve(copied,light));
    copied=q;copied.direction[2]=0;check(!bindings.resolve(copied,light));
    copied=q;copied.direction[0]=std::numeric_limits<float>::quiet_NaN();check(!bindings.resolve(copied,light));
    copied=q;copied.mask=0;check(!bindings.resolve(copied,light));
    xpu2::ShadowBindings missing(3,2,{0});check(!missing.resolve(q,light));
    copied=q;copied.origin[0]=-0.f;copied.farT=std::numeric_limits<float>::max();
    check(bindings.resolve(copied,light));auto bytes=copied;
    check(std::memcmp(&bytes,&copied,sizeof(copied))==0);
    // Bindings copy their input table; later caller mutation cannot rebind work.
    std::vector<uint64_t> ids{789};xpu2::ShadowBindings snapshot(3,2,ids);ids[0]=0;
    check(snapshot.resolve(q,light)&&light==789);
    std::cout<<"shadow request contract passed\n";
}
