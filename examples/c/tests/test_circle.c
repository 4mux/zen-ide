#include "test_runner.h"
#include "circle.h"
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

int main(void) {
    DESCRIBE("Circle");

    IT("has name and color", {
        Circle *c = circle_create(vec3_create(0, 0, 0), 1.0, COLOR_BLUE);
        EXPECT_STR_EQ(c->base.name, "Circle");
        EXPECT_EQ(c->base.color, COLOR_BLUE);
        shape_destroy(&c->base);
    });

    IT("computes area (pi * r^2)", {
        Circle *c = circle_create(vec3_create(0, 0, 0), 5.0, COLOR_RED);
        EXPECT_NEAR(shape_area(&c->base), M_PI * 25.0, 1e-10);
        shape_destroy(&c->base);
    });

    IT("computes perimeter (2 * pi * r)", {
        Circle *c = circle_create(vec3_create(0, 0, 0), 3.0, COLOR_RED);
        EXPECT_NEAR(shape_perimeter(&c->base), 2.0 * M_PI * 3.0, 1e-10);
        shape_destroy(&c->base);
    });

    IT("returns center as centroid", {
        Circle *c = circle_create(vec3_create(3, 4, 5), 2.0, COLOR_GREEN);
        Vec3 cen = shape_centroid(&c->base);
        EXPECT_NEAR(cen.x, 3.0, 1e-10);
        EXPECT_NEAR(cen.y, 4.0, 1e-10);
        EXPECT_NEAR(cen.z, 5.0, 1e-10);
        shape_destroy(&c->base);
    });

    IT("stores radius", {
        Circle *c = circle_create(vec3_create(0, 0, 0), 7.5, COLOR_WHITE);
        EXPECT_NEAR(c->radius, 7.5, 1e-10);
        shape_destroy(&c->base);
    });

    SUMMARY();
}
