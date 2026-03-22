#include "test_runner.h"
#include "rectangle.h"
#include <sstream>

using namespace geo;
using namespace test;

int main() {
    describe("Rectangle defaults", []() {
        it("uses Green as the default color", []() {
            Rectangle r(Vec3d(), 4.0, 3.0);
            EXPECT_EQ(r.color(), Color::Green);
        });

        it("exposes name as Rectangle", []() {
            Rectangle r(Vec3d(), 4.0, 3.0);
            EXPECT_EQ(r.name(), std::string("Rectangle"));
        });
    });

    describe("Rectangle getters", []() {
        it("exposes width and height", []() {
            Rectangle r(Vec3d(), 6.0, 2.5);
            EXPECT_EQ(r.width(),  6.0);
            EXPECT_EQ(r.height(), 2.5);
        });
    });

    describe("Rectangle area", []() {
        it("returns width * height", []() {
            Rectangle r(Vec3d(), 4.0, 3.0);
            EXPECT_NEAR(r.area(), 12.0, 1e-10);
        });

        it("zero width gives zero area", []() {
            Rectangle r(Vec3d(), 0.0, 5.0);
            EXPECT_NEAR(r.area(), 0.0, 1e-10);
        });
    });

    describe("Rectangle perimeter", []() {
        it("returns 2 * (w + h)", []() {
            Rectangle r(Vec3d(), 4.0, 3.0);
            EXPECT_NEAR(r.perimeter(), 14.0, 1e-10);
        });
    });

    describe("Rectangle centroid", []() {
        it("is at origin + (w/2, h/2, 0)", []() {
            Rectangle r(Vec3d(1, 1, 0), 4.0, 2.0);
            Vec3d c = r.centroid();
            EXPECT_NEAR(c.x, 3.0, 1e-10);
            EXPECT_NEAR(c.y, 2.0, 1e-10);
            EXPECT_NEAR(c.z, 0.0, 1e-10);
        });

        it("centroid of origin-aligned rect is (w/2, h/2, 0)", []() {
            Rectangle r(Vec3d(), 10.0, 6.0);
            Vec3d c = r.centroid();
            EXPECT_NEAR(c.x, 5.0, 1e-10);
            EXPECT_NEAR(c.y, 3.0, 1e-10);
            EXPECT_NEAR(c.z, 0.0, 1e-10);
        });
    });

    describe("Rectangle describe", []() {
        it("includes origin, width, and height", []() {
            Rectangle r(Vec3d(0, 0, 0), 4.0, 3.0, Color::Red);
            std::ostringstream os;
            r.describe(os);
            std::string out = os.str();
            EXPECT_TRUE(out.find("Rectangle") != std::string::npos);
            EXPECT_TRUE(out.find("Red")       != std::string::npos);
            EXPECT_TRUE(out.find("w=4")       != std::string::npos);
            EXPECT_TRUE(out.find("h=3")       != std::string::npos);
        });
    });

    return summary();
}
