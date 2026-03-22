#ifndef CIRCLE_H
#define CIRCLE_H

#include "shape.h"

typedef struct {
    Shape base;
    Vec3  center;
    double radius;
} Circle;

Circle *circle_create(Vec3 center, double radius, Color color);

#endif
