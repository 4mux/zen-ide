"""Tests for vector3 module."""

import unittest

from vector3 import Vector3


class TestConstructor(unittest.TestCase):
    def test_creates_with_xyz(self):
        v = Vector3(1.0, 2.0, 3.0)
        self.assertEqual(v.x, 1.0)
        self.assertEqual(v.y, 2.0)
        self.assertEqual(v.z, 3.0)

    def test_frozen_dataclass(self):
        v = Vector3(1.0, 2.0, 3.0)
        with self.assertRaises(AttributeError):
            v.x = 99.0  # type: ignore


class TestLength(unittest.TestCase):
    def test_unit_vector(self):
        v = Vector3(1.0, 0.0, 0.0)
        self.assertEqual(v.length(), 1.0)

    def test_general(self):
        v = Vector3(3.0, 4.0, 0.0)
        self.assertAlmostEqual(v.length(), 5.0)

    def test_zero_vector(self):
        v = Vector3(0.0, 0.0, 0.0)
        self.assertEqual(v.length(), 0.0)


class TestNormalized(unittest.TestCase):
    def test_unit_length(self):
        v = Vector3(3.0, 4.0, 0.0)
        n = v.normalized()
        self.assertAlmostEqual(n.length(), 1.0)

    def test_direction_preserved(self):
        v = Vector3(0.0, 5.0, 0.0)
        n = v.normalized()
        self.assertAlmostEqual(n.x, 0.0)
        self.assertAlmostEqual(n.y, 1.0)
        self.assertAlmostEqual(n.z, 0.0)

    def test_zero_vector(self):
        v = Vector3(0.0, 0.0, 0.0)
        n = v.normalized()
        self.assertEqual(n, Vector3(0.0, 0.0, 0.0))


class TestArithmetic(unittest.TestCase):
    def test_add(self):
        a = Vector3(1.0, 2.0, 3.0)
        b = Vector3(4.0, 5.0, 6.0)
        self.assertEqual(a + b, Vector3(5.0, 7.0, 9.0))

    def test_sub(self):
        a = Vector3(4.0, 5.0, 6.0)
        b = Vector3(1.0, 2.0, 3.0)
        self.assertEqual(a - b, Vector3(3.0, 3.0, 3.0))

    def test_mul_scalar(self):
        v = Vector3(1.0, 2.0, 3.0)
        self.assertEqual(v * 2.0, Vector3(2.0, 4.0, 6.0))


class TestDotCross(unittest.TestCase):
    def test_dot_product(self):
        a = Vector3(1.0, 2.0, 3.0)
        b = Vector3(4.0, 5.0, 6.0)
        self.assertEqual(a.dot(b), 32.0)

    def test_dot_orthogonal(self):
        a = Vector3(1.0, 0.0, 0.0)
        b = Vector3(0.0, 1.0, 0.0)
        self.assertEqual(a.dot(b), 0.0)

    def test_cross_product(self):
        a = Vector3(1.0, 0.0, 0.0)
        b = Vector3(0.0, 1.0, 0.0)
        self.assertEqual(a.cross(b), Vector3(0.0, 0.0, 1.0))

    def test_cross_anticommutative(self):
        a = Vector3(1.0, 2.0, 3.0)
        b = Vector3(4.0, 5.0, 6.0)
        ab = a.cross(b)
        ba = b.cross(a)
        self.assertEqual(ab, Vector3(-ba.x, -ba.y, -ba.z))


class TestIterable(unittest.TestCase):
    def test_unpack(self):
        v = Vector3(1.0, 2.0, 3.0)
        x, y, z = v
        self.assertEqual((x, y, z), (1.0, 2.0, 3.0))

    def test_list_conversion(self):
        v = Vector3(1.0, 2.0, 3.0)
        self.assertEqual(list(v), [1.0, 2.0, 3.0])


class TestRepr(unittest.TestCase):
    def test_format(self):
        v = Vector3(1.0, 2.0, 3.0)
        self.assertEqual(repr(v), "(1.0, 2.0, 3.0)")
