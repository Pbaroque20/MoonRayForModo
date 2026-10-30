#pragma once
namespace moonray {namespace mcrt_common {class ThreadLocalState;} namespace rndr {class Film;}}
namespace xpu2::nativefilm {
void begin();
void drain(moonray::mcrt_common::ThreadLocalState*,moonray::rndr::Film*);
void finish();
}
