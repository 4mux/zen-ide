#include "test_runner.h"
#include "vector3.h"

using namespace geo;
using namespace test;

int main() {
    describe("Vector3 constructor / getters", []() {
        it("stores x, y, z", []() {
            Vec3d v(1, 2, 3);
            EXPECT_EQ(v.x, 1.0);
            EXPECT_EQ(v.y, 2.0);
            EXPECT_EQ(v.z, 3.0);
        });

        it("defaults to (0, 0, 0)", []() {
            Vec3d v;
            EXPECT_EQ(v.x, 0.0);
            EXPECT_EQ(v.y, 0.0);
            EXPECT_EQ(v.z, 0.0);
        });
    });

    describe("Vector3 length", []() {
        it("computes Euclidean length", []() {
            EXPECT_NEAR(Vec3d(3, 4, 0).length(), 5.0, 1e-10);
        });

        it("returns 0 for the zero vector", []() {
            EXPECT_EQ(Vec3d().length(), 0.0);
        });
    });

    describe("Vector3 normalized", []() {
        it("returns a unit vector", []() {
            Vec3d n = Vec3d(3, 0, 0).normalized();
            EXPECT_NEAR(n.x, 1.0, 1e-10);
            EXPECT_NEAR(n.y, 0.0, 1e-10);
            EXPECT_NEAR(n.z, 0.0, 1e-10);
        });

        it("returns zero vector for zero input", []() {
            Vec3d n = Vec3d().normalized();
            EXPECT_EQ(n.x, 0.0);
            EXPECT_EQ(n.y, 0.0);
            EXPECT_EQ(n.z, 0.0);
        });
    });

    describe("Vector3 arithmetic", []() {
        it("adds two vectors", []() {
            Vec3d r = Vec3d(1, 2, 3) + Vec3d(4, 5, 6);
            EXPECT_EQ(r.x, 5.0);
            EXPECT_EQ(r.y, 7.0);
            EXPECT_EQ(r.z, 9.0);
        });

        it("subtracts two vectors", []() {
            Vec3d r = Vec3d(4, 5, 6) - Vec3d(1, 2, 3);
            EXPECT_EQ(r.x, 3.0);
            EXPECT_EQ(r.y, 3.0);
            EXPECT_EQ(r.z, 3.0);
        });

        it("scales by scalar", []() {
            Vec3d r = Vec3d(1, 2, 3) * 2.0;
            EXPECT_EQ(r.x, 2.0);
            EXPECT_EQ(r.y, 4.0);
            EXPECT_EQ(r.z, 6.0);
        });
    });

    describe("Vector3 dot", []() {
        it("computes dot product", []() {
            EXPECT_NEAR(Vec3d(1, 2, 3).dot(Vec3d(4, 5, 6)), 32.0, 1e-10);
        });

        it("returns 0 for perpendicular vectors", []() {
            EXPECT_NEAR(Vec3d(1, 0, 0).dot(Vec3d(0, 1, 0)), 0.0, 1e-10);
        });
    });

    describe("Vector3 cross", []() {
        it("computes cross product", []() {
            Vec3d r = Vec3d(1, 0, 0).cross(Vec3d(0, 1, 0));
            EXPECT_NEAR(r.x, 0.0, 1e-10);
            EXPECT_NEAR(r.y, 0.0, 1e-10);
            EXPECT_NEAR(r.z, 1.0, 1e-10);
        });

        it("is anti-commutative", []() {
            Vec3d a(1, 2, 3), b(4, 5, 6);
            Vec3d ab = a.cross(b);
            Vec3d ba = b.cross(a);
            EXPECT_NEAR(ab.x, -ba.x, 1e-10);
            EXPECT_NEAR(ab.y, -ba.y, 1e-10);
            EXPECT_NEAR(ab.z, -ba.z, 1e-10);
        });
    });

    describe("Vector3 equality", []() {
        it("equal vectors compare equal", []() {
            EXPECT_TRUE(Vec3d(1, 2, 3) == Vec3d(1, 2, 3));
        });

        it("different vectors are not equal", []() {
            EXPECT_TRUE(!(Vec3d(1, 2, 3) == Vec3d(1, 2, 4)));
        });
    });

    return summary();
}
