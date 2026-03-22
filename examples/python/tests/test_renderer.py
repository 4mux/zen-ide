"""Tests for renderer module."""

import math
import unittest

from circle import Circle
from rectangle import Rectangle
from renderer import Renderer
from shape import Color
from vector3 import Vector3


def _make_renderer() -> Renderer:
    r = Renderer()
    r.add(Circle(Vector3(0.0, 0.0, 0.0), 5.0, Color.RED))
    r.add(Rectangle(Vector3(0.0, 0.0, 0.0), 4.0, 6.0, Color.YELLOW))
    return r


class TestAddAndCount(unittest.TestCase):
    def test_empty(self):
        r = Renderer()
        self.assertEqual(r.count, 0)

    def test_after_add(self):
        r = _make_renderer()
        self.assertEqual(r.count, 2)


class TestTotalArea(unittest.TestCase):
    def test_computed(self):
        r = _make_renderer()
        expected = math.pi * 25.0 + 24.0
        self.assertAlmostEqual(r.total_area(), expected)


class TestFilter(unittest.TestCase):
    def test_by_area(self):
        r = _make_renderer()
        big = r.filter(lambda s: s.area() > 25)
        self.assertEqual(len(big), 1)
        self.assertEqual(big[0].name, "Circle")

    def test_empty_result(self):
        r = _make_renderer()
        none = r.filter(lambda s: s.area() > 1000)
        self.assertEqual(len(none), 0)


class TestSortedByArea(unittest.TestCase):
    def test_ascending(self):
        r = _make_renderer()
        shapes = r.sorted_by_area()
        self.assertLessEqual(shapes[0].area(), shapes[1].area())

    def test_descending(self):
        r = _make_renderer()
        shapes = r.sorted_by_area(reverse=True)
        self.assertGreaterEqual(shapes[0].area(), shapes[1].area())


class TestRender(unittest.TestCase):
    def test_header(self):
        r = _make_renderer()
        output = r.render()
        self.assertIn("Renderer (2 shapes)", output)

    def test_total_area_in_output(self):
        r = _make_renderer()
        output = r.render()
        self.assertIn("Total area:", output)


class TestIterShapes(unittest.TestCase):
    def test_yields_all(self):
        r = _make_renderer()
        shapes = list(r.iter_shapes())
        self.assertEqual(len(shapes), 2)

    def test_order_preserved(self):
        r = _make_renderer()
        shapes = list(r.iter_shapes())
        self.assertEqual(shapes[0].name, "Circle")
        self.assertEqual(shapes[1].name, "Rectangle")
