#include "shape.h"

namespace geo {

std::string color_name(Color c) {
    switch (c) {
        case Color::Red:    return "Red";
        case Color::Green:  return "Green";
        case Color::Blue:   return "Blue";
        case Color::Yellow: return "Yellow";
        case Color::White:  return "White";
    }
    return "Unknown";
}

Shape::Shape(std::string name, Color color)
    : name_(std::move(name)), color_(color) {}

void Shape::describe(std::ostream& os) const {
    os << name_ << " [" << color_name(color_) << "]"
       << "  area=" << area()
       << "  perimeter=" << perimeter()
       << "  centroid=" << centroid() << "\n";
}

} // namespace geo
