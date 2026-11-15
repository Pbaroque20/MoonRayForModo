# How XPU2 and MoonLightIPR handle textures

The two GPU engines in MoonRay for Modo handle textures differently. XPU2 keeps textures exact and loads them a piece at a time, compressing only when memory runs short. MoonLightIPR always compresses and keeps whole textures on the graphics card, which suits a fast preview.

| | XPU2 | MoonLightIPR |
|---|---|---|
| **File the engine reads** | `.tx` (OpenImageIO's tiled, mipmapped format), made by `maketx` | Targa for 8-bit images, PFM for float ones, made by `oiiotool`; the session then caches its own prepared `.mlt` |
| **Smaller detail levels (mips)** | Stored in the `.tx` | Made by the session when it prepares the texture, then cached |
| **Compression** | None normally: bytes, half floats, or one channel for grey maps. BC6H (1 byte a texel) only in texture overflow | Always: BC7 for 8-bit images, BC6H for floats (Intel's ISPC compressor), about 1 byte a texel |
| **Lossy?** | No, outside overflow | Yes, slightly (BC7 and BC6H) |
| **Loading** | Finest level read tile by tile when first sampled, on the processor; tiles let go when memory runs short | Whole texture uploaded to the card at load |
| **When textures don't fit** | Texture overflow mode: fit each texture to what its meshes show on screen, then compress, then halve | Keeps the largest textures in the computer's memory, outside the card |
| **Realtime size cap** | 1024 a side on the card, normal maps included | 1024 a side |
| **Render size** | Full size | Full size (Render and Render Animation) |
| **MoonShine graph bakes** | Not baked: graphs run natively as MoonRay maps | Baked to images: 512 or 2048 in realtime, the image's own size up to 8192 for a final Render |
| **Shader Tree procedural layers** | Through the object, the native `ModoProceduralMap`; flat projections use the C++ 2D bake | The same C++ bake for flat projections (512 in realtime, 2048 for a Render); the native map through the object |
| **Layered environments** | Composed natively, 2048 × 1024 | Composed natively, 1024 × 512 in realtime, 2048 × 1024 for a Render |
| **Texture conversion** | Side by side, up to 8 converters | Side by side, up to 8 converters |
| **Animations** | Overflow fitting sized over the whole shot, so no popping | No overflow fitting, so nothing to pop |

## Coming next

XPU2 will load only the texture tiles and detail levels a frame actually samples onto the graphics card, so texture overflow mode becomes rare. Realtime keeps its 1024 cap.
