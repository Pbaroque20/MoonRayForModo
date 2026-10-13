// Original MoonRayForModo fur geometry, using MoonRay's procedural API.
//
// The fibres of Modo's fur come to MoonRay in a file of plain numbers written by modo_fur_grow, in place of lists in
// the scene: a million fibres are sixteen million points, which as text in a scene are slow to write, slow to read
// and several times the size. The file is "MFC1", the number of fibres (32-bit) and of points (64-bit), the radius at
// the root and at the tip (floats), the number of points of each fibre (32-bit), each point as four floats (where it
// is, and the fibre's radius there), and each point's place as two floats (which fibre, and how far along it).
#include <moonray/rendering/geom/Api.h>
#include <moonray/rendering/geom/ProceduralLeaf.h>

#include <scene_rdl2/scene/rdl2/Geometry.h>

#include <cstdint>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "attributes.cc"

using namespace scene_rdl2;

RDL2_DSO_CLASS_BEGIN(ModoFurGeometry, scene_rdl2::rdl2::Geometry)

public:
    RDL2_DSO_DEFAULT_CTOR(ModoFurGeometry)
    moonray::geom::Procedural* createProcedural() const;
    void destroyProcedural() const;

RDL2_DSO_CLASS_END(ModoFurGeometry)

namespace moonray {
namespace geom {

class ModoFurProcedural : public ProceduralLeaf
{
public:
    explicit ModoFurProcedural(const State &state) : ProceduralLeaf(state) {}

    void generate(const GenerateContext &generateContext,
                  const shading::XformSamples &parent2render);
};

void
ModoFurProcedural::generate(const GenerateContext &generateContext,
                            const shading::XformSamples &parent2render)
{
    clear();

    const scene_rdl2::rdl2::Geometry *rdlGeometry = generateContext.getRdlGeometry();
    const scene_rdl2::rdl2::Layer *rdlLayer = generateContext.getRdlLayer();

    const std::string path = rdlGeometry->get(attrFile);
    std::ifstream source(path, std::ios::binary);
    char magic[4];
    uint32_t fibres = 0;
    uint64_t points = 0;
    float ends[2];
    if (!source.read(magic, 4) || std::memcmp(magic, "MFC1", 4) != 0 ||
        !source.read(reinterpret_cast<char*>(&fibres), sizeof(fibres)) ||
        !source.read(reinterpret_cast<char*>(&points), sizeof(points)) ||
        !source.read(reinterpret_cast<char*>(ends), sizeof(ends))) {
        rdlGeometry->error("Modo fur: cannot read the fur file ", path);
        return;
    }
    if (fibres == 0 || points == 0) return;

    std::vector<uint32_t> counts(fibres);
    std::vector<float> placed(size_t(points) * 4), across(size_t(points) * 2);
    if (!source.read(reinterpret_cast<char*>(counts.data()), counts.size() * sizeof(uint32_t)) ||
        !source.read(reinterpret_cast<char*>(placed.data()), placed.size() * sizeof(float)) ||
        !source.read(reinterpret_cast<char*>(across.data()), across.size() * sizeof(float))) {
        rdlGeometry->error("Modo fur: the fur file is cut short: ", path);
        return;
    }
    uint64_t counted = 0;
    for (uint32_t count : counts) counted += count;
    if (counted != points) {
        rdlGeometry->error("Modo fur: the fur file does not add up: ", path);
        return;
    }

    Curves::CurvesVertexCount vertexCounts(counts.begin(), counts.end());
    const size_t total = static_cast<size_t>(points);
    Curves::VertexBuffer vertices(total, 1);
    std::vector<scene_rdl2::math::Vec2f> places(total);
    for (size_t i = 0; i < total; ++i) {
        vertices(i, 0) = Vec3fa(placed[4 * i], placed[4 * i + 1], placed[4 * i + 2], placed[4 * i + 3]);
        places[i] = scene_rdl2::math::Vec2f(across[2 * i], across[2 * i + 1]);
    }
    // The numbers are not needed twice over.
    std::vector<float>().swap(placed);
    std::vector<float>().swap(across);

    shading::PrimitiveAttributeTable primitiveAttributeTable;
    primitiveAttributeTable.addAttribute(shading::StandardAttributes::sUv, shading::RATE_VERTEX, std::move(places));
    // Fur says it is fine: the plugin's matte of fur, hair and curves, by which a denoised picture keeps its fibres.
    primitiveAttributeTable.addAttribute(shading::TypedAttributeKey<float>("modo_fine"), shading::RATE_CONSTANT,
                                         std::vector<float>{1.0f});

    const Curves::Type type = Curves::Type::LINEAR;
    const Curves::SubType subtype = rdlGeometry->get(attrCurvesSubType) == 1 ? Curves::SubType::ROUND : Curves::SubType::RAY_FACING;
    const int tessellationRate = rdlGeometry->get(attrTessellationRate);

    std::string errorMessage;
    const Primitive::DataValidness dataValid = Curves::checkPrimitiveData(type, subtype, tessellationRate, vertexCounts, vertices,
                                                                         primitiveAttributeTable, &errorMessage);
    if (dataValid != Primitive::DataValidness::VALID) {
        rdlGeometry->error(errorMessage);
        return;
    }

    LayerAssignmentId layerAssignmentId(rdlLayer->getAssignmentId(rdlGeometry, std::string("")));
    std::unique_ptr<Curves> primitive = createCurves(type, subtype, tessellationRate, std::move(vertexCounts), std::move(vertices),
                                                     std::move(layerAssignmentId), std::move(primitiveAttributeTable));
    if (primitive) {
        addPrimitive(std::move(primitive), generateContext.getMotionBlurParams(), parent2render);
    }
}

} // namespace geom
} // namespace moonray

moonray::geom::Procedural*
ModoFurGeometry::createProcedural() const
{
    moonray::geom::State state;
    return new moonray::geom::ModoFurProcedural(state);
}

void
ModoFurGeometry::destroyProcedural() const
{
    delete mProcedural;
}
