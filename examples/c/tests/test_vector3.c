#include "test_runner.h"
#include "vector3.h"

#define EPS 1e-10

int main(void) {
    DESCRIBE("Vector3");

    IT("creates with values", {
        Vec3 v = vec3_create(1, 2, 3);
        EXPECT_NEAR(v.x, 1.0, EPS);
        EXPECT_NEAR(v.y, 2.0, EPS);
        EXPECT_NEAR(v.z, 3.0, EPS);
    });

    IT("computes length", {
        Vec3 v = vec3_create(3, 4, 0);
        EXPECT_NEAR(vec3_length(v), 5.0, EPS);
    });

    IT("normalizes", {
        Vec3 v = vec3_create(0, 0, 5);
        Vec3 n = vec3_normalized(v);
        EXPECT_NEAR(n.x, 0.0, EPS);
        EXPECT_NEAR(n.y, 0.0, EPS);
        EXPECT_NEAR(n.z, 1.0, EPS);
    });

    IT("adds", {
        Vec3 r = vec3_add(vec3_create(1, 2, 3), vec3_create(4, 5, 6));
        EXPECT_NEAR(r.x, 5.0, EPS);
        EXPECT_NEAR(r.y, 7.0, EPS);
        EXPECT_NEAR(r.z, 9.0, EPS);
    });

    IT("subtracts", {
        Vec3 r = vec3_sub(vec3_create(5, 7, 9), vec3_create(1, 2, 3));
        EXPECT_NEAR(r.x, 4.0, EPS);
        EXPECT_NEAR(r.y, 5.0, EPS);
        EXPECT_NEAR(r.z, 6.0, EPS);
    });

    IT("scales", {
        Vec3 r = vec3_scale(vec3_create(1, 2, 3), 2.0);
        EXPECT_NEAR(r.x, 2.0, EPS);
        EXPECT_NEAR(r.y, 4.0, EPS);
        EXPECT_NEAR(r.z, 6.0, EPS);
    });

    IT("computes dot product", {
        Vec3 a = vec3_create(1, 2, 3);
        Vec3 b = vec3_create(4, 5, 6);
        EXPECT_NEAR(vec3_dot(a, b), 32.0, EPS);
    });

    IT("computes cross product", {
        Vec3 a = vec3_create(1, 0, 0);
        Vec3 b = vec3_create(0, 1, 0);
        Vec3 c = vec3_cross(a, b);
        EXPECT_NEAR(c.x, 0.0, EPS);
        EXPECT_NEAR(c.y, 0.0, EPS);
        EXPECT_NEAR(c.z, 1.0, EPS);
    });

    IT("checks equality", {
        Vec3 a = vec3_create(1, 2, 3);
        Vec3 b = vec3_create(1, 2, 3);
        EXPECT_TRUE(vec3_equal(a, b));
        EXPECT_TRUE(!vec3_equal(a, vec3_create(0, 0, 0)));
    });

    SUMMARY();
}
