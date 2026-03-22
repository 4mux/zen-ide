#include "renderer.h"
#include <stdlib.h>

#define INITIAL_CAP 8

Renderer *renderer_create(void) {
    Renderer *r = malloc(sizeof(Renderer));
    if (!r) return NULL;
    r->shapes   = malloc(sizeof(Shape *) * INITIAL_CAP);
    r->count    = 0;
    r->capacity = INITIAL_CAP;
    if (!r->shapes) { free(r); return NULL; }
    return r;
}

void renderer_add(Renderer *r, Shape *s) {
    if (r->count == r->capacity) {
        r->capacity *= 2;
        r->shapes = realloc(r->shapes, sizeof(Shape *) * r->capacity);
    }
    r->shapes[r->count++] = s;
}

void renderer_render(const Renderer *r, FILE *out) {
    fprintf(out, "=== Rendering %zu shape(s) ===\n", r->count);
    for (size_t i = 0; i < r->count; i++) {
        shape_describe(r->shapes[i], out);
        fprintf(out, "\n");
    }
    fprintf(out, "Total area: %.2f\n", renderer_total_area(r));
}

double renderer_total_area(const Renderer *r) {
    double total = 0.0;
    for (size_t i = 0; i < r->count; i++) {
        total += shape_area(r->shapes[i]);
    }
    return total;
}

size_t renderer_count(const Renderer *r) {
    return r->count;
}

size_t renderer_filter(const Renderer *r, ShapeFilter fn,
                       Shape **out, size_t out_cap) {
    size_t n = 0;
    for (size_t i = 0; i < r->count && n < out_cap; i++) {
        if (fn(r->shapes[i])) {
            out[n++] = r->shapes[i];
        }
    }
    return n;
}

void renderer_destroy(Renderer *r) {
    if (!r) return;
    for (size_t i = 0; i < r->count; i++) {
        shape_destroy(r->shapes[i]);
    }
    free(r->shapes);
    free(r);
}
