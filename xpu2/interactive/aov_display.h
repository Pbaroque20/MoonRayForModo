// Display filters as MoonRay runs them (rndr/DisplayFilterDriver.cc), with MoonRay's own filters: the scene XPU2
// reads holds proxies, which carry no code, so the display filters and the render outputs they read are copied into
// a scene context of their own that loads the real filter DSOs. MoonRay's InputBuffer feeds each filter its inputs:
// the outputs' values as the output driver snapshots them (aov_write.h outputValues), in buffers the film's aligned
// size, padded with zeros, rows from the bottom, read through a window about each 8 by 8 tile (clamped at the
// buffer's edges) or whole; another display filter's output, read through its tiles (clamped at the image's edge).
// Each filter runs a row of a tile at a time, VLEN pixels across (the last repeated past the tile's edge); one with a
// missing input is the scene's fatal colour.
#pragma once
#include "aov_plan.h"
#include "aov_write.h"
#include "InputBuffer.h"     // moonray/lib/rendering/displayfilter
#include "DisplayFilter.h"   // moonray/lib/rendering/displayfilter: InitializeData, InputData, DisplayFilterStatev
#include <scene_rdl2/common/math/ispc/Typesv.h>
#include <scene_rdl2/scene/rdl2/DisplayFilter.h>
#include <scene_rdl2/scene/rdl2/SceneVariables.h>
#include <functional>
#include <map>
#include <memory>

namespace xpu2::interactive::aov {

namespace df = moonray::displayfilter;
using VariablePixelBuffer = scene_rdl2::fb_util::VariablePixelBuffer;

class DisplayFilters {
public:
    // The scene's display filters and what they read, copied from the proxies into a context of real DSOs.
    void prepare(const rdl::SceneContext& proxy, const Plan& plan, const std::string& dsoPath, U32 width, U32 height) {
        width_ = width;
        height_ = height;
        alignedWidth_ = (width + 7) & ~7u;
        alignedHeight_ = (height + 7) & ~7u;
        real_ = std::make_unique<rdl::SceneContext>();
        real_->setDsoPath(dsoPath);
        real_->setProxyModeEnabled(false);
        copies_.clear();
        // The scene variables the filters may read (the fatal colour, the image size).
        {
            rdl::SceneVariables& sv = real_->getSceneVariables();
            sv.beginUpdate();
            copyAttributes(proxy.getSceneVariables(), sv);
            sv.endUpdate();
        }
        outputs_.clear();
        for (const Output* out : plan.all) {
            if (out->result != ResultDisplayFilter) continue;
            rdl::SceneObject* ro = copy(*out->ro);
            outputs_.push_back(ro);
        }
        for (rdl::SceneObject* ro : outputs_) ro->applyUpdates();
        buildDag(plan);
    }
    bool empty() const { return dag_.empty(); }

