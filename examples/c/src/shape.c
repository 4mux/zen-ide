#include "shape.h"

const char *color_name(Color c) {
    switch (c) {
        case COLOR_RED:    return "Red";
        case COLOR_GREEN:  return "Green";
        case COLOR_BLUE:   return "Blue";
        case COLOR_YELLOW: return "Yellow";
        case COLOR_WHITE:  return "White";
    }
    return "Unknown";
}

double shape_area(const Shape *s) {
    return s->vtable->area(s);
}

double shape_perimeter(const Shape *s) {
    return s->vtable->perimeter(s);
}

Vec3 shape_centroid(const Shape *s) {
    return s->vtable->centroid(s);
}

void shape_describe(const Shape *s, FILE *out) {
    Vec3 c = shape_centroid(s);
    fprintf(out, "[%s] %s\n", s->name, color_name(s->color));
    fprintf(out, "  area:      %.2f\n", shape_area(s));
    fprintf(out, "  perimeter: %.2f\n", shape_perimeter(s));
    fprintf(out, "  centroid:  (%.2f, %.2f, %.2f)\n", c.x, c.y, c.z);
}

void shape_destroy(Shape *s) {
    if (s && s->vtable->destroy) {
        s->vtable->destroy(s);
    }
}
