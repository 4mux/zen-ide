"""Utilities: context manager, generator, and helper functions."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator


@contextmanager
def timer(label: str) -> Generator[None, None, None]:
    """Context manager that prints elapsed time."""
    start = time.perf_counter()
    yield
    elapsed = (time.perf_counter() - start) * 1000
    print(f"[{label}] {elapsed:.2f} ms")


def fibonacci(n: int) -> Generator[int, None, None]:
    """Generator that yields the first n Fibonacci numbers."""
    a, b = 0, 1
    for _ in range(n):
        yield a
        a, b = b, a + b


def chunk(lst: list, size: int) -> list[list]:
    """Split a list into fixed-size chunks."""
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def flatten(nested: list[list]) -> list:
    """Flatten one level of nesting."""
    return [item for sub in nested for item in sub]
