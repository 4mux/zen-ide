"""Renderer: collects shapes, filters, and computes aggregates."""

from __future__ import annotations

from functools import reduce
from typing import Callable, Protocol

from shape import Shape


class HasArea(Protocol):
    """Structural typing — any object with an area() method."""

    def area(self) -> float: ...


FilterFn = Callable[[Shape], bool]


class Renderer:
    def __init__(self) -> None:
        self._shapes: list[Shape] = []

    def add(self, shape: Shape) -> None:
        self._shapes.append(shape)

    @property
    def count(self) -> int:
        return len(self._shapes)

    def render(self) -> str:
        header = f"=== Renderer ({self.count} shapes) ==="
        body = "\n".join(s.describe() for s in self._shapes)
        footer = f"Total area: {self.total_area():.4f}"
        return f"{header}\n{body}\n{footer}"

    def filter(self, predicate: FilterFn) -> list[Shape]:
        return [s for s in self._shapes if predicate(s)]

    def total_area(self) -> float:
        return reduce(lambda acc, s: acc + s.area(), self._shapes, 0.0)

    def sorted_by_area(self, *, reverse: bool = False) -> list[Shape]:
        return sorted(self._shapes, key=lambda s: s.area(), reverse=reverse)

    # Generator — yields shapes lazily
    def iter_shapes(self):
        yield from self._shapes