    // After a frame: each display filter output's pixels (three floats a pixel, the film's rows from the bottom), in
    // the plan's order of display filter outputs.
    void run(const Plan& plan, const async::RenderResult& r, std::vector<std::vector<float>>& results) {
        const scene_rdl2::math::Color fatal = real_->getSceneVariables().get(rdl::SceneVariables::sFatalColor);
        // The AOV nodes' buffers: the outputs' values as snapshots resolve them.
        std::vector<float> v(64);
        for (Node& n : dag_) {
            if (n.type != NodeAov) continue;
            const U32 channels = U32(n.output->channels.size());
            if (v.size() < channels) v.resize(channels);
            uint8_t* data = n.buffer->getData();
            const size_t pixelBytes = n.buffer->getSizeOfPixel();
            std::fill(data, data + size_t(alignedWidth_) * alignedHeight_ * pixelBytes, uint8_t(0));
            for (U32 y = 0; y < height_; ++y)
                for (U32 x = 0; x < width_; ++x) {
                    outputValues(plan, *n.output, r, size_t(y) * width_ + x, v.data());
                    // A visibility AOV is read as its ratio (snapshotVisibilityBuffer), the third of a resumable one's.
                    const float* src = n.output->result == ResultVisibilityAov && plan.resumable ? v.data() + 2 : v.data();
                    std::memcpy(data + (size_t(y) * alignedWidth_ + x) * pixelBytes, src, pixelBytes);
                }
        }
        // The display filters, each after the filters it reads (prepareFatalBuffers: one with a missing input is the
        // fatal colour throughout).
        for (int i : order_) {
            Node& n = dag_[size_t(i)];
            auto& buf = n.buffer->getFloat3Buffer();
            if (n.bad) {
                buf.clear(scene_rdl2::math::Vec3f(fatal.r, fatal.g, fatal.b));
                continue;
            }
            buf.clear(scene_rdl2::math::Vec3f(0.0f));
            for (U32 ty = 0; ty < alignedHeight_ / 8; ++ty)
                for (U32 tx = 0; tx < alignedWidth_ / 8; ++tx) runTile(n, tx, ty);
        }
        results.clear();
        for (rdl::SceneObject* ro : outputs_) {
            const Node* n = nullptr;
            const rdl::SceneObject* f = ro->get<rdl::SceneObject*>("display_filter");
            for (const Node& m : dag_)
                if (m.type == NodeFilter && m.filter == f) n = &m;
            std::vector<float> px(size_t(width_) * height_ * 3, 0.0f);
            if (n)
                for (U32 y = 0; y < height_; ++y)
                    for (U32 x = 0; x < width_; ++x) {
                        const auto& p = n->buffer->getFloat3Buffer().getPixel(x, y);
                        float* d = px.data() + (size_t(y) * width_ + x) * 3;
                        d[0] = p.x;
                        d[1] = p.y;
                        d[2] = p.z;
                    }
            results.push_back(std::move(px));
        }
    }

private:
    enum NodeType { NodeFilter, NodeAov };
    struct Node {
        NodeType type;
        const rdl::DisplayFilter* filter = nullptr;  // a filter node's filter
        const Output* output = nullptr;              // an AOV node's output
        std::shared_ptr<VariablePixelBuffer> buffer;
        std::vector<int> children;                   // a filter's inputs' nodes (-1: missing)
        std::vector<int> windows;                    // their window widths
        std::vector<std::unique_ptr<df::InputBuffer>> inputs;
        bool bad = false;                            // an input is missing: the fatal colour
    };

