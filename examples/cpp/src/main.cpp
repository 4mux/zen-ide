#include "circle.h"
#include "rectangle.h"
#include "renderer.h"
#include <iostream>
#include <algorithm>

using namespace geo;

int main() {
    // --- Vector3 demo ---
    Vec3d a(1.0, 2.0, 3.0);
    Vec3d b(4.0, 5.0, 6.0);

    std::cout << "a = " << a << "  b = " << b << "\n";
    std::cout << "a + b  = " << (a + b) << "\n";
    std::cout << "a dot b = " << a.dot(b) << "\n";
    std::cout << "a x b  = " << a.cross(b) << "\n";
    std::cout << "|a|    = " << a.length() << "\n";
    std::cout << "norm(a)= " << a.normalized() << "\n\n";

    // --- Shape hierarchy demo ---
    Renderer renderer;

    renderer.add(std::make_shared<Circle>(Vec3d(0, 0, 0), 5.0, Color::Red));
    renderer.add(std::make_shared<Circle>(Vec3d(10, 0, 0), 3.0));
    renderer.add(std::make_shared<Rectangle>(Vec3d(0, 0, 0), 4.0, 6.0, Color::Yellow));
    renderer.add(std::make_shared<Rectangle>(Vec3d(5, 5, 0), 10.0, 2.0));

    renderer.render(std::cout);

    // --- Lambda + filter demo ---
    auto big_shapes = renderer.filter([](const Shape& s) {
        return s.area() > 20.0;
    });

    std::cout << "\nShapes with area > 20:\n";
    for (const auto& s : big_shapes) {
        std::cout << "  " << s->name() << " (" << color_name(s->color())
                  << ") area=" << s->area() << "\n";
    }

    // --- STL algorithm demo ---
    std::vector<int> nums = {5, 3, 8, 1, 9, 2, 7};
    std::sort(nums.begin(), nums.end());

    std::cout << "\nSorted: ";
    for (int n : nums) std::cout << n << " ";
    std::cout << "\n";

    // --- Structured bindings (C++17) ---
    auto [cx, cy, cz] = renderer.filter([](const Shape& s) {
        return s.name() == "Circle";
    }).front()->centroid();

    std::cout << "First circle centroid: (" << cx << ", " << cy << ", " << cz << ")\n";

    return 0;
}
