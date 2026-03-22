"""Tests for rectangle module."""

import unittest

from rectangle import Rectangle
from shape import Color
from vector3 import Vector3


class TestDefaults(unittest.TestCase):
    def test_default_color_is_green(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 1.0, 1.0)
        self.assertEqual(r.color, Color.GREEN)

    def test_custom_color(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 1.0, 1.0, Color.YELLOW)
        self.assertEqual(r.color, Color.YELLOW)

    def test_name(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 1.0, 1.0)
        self.assertEqual(r.name, "Rectangle")


class TestProperties(unittest.TestCase):
    def test_width(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 4.0, 6.0)
        self.assertEqual(r.width, 4.0)

    def test_height(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 4.0, 6.0)
        self.assertEqual(r.height, 6.0)

    def test_origin(self):
        origin = Vector3(1.0, 2.0, 3.0)
        r = Rectangle(origin, 4.0, 6.0)
        self.assertEqual(r.origin, origin)


class TestArea(unittest.TestCase):
    def test_unit_square(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 1.0, 1.0)
        self.assertEqual(r.area(), 1.0)

    def test_4x6(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 4.0, 6.0)
        self.assertEqual(r.area(), 24.0)


class TestPerimeter(unittest.TestCase):
    def test_unit_square(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 1.0, 1.0)
        self.assertEqual(r.perimeter(), 4.0)

    def test_4x6(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 4.0, 6.0)
        self.assertEqual(r.perimeter(), 20.0)


class TestCentroid(unittest.TestCase):
    def test_at_origin(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 4.0, 6.0)
        c = r.centroid()
        self.assertAlmostEqual(c.x, 2.0)
        self.assertAlmostEqual(c.y, 3.0)
        self.assertAlmostEqual(c.z, 0.0)

    def test_offset_origin(self):
        r = Rectangle(Vector3(2.0, 3.0, 0.0), 10.0, 4.0)
        c = r.centroid()
        self.assertAlmostEqual(c.x, 7.0)
        self.assertAlmostEqual(c.y, 5.0)


class TestDescribe(unittest.TestCase):
    def test_includes_dimensions(self):
        r = Rectangle(Vector3(0.0, 0.0, 0.0), 4.0, 6.0, Color.YELLOW)
        desc = r.describe()
        self.assertIn("Rectangle", desc)
        self.assertIn("YELLOW", desc)
        self.assertIn("w=4.0", desc)
        self.assertIn("h=6.0", desc)
