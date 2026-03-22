#include "test_runner.h"
#include "circle.h"
#include <cmath>
#include <sstream>

using namespace geo;
using namespace test;

static constexpr double PI = 3.14159265358979323846;

int main() {
    describe("Circle defaults", []() {
        it("uses Blue as the default color", []() {
            Circle c(Vec3d(), 1.0);
            EXPECT_EQ(c.color(), Color::Blue);
        });

        it("exposes name as Circle", []() {
            Circle c(Vec3d(), 1.0);
            EXPECT_EQ(c.name(), std::string("Circle"));
        });
    });

    describe("Circle area", []() {
        it("returns pi * r^2", []() {
            Circle c(Vec3d(), 5.0);
            EXPECT_NEAR(c.area(), PI * 25.0, 1e-9);
        });

        it("scales with radius squared", []() {
            Circle c1(Vec3d(), 1.0);
            Circle c2(Vec3d(), 2.0);
            EXPECT_NEAR(c2.area(), c1.area() * 4.0, 1e-9);
        });
    });

    describe("Circle perimeter", []() {
        it("returns 2 * pi * r", []() {
            Circle c(Vec3d(), 3.0);
            EXPECT_NEAR(c.perimeter(), 2.0 * PI * 3.0, 1e-9);
        });
    });

    describe("Circle centroid", []() {
        it("equals the center", []() {
            Vec3d center(1, 2, 0);
            Circle c(center, 4.0);
            Vec3d cen = c.centroid();
            EXPECT_EQ(cen.x, center.x);
            EXPECT_EQ(cen.y, center.y);
            EXPECT_EQ(cen.z, center.z);
        });
    });

    describe("Circle getters", []() {
        it("exposes radius", []() {
            Circle c(Vec3d(), 7.0, Color::Red);
            EXPECT_EQ(c.radius(), 7.0);
        });

        it("respects explicit color", []() {
            Circle c(Vec3d(), 1.0, Color::Green);
            EXPECT_EQ(c.color(), Color::Green);
        });
    });

    describe("Circle describe", []() {
        it("includes radius and center", []() {
            Circle c(Vec3d(1, 2, 0), 5.0, Color::Red);
            std::ostringstream os;
            c.describe(os);
            std::string out = os.str();
            EXPECT_TRUE(out.find("radius=5") != std::string::npos);
            EXPECT_TRUE(out.find("Red")      != std::string::npos);
            EXPECT_TRUE(out.find("Circle")   != std::string::npos);
        });
    });

    return summary();
}
