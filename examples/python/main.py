#!/usr/bin/env python3
"""Demo entry point — exercises cross-file imports, classes, and language features."""

from __future__ import annotations

from circle import Circle
from rectangle import Rectangle
from renderer import Renderer
from shape import Color, get_registered_shapes
from utils import chunk, fibonacci, timer
from vector3 import Vector3


def main() -> None:
    # --- Vector3 demo ---
    a = Vector3(1.0, 2.0, 3.0)
    b = Vector3(4.0, 5.0, 6.0)

    print(f"a = {a}  b = {b}")
    print(f"a + b   = {a + b}")
    print(f"a dot b = {a.dot(b)}")
    print(f"a x b   = {a.cross(b)}")
    print(f"|a|     = {a.length():.5f}")
    print(f"norm(a) = {a.normalized()}\n")

    # --- Unpacking (structural iteration) ---
    x, y, z = a
    print(f"Unpacked a: x={x}, y={y}, z={z}\n")

    # --- Shape hierarchy + decorator registry ---
    renderer = Renderer()
    renderer.add(Circle(Vector3(0.0, 0.0, 0.0), 5.0, Color.RED))
    renderer.add(Circle(Vector3(10.0, 0.0, 0.0), 3.0))
    renderer.add(Rectangle(Vector3(0.0, 0.0, 0.0), 4.0, 6.0, Color.YELLOW))
    renderer.add(Rectangle(Vector3(5.0, 5.0, 0.0), 10.0, 2.0))

    print(renderer.render())

    # --- Lambda filter ---
    big = renderer.filter(lambda s: s.area() > 20)
    print("\nShapes with area > 20:")
    for s in big:
        print(f"  {s.name} ({s.color.name}) area={s.area():.4f}")

    # --- Sorted + walrus operator ---
    if (top := renderer.sorted_by_area(reverse=True)) and len(top) > 0:
        print(f"\nLargest shape: {top[0].name} area={top[0].area():.4f}")

    # --- Generator demo ---
    fibs = list(fibonacci(10))
    print(f"\nFibonacci(10): {fibs}")
    print(f"Chunked(3):    {chunk(fibs, 3)}")

    # --- Generator iteration from renderer ---
    print("\nAll shapes (via generator):")
    for shape in renderer.iter_shapes():
        print(f"  {shape!r}")

    # --- Class registry ---
    registry = get_registered_shapes()
    print(f"\nRegistered shapes: {list(registry.keys())}")

    # --- Context manager ---
    with timer("sort 10k ints"):
        sorted(range(10_000, 0, -1))

    # --- Dict / set comprehensions ---
    area_map = {s.name: s.area() for s in renderer.iter_shapes()}
    unique_colors = {s.color for s in renderer.iter_shapes()}
    print(f"\nArea map: {area_map}")
    print(f"Unique colors: {sorted(c.name for c in unique_colors)}")

    # --- Match statement (Python 3.10+) ---
    for shape in renderer.iter_shapes():
        match shape:
            case Circle(radius=r) if r > 4:
                print(f"\n[match] Big circle: radius={r}")
            case Rectangle(width=w, height=h) if w * h > 20:
                print(f"[match] Big rectangle: {w}x{h}")
            case _:
                pass


if __name__ == "__main__":
    main()
