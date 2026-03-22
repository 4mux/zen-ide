#include "rectangle.h"
#include <stdlib.h>

static double rectangle_area(const Shape *s) {
    const Rectangle *r = (const Rectangle *)s;
    return r->width * r->height;
}

static double rectangle_perimeter(const Shape *s) {
    const Rectangle *r = (const Rectangle *)s;
    return 2.0 * (r->width + r->height);
}

static Vec3 rectangle_centroid(const Shape *s) {
    const Rectangle *r = (const Rectangle *)s;
    return vec3_create(
        r->origin.x + r->width / 2.0,
        r->origin.y + r->height / 2.0,
        r->origin.z
    );
}

static void rectangle_destroy(Shape *s) {
    free(s);
}

static const ShapeVTable rectangle_vtable = {
    .area      = rectangle_area,
    .perimeter = rectangle_perimeter,
    .centroid  = rectangle_centroid,
    .destroy   = rectangle_destroy,
};

Rectangle *rectangle_create(Vec3 origin, double width, double height, Color color) {
    Rectangle *r = malloc(sizeof(Rectangle));
    if (!r) return NULL;
    r->base.type   = SHAPE_RECTANGLE;
    r->base.name   = "Rectangle";
    r->base.color  = color;
    r->base.vtable = &rectangle_vtable;
    r->origin      = origin;
    r->width       = width;
    r->height      = height;
    return r;
}
