#include <stdio.h>
#include "vector3.h"
#include "circle.h"
#include "rectangle.h"
#include "renderer.h"

static int area_above_20(const Shape *s) {
    return shape_area(s) > 20.0;
}

int main(void) {
    /* Vector3 operations */
    printf("=== Vector3 ===\n");
    Vec3 a = vec3_create(1, 2, 3);
    Vec3 b = vec3_create(4, 5, 6);
    Vec3 sum = vec3_add(a, b);
    printf("a + b = (%.1f, %.1f, %.1f)\n", sum.x, sum.y, sum.z);
    printf("dot(a, b) = %.1f\n", vec3_dot(a, b));

    Vec3 cross = vec3_cross(a, b);
    printf("cross(a, b) = (%.1f, %.1f, %.1f)\n", cross.x, cross.y, cross.z);

    printf("length(a) = %.4f\n", vec3_length(a));
    Vec3 norm = vec3_normalized(a);
    printf("normalized(a) = (%.4f, %.4f, %.4f)\n", norm.x, norm.y, norm.z);

    /* Shapes and rendering */
    printf("\n");
    Renderer *r = renderer_create();

    renderer_add(r, (Shape *)circle_create(vec3_create(0, 0, 0), 5.0, COLOR_BLUE));
    renderer_add(r, (Shape *)circle_create(vec3_create(3, 4, 0), 2.0, COLOR_RED));
    renderer_add(r, (Shape *)rectangle_create(vec3_create(0, 0, 0), 10, 4, COLOR_GREEN));
    renderer_add(r, (Shape *)rectangle_create(vec3_create(1, 1, 0), 3, 3, COLOR_YELLOW));

    renderer_render(r, stdout);

    /* Filtering */
    printf("\n=== Shapes with area > 20 ===\n");
    Shape *filtered[16];
    size_t n = renderer_filter(r, area_above_20, filtered, 16);
    for (size_t i = 0; i < n; i++) {
        printf("  %s (area=%.2f)\n", filtered[i]->name, shape_area(filtered[i]));
    }

    renderer_destroy(r);
    return 0;
}
