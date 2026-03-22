"""Tests for circle module."""

import math
import unittest

from circle import Circle
from shape import Color
from vector3 import Vector3


class TestDefaults(unittest.TestCase):
    def test_default_color_is_blue(self):
        c = Circle(Vector3(0.0, 0.0, 0.0), 1.0)
        self.assertEqual(c.color, Color.BLUE)

    def test_custom_color(self):
        c = Circle(Vector3(0.0, 0.0, 0.0), 1.0, Color.RED)
        self.assertEqual(c.color, Color.RED)

    def test_name(self):
        c = Circle(Vector3(0.0, 0.0, 0.0), 1.0)
        self.assertEqual(c.name, "Circle")


class TestProperties(unittest.TestCase):
    def test_radius(self):
        c = Circle(Vector3(0.0, 0.0, 0.0), 5.0)
        self.assertEqual(c.radius, 5.0)

    def test_center(self):
        center = Vector3(1.0, 2.0, 3.0)
        c = Circle(center, 5.0)
        self.assertEqual(c.center, center)


class TestArea(unittest.TestCase):
    def test_unit_circle(self):
        c = Circle(Vector3(0.0, 0.0, 0.0), 1.0)
        self.assertAlmostEqual(c.area(), math.pi)

    def test_radius_5(self):
        c = Circle(Vector3(0.0, 0.0, 0.0), 5.0)
        self.assertAlmostEqual(c.area(), math.pi * 25.0)


class TestPerimeter(unittest.TestCase):
    def test_unit_circle(self):
        c = Circle(Vector3(0.0, 0.0, 0.0), 1.0)
        self.assertAlmostEqual(c.perimeter(), 2.0 * math.pi)

    def test_radius_3(self):
        c = Circle(Vector3(0.0, 0.0, 0.0), 3.0)
        self.assertAlmostEqual(c.perimeter(), 6.0 * math.pi)


class TestCentroid(unittest.TestCase):
    def test_returns_center(self):
        center = Vector3(10.0, 20.0, 30.0)
        c = Circle(center, 5.0)
        self.assertEqual(c.centroid(), center)


class TestDescribe(unittest.TestCase):
    def test_includes_radius_and_center(self):
        c = Circle(Vector3(1.0, 2.0, 0.0), 3.0, Color.RED)
        desc = c.describe()
        self.assertIn("Circle", desc)
        self.assertIn("RED", desc)
        self.assertIn("radius=3.0", desc)
