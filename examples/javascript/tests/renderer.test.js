import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { Renderer }  from "../src/renderer.js";
import { Circle }    from "../src/circle.js";
import { Rectangle } from "../src/rectangle.js";
import { Color }     from "../src/shape.js";
import { Vector3 }   from "../src/vector3.js";

function makeRenderer() {
  const r = new Renderer();
  r.add(new Circle(new Vector3(0, 0, 0), 5, Color.RED));
  r.add(new Circle(new Vector3(10, 0, 0), 3));
  r.add(new Rectangle(new Vector3(0, 0, 0), 4, 6, Color.YELLOW));
  return r;
}

describe("Renderer", () => {
  describe("add / count", () => {
    it("starts empty", () => {
      assert.equal(new Renderer().count, 0);
    });

    it("increments count on add", () => {
      const r = new Renderer();
      r.add(new Circle());
      r.add(new Circle());
      assert.equal(r.count, 2);
    });

    it("supports method chaining", () => {
      const r = new Renderer();
      const ret = r.add(new Circle());
      assert.equal(ret, r);
    });
  });

  describe("render", () => {
    it("contains header with shape count", () => {
      const r = makeRenderer();
      assert.ok(r.render().includes("3 shapes"));
    });

    it("contains total area", () => {
      const r = makeRenderer();
      assert.ok(r.render().includes("Total area:"));
    });
  });

  describe("filter", () => {
    it("returns only matching shapes", () => {
      const r = makeRenderer();
      const big = r.filter((s) => s.area() > 50);
      assert.equal(big.length, 1);
      assert.equal(big[0].name, "Circle");
    });

    it("returns empty array when nothing matches", () => {
      const r = makeRenderer();
      assert.deepEqual(r.filter(() => false), []);
    });

    it("returns all when predicate is always true", () => {
      const r = makeRenderer();
      assert.equal(r.filter(() => true).length, 3);
    });
  });

  describe("totalArea", () => {
    it("sums areas of all shapes", () => {
      const r = new Renderer();
      r.add(new Rectangle(new Vector3(), 4, 5));   // area = 20
      r.add(new Rectangle(new Vector3(), 3, 3));   // area = 9
      assert.equal(r.totalArea(), 29);
    });

    it("returns 0 for empty renderer", () => {
      assert.equal(new Renderer().totalArea(), 0);
    });
  });

  describe("sortedByArea", () => {
    it("returns ascending order by default", () => {
      const r = makeRenderer();
      const sorted = r.sortedByArea();
      for (let i = 1; i < sorted.length; i++) {
        assert.ok(sorted[i].area() >= sorted[i - 1].area());
      }
    });

    it("returns descending order when reverse=true", () => {
      const r = makeRenderer();
      const sorted = r.sortedByArea({ reverse: true });
      for (let i = 1; i < sorted.length; i++) {
        assert.ok(sorted[i].area() <= sorted[i - 1].area());
      }
    });

    it("does not mutate original order", () => {
      const r = makeRenderer();
      const before = r.filter(() => true).map((s) => s.name);
      r.sortedByArea({ reverse: true });
      const after = r.filter(() => true).map((s) => s.name);
      assert.deepEqual(before, after);
    });
  });

  describe("Symbol.iterator", () => {
    it("iterates all shapes via for…of", () => {
      const r = makeRenderer();
      const names = [];
      for (const s of r) names.push(s.name);
      assert.equal(names.length, 3);
    });

    it("spreads into an array", () => {
      const r = makeRenderer();
      assert.equal([...r].length, 3);
    });
  });
});
