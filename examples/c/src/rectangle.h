#ifndef RECTANGLE_H
#define RECTANGLE_H

#include "shape.h"

typedef struct {
    Shape  base;
    Vec3   origin;
    double width;
    double height;
} Rectangle;

Rectangle *rectangle_create(Vec3 origin, double width, double height, Color color);

#endif
