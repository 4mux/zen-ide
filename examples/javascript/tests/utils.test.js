import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { chunk, fibonacci, flatten, groupBy } from "../utils.js";

describe("fibonacci", () => {
  it("yields first 10 Fibonacci numbers", () => {
    assert.deepEqual([...fibonacci(10)], [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]);
  });

  it("yields nothing for n=0", () => {
    assert.deepEqual([...fibonacci(0)], []);
  });

  it("yields [0] for n=1", () => {
    assert.deepEqual([...fibonacci(1)], [0]);
  });

  it("is lazy (is a generator)", () => {
    const gen = fibonacci(100);
    assert.equal(gen.next().value, 0);
    assert.equal(gen.next().value, 1);
  });
});

describe("chunk", () => {
  it("splits array into fixed-size chunks", () => {
    assert.deepEqual(chunk([1, 2, 3, 4, 5, 6], 2), [[1, 2], [3, 4], [5, 6]]);
  });

  it("last chunk may be smaller", () => {
    assert.deepEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
  });

  it("returns empty array for empty input", () => {
    assert.deepEqual(chunk([], 3), []);
  });

  it("chunk size larger than array returns one chunk", () => {
    assert.deepEqual(chunk([1, 2], 10), [[1, 2]]);
  });
});

describe("flatten", () => {
  it("flattens one level of nesting", () => {
    assert.deepEqual(flatten([[1, 2], [3, 4], [5]]), [1, 2, 3, 4, 5]);
  });

  it("returns empty array for empty input", () => {
    assert.deepEqual(flatten([]), []);
  });

  it("does not flatten more than one level", () => {
    assert.deepEqual(flatten([[[1, 2]], [3]]), [[1, 2], 3]);
  });
});

describe("groupBy", () => {
  it("groups items by key function", () => {
    const items = [
      { name: "Circle", area: 10 },
      { name: "Rectangle", area: 20 },
      { name: "Circle", area: 30 },
    ];
    const groups = groupBy(items, (i) => i.name);
    assert.equal(groups.get("Circle").length, 2);
    assert.equal(groups.get("Rectangle").length, 1);
  });

  it("returns empty Map for empty input", () => {
    assert.equal(groupBy([], (x) => x).size, 0);
  });

  it("groups single items per key correctly", () => {
    const items = [{ k: "a" }, { k: "b" }];
    const groups = groupBy(items, (i) => i.k);
    assert.equal(groups.size, 2);
  });
});
