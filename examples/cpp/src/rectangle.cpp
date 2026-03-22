#include "rectangle.h"

namespace geo {

Rectangle::Rectangle(Vec3d origin, double width, double height, Color color)
    : Shape("Rectangle", color), origin_(origin), width_(width), height_(height) {}

double Rectangle::area() const {
    return width_ * height_;
}

double Rectangle::perimeter() const {
    return 2.0 * (width_ + height_);
}

Vec3d Rectangle::centroid() const {
    return origin_ + Vec3d(width_ / 2.0, height_ / 2.0, 0.0);
}

void Rectangle::describe(std::ostream& os) const {
    Shape::describe(os);
    os << "  origin=" << origin_
       << "  w=" << width_ << "  h=" << height_ << "\n";
}

} // namespace geo
