#ifndef RENDERER_H
#define RENDERER_H

#include "shape.h"
#include <stddef.h>

typedef int (*ShapeFilter)(const Shape *s);

typedef struct {
    Shape **shapes;
    size_t  count;
    size_t  capacity;
} Renderer;

Renderer *renderer_create(void);
void      renderer_add(Renderer *r, Shape *s);
void      renderer_render(const Renderer *r, FILE *out);
double    renderer_total_area(const Renderer *r);
size_t    renderer_count(const Renderer *r);
size_t    renderer_filter(const Renderer *r, ShapeFilter fn,
                          Shape **out, size_t out_cap);
void      renderer_destroy(Renderer *r);

#endif