    // A proxy object's copy in the real context (display filters, render outputs; other references are left empty).
    rdl::SceneObject* copy(const rdl::SceneObject& o) {
        auto it = copies_.find(o.getName());
        if (it != copies_.end()) return it->second;
        rdl::SceneObject* c = real_->createSceneObject(o.getSceneClass().getName(), o.getName());
        copies_[o.getName()] = c;
        c->beginUpdate();
        copyAttributes(o, *c);
        c->endUpdate();
        return c;
    }
    rdl::SceneObject* reference(const rdl::SceneObject* o) {
        if (!o) return nullptr;
        if (o->isA<rdl::DisplayFilter>() || o->isA<rdl::RenderOutput>()) return copy(*o);
        return nullptr;
    }
    // The copy's attribute of the name (SceneClass's lookups are not const).
    static const rdl::Attribute& attributeOf(rdl::SceneObject& o, const std::string& name) {
        return *const_cast<rdl::SceneClass&>(o.getSceneClass()).getAttribute(name);
    }
    template <class T>
    static void set(const rdl::SceneObject& from, rdl::SceneObject& to, const rdl::Attribute& a) {
        to.set(rdl::AttributeKey<T>(attributeOf(to, a.getName())), from.get(rdl::AttributeKey<T>(a)));
    }
    void copyAttributes(const rdl::SceneObject& from, rdl::SceneObject& to) {
        for (auto i = from.getSceneClass().beginAttributes(); i != from.getSceneClass().endAttributes(); ++i) {
            const rdl::Attribute& a = **i;
            if (!const_cast<rdl::SceneClass&>(to.getSceneClass()).hasAttribute(a.getName())) continue;
            switch (a.getType()) {
            case rdl::TYPE_BOOL: set<rdl::Bool>(from, to, a); break;
            case rdl::TYPE_INT: set<rdl::Int>(from, to, a); break;
            case rdl::TYPE_LONG: set<rdl::Long>(from, to, a); break;
            case rdl::TYPE_FLOAT: set<rdl::Float>(from, to, a); break;
            case rdl::TYPE_DOUBLE: set<rdl::Double>(from, to, a); break;
            case rdl::TYPE_STRING: set<rdl::String>(from, to, a); break;
            case rdl::TYPE_RGB: set<rdl::Rgb>(from, to, a); break;
            case rdl::TYPE_RGBA: set<rdl::Rgba>(from, to, a); break;
            case rdl::TYPE_VEC2F: set<rdl::Vec2f>(from, to, a); break;
            case rdl::TYPE_VEC2D: set<rdl::Vec2d>(from, to, a); break;
            case rdl::TYPE_VEC3F: set<rdl::Vec3f>(from, to, a); break;
            case rdl::TYPE_VEC3D: set<rdl::Vec3d>(from, to, a); break;
            case rdl::TYPE_VEC4F: set<rdl::Vec4f>(from, to, a); break;
            case rdl::TYPE_VEC4D: set<rdl::Vec4d>(from, to, a); break;
            case rdl::TYPE_MAT4F: set<rdl::Mat4f>(from, to, a); break;
            case rdl::TYPE_MAT4D: set<rdl::Mat4d>(from, to, a); break;
            case rdl::TYPE_BOOL_VECTOR: set<rdl::BoolVector>(from, to, a); break;
            case rdl::TYPE_INT_VECTOR: set<rdl::IntVector>(from, to, a); break;
            case rdl::TYPE_LONG_VECTOR: set<rdl::LongVector>(from, to, a); break;
            case rdl::TYPE_FLOAT_VECTOR: set<rdl::FloatVector>(from, to, a); break;
            case rdl::TYPE_DOUBLE_VECTOR: set<rdl::DoubleVector>(from, to, a); break;
            case rdl::TYPE_STRING_VECTOR: set<rdl::StringVector>(from, to, a); break;
            case rdl::TYPE_RGB_VECTOR: set<rdl::RgbVector>(from, to, a); break;
            case rdl::TYPE_RGBA_VECTOR: set<rdl::RgbaVector>(from, to, a); break;
            case rdl::TYPE_VEC2F_VECTOR: set<rdl::Vec2fVector>(from, to, a); break;
            case rdl::TYPE_VEC2D_VECTOR: set<rdl::Vec2dVector>(from, to, a); break;
            case rdl::TYPE_VEC3F_VECTOR: set<rdl::Vec3fVector>(from, to, a); break;
            case rdl::TYPE_VEC3D_VECTOR: set<rdl::Vec3dVector>(from, to, a); break;
            case rdl::TYPE_VEC4F_VECTOR: set<rdl::Vec4fVector>(from, to, a); break;
            case rdl::TYPE_VEC4D_VECTOR: set<rdl::Vec4dVector>(from, to, a); break;
            case rdl::TYPE_MAT4F_VECTOR: set<rdl::Mat4fVector>(from, to, a); break;
            case rdl::TYPE_MAT4D_VECTOR: set<rdl::Mat4dVector>(from, to, a); break;
            case rdl::TYPE_SCENE_OBJECT: {
                rdl::SceneObject* ref = reference(from.get(rdl::AttributeKey<rdl::SceneObject*>(a)));
                to.set(rdl::AttributeKey<rdl::SceneObject*>(attributeOf(to, a.getName())), ref);
                break;
            }
            case rdl::TYPE_SCENE_OBJECT_VECTOR: {
                rdl::SceneObjectVector refs;
                for (const rdl::SceneObject* s : from.get(rdl::AttributeKey<rdl::SceneObjectVector>(a)))
                    if (rdl::SceneObject* ref = reference(s)) refs.push_back(ref);
                to.set(rdl::AttributeKey<rdl::SceneObjectVector>(attributeOf(to, a.getName())), refs);
                break;
            }
            default: break;  // indexables and anything else: not read by display filters
            }
        }
    }

