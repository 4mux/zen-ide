#pragma once

#include "shape.h"

namespace geo {

class Rectangle : public Shape {
public:
    Rectangle(Vec3d origin, double width, double height, Color color = Color::Green);

    double area() const override;
    double perimeter() const override;
    Vec3d  centroid() const override;
    void   describe(std::ostream& os) const override;

    double width() const { return width_; }
    double height() const { return height_; }

private:
    Vec3d  origin_;
    double width_;
    double height_;
};

} // namespace geo
