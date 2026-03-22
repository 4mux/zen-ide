import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { Vector3 } from "../src/vector3.js";

describe("Vector3", () => {
  describe("constructor / getters", () => {
    it("stores x, y, z", () => {
      const v = new Vector3(1, 2, 3);
      assert.equal(v.x, 1);
      assert.equal(v.y, 2);
      assert.equal(v.z, 3);
    });

    it("defaults to (0, 0, 0)", () => {
      const v = new Vector3();
      assert.equal(v.x, 0);
      assert.equal(v.y, 0);
      assert.equal(v.z, 0);
    });

    it("is immutable (frozen)", () => {
      const v = new Vector3(1, 2, 3);
      assert.ok(Object.isFrozen(v));
    });
  });

  describe("length", () => {
    it("computes Euclidean length", () => {
      const v = new Vector3(3, 4, 0);
      assert.equal(v.length(), 5);
    });

    it("returns 0 for zero vector", () => {
      assert.equal(new Vector3().length(), 0);
    });
  });

  describe("normalized", () => {
    it("returns unit vector", () => {
      const n = new Vector3(3, 0, 0).normalized();
      assert.equal(n.x, 1);
      assert.equal(n.y, 0);
      assert.equal(n.z, 0);
    });

    it("returns zero vector for zero input", () => {
      const n = new Vector3().normalized();
      assert.equal(n.x, 0);
      assert.equal(n.y, 0);
      assert.equal(n.z, 0);
    });
  });

  describe("add / sub / scale", () => {
    it("adds two vectors", () => {
      const r = new Vector3(1, 2, 3).add(new Vector3(4, 5, 6));
      assert.deepEqual([r.x, r.y, r.z], [5, 7, 9]);
    });

    it("subtracts two vectors", () => {
      const r = new Vector3(4, 5, 6).sub(new Vector3(1, 2, 3));
      assert.deepEqual([r.x, r.y, r.z], [3, 3, 3]);
    });

    it("scales by scalar", () => {
      const r = new Vector3(1, 2, 3).scale(2);
      assert.deepEqual([r.x, r.y, r.z], [2, 4, 6]);
    });

    it("returns a new Vector3 (immutable)", () => {
      const a = new Vector3(1, 2, 3);
      const b = new Vector3(1, 0, 0);
      const c = a.add(b);
      assert.notEqual(c, a);
    });
  });

  describe("dot", () => {
    it("computes dot product", () => {
      assert.equal(new Vector3(1, 2, 3).dot(new Vector3(4, 5, 6)), 32);
    });

    it("returns 0 for perpendicular vectors", () => {
      assert.equal(new Vector3(1, 0, 0).dot(new Vector3(0, 1, 0)), 0);
    });
  });

  describe("cross", () => {
    it("computes cross product", () => {
      const r = new Vector3(1, 0, 0).cross(new Vector3(0, 1, 0));
      assert.deepEqual([r.x, r.y, r.z], [0, 0, 1]);
    });

    it("is anti-commutative", () => {
      const a = new Vector3(1, 2, 3);
      const b = new Vector3(4, 5, 6);
      const ab = a.cross(b);
      const ba = b.cross(a);
      assert.deepEqual([ab.x, ab.y, ab.z], [-ba.x, -ba.y, -ba.z]);
    });
  });

  describe("Symbol.iterator", () => {
    it("supports destructuring", () => {
      const [x, y, z] = new Vector3(7, 8, 9);
      assert.equal(x, 7);
      assert.equal(y, 8);
      assert.equal(z, 9);
    });

    it("spreads into an array", () => {
      assert.deepEqual([...new Vector3(1, 2, 3)], [1, 2, 3]);
    });
  });

  describe("toString", () => {
    it("formats as (x, y, z)", () => {
      assert.equal(new Vector3(1, 2, 3).toString(), "(1, 2, 3)");
    });
  });
});
