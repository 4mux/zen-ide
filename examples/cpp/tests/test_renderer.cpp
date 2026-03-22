#include "test_runner.h"
#include "renderer.h"
#include "circle.h"
#include "rectangle.h"
#include <memory>
#include <sstream>

using namespace geo;
using namespace test;

static ShapePtr make_circle(double r, Color c = Color::Blue) {
    return std::make_shared<Circle>(Vec3d(), r, c);
}

static ShapePtr make_rect(double w, double h, Color c = Color::Green) {
    return std::make_shared<Rectangle>(Vec3d(), w, h, c);
}

int main() {
    describe("Renderer count", []() {
        it("starts empty", []() {
            Renderer rnd;
            EXPECT_EQ(rnd.count(), size_t(0));
        });

        it("count grows with each add", []() {
            Renderer rnd;
            rnd.add(make_circle(1.0));
            rnd.add(make_rect(2.0, 3.0));
            EXPECT_EQ(rnd.count(), size_t(2));
        });
    });

    describe("Renderer total_area", []() {
        it("returns 0 when empty", []() {
            Renderer rnd;
            EXPECT_NEAR(rnd.total_area(), 0.0, 1e-10);
        });

        it("sums areas of all shapes", []() {
            Renderer rnd;
            rnd.add(make_rect(4.0, 3.0));  // area = 12
            rnd.add(make_rect(2.0, 5.0));  // area = 10
            EXPECT_NEAR(rnd.total_area(), 22.0, 1e-10);
        });
    });

    describe("Renderer filter", []() {
        it("returns all shapes when predicate is always true", []() {
            Renderer rnd;
            rnd.add(make_circle(1.0));
            rnd.add(make_rect(2.0, 2.0));
            auto all = rnd.filter([](const Shape&) { return true; });
            EXPECT_EQ(all.size(), size_t(2));
        });

        it("filters by color", []() {
            Renderer rnd;
            rnd.add(make_circle(1.0, Color::Red));
            rnd.add(make_circle(2.0, Color::Blue));
            rnd.add(make_rect(3.0, 3.0, Color::Red));
            auto reds = rnd.filter([](const Shape& s) { return s.color() == Color::Red; });
            EXPECT_EQ(reds.size(), size_t(2));
        });

        it("returns empty vector when nothing matches", []() {
            Renderer rnd;
            rnd.add(make_circle(1.0, Color::Blue));
            auto none = rnd.filter([](const Shape& s) { return s.color() == Color::Yellow; });
            EXPECT_EQ(none.size(), size_t(0));
        });
    });

    describe("Renderer render", []() {
        it("output includes shape count", []() {
            Renderer rnd;
            rnd.add(make_circle(1.0));
            rnd.add(make_rect(2.0, 3.0));
            std::ostringstream os;
            rnd.render(os);
            std::string out = os.str();
            EXPECT_TRUE(out.find("2") != std::string::npos);
        });

        it("output includes total area", []() {
            Renderer rnd;
            rnd.add(make_rect(4.0, 5.0));  // area = 20
            std::ostringstream os;
            rnd.render(os);
            std::string out = os.str();
            EXPECT_TRUE(out.find("Total area") != std::string::npos);
            EXPECT_TRUE(out.find("20") != std::string::npos);
        });
    });

    return summary();
}
