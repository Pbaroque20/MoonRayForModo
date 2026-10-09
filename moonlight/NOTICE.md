# MoonLight

MoonLight is a GPU preview renderer created by Raphael Tobar for MoonRay for Modo.

- **Licence.** MoonLight is released under the MIT License; see [LICENSE](LICENSE).
  Copyright (c) 2026 Raphael Tobar.
- **Not affiliated with DreamWorks.** MoonLight is not a DreamWorks Animation product. It is not
  part of MoonRay or OpenMoonRay, and is not affiliated with, sponsored by or endorsed by
  DreamWorks Animation LLC. "MoonRay" and "DreamWorks" are trademarks of their owners and are
  used here only to say what MoonLight previews.
- **What it is to MoonRay.** MoonLight is a separate program with its own path tracer. It reads
  the scene the plugin prepares for MoonRay and aims to look like MoonRay's render of it, so that
  a preview can be trusted; final frames come from MoonRay. MoonRay itself is distributed by
  DreamWorks Animation under the Apache License 2.0, and that licence and its notices continue to
  apply to MoonRay.
- **What it is built on.** MoonLight runs on NVIDIA OptiX and CUDA, which remain under NVIDIA's
  own licences; their notices are installed beside MoonLight in `licenses/`.
