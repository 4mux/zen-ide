#pragma once

#include "shape.h"

namespace geo {

class Circle : public Shape {
public:
    Circle(Vec3d center, double radius, Color color = Color::Blue);

    double area() const override;
    double perimeter() const override;
    Vec3d  centroid() const override;
    void   describe(std::ostream& os) const override;

    double radius() const { return radius_; }

private:
    Vec3d  center_;
    double radius_;
};

} // namespace geo
