#pragma once
namespace moonray { namespace pbr { class TLState;struct RayState; } }
namespace xpu2::nativepath {
void begin(bool fixedSamples);
void finish();
bool defer(moonray::pbr::TLState*,unsigned,moonray::pbr::RayState**);
unsigned drain(moonray::pbr::TLState*);
bool pending(moonray::pbr::TLState*);
}
