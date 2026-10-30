// SDK lifecycle only. Geometry exports live in render_cache.cpp.
// Deliberately registers no ExternalRender server and starts no PView worker.
#include <lx_plugin.hpp>
extern "C" void MR_geometry_live_stop();
void initialize() {}
// The live render cache let go before Modo's services are (render_cache.cpp).
void cleanup() {MR_geometry_live_stop();}
