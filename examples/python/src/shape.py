"""Abstract shape base with enum colors and the registry decorator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Type

from vector3 import Vector3


class Color(Enum):
    RED = auto()
    GREEN = auto()
    BLUE = auto()
    YELLOW = auto()
    WHITE = auto()


# --- Class registry via decorator ---

_shape_registry: dict[str, Type[Shape]] = {}


def register_shape(cls: Type[Shape]) -> Type[Shape]:
    """Class decorator that registers a Shape subclass by name."""
    _shape_registry[cls.__name__] = cls
    return cls


def get_registered_shapes() -> dict[str, Type[Shape]]:
    return dict(_shape_registry)


class Shape(ABC):
    def __init__(self, name: str, color: Color) -> None:
        self._name = name
        self._color = color

    @property
    def name(self) -> str:
        return self._name

    @property
    def color(self) -> Color:
        return self._color

    @abstractmethod
    def area(self) -> float: ...

    @abstractmethod
    def perimeter(self) -> float: ...

    @abstractmethod
    def centroid(self) -> Vector3[float]: ...

    def describe(self) -> str:
        return (
            f"{self.name} [{self.color.name}]  "
            f"area={self.area():.4f}  "
            f"perimeter={self.perimeter():.4f}  "
            f"centroid={self.centroid()}"
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} color={self.color.name}>"
