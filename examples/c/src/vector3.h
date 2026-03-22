#ifndef VECTOR3_H
#define VECTOR3_H

typedef struct {
    double x;
    double y;
    double z;
} Vec3;

Vec3   vec3_create(double x, double y, double z);
Vec3   vec3_add(Vec3 a, Vec3 b);
Vec3   vec3_sub(Vec3 a, Vec3 b);
Vec3   vec3_scale(Vec3 v, double s);
double vec3_dot(Vec3 a, Vec3 b);
Vec3   vec3_cross(Vec3 a, Vec3 b);
double vec3_length(Vec3 v);
Vec3   vec3_normalized(Vec3 v);
int    vec3_equal(Vec3 a, Vec3 b);

#endif
