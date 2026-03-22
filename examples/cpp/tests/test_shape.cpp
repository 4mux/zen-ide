#include "test_runner.h"
#include "shape.h"
#include <sstream>

using namespace geo;
using namespace test;

class ConcreteShape : public Shape {
public:
    ConcreteShape(Color c) : Shape("Concrete", c) {}
    double area()      const override { return 10.0; }
    double perimeter() const override { return 20.0; }
    Vec3d  centroid()  const override { return Vec3d(1, 2, 0); }
};

int main() {
    describe("color_name", []() {
        it("returns correct name for each color", []() {
            EXPECT_EQ(color_name(Color::Red),    std::string("Red"));
            EXPECT_EQ(color_name(Color::Green),  std::string("Green"));
            EXPECT_EQ(color_name(Color::Blue),   std::string("Blue"));
            EXPECT_EQ(color_name(Color::Yellow), std::string("Yellow"));
            EXPECT_EQ(color_name(Color::White),  std::string("White"));
        });
    });

    describe("Shape getters", []() {
        it("exposes name and color", []() {
            ConcreteShape s(Color::Yellow);
            EXPECT_EQ(s.name(), std::string("Concrete"));
            EXPECT_EQ(s.color(), Color::Yellow);
        });
    });

    describe("Shape::describe", []() {
        it("includes name, color, area, and perimeter", []() {
            ConcreteShape s(Color::Red);
            std::ostringstream os;
            s.describe(os);
            std::string out = os.str();
            EXPECT_TRUE(out.find("Concrete") != std::string::npos);
            EXPECT_TRUE(out.find("Red")      != std::string::npos);
            EXPECT_TRUE(out.find("10")       != std::string::npos);
            EXPECT_TRUE(out.find("20")       != std::string::npos);
        });
    });

    return summary();
}
