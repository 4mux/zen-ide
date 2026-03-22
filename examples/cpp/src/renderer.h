#pragma once

#include "shape.h"
#include <functional>
#include <vector>

namespace geo {

class Renderer {
public:
    using FilterFn = std::function<bool(const Shape&)>;

    void add(ShapePtr shape);
    void render(std::ostream& os) const;

    std::vector<ShapePtr> filter(FilterFn predicate) const;
    double                total_area() const;

    size_t count() const { return shapes_.size(); }

private:
    std::vector<ShapePtr> shapes_;
};

} // namespace geo
