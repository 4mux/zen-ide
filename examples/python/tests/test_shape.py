"""Tests for shape module."""

import unittest

from shape import Color, Shape, get_registered_shapes, register_shape
from vector3 import Vector3


class _ConcreteShape(Shape):
    """Minimal concrete shape for testing the abstract base."""

    def __init__(self, color: Color = Color.WHITE) -> None:
        super().__init__("TestShape", color)

    def area(self) -> float:
        return 42.0

    def perimeter(self) -> float:
        return 10.0

    def centroid(self) -> Vector3[float]:
        return Vector3(0.0, 0.0, 0.0)


class TestColor(unittest.TestCase):
    def test_enum_members(self):
        self.assertIsNotNone(Color.RED)
        self.assertIsNotNone(Color.GREEN)
        self.assertIsNotNone(Color.BLUE)
        self.assertIsNotNone(Color.YELLOW)
        self.assertIsNotNone(Color.WHITE)

    def test_name(self):
        self.assertEqual(Color.RED.name, "RED")
        self.assertEqual(Color.BLUE.name, "BLUE")


class TestShape(unittest.TestCase):
    def test_name(self):
        s = _ConcreteShape()
        self.assertEqual(s.name, "TestShape")

    def test_color(self):
        s = _ConcreteShape(Color.RED)
        self.assertEqual(s.color, Color.RED)

    def test_describe(self):
        s = _ConcreteShape(Color.RED)
        desc = s.describe()
        self.assertIn("TestShape", desc)
        self.assertIn("RED", desc)
        self.assertIn("42.0000", desc)

    def test_repr(self):
        s = _ConcreteShape()
        self.assertIn("_ConcreteShape", repr(s))
        self.assertIn("WHITE", repr(s))


class TestAbstract(unittest.TestCase):
    def test_cannot_instantiate(self):
        with self.assertRaises(TypeError):
            Shape("x", Color.RED)  # type: ignore


class TestRegistry(unittest.TestCase):
    def test_register_and_retrieve(self):
        @register_shape
        class _Dummy(Shape):
            def __init__(self):
                super().__init__("Dummy", Color.WHITE)

            def area(self):
                return 0

            def perimeter(self):
                return 0

            def centroid(self):
                return Vector3(0, 0, 0)

        registry = get_registered_shapes()
        self.assertIn("_Dummy", registry)

    def test_registry_includes_circle_and_rectangle(self):
        import circle  # noqa: F401
        import rectangle  # noqa: F401

        registry = get_registered_shapes()
        self.assertIn("Circle", registry)
        self.assertIn("Rectangle", registry)
