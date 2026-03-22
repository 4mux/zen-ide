#ifndef SHAPE_H
#define SHAPE_H

#include "vector3.h"
#include <stdio.h>

typedef enum {
    COLOR_RED,
    COLOR_GREEN,
    COLOR_BLUE,
    COLOR_YELLOW,
    COLOR_WHITE
} Color;

const char *color_name(Color c);

typedef enum {
    SHAPE_CIRCLE,
    SHAPE_RECTANGLE
} ShapeType;

typedef struct Shape Shape;

/* vtable: function pointers for polymorphism */
typedef struct {
    double (*area)(const Shape *s);
    double (*perimeter)(const Shape *s);
    Vec3   (*centroid)(const Shape *s);
    void   (*destroy)(Shape *s);
} ShapeVTable;

struct Shape {
    ShapeType        type;
    const char      *name;
    Color            color;
    const ShapeVTable *vtable;
};

double shape_area(const Shape *s);
double shape_perimeter(const Shape *s);
Vec3   shape_centroid(const Shape *s);
void   shape_describe(const Shape *s, FILE *out);
void   shape_destroy(Shape *s);

#endif
