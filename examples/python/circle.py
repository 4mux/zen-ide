"""Circle shape implementation."""

from __future__ import annotations

import math

from shape import Color, Shape, register_shape
from vector3 import Vector3


@register_shape
class Circle(Shape):
    def __init__(
        self,
        center: Vector3[float],
        radius: float,
        color: Color = Color.BLUE,
    ) -> None:
        super().__init__("Circle", color)
        self._center = center
        self._radius = radius

    @property
    def radius(self) -> float:
        return self._radius

    @property
    def center(self) -> Vector3[float]:
        return self._center

    def area(self) -> float:
        return math.pi * self._radius**2

    def perimeter(self) -> float:
        return 2.0 * math.pi * self._radius

    def centroid(self) -> Vector3[float]:
        return self._center

    def describe(self) -> str:
        base = super().describe()
        return f"{base}\n  radius={self._radius}  center={self._center}"
