#include "circle.h"
#include <cmath>

namespace geo {

static constexpr double PI = 3.14159265358979323846;

Circle::Circle(Vec3d center, double radius, Color color)
    : Shape("Circle", color), center_(center), radius_(radius) {}

double Circle::area() const {
    return PI * radius_ * radius_;
}

double Circle::perimeter() const {
    return 2.0 * PI * radius_;
}

Vec3d Circle::centroid() const {
    return center_;
}

void Circle::describe(std::ostream& os) const {
    Shape::describe(os);
    os << "  radius=" << radius_ << "  center=" << center_ << "\n";
}

} // namespace geo
