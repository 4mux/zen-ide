#pragma once

#include <cmath>
#include <iostream>

namespace geo {

template <typename T>
class Vector3 {
public:
    T x, y, z;

    Vector3() : x(0), y(0), z(0) {}
    Vector3(T x, T y, T z) : x(x), y(y), z(z) {}

    T length() const { return std::sqrt(x * x + y * y + z * z); }

    Vector3 normalized() const {
        T len = length();
        return (len > 0) ? Vector3(x / len, y / len, z / len) : *this;
    }

    T dot(const Vector3& other) const {
        return x * other.x + y * other.y + z * other.z;
    }

    Vector3 cross(const Vector3& other) const {
        return Vector3(
            y * other.z - z * other.y,
            z * other.x - x * other.z,
            x * other.y - y * other.x
        );
    }

    Vector3 operator+(const Vector3& rhs) const { return {x + rhs.x, y + rhs.y, z + rhs.z}; }
    Vector3 operator-(const Vector3& rhs) const { return {x - rhs.x, y - rhs.y, z - rhs.z}; }
    Vector3 operator*(T scalar) const { return {x * scalar, y * scalar, z * scalar}; }
    bool    operator==(const Vector3& rhs) const { return x == rhs.x && y == rhs.y && z == rhs.z; }

    friend std::ostream& operator<<(std::ostream& os, const Vector3& v) {
        return os << "(" << v.x << ", " << v.y << ", " << v.z << ")";
    }
};

using Vec3f = Vector3<float>;
using Vec3d = Vector3<double>;
using Vec3i = Vector3<int>;

} // namespace geo