    // DisplayFilterDriver::createDAG: the outputs' filters, the filters they read, then the AOVs they read.
    void buildDag(const Plan& plan) {
        dag_.clear();
        std::map<const rdl::SceneObject*, df::InputData> inputData;
        const df::InitializeData init(width_, height_);
        std::function<int(const rdl::DisplayFilter*)> filterNode = [&](const rdl::DisplayFilter* f) -> int {
            for (size_t i = 0; i < dag_.size(); ++i)
                if (dag_[i].type == NodeFilter && dag_[i].filter == f) return int(i);
            dag_.push_back(Node{NodeFilter, f});
            const int me = int(dag_.size() - 1);
            dag_[me].buffer = std::make_shared<VariablePixelBuffer>();
            dag_[me].buffer->init(VariablePixelBuffer::FLOAT3, alignedWidth_, alignedHeight_);
            df::InputData d;
            f->getInputData(init, d);
            for (size_t k = 0; k < d.mInputs.size(); ++k) {
                const rdl::SceneObject* in = d.mInputs[k];
                int child = -1;
                if (in && in->isA<rdl::DisplayFilter>()) {
                    child = filterNode(in->asA<rdl::DisplayFilter>());
                } else if (in && in->isA<rdl::RenderOutput>()) {
                    const rdl::RenderOutput* ro = in->asA<rdl::RenderOutput>();
                    if (ro->getResult() == rdl::RenderOutput::RESULT_DISPLAY_FILTER) {
                        if (const rdl::DisplayFilter* g = ro->getDisplayFilter()) child = filterNode(g);
                    } else {
                        child = aovNode(plan, ro->getName());
                    }
                }
                dag_[me].children.push_back(child);
                dag_[me].windows.push_back(k < d.mWindowWidths.size() ? d.mWindowWidths[k] : 0);
                if (child < 0) dag_[me].bad = true;
            }
            return me;
        };
        for (rdl::SceneObject* ro : outputs_)
            if (const rdl::SceneObject* f = ro->get<rdl::SceneObject*>("display_filter"))
                if (f->isA<rdl::DisplayFilter>()) filterNode(f->asA<rdl::DisplayFilter>());
        // The filters in an order that runs each after those it reads.
        order_.clear();
        std::vector<char> seen(dag_.size(), 0);
        std::function<void(int)> visit = [&](int i) {
            if (i < 0 || seen[size_t(i)] || dag_[size_t(i)].type != NodeFilter) return;
            seen[size_t(i)] = 1;
            for (int c : dag_[size_t(i)].children) visit(c);
            order_.push_back(i);
        };
        for (size_t i = 0; i < dag_.size(); ++i) visit(int(i));
        // The input buffers (createInputBuffers): a window rounded to whole tiles about the tile, or the whole buffer.
        for (Node& n : dag_) {
            if (n.type != NodeFilter) continue;
            for (size_t k = 0; k < n.children.size(); ++k) {
                n.inputs.emplace_back();
                if (n.children[k] < 0) continue;
                const Node& c = dag_[size_t(n.children[k])];
                auto in = std::make_unique<df::InputBuffer>();
                if (n.windows[k] == 0) {
                    in->init(c.buffer);
                    in->setStartPixel(0, 0);
                } else {
                    const int w = n.windows[k] - 1;
                    const int window = int(std::max(VLEN / 8u, 1u) + 2 * (w / 8 + (w % 8 > 0))) * 8;
                    in->init(c.buffer->getFormat(), unsigned(window), unsigned(window));
                }
                n.inputs.back() = std::move(in);
            }
        }
    }
    // An output's AOV node (createChildAovNodes): its values, one, two or three floats a pixel.
    int aovNode(const Plan& plan, const std::string& name) {
        const Output* out = nullptr;
        for (const Output* o : plan.all)
            if (o->name == name) out = o;
        if (!out || out->entry < 0 && out->result != ResultBeauty && out->result != ResultAlpha) return -1;
        for (size_t i = 0; i < dag_.size(); ++i)
            if (dag_[i].type == NodeAov && dag_[i].output == out) return int(i);
        Node n{NodeAov};
        n.output = out;
        const size_t channels = out->result == ResultVisibilityAov ? 1 : out->channels.size();
        n.buffer = std::make_shared<VariablePixelBuffer>();
        n.buffer->init(channels == 1 ? VariablePixelBuffer::FLOAT : channels == 2 ? VariablePixelBuffer::FLOAT2 : VariablePixelBuffer::FLOAT3,
                       alignedWidth_, alignedHeight_);
        dag_.push_back(std::move(n));
        return int(dag_.size() - 1);
    }

