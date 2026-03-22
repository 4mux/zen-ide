#include "vector3.h"
#include <math.h>

Vec3 vec3_create(double x, double y, double z) {
    return (Vec3){x, y, z};
}

Vec3 vec3_add(Vec3 a, Vec3 b) {
    return (Vec3){a.x + b.x, a.y + b.y, a.z + b.z};
}

Vec3 vec3_sub(Vec3 a, Vec3 b) {
    return (Vec3){a.x - b.x, a.y - b.y, a.z - b.z};
}

Vec3 vec3_scale(Vec3 v, double s) {
    return (Vec3){v.x * s, v.y * s, v.z * s};
}

double vec3_dot(Vec3 a, Vec3 b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

Vec3 vec3_cross(Vec3 a, Vec3 b) {
    return (Vec3){
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x
    };
}

double vec3_length(Vec3 v) {
    return sqrt(vec3_dot(v, v));
}

Vec3 vec3_normalized(Vec3 v) {
    double len = vec3_length(v);
    if (len == 0.0) return (Vec3){0, 0, 0};
    return vec3_scale(v, 1.0 / len);
}

int vec3_equal(Vec3 a, Vec3 b) {
    return a.x == b.x && a.y == b.y && a.z == b.z;
}
