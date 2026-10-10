// A VDB grid as a plain block of numbers, for the MoonLightIPR preview, which has no VDB reader of its own.
//
//   modo_vdb_grid <file.vdb> <grid name> <most cells along an edge> <output>
// reads one float grid and writes the box around its active voxels as a dense block no larger than asked along any
// edge: "MLV1", three counts, the largest value, sixteen floats that take a point of the unit cube into the grid's
// own space (basis vectors in rows, as MoonRay and Modo hold a transform), then the values, x fastest. A grid of
// colours, as an emission grid is, is written as "MLV4" with four numbers a cell: red, green, blue and one to spare.
//
//   modo_vdb_grid --ball <output.vdb>
// writes a small grid named "density" for tests: a ball of fog, thickest in the middle, with a hole off to one side,
// and one named "emission": a smaller ball of orange light inside it, as colours.
#include <openvdb/openvdb.h>
#include <openvdb/tools/Interpolation.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    try {
        openvdb::initialize();
        if (argc == 3 && std::string(argv[1]) == "--ball") {
            openvdb::FloatGrid::Ptr grid = openvdb::FloatGrid::create(0.0f);
            grid->setName("density");
            grid->setTransform(openvdb::math::Transform::createLinearTransform(0.05));
            openvdb::FloatGrid::Accessor at = grid->getAccessor();
            for (int z = -24; z <= 24; ++z)
                for (int y = -24; y <= 24; ++y)
                    for (int x = -24; x <= 24; ++x) {
                        const float r = std::sqrt(float(x * x + y * y + z * z)) / 24.0f;
                        const float hole = std::sqrt(float((x - 12) * (x - 12) + (y - 6) * (y - 6) + z * z)) / 9.0f;
                        if (r < 1.0f && hole > 1.0f) at.setValue(openvdb::Coord(x, y, z), (1.0f - r * r) * std::min(1.0f, (hole - 1.0f) * 3.0f));
                    }
            // And a grid named "emission": a glowing core, smaller than the fog, so the two grids have boxes of their own.
            openvdb::Vec3SGrid::Ptr glow = openvdb::Vec3SGrid::create(openvdb::Vec3f(0.0f));
            glow->setName("emission");
            glow->setTransform(openvdb::math::Transform::createLinearTransform(0.05));
            openvdb::Vec3SGrid::Accessor lit = glow->getAccessor();
            for (int z = -10; z <= 10; ++z)
                for (int y = -10; y <= 10; ++y)
                    for (int x = -10; x <= 10; ++x) {
                        const float r = std::sqrt(float(x * x + y * y + z * z)) / 10.0f;
                        if (r < 1.0f) lit.setValue(openvdb::Coord(x - 6, y, z), openvdb::Vec3f(1.0f, 0.45f, 0.1f) * (1.0f - r * r));
                    }
            openvdb::io::File out(argv[2]);
            out.write(openvdb::GridPtrVec{grid, glow});
            out.close();
            return 0;
        }
        if (argc != 5) {
            std::cerr << "usage: modo_vdb_grid <file.vdb> <grid name> <most cells along an edge> <output>" << std::endl;
            return 2;
        }
        const int most = std::max(8, std::atoi(argv[3]));
        openvdb::io::File file(argv[1]);
        file.open();
        openvdb::GridBase::Ptr base;
        const std::string wanted = argv[2];
        for (openvdb::io::File::NameIterator name = file.beginName(); name != file.endName(); ++name)
            if (wanted.empty() || name.gridName() == wanted) { base = file.readGrid(name.gridName()); break; }
        file.close();
        if (!base) throw std::runtime_error("the file has no grid named " + wanted);
        openvdb::FloatGrid::Ptr grid = openvdb::gridPtrCast<openvdb::FloatGrid>(base);
        openvdb::Vec3SGrid::Ptr colours = openvdb::gridPtrCast<openvdb::Vec3SGrid>(base);
        if (!grid && !colours) throw std::runtime_error("grid " + base->getName() + " holds neither single numbers nor colours");
        const openvdb::CoordBBox box = base->evalActiveVoxelBoundingBox();
        if (box.empty()) throw std::runtime_error("grid " + base->getName() + " is empty");
        const openvdb::Coord size = box.dim();
        const double step = std::max(1.0, double(std::max(size.x(), std::max(size.y(), size.z()))) / most);
        const uint32_t counts[3] = {uint32_t(std::max(1.0, std::ceil(size.x() / step))), uint32_t(std::max(1.0, std::ceil(size.y() / step))),
                                    uint32_t(std::max(1.0, std::ceil(size.z() / step)))};
        // A number a cell for a grid of numbers; four for a grid of colours: red, green, blue and one to spare.
        const size_t width = grid ? 1 : 4;
        std::vector<float> values(size_t(counts[0]) * counts[1] * counts[2] * width);
        float largest = 0.0f;
        for (uint32_t z = 0; z < counts[2]; ++z)
            for (uint32_t y = 0; y < counts[1]; ++y)
                for (uint32_t x = 0; x < counts[0]; ++x) {
                    // The middle of this cell, in the grid's own voxels. A voxel i covers i - 1/2 to i + 1/2.
                    const openvdb::Vec3d at(box.min().x() - 0.5 + (x + 0.5) * size.x() / counts[0], box.min().y() - 0.5 + (y + 0.5) * size.y() / counts[1],
                                            box.min().z() - 0.5 + (z + 0.5) * size.z() / counts[2]);
                    float* cell = &values[((size_t(z) * counts[1] + y) * counts[0] + x) * width];
                    if (grid) {
                        const float value = std::max(0.0f, openvdb::tools::BoxSampler::sample(grid->tree(), at));
                        cell[0] = std::isfinite(value) ? value : 0.0f;
                        largest = std::max(largest, cell[0]);
                    } else {
                        const openvdb::Vec3f value = openvdb::tools::BoxSampler::sample(colours->tree(), at);
                        for (int k = 0; k < 3; ++k) {
                            cell[k] = std::isfinite(value[k]) ? std::max(0.0f, value[k]) : 0.0f;
                            largest = std::max(largest, cell[k]);
                        }
                    }
                }
        // The unit cube to the box of voxels, then the grid's own transform to its space.
        const openvdb::math::Transform& placed = base->transform();
        const openvdb::Vec3d origin = placed.indexToWorld(openvdb::Vec3d(box.min().x() - 0.5, box.min().y() - 0.5, box.min().z() - 0.5));
        float matrix[16] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1};
        for (int axis = 0; axis < 3; ++axis) {
            openvdb::Vec3d far(box.min().x() - 0.5, box.min().y() - 0.5, box.min().z() - 0.5);
            far[axis] += size[axis];
            const openvdb::Vec3d edge = placed.indexToWorld(far) - origin;
            for (int k = 0; k < 3; ++k) matrix[axis * 4 + k] = float(edge[k]);
        }
        for (int k = 0; k < 3; ++k) matrix[12 + k] = float(origin[k]);
        std::ofstream out(argv[4], std::ios::binary);
        out.write(grid ? "MLV1" : "MLV4", 4);
        out.write(reinterpret_cast<const char*>(counts), sizeof(counts));
        out.write(reinterpret_cast<const char*>(&largest), sizeof(largest));
        out.write(reinterpret_cast<const char*>(matrix), sizeof(matrix));
        out.write(reinterpret_cast<const char*>(values.data()), values.size() * sizeof(float));
        if (!out) throw std::runtime_error("cannot write the output");
        std::cout << counts[0] << " " << counts[1] << " " << counts[2] << " " << largest << std::endl;
        return 0;
    } catch (const std::exception& problem) {
        std::cerr << "modo_vdb_grid: " << problem.what() << std::endl;
        return 1;
    }
}
