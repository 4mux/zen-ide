#include "renderer.h"
#include <algorithm>
#include <numeric>

namespace geo {

void Renderer::add(ShapePtr shape) {
    shapes_.push_back(std::move(shape));
}

void Renderer::render(std::ostream& os) const {
    os << "=== Renderer (" << shapes_.size() << " shapes) ===\n";
    for (const auto& s : shapes_) {
        s->describe(os);
    }
    os << "Total area: " << total_area() << "\n";
}

std::vector<ShapePtr> Renderer::filter(FilterFn predicate) const {
    std::vector<ShapePtr> result;
    std::copy_if(shapes_.begin(), shapes_.end(),
                 std::back_inserter(result),
                 [&](const ShapePtr& s) { return predicate(*s); });
    return result;
}

double Renderer::total_area() const {
    return std::accumulate(shapes_.begin(), shapes_.end(), 0.0,
        [](double sum, const ShapePtr& s) { return sum + s->area(); });
}

} // namespace geo
