"""Let a render be asked to finish with what it has in hand: the tiles its workers are on are rendered to the end,
the light of their samples is let come in, and the frame ends there as a finished one.

MoonRay can be stopped at once, which leaves the samples then in flight unpaid (dark and coarse pixels where the
hard tiles were), or at the end of a pass, which may be most of the render away. This is between the two: the workers
take no new tiles, and what follows is what follows any pass, queues drained and all. Used when a render is stopped
by hand, or by Smart Render, and its picture is to be kept."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RNDR = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering/rndr'

EDITS = {
    'RenderDriver.h': [
        ("    void requestStopAtPassBoundary() { mRenderStopAtPassBoundary = true; } // called by progmcrt_computation\n",
         "    void requestStopAtPassBoundary() { mRenderStopAtPassBoundary = true; } // called by progmcrt_computation\n"
         "    // Modo: finish the tiles in hand, let their light come in, and end the frame there as a finished one.\n"
         "    void requestDrain() { mModoDrain = true; }\n"
         "    bool isDraining() const { return mModoDrain; }\n"),
        ("    bool mRenderStopAtPassBoundary;\n",
         "    bool mRenderStopAtPassBoundary;\n"
         "    // Modo: the workers take no more tiles, and the pass they are in is the frame's last.\n"
         "    std::atomic<bool> mModoDrain {false};\n"),
    ],
    'RenderDriver.cc': [
        ("    mStopAtFrameReadyForDisplay = false;\n    mRenderStopAtPassBoundary = false;\n",
         "    mStopAtFrameReadyForDisplay = false;\n    mRenderStopAtPassBoundary = false;\n    mModoDrain = false;\n"),
    ],
    'RenderFramePasses.cc': [
        ("    if (driver->mRenderStopAtPassBoundary) {\n        return RenderPassesResult::STOP_AT_PASS_BOUNDARY; // render completed at pass boundary\n    }\n",
         "    if (driver->mRenderStopAtPassBoundary || driver->isDraining()) {\n        return RenderPassesResult::STOP_AT_PASS_BOUNDARY; // render completed at pass boundary\n    }\n"),
        ("            while (!tls->isCanceled() && workQueue->getNextTileGroup(threadIdx, &group, driver->getLastCoarsePassIdx())) {\n",
         "            // Modo: asked to finish with what is in hand, a worker takes no more tiles; its queues are drained below\n"
         "            // as at the end of any pass.\n"
         "            while (!tls->isCanceled() && !driver->isDraining() &&\n"
         "                   workQueue->getNextTileGroup(threadIdx, &group, driver->getLastCoarsePassIdx())) {\n"),
        ("    if (stopAtPassBoundary) return RenderPassesResult::STOP_AT_PASS_BOUNDARY;\n    if (canceled) return RenderPassesResult::ERROR_OR_CANCEL;\n",
         "    if (stopAtPassBoundary) return RenderPassesResult::STOP_AT_PASS_BOUNDARY;\n    if (canceled) return RenderPassesResult::ERROR_OR_CANCEL;\n"
         "    if (driver->isDraining()) return RenderPassesResult::STOP_AT_PASS_BOUNDARY; // Modo: the frame ends here\n"),
    ],
    'RenderContext.h': [
        ("    void requestStopRenderAtPassBoundary();\n",
         "    void requestStopRenderAtPassBoundary();\n\n"
         "    /**\n"
         "     * Modo: finish the tiles the workers are on, let the light of their samples come in, and end the frame\n"
         "     * there as a finished one.\n"
         "     */\n"
         "    void requestDrain();\n"),
    ],
    'RenderContext.cc': [
        ("RenderContext::requestStopRenderAtPassBoundary()\n{\n    if (mRendering && !isFrameComplete()) {\n        mDriver->requestStopAtPassBoundary();\n    }\n}\n",
         "RenderContext::requestStopRenderAtPassBoundary()\n{\n    if (mRendering && !isFrameComplete()) {\n        mDriver->requestStopAtPassBoundary();\n    }\n}\n\n"
         "void\nRenderContext::requestDrain()\n{\n    if (mRendering && !isFrameComplete()) {\n        mDriver->requestDrain();\n    }\n}\n"),
    ],
}


def patch_text(name, text):
    for old, new in EDITS[name]:
        if new in text:
            continue
        if text.count(old) != 1:
            raise RuntimeError('Drain patch anchor missing or ambiguous in %s: %r' % (name, old[:60]))
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
