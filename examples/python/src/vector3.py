"""3D vector with operator overloads and generic type support."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Generic, Iterator, TypeVar

T = TypeVar("T", int, float)


@dataclass(frozen=True, slots=True)
class Vector3(Generic[T]):
    x: T
    y: T
    z: T

    def length(self) -> float:
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def normalized(self) -> Vector3[float]:
        ln = self.length()
        if ln == 0:
            return Vector3(0.0, 0.0, 0.0)
        return Vector3(self.x / ln, self.y / ln, self.z / ln)

    def dot(self, other: Vector3[T]) -> T:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vector3[T]) -> Vector3[T]:
        return Vector3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def __add__(self, other: Vector3[T]) -> Vector3[T]:
        return Vector3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vector3[T]) -> Vector3[T]:
        return Vector3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: T) -> Vector3[T]:
        return Vector3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __iter__(self) -> Iterator[T]:
        yield self.x
        yield self.y
        yield self.z

    def __repr__(self) -> str:
        return f"({self.x}, {self.y}, {self.z})"


Vec3f = Vector3[float]
Vec3i = Vector3[int]
