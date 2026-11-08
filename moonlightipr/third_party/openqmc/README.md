# OpenQMC (vendored)

The headers MoonLightIPR's kernel needs for OpenQMC's Owen-scrambled Sobol sampler
(`oqmc/sobol.h` and what it includes), unchanged, from OpenQMC v0.7.1
(https://github.com/AcademySoftwareFoundation/openqmc, commit 72617f52751d53a4ca49f60fd0cb4f5946236f2f).

OpenQMC is released under the Apache License 2.0 (`LICENSE`), with NVIDIA's covenant not to assert
patents (`LICENSE-NVIDIA`). Copyright Contributors to the OpenQMC Project.

The kernel is compiled by NVRTC, which has no standard library; `../nvrtc-std` gives these headers the
few standard headers they include. `src/device/qmc.h` is where MoonLightIPR uses them.
