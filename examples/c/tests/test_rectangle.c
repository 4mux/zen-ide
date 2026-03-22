#include "test_runner.h"
#include "rectangle.h"
#include <string.h>

int main(void) {
    DESCRIBE("Rectangle");

    IT("has name and color", {
        Rectangle *r = rectangle_create(vec3_create(0, 0, 0), 4, 5, COLOR_GREEN);
        EXPECT_STR_EQ(r->base.name, "Rectangle");
        EXPECT_EQ(r->base.color, COLOR_GREEN);
        shape_destroy(&r->base);
    });

    IT("stores width and height", {
        Rectangle *r = rectangle_create(vec3_create(0, 0, 0), 10, 3, COLOR_RED);
        EXPECT_NEAR(r->width, 10.0, 1e-10);
        EXPECT_NEAR(r->height, 3.0, 1e-10);
        shape_destroy(&r->base);
    });

    IT("computes area (w * h)", {
        Rectangle *r = rectangle_create(vec3_create(0, 0, 0), 6, 4, COLOR_RED);
        EXPECT_NEAR(shape_area(&r->base), 24.0, 1e-10);
        shape_destroy(&r->base);
    });

    IT("computes perimeter (2 * (w + h))", {
        Rectangle *r = rectangle_create(vec3_create(0, 0, 0), 6, 4, COLOR_RED);
        EXPECT_NEAR(shape_perimeter(&r->base), 20.0, 1e-10);
        shape_destroy(&r->base);
    });

    IT("computes centroid from origin", {
        Rectangle *r = rectangle_create(vec3_create(2, 3, 0), 10, 4, COLOR_BLUE);
        Vec3 c = shape_centroid(&r->base);
        EXPECT_NEAR(c.x, 7.0, 1e-10);
        EXPECT_NEAR(c.y, 5.0, 1e-10);
        EXPECT_NEAR(c.z, 0.0, 1e-10);
        shape_destroy(&r->base);
    });

    IT("computes centroid at zero origin", {
        Rectangle *r = rectangle_create(vec3_create(0, 0, 0), 8, 6, COLOR_YELLOW);
        Vec3 c = shape_centroid(&r->base);
        EXPECT_NEAR(c.x, 4.0, 1e-10);
        EXPECT_NEAR(c.y, 3.0, 1e-10);
        shape_destroy(&r->base);
    });

    SUMMARY();
}
