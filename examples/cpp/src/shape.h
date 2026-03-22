#pragma once

#include "vector3.h"
#include <memory>
#include <string>

namespace geo {

enum class Color : uint8_t {
    Red,
    Green,
    Blue,
    Yellow,
    White,
};

std::string color_name(Color c);

class Shape {
public:
    Shape(std::string name, Color color);
    virtual ~Shape() = default;

    virtual double area() const = 0;
    virtual double perimeter() const = 0;
    virtual Vec3d  centroid() const = 0;
    virtual void   describe(std::ostream& os) const;

    const std::string& name() const { return name_; }
    Color              color() const { return color_; }

protected:
    std::string name_;
    Color       color_;
};

using ShapePtr = std::shared_ptr<Shape>;

} // namespace geo
