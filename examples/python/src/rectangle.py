"""Rectangle shape implementation."""

from __future__ import annotations

from shape import Color, Shape, register_shape
from vector3 import Vector3


@register_shape
class Rectangle(Shape):
    def __init__(
        self,
        origin: Vector3[float],
        width: float,
        height: float,
        color: Color = Color.GREEN,
    ) -> None:
        super().__init__("Rectangle", color)
        self._origin = origin
        self._width = width
        self._height = height

    @property
    def width(self) -> float:
        return self._width

    @property
    def height(self) -> float:
        return self._height

    @property
    def origin(self) -> Vector3[float]:
        return self._origin

    def area(self) -> float:
        return self._width * self._height

    def perimeter(self) -> float:
        return 2.0 * (self._width + self._height)

    def centroid(self) -> Vector3[float]:
        return self._origin + Vector3(self._width / 2.0, self._height / 2.0, 0.0)

    def describe(self) -> str:
        base = super().describe()
        return f"{base}\n  origin={self._origin}  w={self._width}  h={self._height}"
