#include <embree4/rtcore.h>
#include <algorithm>
#include <cmath>
#include <iostream>

int main() {
    RTCDevice device = rtcNewDevice("isa=avx");
    if (!device || rtcGetDeviceError(device) != RTC_ERROR_NONE) return 1;
    RTCScene scene = rtcNewScene(device);
    RTCGeometry triangle = rtcNewGeometry(device, RTC_GEOMETRY_TYPE_TRIANGLE);
    auto* vertices = static_cast<float*>(rtcSetNewGeometryBuffer(triangle,
        RTC_BUFFER_TYPE_VERTEX, 0, RTC_FORMAT_FLOAT3, 3 * sizeof(float), 3));
    auto* indices = static_cast<unsigned*>(rtcSetNewGeometryBuffer(triangle,
        RTC_BUFFER_TYPE_INDEX, 0, RTC_FORMAT_UINT3, 3 * sizeof(unsigned), 1));
    const float points[] = {-1, -1, -3, 1, -1, -3, 0, 1, -3};
    std::copy(points, points + 9, vertices);
    indices[0] = 0; indices[1] = 1; indices[2] = 2;
    rtcCommitGeometry(triangle);
    const unsigned id = rtcAttachGeometry(scene, triangle);
    rtcReleaseGeometry(triangle);
    rtcCommitScene(scene);
    RTCRayHit ray{};
    ray.ray.dir_z = -1;
    ray.ray.tfar = 10;
    ray.ray.mask = ~0U;
    ray.hit.geomID = RTC_INVALID_GEOMETRY_ID;
    RTCIntersectArguments args;
    rtcInitIntersectArguments(&args);
    rtcIntersect1(scene, &ray, &args);
    const bool passed = rtcGetDeviceError(device) == RTC_ERROR_NONE &&
        ray.hit.geomID == id && std::abs(ray.ray.tfar - 3.0f) < 0.0001f;
    rtcReleaseScene(scene);
    rtcReleaseDevice(device);
    std::cout << (passed ? "Embree AVX triangle intersection passed\n" : "Embree AVX intersection failed\n");
    return passed ? 0 : 1;
}
