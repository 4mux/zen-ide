"""Tests for utils module."""

import unittest

from utils import chunk, fibonacci, flatten


class TestFibonacci(unittest.TestCase):
    def test_first_10(self):
        self.assertEqual(list(fibonacci(10)), [0, 1, 1, 2, 3, 5, 8, 13, 21, 34])

    def test_zero(self):
        self.assertEqual(list(fibonacci(0)), [])

    def test_one(self):
        self.assertEqual(list(fibonacci(1)), [0])


class TestChunk(unittest.TestCase):
    def test_even_split(self):
        self.assertEqual(chunk([1, 2, 3, 4, 5, 6], 3), [[1, 2, 3], [4, 5, 6]])

    def test_uneven_split(self):
        self.assertEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_size_larger_than_list(self):
        self.assertEqual(chunk([1, 2], 5), [[1, 2]])

    def test_empty(self):
        self.assertEqual(chunk([], 3), [])


class TestFlatten(unittest.TestCase):
    def test_nested(self):
        self.assertEqual(flatten([[1, 2], [3, 4], [5]]), [1, 2, 3, 4, 5])

    def test_empty_sublists(self):
        self.assertEqual(flatten([[], [1], []]), [1])

    def test_empty(self):
        self.assertEqual(flatten([]), [])
