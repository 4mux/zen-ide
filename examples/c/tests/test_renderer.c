#include "test_runner.h"
#include "circle.h"
#include "rectangle.h"
#include "renderer.h"
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static Shape *make_circle(double r) {
    return (Shape *)circle_create(vec3_create(0, 0, 0), r, COLOR_BLUE);
}

static Shape *make_rect(double w, double h) {
    return (Shape *)rectangle_create(vec3_create(0, 0, 0), w, h, COLOR_GREEN);
}

static int is_blue(const Shape *s) {
    return s->color == COLOR_BLUE;
}

static int area_gt_20(const Shape *s) {
    return shape_area(s) > 20.0;
}

int main(void) {
    DESCRIBE("Renderer");

    IT("starts empty", {
        Renderer *r = renderer_create();
        EXPECT_EQ(renderer_count(r), (size_t)0);
        EXPECT_NEAR(renderer_total_area(r), 0.0, 1e-10);
        renderer_destroy(r);
    });

    IT("counts shapes", {
        Renderer *r = renderer_create();
        renderer_add(r, make_circle(1));
        renderer_add(r, make_rect(2, 3));
        EXPECT_EQ(renderer_count(r), (size_t)2);
        renderer_destroy(r);
    });

    IT("computes total area", {
        Renderer *r = renderer_create();
        renderer_add(r, make_circle(1));
        renderer_add(r, make_rect(2, 3));
        double expected = M_PI * 1.0 + 6.0;
        EXPECT_NEAR(renderer_total_area(r), expected, 1e-10);
        renderer_destroy(r);
    });

    IT("filters by predicate", {
        Renderer *r = renderer_create();
        renderer_add(r, make_circle(1));
        renderer_add(r, make_rect(2, 3));
        renderer_add(r, make_circle(2));
        Shape *out[8];
        size_t n = renderer_filter(r, is_blue, out, 8);
        EXPECT_EQ(n, (size_t)2);
        renderer_destroy(r);
    });

    IT("filters by area", {
        Renderer *r = renderer_create();
        renderer_add(r, make_rect(3, 3));     /* 9 */
        renderer_add(r, make_rect(10, 5));    /* 50 */
        renderer_add(r, make_circle(1));      /* ~3.14 */
        Shape *out[8];
        size_t n = renderer_filter(r, area_gt_20, out, 8);
        EXPECT_EQ(n, (size_t)1);
        renderer_destroy(r);
    });

    IT("renders to stream", {
        Renderer *r = renderer_create();
        renderer_add(r, make_circle(1));
        FILE *f = tmpfile();
        renderer_render(r, f);
        fseek(f, 0, SEEK_SET);
        char buf[512];
        size_t bytes = fread(buf, 1, sizeof(buf) - 1, f);
        buf[bytes] = '\0';
        fclose(f);
        EXPECT_TRUE(strstr(buf, "Rendering 1 shape(s)") != NULL);
        EXPECT_TRUE(strstr(buf, "Circle") != NULL);
        renderer_destroy(r);
    });

    SUMMARY();
}
