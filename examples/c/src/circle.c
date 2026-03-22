#include "circle.h"
#include <math.h>
#include <stdlib.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static double circle_area(const Shape *s) {
    const Circle *c = (const Circle *)s;
    return M_PI * c->radius * c->radius;
}

static double circle_perimeter(const Shape *s) {
    const Circle *c = (const Circle *)s;
    return 2.0 * M_PI * c->radius;
}

static Vec3 circle_centroid(const Shape *s) {
    const Circle *c = (const Circle *)s;
    return c->center;
}

static void circle_destroy(Shape *s) {
    free(s);
}

static const ShapeVTable circle_vtable = {
    .area      = circle_area,
    .perimeter = circle_perimeter,
    .centroid  = circle_centroid,
    .destroy   = circle_destroy,
};

Circle *circle_create(Vec3 center, double radius, Color color) {
    Circle *c = malloc(sizeof(Circle));
    if (!c) return NULL;
    c->base.type   = SHAPE_CIRCLE;
    c->base.name   = "Circle";
    c->base.color  = color;
    c->base.vtable = &circle_vtable;
    c->center      = center;
    c->radius      = radius;
    return c;
}
