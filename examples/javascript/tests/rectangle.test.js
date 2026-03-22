import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { Rectangle } from "../rectangle.js";
import { Color }     from "../shape.js";
import { Vector3 }   from "../vector3.js";

describe("Rectangle", () => {
  describe("defaults", () => {
    it("uses GREEN as default color", () => {
      const r = new Rectangle();
      assert.equal(r.color, Color.GREEN);
    });

    it("defaults to origin (0,0,0), width 1, height 1", () => {
      const r = new Rectangle();
      assert.equal(r.width,  1);
      assert.equal(r.height, 1);
      assert.equal(r.origin.toString(), "(0, 0, 0)");
    });
  });

  describe("area", () => {
    it("returns width × height", () => {
      assert.equal(new Rectangle(new Vector3(), 4, 6).area(), 24);
    });

    it("is zero for zero-dimension rectangle", () => {
      assert.equal(new Rectangle(new Vector3(), 0, 5).area(), 0);
    });
  });

  describe("perimeter", () => {
    it("returns 2·(w + h)", () => {
      assert.equal(new Rectangle(new Vector3(), 4, 6).perimeter(), 20);
    });

    it("square perimeter is 4 × side", () => {
      assert.equal(new Rectangle(new Vector3(), 5, 5).perimeter(), 20);
    });
  });

  describe("centroid", () => {
    it("is origin offset by (w/2, h/2, 0)", () => {
      const r = new Rectangle(new Vector3(0, 0, 0), 4, 6);
      const c = r.centroid();
      assert.equal(c.x, 2);
      assert.equal(c.y, 3);
      assert.equal(c.z, 0);
    });

    it("offsets from non-zero origin", () => {
      const r = new Rectangle(new Vector3(10, 20, 0), 4, 6);
      const c = r.centroid();
      assert.equal(c.x, 12);
      assert.equal(c.y, 23);
    });
  });

  describe("describe", () => {
    it("includes dimensions and origin", () => {
      const r = new Rectangle(new Vector3(1, 2, 0), 3, 4, Color.YELLOW);
      const d = r.describe();
      assert.ok(d.includes("w=3"));
      assert.ok(d.includes("h=4"));
      assert.ok(d.includes("(1, 2, 0)"));
      assert.ok(d.includes("YELLOW"));
    });
  });

  describe("getters", () => {
    it("exposes width, height, origin", () => {
      const origin = new Vector3(1, 2, 0);
      const r = new Rectangle(origin, 8, 3);
      assert.equal(r.width,  8);
      assert.equal(r.height, 3);
      assert.equal(r.origin, origin);
      assert.equal(r.name, "Rectangle");
    });
  });
});
