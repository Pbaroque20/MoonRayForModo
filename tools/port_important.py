"""Let a render take the tiles with the most in them first.

MoonRay renders each pass's tiles in one fixed order (a spiral, say), whatever is in them. Asked to, the first coarse
passes over the whole picture are also its analysis: at the start of each fine pass every tile is scored by how much
its pixels differ from their neighbours (edges, texture, noise), and the tiles scoring above the average are rendered
first, in the order chosen among themselves, then the rest in that order too. Every pass still renders every tile
once, so nothing else of the render changes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RNDR = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering/rndr'

EDITS = {
    'RenderDriver.h': [
        ("    bool isDraining() const { return mModoDrain; }\n",
         "    bool isDraining() const { return mModoDrain; }\n"
         "    // Modo: in each fine pass, the tiles with the most in them are rendered first.\n"
         "    void setModoImportant(bool on) { mModoImportant = on; }\n"
         "    // The tile a pass renders in a place of its order.\n"
         "    unsigned modoTileOf(unsigned passIdx, unsigned itile);\n"),
        ("    std::atomic<bool> mModoDrain {false};\n",
         "    std::atomic<bool> mModoDrain {false};\n"
         "    // Modo: important tiles first. An order for each fine pass, made when the pass is first asked for a tile.\n"
         "    std::atomic<bool> mModoImportant {false};\n"
         "    std::mutex mModoOrderMutex;\n"
         "    std::vector<std::vector<uint32_t>> mModoOrder;\n"),
    ],
    'RenderDriver.cc': [
        ("    mRenderStopAtPassBoundary = false;\n    mModoDrain = false;\n",
         "    mRenderStopAtPassBoundary = false;\n    mModoDrain = false;\n"
         "    {\n        std::lock_guard<std::mutex> modoLock(mModoOrderMutex);\n        mModoOrder.clear();\n    }\n"),
    ],
    'RenderFramePasses.cc': [
        ("        params.mTileIdx = itile;\n        if (!renderTile(driver, tls, group, params, deepBuffer, cryptomatteBuffer, processedSampleTotal)) {\n",
         "        params.mTileIdx = driver->modoTileOf(group.mPassIdx, itile);\n"
         "        if (!renderTile(driver, tls, group, params, deepBuffer, cryptomatteBuffer, processedSampleTotal)) {\n"),
        ("// static function\nbool\nRenderDriver::renderTile(RenderDriver *driver,\n",
         "// Modo: the tile a pass renders in a place of its order. As MoonRay has it, the tile in that place; with the\n"
         "// important ones first, the tiles whose pixels differ most from their neighbours come before the others, each\n"
         "// lot in the order it was in. A pass keeps the order it was first given, so it renders every tile once.\n"
         "unsigned\n"
         "RenderDriver::modoTileOf(unsigned passIdx, unsigned itile)\n"
         "{\n"
         "    if (!mModoImportant || passIdx >= mTileWorkQueue.getNumPasses() ||\n"
         "        mTileWorkQueue.getPass(passIdx).isCoarsePass()) {\n"
         "        return itile;\n"
         "    }\n"
         "    const std::vector<scene_rdl2::fb_util::Tile> *tiles = getTiles();\n"
         "    if (!tiles || !mFilm || itile >= tiles->size()) return itile;\n"
         "    std::lock_guard<std::mutex> lock(mModoOrderMutex);\n"
         "    if (mModoOrder.size() <= passIdx) mModoOrder.resize(passIdx + 1);\n"
         "    std::vector<uint32_t> &order = mModoOrder[passIdx];\n"
         "    if (order.size() != tiles->size()) {\n"
         "        const size_t count = tiles->size();\n"
         "        const scene_rdl2::fb_util::RenderBuffer &colors = mFilm->getRenderBuffer();\n"
         "        const scene_rdl2::fb_util::FloatBuffer &weights = mFilm->getWeightBuffer();\n"
         "        const scene_rdl2::fb_util::Tiler &tiler = mFilm->getTiler();\n"
         "        std::vector<float> score(count, 0.f);\n"
         "        double total = 0.0;\n"
         "        std::vector<float> above;\n"
         "        for (size_t t = 0; t < count; ++t) {\n"
         "            const scene_rdl2::fb_util::Tile &tile = (*tiles)[t];\n"
         "            const unsigned wide = tile.mMaxX - tile.mMinX;\n"
         "            above.assign(wide, 0.f);\n"
         "            double sum = 0.0;\n"
         "            unsigned pixels = 0;\n"
         "            for (unsigned y = tile.mMinY; y < tile.mMaxY; ++y) {\n"
         "                float left = 0.f;\n"
         "                for (unsigned x = tile.mMinX; x < tile.mMaxX; ++x) {\n"
         "                    unsigned tx, ty;\n"
         "                    tiler.linearToTiledCoords(x, y, &tx, &ty);\n"
         "                    const float weight = weights.getPixel(tx, ty);\n"
         "                    const scene_rdl2::fb_util::RenderColor &c = colors.getPixel(tx, ty);\n"
         "                    float light = weight > 0.f ? (0.2126f * c.x + 0.7152f * c.y + 0.0722f * c.z) / weight : 0.f;\n"
         "                    // Bright and dark are weighed alike: a lamp is no more important than a face.\n"
         "                    light = std::isfinite(light) && light > 0.f ? light / (1.f + light) : 0.f;\n"
         "                    if (x > tile.mMinX) sum += std::fabs(light - left);\n"
         "                    if (y > tile.mMinY) sum += std::fabs(light - above[x - tile.mMinX]);\n"
         "                    left = light;\n"
         "                    above[x - tile.mMinX] = light;\n"
         "                    ++pixels;\n"
         "                }\n"
         "            }\n"
         "            score[t] = pixels ? float(sum / pixels) : 0.f;\n"
         "            total += score[t];\n"
         "        }\n"
         "        const float average = count ? float(total / count) : 0.f;\n"
         "        order.clear();\n"
         "        order.reserve(count);\n"
         "        for (size_t t = 0; t < count; ++t) if (score[t] > average) order.push_back(uint32_t(t));\n"
         "        for (size_t t = 0; t < count; ++t) if (!(score[t] > average)) order.push_back(uint32_t(t));\n"
         "    }\n"
         "    return order[itile];\n"
         "}\n\n"
         "// static function\nbool\nRenderDriver::renderTile(RenderDriver *driver,\n"),
    ],
}


def patch_text(name, text):
    for old, new in EDITS[name]:
        if new in text:
            continue
        if text.count(old) != 1:
            raise RuntimeError('Important-first patch anchor missing or ambiguous in %s: %r' % (name, old[:60]))
        text = text.replace(old, new, 1)
    return text


def main():
    for name in EDITS:
        source = RNDR / name
        raw = source.read_bytes()
        crlf = b'\r\n' in raw
        text = raw.decode('utf-8').replace('\r\n', '\n')
        patched = patch_text(name, text)
        if patched != text:
            source.write_bytes((patched.replace('\n', '\r\n') if crlf else patched).encode('utf-8'))
            print('patched', name)
        else:
            print('already in', name)


if __name__ == '__main__':
    main()