    // runDisplayFilter for one tile: its inputs gathered (grabAovInput, grabDisplayFilterInput), then filterv a row at
    // a time.
    void runTile(Node& n, U32 tx, U32 ty) {
        const U32 minX = tx * 8, minY = ty * 8, maxX = std::min(minX + 8, width_), maxY = std::min(minY + 8, height_);
        if (minX >= width_ || minY >= height_) return;
        for (size_t k = 0; k < n.children.size(); ++k) {
            df::InputBuffer* in = n.inputs[k].get();
            const Node& c = dag_[size_t(n.children[k])];
            if (in->getPixelBuffer() == c.buffer.get()) continue;  // the whole buffer
            const VariablePixelBuffer& src = *c.buffer;
            const unsigned pixelBytes = src.getSizeOfPixel();
            const int window = int(in->getWidth());
            if (c.type == NodeAov) {
                const int pad = (window - 8) / 2;
                const int x0 = int(minX) - pad, x1 = int(minX) + 8 + pad, y0 = int(minY) - pad, y1 = int(minY) + 8 + pad;
                const int W = int(src.getWidth()), H = int(src.getHeight());
                unsigned offset = 0;
                for (int iy = y0; iy < y1; ++iy) {
                    const int ry = iy < 0 ? 0 : iy >= H ? H - 1 : iy;
                    int rx = x0;
                    if (rx < 0) {
                        const uint8_t* row = src.getData() + size_t(ry) * W * pixelBytes;
                        for (int i = 0; i < -rx; ++i) in->setData(offset++, 1, row);
                        rx = 0;
                    }
                    const int length = x1 > W ? W - rx : x1 - rx;
                    in->setData(offset, unsigned(length), src.getData() + (size_t(ry) * W + rx) * pixelBytes);
                    offset += unsigned(length);
                    if (x1 > W) {
                        const uint8_t* last = src.getData() + (size_t(ry) * W + W - 1) * pixelBytes;
                        for (int i = 0; i < x1 - W; ++i) in->setData(offset++, 1, last);
                    }
                }
                in->setStartPixel(unsigned(x0), unsigned(y0));
            } else {
                const int tiles = (window - 8) / 16;  // tiles to either side
                const int tilesX = int(alignedWidth_ / 8), tilesY = int(alignedHeight_ / 8);
                const int lastX = int((width_ + 7) / 8) - 1, lastY = int((height_ + 7) / 8) - 1;
                (void)tilesX;
                (void)tilesY;
                const int width = int(src.getWidth());
                unsigned offsetY = 0;
                for (int t2 = int(ty) - tiles; t2 <= int(ty) + tiles; ++t2) {
                    const int cy = std::min(std::max(t2, 0), lastY);
                    unsigned offsetX = 0;
                    for (int t1 = int(tx) - tiles; t1 <= int(tx) + tiles; ++t1) {
                        const int cx = std::min(std::max(t1, 0), lastX);
                        const U32 px = U32(cx) * 8, tMaxX = std::min(px + 8, width_), tMinY = U32(cy) * 8, tMaxY = std::min(tMinY + 8, height_);
                        const unsigned length = tMaxX - px;
                        for (U32 py = tMinY; py < tMinY + 8; ++py) {
                            const U32 pyc = py < tMaxY ? py : tMaxY - 1;
                            const uint8_t* data = src.getData() + (size_t(pyc) * width + px) * pixelBytes;
                            unsigned offset = (offsetY + py - tMinY) * unsigned(window) + offsetX;
                            in->setData(offset, length, data);
                            if (length < 8) {
                                offset += length;
                                for (unsigned i = 0; i < 8 - length; ++i) in->setData(offset++, 1, data + length * pixelBytes);
                            }
                        }
                        offsetX += 8;
                    }
                    offsetY += 8;
                }
                in->setStartPixel(unsigned(int(minX) - 8 * tiles), unsigned(int(minY) - 8 * tiles));
            }
        }
        std::vector<const df::InputBuffer*> inputs;
        for (const auto& in : n.inputs) inputs.push_back(in.get());
        auto& out = n.buffer->getFloat3Buffer();
        const U32 columns = maxX - minX;
        for (U32 row = 0; row < maxY - minY; ++row) {
            df::DisplayFilterStatev state;
            for (U32 i = 0; i < VLEN; ++i) {
                state.mOutputPixelX[i] = i < columns ? minX + i : maxX - 1;
                state.mOutputPixelY[i] = minY + row;
                state.mImageWidth[i] = width_;
                state.mImageHeight[i] = height_;
            }
            scene_rdl2::math::Colorv result;
            std::memset(&result, 0, sizeof(result));
            n.filter->filterv(reinterpret_cast<const rdl::DisplayFilterInputBufferv* const*>(inputs.data()),
                              reinterpret_cast<const rdl::DisplayFilterStatev*>(&state), reinterpret_cast<rdl::Colorv*>(&result));
            for (U32 i = 0; i < columns; ++i)
                out.setPixel(minX + i, minY + row, scene_rdl2::math::Vec3f(result.r[i], result.g[i], result.b[i]));
        }
    }

    U32 width_ = 0, height_ = 0, alignedWidth_ = 0, alignedHeight_ = 0;
    std::unique_ptr<rdl::SceneContext> real_;
    std::map<std::string, rdl::SceneObject*> copies_;
    std::vector<rdl::SceneObject*> outputs_;
    std::vector<Node> dag_;
    std::vector<int> order_;
};

}  // namespace xpu2::interactive::aov
