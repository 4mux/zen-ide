#include "test_runner.h"
#include "shape.h"
#include <string.h>
#include <stdlib.h>

/* Concrete shape for testing the base interface */
static double dummy_area(const Shape *s)      { (void)s; return 42.0; }
static double dummy_perimeter(const Shape *s)  { (void)s; return 10.0; }
static Vec3   dummy_centroid(const Shape *s)    { (void)s; return vec3_create(1, 2, 3); }
static void   dummy_destroy(Shape *s)          { free(s); }

static const ShapeVTable dummy_vtable = {
    .area = dummy_area, .perimeter = dummy_perimeter,
    .centroid = dummy_centroid, .destroy = dummy_destroy,
};

static Shape *make_dummy(const char *name, Color color) {
    Shape *s = malloc(sizeof(Shape));
    s->type   = SHAPE_CIRCLE;
    s->name   = name;
    s->color  = color;
    s->vtable = &dummy_vtable;
    return s;
}

int main(void) {
    DESCRIBE("color_name");

    IT("returns Red",    { EXPECT_STR_EQ(color_name(COLOR_RED),    "Red"); });
    IT("returns Green",  { EXPECT_STR_EQ(color_name(COLOR_GREEN),  "Green"); });
    IT("returns Blue",   { EXPECT_STR_EQ(color_name(COLOR_BLUE),   "Blue"); });
    IT("returns Yellow", { EXPECT_STR_EQ(color_name(COLOR_YELLOW), "Yellow"); });
    IT("returns White",  { EXPECT_STR_EQ(color_name(COLOR_WHITE),  "White"); });

    DESCRIBE("Shape (via vtable)");

    IT("dispatches area", {
        Shape *s = make_dummy("Test", COLOR_RED);
        EXPECT_NEAR(shape_area(s), 42.0, 1e-10);
        shape_destroy(s);
    });

    IT("dispatches perimeter", {
        Shape *s = make_dummy("Test", COLOR_RED);
        EXPECT_NEAR(shape_perimeter(s), 10.0, 1e-10);
        shape_destroy(s);
    });

    IT("dispatches centroid", {
        Shape *s = make_dummy("Test", COLOR_RED);
        Vec3 c = shape_centroid(s);
        EXPECT_NEAR(c.x, 1.0, 1e-10);
        EXPECT_NEAR(c.y, 2.0, 1e-10);
        EXPECT_NEAR(c.z, 3.0, 1e-10);
        shape_destroy(s);
    });

    IT("stores name and color", {
        Shape *s = make_dummy("TestShape", COLOR_YELLOW);
        EXPECT_STR_EQ(s->name, "TestShape");
        EXPECT_EQ(s->color, COLOR_YELLOW);
        shape_destroy(s);
    });

    SUMMARY();
}
